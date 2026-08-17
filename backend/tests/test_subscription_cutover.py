import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "subscription_cutover.py"
SPEC = importlib.util.spec_from_file_location("subscription_cutover", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def app(
    name,
    service,
    *,
    external,
    target_port,
    transport="Auto",
    allow_insecure=False,
):
    return {
        "name": name,
        "tags": {"azd-service-name": service},
        "properties": {
            "configuration": {
                "ingress": {
                    "external": external,
                    "targetPort": target_port,
                    "transport": transport,
                    "allowInsecure": allow_insecure,
                }
            }
        },
    }


def revision(name, *, active=True):
    return {
        "name": name,
        "properties": {
            "active": active,
        },
    }


def without_ingress(container_app):
    copied = json.loads(json.dumps(container_app))
    copied["properties"]["configuration"].pop("ingress", None)
    return copied


class FakeAzRunner:
    def __init__(self, apps, revisions_by_app, *, fail_on_summary=None, events=None):
        self.apps = json.loads(json.dumps(apps))
        self.revisions_by_app = json.loads(json.dumps(revisions_by_app))
        self.fail_on_summary = fail_on_summary
        self.events = events if events is not None else []

    def _argument(self, command, flag):
        return command[command.index(flag) + 1]

    def _find_app(self, name):
        return next(app for app in self.apps if app["name"] == name)

    def _summary(self, command):
        if command[:3] == ["az", "containerapp", "list"]:
            return "containerapp list"
        if command[:4] == ["az", "containerapp", "revision", "list"]:
            return f"containerapp revision list {self._argument(command, '--name')}"
        if command[:4] == ["az", "containerapp", "ingress", "disable"]:
            return f"containerapp ingress disable {self._argument(command, '--name')}"
        if command[:4] == ["az", "containerapp", "revision", "deactivate"]:
            return (
                "containerapp revision deactivate "
                f"{self._argument(command, '--revision')}"
            )
        if command[:4] == ["az", "containerapp", "revision", "activate"]:
            return (
                "containerapp revision activate "
                f"{self._argument(command, '--revision')}"
            )
        if command[:4] == ["az", "containerapp", "ingress", "enable"]:
            return (
                "containerapp ingress enable "
                f"{self._argument(command, '--name')} "
                f"{self._argument(command, '--type')} "
                f"{self._argument(command, '--target-port')} "
                f"{self._argument(command, '--transport')} "
                f"{self._argument(command, '--allow-insecure')}"
            )
        raise AssertionError(f"unexpected command {command}")

    def __call__(self, command):
        command = list(command)
        summary = self._summary(command)
        self.events.append(summary)
        if self.fail_on_summary == summary:
            raise subprocess.CalledProcessError(
                returncode=2,
                cmd=command,
                stderr="boom",
            )

        if command[:3] == ["az", "containerapp", "list"]:
            return SimpleNamespace(stdout=json.dumps(self.apps))

        if command[:4] == ["az", "containerapp", "revision", "list"]:
            app_name = self._argument(command, "--name")
            return SimpleNamespace(
                stdout=json.dumps(self.revisions_by_app[app_name])
            )

        if command[:4] == ["az", "containerapp", "ingress", "disable"]:
            app_name = self._argument(command, "--name")
            self._find_app(app_name)["properties"]["configuration"].pop(
                "ingress", None
            )
            return SimpleNamespace(stdout="{}")

        if command[:4] == ["az", "containerapp", "revision", "deactivate"]:
            app_name = self._argument(command, "--name")
            revision_name = self._argument(command, "--revision")
            for item in self.revisions_by_app[app_name]:
                if item["name"] == revision_name:
                    item["properties"]["active"] = False
            return SimpleNamespace(stdout="{}")

        if command[:4] == ["az", "containerapp", "revision", "activate"]:
            app_name = self._argument(command, "--name")
            revision_name = self._argument(command, "--revision")
            for item in self.revisions_by_app[app_name]:
                if item["name"] == revision_name:
                    item["properties"]["active"] = True
            return SimpleNamespace(stdout="{}")

        if command[:4] == ["az", "containerapp", "ingress", "enable"]:
            app_name = self._argument(command, "--name")
            target_port = int(self._argument(command, "--target-port"))
            transport = self._argument(command, "--transport")
            self._find_app(app_name)["properties"]["configuration"]["ingress"] = {
                "external": self._argument(command, "--type") == "external",
                "targetPort": target_port,
                "transport": transport,
                "allowInsecure": (
                    self._argument(command, "--allow-insecure") == "true"
                ),
            }
            return SimpleNamespace(stdout="{}")

        raise AssertionError(f"unexpected command {command}")


def test_build_freeze_state_requires_backend_and_frontend():
    apps = [
        app("ca-backend", "backend", external=False, target_port=8000),
        app("ca-frontend", "frontend", external=True, target_port=3000),
    ]
    revisions = {
        "ca-backend": [revision("ca-backend--0000004")],
        "ca-frontend": [revision("ca-frontend--0000004")],
    }

    state = MODULE.build_freeze_state(
        subscription_id="source-sub",
        resource_group="rg-jjflipbook-p2",
        apps=apps,
        revisions_by_app=revisions,
    )

    assert state["schema_version"] == 1
    assert [item["service"] for item in state["apps"]] == [
        "backend",
        "frontend",
    ]
    assert state["apps"][1]["ingress"]["external"] is True
    assert state["apps"][1]["active_revisions"] == [
        "ca-frontend--0000004"
    ]


def test_build_freeze_state_rejects_duplicate_service_tags():
    apps = [
        app("ca-one", "backend", external=False, target_port=8000),
        app("ca-two", "backend", external=False, target_port=8001),
        app("ca-three", "frontend", external=True, target_port=3000),
    ]

    with pytest.raises(RuntimeError, match="backend"):
        MODULE.build_freeze_state(
            subscription_id="source-sub",
            resource_group="rg-jjflipbook-p2",
            apps=apps,
            revisions_by_app={},
        )


def test_write_json_state_rejects_symlink_destination(tmp_path):
    real_file = tmp_path / "real-state.json"
    real_file.write_text("{}", encoding="utf-8")
    symlink = tmp_path / "state.json"
    symlink.symlink_to(real_file)

    with pytest.raises(RuntimeError, match="symlink"):
        MODULE.write_json_state(symlink, {"schema_version": 1})



def test_write_json_state_uses_sibling_temporary_file_and_replace(monkeypatch, tmp_path):
    destination = tmp_path / "state.json"
    payload = {"schema_version": 1, "frozen": False}
    calls = []
    real_replace = MODULE.os.replace
    real_fsync = MODULE.os.fsync

    def fake_fsync(fd):
        calls.append(("fsync", fd))
        return real_fsync(fd)

    def fake_replace(source, target):
        calls.append(("replace", Path(source), Path(target)))
        return real_replace(source, target)

    monkeypatch.setattr(MODULE.os, "fsync", fake_fsync)
    monkeypatch.setattr(MODULE.os, "replace", fake_replace)

    MODULE.write_json_state(destination, payload)

    assert json.loads(destination.read_text(encoding="utf-8")) == payload
    replace_call = next(call for call in calls if call[0] == "replace")
    assert replace_call[1].parent == destination.parent
    assert replace_call[1].name == "state.json.tmp"
    assert replace_call[2] == destination
    assert any(call[0] == "fsync" for call in calls)
    assert not replace_call[1].exists()



def test_run_command_uses_argument_array_subprocess_contract(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="[]")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    MODULE.run_command(["az", "containerapp", "list"])

    assert captured == {
        "command": ["az", "containerapp", "list"],
        "kwargs": {
            "check": True,
            "text": True,
            "capture_output": True,
        },
    }


def test_freeze_cli_writes_state_before_mutations_and_marks_it_frozen(
    monkeypatch, tmp_path
):
    state_file = tmp_path / "source-freeze.json"
    events = []
    writes = []
    runner = FakeAzRunner(
        apps=[
            app("ca-api-prod", "backend", external=False, target_port=8080),
            app("ca-web-prod", "frontend", external=True, target_port=3000),
        ],
        revisions_by_app={
            "ca-api-prod": [revision("ca-api-prod--0000007")],
            "ca-web-prod": [revision("ca-web-prod--0000008")],
        },
        events=events,
    )

    def fake_write(path, payload):
        events.append(f"write:{payload['frozen']}")
        writes.append((Path(path), json.loads(json.dumps(payload))))

    monkeypatch.setattr(MODULE, "run_command", runner)
    monkeypatch.setattr(MODULE, "write_json_state", fake_write)

    MODULE.main(
        [
            "freeze",
            "--subscription",
            "source-sub",
            "--resource-group",
            "rg-source",
            "--state-file",
            str(state_file),
        ]
    )

    assert writes == [
        (
            state_file,
            {
                "schema_version": 1,
                "subscription_id": "source-sub",
                "resource_group": "rg-source",
                "frozen": False,
                "apps": [
                    {
                        "service": "backend",
                        "name": "ca-api-prod",
                        "ingress": {
                            "external": False,
                            "targetPort": 8080,
                            "transport": "Auto",
                            "allowInsecure": False,
                        },
                        "active_revisions": ["ca-api-prod--0000007"],
                    },
                    {
                        "service": "frontend",
                        "name": "ca-web-prod",
                        "ingress": {
                            "external": True,
                            "targetPort": 3000,
                            "transport": "Auto",
                            "allowInsecure": False,
                        },
                        "active_revisions": ["ca-web-prod--0000008"],
                    },
                ],
            },
        ),
        (
            state_file,
            {
                "schema_version": 1,
                "subscription_id": "source-sub",
                "resource_group": "rg-source",
                "frozen": True,
                "apps": [
                    {
                        "service": "backend",
                        "name": "ca-api-prod",
                        "ingress": {
                            "external": False,
                            "targetPort": 8080,
                            "transport": "Auto",
                            "allowInsecure": False,
                        },
                        "active_revisions": ["ca-api-prod--0000007"],
                    },
                    {
                        "service": "frontend",
                        "name": "ca-web-prod",
                        "ingress": {
                            "external": True,
                            "targetPort": 3000,
                            "transport": "Auto",
                            "allowInsecure": False,
                        },
                        "active_revisions": ["ca-web-prod--0000008"],
                    },
                ],
            },
        ),
    ]
    assert events == [
        "containerapp list",
        "containerapp revision list ca-api-prod",
        "containerapp revision list ca-web-prod",
        "write:False",
        "containerapp ingress disable ca-api-prod",
        "containerapp ingress disable ca-web-prod",
        "containerapp revision deactivate ca-api-prod--0000007",
        "containerapp revision deactivate ca-web-prod--0000008",
        "containerapp list",
        "containerapp revision list ca-api-prod",
        "containerapp revision list ca-web-prod",
        "write:True",
    ]


def test_freeze_cli_prints_restore_hint_and_exits_nonzero_on_mutation_failure(
    monkeypatch, tmp_path, capsys
):
    state_file = tmp_path / "source-freeze.json"
    events = []
    writes = []
    runner = FakeAzRunner(
        apps=[
            app("ca-api-prod", "backend", external=False, target_port=8080),
            app("ca-web-prod", "frontend", external=True, target_port=3000),
        ],
        revisions_by_app={
            "ca-api-prod": [revision("ca-api-prod--0000007")],
            "ca-web-prod": [revision("ca-web-prod--0000008")],
        },
        fail_on_summary="containerapp revision deactivate ca-web-prod--0000008",
        events=events,
    )

    def fake_write(path, payload):
        events.append(f"write:{payload['frozen']}")
        writes.append((Path(path), json.loads(json.dumps(payload))))

    monkeypatch.setattr(MODULE, "run_command", runner)
    monkeypatch.setattr(MODULE, "write_json_state", fake_write)

    with pytest.raises(SystemExit) as excinfo:
        MODULE.main(
            [
                "freeze",
                "--subscription",
                "source-sub",
                "--resource-group",
                "rg-source",
                "--state-file",
                str(state_file),
            ]
        )

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert writes == [
        (
            state_file,
            {
                "schema_version": 1,
                "subscription_id": "source-sub",
                "resource_group": "rg-source",
                "frozen": False,
                "apps": [
                    {
                        "service": "backend",
                        "name": "ca-api-prod",
                        "ingress": {
                            "external": False,
                            "targetPort": 8080,
                            "transport": "Auto",
                            "allowInsecure": False,
                        },
                        "active_revisions": ["ca-api-prod--0000007"],
                    },
                    {
                        "service": "frontend",
                        "name": "ca-web-prod",
                        "ingress": {
                            "external": True,
                            "targetPort": 3000,
                            "transport": "Auto",
                            "allowInsecure": False,
                        },
                        "active_revisions": ["ca-web-prod--0000008"],
                    },
                ],
            },
        )
    ]
    assert (
        f'python3 scripts/subscription_cutover.py restore --state-file "{state_file}"'
        in captured.err
    )
    assert events == [
        "containerapp list",
        "containerapp revision list ca-api-prod",
        "containerapp revision list ca-web-prod",
        "write:False",
        "containerapp ingress disable ca-api-prod",
        "containerapp ingress disable ca-web-prod",
        "containerapp revision deactivate ca-api-prod--0000007",
        "containerapp revision deactivate ca-web-prod--0000008",
    ]


def test_verify_frozen_cli_checks_live_apps_from_state_file(monkeypatch, tmp_path):
    state_file = tmp_path / "source-freeze.json"
    state = MODULE.build_freeze_state(
        subscription_id="source-sub",
        resource_group="rg-source",
        apps=[
            app("ca-api-prod", "backend", external=False, target_port=8080),
            app("ca-web-prod", "frontend", external=True, target_port=3000),
        ],
        revisions_by_app={
            "ca-api-prod": [revision("ca-api-prod--0000007")],
            "ca-web-prod": [revision("ca-web-prod--0000008")],
        },
    )
    state["frozen"] = True
    state_file.write_text(json.dumps(state), encoding="utf-8")

    events = []
    runner = FakeAzRunner(
        apps=[
            without_ingress(
                app("ca-api-prod", "backend", external=False, target_port=8080)
            ),
            without_ingress(
                app("ca-web-prod", "frontend", external=True, target_port=3000)
            ),
        ],
        revisions_by_app={
            "ca-api-prod": [revision("ca-api-prod--0000007", active=False)],
            "ca-web-prod": [revision("ca-web-prod--0000008", active=False)],
        },
        events=events,
    )
    monkeypatch.setattr(MODULE, "run_command", runner)

    MODULE.main(["verify-frozen", "--state-file", str(state_file)])

    assert events == [
        "containerapp list",
        "containerapp revision list ca-api-prod",
        "containerapp revision list ca-web-prod",
    ]


def test_verify_frozen_cli_rejects_state_file_not_marked_frozen(tmp_path):
    state_file = tmp_path / "source-freeze.json"
    state = {
        "schema_version": 1,
        "subscription_id": "source-sub",
        "resource_group": "rg-source",
        "frozen": False,
        "apps": [],
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        MODULE.main(["verify-frozen", "--state-file", str(state_file)])

    assert excinfo.value.code == 1


def test_restore_cli_reactivates_revisions_before_enabling_ingress(
    monkeypatch, tmp_path
):
    state_file = tmp_path / "source-freeze.json"
    state = {
        "schema_version": 1,
        "subscription_id": "source-sub",
        "resource_group": "rg-source",
        "frozen": False,
        "apps": [
            {
                "service": "backend",
                "name": "ca-api-prod",
                "ingress": {
                    "external": False,
                    "targetPort": 8080,
                    "transport": "auto",
                    "allowInsecure": False,
                },
                "active_revisions": ["ca-api-prod--0000007"],
            },
            {
                "service": "frontend",
                "name": "ca-web-prod",
                "ingress": {
                    "external": True,
                    "targetPort": 3000,
                    "transport": "auto",
                    "allowInsecure": True,
                },
                "active_revisions": ["ca-web-prod--0000008"],
            },
        ],
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    events = []
    runner = FakeAzRunner(
        apps=[
            without_ingress(
                app("ca-api-prod", "backend", external=False, target_port=8080)
            ),
            without_ingress(
                app("ca-web-prod", "frontend", external=True, target_port=3000)
            ),
        ],
        revisions_by_app={
            "ca-api-prod": [revision("ca-api-prod--0000007", active=False)],
            "ca-web-prod": [revision("ca-web-prod--0000008", active=False)],
        },
        events=events,
    )
    monkeypatch.setattr(MODULE, "run_command", runner)

    MODULE.main(["restore", "--state-file", str(state_file)])

    assert events == [
        "containerapp revision activate ca-api-prod--0000007",
        "containerapp revision activate ca-web-prod--0000008",
        "containerapp ingress enable ca-api-prod internal 8080 auto false",
        "containerapp ingress enable ca-web-prod external 3000 auto true",
        "containerapp list",
        "containerapp revision list ca-api-prod",
        "containerapp revision list ca-web-prod",
    ]


def test_disable_ingress_cli_disables_both_tagged_apps(monkeypatch):
    events = []
    runner = FakeAzRunner(
        apps=[
            app("ca-api-target", "backend", external=False, target_port=8080),
            app("ca-web-target", "frontend", external=True, target_port=3000),
        ],
        revisions_by_app={
            "ca-api-target": [revision("ca-api-target--0000001")],
            "ca-web-target": [revision("ca-web-target--0000001")],
        },
        events=events,
    )
    monkeypatch.setattr(MODULE, "run_command", runner)

    MODULE.main(
        [
            "disable-ingress",
            "--subscription",
            "target-sub",
            "--resource-group",
            "rg-target",
        ]
    )

    assert events == [
        "containerapp list",
        "containerapp ingress disable ca-api-target",
        "containerapp ingress disable ca-web-target",
    ]

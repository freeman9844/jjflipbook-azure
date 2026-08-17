#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence


SCHEMA_VERSION = 1
SERVICES = ("backend", "frontend")

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
StateWriter = Callable[[str | Path, dict], None]


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=True,
        text=True,
        capture_output=True,
    )


def _with_command_runner(command_runner: CommandRunner | None) -> CommandRunner:
    return run_command if command_runner is None else command_runner


def _with_state_writer(state_writer: StateWriter | None) -> StateWriter:
    return write_json_state if state_writer is None else state_writer


def _run_az_json(
    *args: str,
    command_runner: CommandRunner | None = None,
):
    completed = _with_command_runner(command_runner)(
        ["az", *args, "--output", "json"]
    )
    stdout = completed.stdout.strip()
    return json.loads(stdout or "null")


def _list_apps(
    subscription_id: str,
    resource_group: str,
    *,
    command_runner: CommandRunner | None = None,
) -> list[dict]:
    apps = _run_az_json(
        "containerapp",
        "list",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        command_runner=command_runner,
    )
    if not isinstance(apps, list):
        raise RuntimeError("az containerapp list did not return a JSON array")
    return apps


def _list_revisions(
    subscription_id: str,
    resource_group: str,
    app_name: str,
    *,
    command_runner: CommandRunner | None = None,
) -> list[dict]:
    revisions = _run_az_json(
        "containerapp",
        "revision",
        "list",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--name",
        app_name,
        command_runner=command_runner,
    )
    if not isinstance(revisions, list):
        raise RuntimeError(
            f"az containerapp revision list for {app_name} did not return a JSON array"
        )
    return revisions


def _disable_app_ingress(
    subscription_id: str,
    resource_group: str,
    app_name: str,
    *,
    command_runner: CommandRunner | None = None,
) -> None:
    _run_az_json(
        "containerapp",
        "ingress",
        "disable",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--name",
        app_name,
        command_runner=command_runner,
    )


def _deactivate_revision(
    subscription_id: str,
    resource_group: str,
    app_name: str,
    revision_name: str,
    *,
    command_runner: CommandRunner | None = None,
) -> None:
    _run_az_json(
        "containerapp",
        "revision",
        "deactivate",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--name",
        app_name,
        "--revision",
        revision_name,
        command_runner=command_runner,
    )


def _activate_revision(
    subscription_id: str,
    resource_group: str,
    app_name: str,
    revision_name: str,
    *,
    command_runner: CommandRunner | None = None,
) -> None:
    _run_az_json(
        "containerapp",
        "revision",
        "activate",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--name",
        app_name,
        "--revision",
        revision_name,
        command_runner=command_runner,
    )


def _normalize_transport(value: object) -> str:
    if value is None:
        raise RuntimeError("Ingress transport is required")
    return str(value).strip().lower()


def _enable_app_ingress(
    subscription_id: str,
    resource_group: str,
    app_name: str,
    ingress: dict,
    *,
    command_runner: CommandRunner | None = None,
) -> None:
    _run_az_json(
        "containerapp",
        "ingress",
        "enable",
        "--subscription",
        subscription_id,
        "--resource-group",
        resource_group,
        "--name",
        app_name,
        "--type",
        "external" if ingress.get("external") else "internal",
        "--target-port",
        str(int(ingress["targetPort"])),
        "--transport",
        _normalize_transport(ingress.get("transport")),
        "--allow-insecure",
        "true" if ingress.get("allowInsecure") else "false",
        command_runner=command_runner,
    )


def _app_matches_service(app: dict, service: str) -> bool:
    return (app.get("tags") or {}).get("azd-service-name") == service


def _select_required_apps(apps: list[dict]) -> dict[str, dict]:
    selected = {}
    for service in SERVICES:
        matches = [app for app in apps if _app_matches_service(app, service)]
        if len(matches) != 1:
            names = [app.get("name") for app in matches]
            raise RuntimeError(
                f"Expected exactly one {service} Container App, found {names}"
            )
        selected[service] = matches[0]
    return selected


def _select_required_state_apps(apps: list[dict]) -> dict[str, dict]:
    selected = {}
    for service in SERVICES:
        matches = [app for app in apps if app.get("service") == service]
        if len(matches) != 1:
            raise RuntimeError(
                f"State file must contain exactly one {service} app entry"
            )
        selected[service] = matches[0]
    return selected


def _ingress_state(app: dict) -> dict:
    ingress = (
        ((app.get("properties") or {}).get("configuration") or {}).get("ingress")
    )
    if not ingress:
        raise RuntimeError(f"Container App {app.get('name')} has no ingress settings")
    if ingress.get("targetPort") is None:
        raise RuntimeError(
            f"Container App {app.get('name')} is missing an ingress targetPort"
        )
    transport = ingress.get("transport")
    if transport is None:
        raise RuntimeError(
            f"Container App {app.get('name')} is missing an ingress transport"
        )
    return {
        "external": bool(ingress.get("external", False)),
        "targetPort": int(ingress["targetPort"]),
        "transport": transport,
        "allowInsecure": bool(ingress.get("allowInsecure", False)),
    }


def _live_ingress_state(app: dict) -> dict | None:
    ingress = (
        ((app.get("properties") or {}).get("configuration") or {}).get("ingress")
    )
    if not ingress:
        return None
    if ingress.get("targetPort") is None:
        raise RuntimeError(
            f"Container App {app.get('name')} is missing an ingress targetPort"
        )
    transport = ingress.get("transport")
    if transport is None:
        raise RuntimeError(
            f"Container App {app.get('name')} is missing an ingress transport"
        )
    return {
        "external": bool(ingress.get("external", False)),
        "targetPort": int(ingress["targetPort"]),
        "transport": transport,
        "allowInsecure": bool(ingress.get("allowInsecure", False)),
    }


def _active_revision_names(revisions: list[dict]) -> list[str]:
    return sorted(
        revision["name"]
        for revision in revisions
        if (revision.get("properties") or {}).get("active") is True
    )


def build_freeze_state(
    *,
    subscription_id: str,
    resource_group: str,
    apps: list[dict],
    revisions_by_app: dict[str, list[dict]],
) -> dict:
    selected_apps = _select_required_apps(apps)
    state_apps = []
    for service in SERVICES:
        app = selected_apps[service]
        app_name = app["name"]
        state_apps.append(
            {
                "service": service,
                "name": app_name,
                "ingress": _ingress_state(app),
                "active_revisions": _active_revision_names(
                    revisions_by_app.get(app_name, [])
                ),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "frozen": False,
        "apps": state_apps,
    }


def _checked_state_path(path: str | Path) -> Path:
    state_path = Path(path)
    current = Path(state_path.anchor) if state_path.is_absolute() else Path.cwd()
    parts = state_path.parts[1:] if state_path.is_absolute() else state_path.parts

    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"Refusing symlink state path: {current}")
    return state_path


def write_json_state(path: str | Path, payload: dict) -> None:
    destination = _checked_state_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _checked_state_path(destination.with_name(f"{destination.name}.tmp"))

    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists() and temporary != destination:
            temporary.unlink()


def load_json_state(path: str | Path) -> dict:
    state_path = _checked_state_path(path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported state schema version: {state.get('schema_version')}"
        )
    return state


def _ingress_matches(expected: dict, actual: dict | None) -> bool:
    if actual is None:
        return False
    return (
        bool(expected.get("external", False)) == bool(actual.get("external", False))
        and int(expected.get("targetPort")) == int(actual.get("targetPort"))
        and _normalize_transport(expected.get("transport"))
        == _normalize_transport(actual.get("transport"))
        and bool(expected.get("allowInsecure", False))
        == bool(actual.get("allowInsecure", False))
    )


def verify_frozen_state(
    state: dict,
    *,
    command_runner: CommandRunner | None = None,
) -> None:
    live_apps = _select_required_apps(
        _list_apps(
            state["subscription_id"],
            state["resource_group"],
            command_runner=command_runner,
        )
    )
    expected_apps = _select_required_state_apps(state.get("apps", []))

    for service in SERVICES:
        expected_app = expected_apps[service]
        live_app = live_apps[service]
        if live_app.get("name") != expected_app.get("name"):
            raise RuntimeError(
                f"{service} Container App changed from {expected_app.get('name')} "
                f"to {live_app.get('name')}"
            )
        if _live_ingress_state(live_app) is not None:
            raise RuntimeError(f"{service} ingress is still enabled")
        active_revisions = _active_revision_names(
            _list_revisions(
                state["subscription_id"],
                state["resource_group"],
                expected_app["name"],
                command_runner=command_runner,
            )
        )
        if active_revisions:
            raise RuntimeError(
                f"{service} still has active revisions: {active_revisions}"
            )


def verify_restored_state(
    state: dict,
    *,
    command_runner: CommandRunner | None = None,
) -> None:
    live_apps = _select_required_apps(
        _list_apps(
            state["subscription_id"],
            state["resource_group"],
            command_runner=command_runner,
        )
    )
    expected_apps = _select_required_state_apps(state.get("apps", []))

    for service in SERVICES:
        expected_app = expected_apps[service]
        live_app = live_apps[service]
        if live_app.get("name") != expected_app.get("name"):
            raise RuntimeError(
                f"{service} Container App changed from {expected_app.get('name')} "
                f"to {live_app.get('name')}"
            )
        if not _ingress_matches(
            expected_app["ingress"],
            _live_ingress_state(live_app),
        ):
            raise RuntimeError(f"{service} ingress settings were not fully restored")
        active_revisions = _active_revision_names(
            _list_revisions(
                state["subscription_id"],
                state["resource_group"],
                expected_app["name"],
                command_runner=command_runner,
            )
        )
        if active_revisions != sorted(expected_app.get("active_revisions", [])):
            raise RuntimeError(
                f"{service} active revisions are {active_revisions}, expected "
                f"{sorted(expected_app.get('active_revisions', []))}"
            )


def freeze_source(
    *,
    subscription_id: str,
    resource_group: str,
    state_file: str | Path,
    command_runner: CommandRunner | None = None,
    state_writer: StateWriter | None = None,
) -> None:
    command_runner = _with_command_runner(command_runner)
    state_writer = _with_state_writer(state_writer)

    apps = _list_apps(
        subscription_id,
        resource_group,
        command_runner=command_runner,
    )
    selected_apps = _select_required_apps(apps)
    revisions_by_app = {
        selected_apps[service]["name"]: _list_revisions(
            subscription_id,
            resource_group,
            selected_apps[service]["name"],
            command_runner=command_runner,
        )
        for service in SERVICES
    }
    state = build_freeze_state(
        subscription_id=subscription_id,
        resource_group=resource_group,
        apps=apps,
        revisions_by_app=revisions_by_app,
    )
    state_writer(state_file, state)

    expected_apps = _select_required_state_apps(state["apps"])
    try:
        for service in SERVICES:
            _disable_app_ingress(
                subscription_id,
                resource_group,
                expected_apps[service]["name"],
                command_runner=command_runner,
            )
        for service in SERVICES:
            for revision_name in expected_apps[service]["active_revisions"]:
                _deactivate_revision(
                    subscription_id,
                    resource_group,
                    expected_apps[service]["name"],
                    revision_name,
                    command_runner=command_runner,
                )
        verify_frozen_state(state, command_runner=command_runner)
    except Exception as exc:
        print(f"Freeze failed: {exc}", file=sys.stderr)
        print(
            (
                "python3 scripts/subscription_cutover.py restore "
                f'--state-file "{state_file}"'
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    frozen_state = dict(state)
    frozen_state["frozen"] = True
    state_writer(state_file, frozen_state)


def verify_frozen_from_file(
    state_file: str | Path,
    *,
    command_runner: CommandRunner | None = None,
) -> None:
    state = load_json_state(state_file)
    if not state.get("frozen"):
        print("State file is not marked frozen.", file=sys.stderr)
        raise SystemExit(1)
    verify_frozen_state(state, command_runner=command_runner)


def restore_source(
    *,
    state_file: str | Path,
    command_runner: CommandRunner | None = None,
) -> None:
    command_runner = _with_command_runner(command_runner)
    state = load_json_state(state_file)
    expected_apps = _select_required_state_apps(state.get("apps", []))

    for service in SERVICES:
        for revision_name in expected_apps[service].get("active_revisions", []):
            _activate_revision(
                state["subscription_id"],
                state["resource_group"],
                expected_apps[service]["name"],
                revision_name,
                command_runner=command_runner,
            )
    for service in SERVICES:
        _enable_app_ingress(
            state["subscription_id"],
            state["resource_group"],
            expected_apps[service]["name"],
            expected_apps[service]["ingress"],
            command_runner=command_runner,
        )
    verify_restored_state(state, command_runner=command_runner)


def disable_ingress(
    *,
    subscription_id: str,
    resource_group: str,
    command_runner: CommandRunner | None = None,
) -> None:
    command_runner = _with_command_runner(command_runner)
    apps = _select_required_apps(
        _list_apps(
            subscription_id,
            resource_group,
            command_runner=command_runner,
        )
    )
    for service in SERVICES:
        _disable_app_ingress(
            subscription_id,
            resource_group,
            apps[service]["name"],
            command_runner=command_runner,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="subscription_cutover.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--subscription", required=True)
    freeze_parser.add_argument("--resource-group", required=True)
    freeze_parser.add_argument("--state-file", required=True)

    verify_parser = subparsers.add_parser("verify-frozen")
    verify_parser.add_argument("--state-file", required=True)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--state-file", required=True)

    disable_parser = subparsers.add_parser("disable-ingress")
    disable_parser.add_argument("--subscription", required=True)
    disable_parser.add_argument("--resource-group", required=True)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.command == "freeze":
        freeze_source(
            subscription_id=args.subscription,
            resource_group=args.resource_group,
            state_file=args.state_file,
        )
        return
    if args.command == "verify-frozen":
        verify_frozen_from_file(state_file=args.state_file)
        return
    if args.command == "restore":
        restore_source(state_file=args.state_file)
        return
    if args.command == "disable-ingress":
        disable_ingress(
            subscription_id=args.subscription,
            resource_group=args.resource_group,
        )
        return
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()

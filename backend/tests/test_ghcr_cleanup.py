import importlib.util
import json
from pathlib import Path
import subprocess
import urllib.error

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_ghcr_versions.py"
SPEC = importlib.util.spec_from_file_location("cleanup_ghcr_versions", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def version(
    version_id,
    created_at,
    *tags,
    name=None,
    referenced_digests=(),
):
    return {
        "id": version_id,
        "name": name or f"sha256:{version_id:064x}",
        "created_at": created_at,
        "metadata": {
            "container": {
                "tags": list(tags),
                "referenced_digests": list(referenced_digests),
            }
        },
    }


def revision(
    created_at,
    *images,
    active=False,
    health_state=None,
    running_state=None,
    provisioning_state=None,
):
    properties = {
        "active": active,
        "createdTime": created_at,
        "template": {
            "containers": [{"image": image} for image in images],
        },
    }
    if health_state is not None:
        properties["healthState"] = health_state
    if running_state is not None:
        properties["runningState"] = running_state
    if provisioning_state is not None:
        properties["provisioningState"] = provisioning_state
    return {"properties": properties}


def test_keeps_five_newest_versions():
    versions = [
        version(i, f"2026-08-{i:02d}T00:00:00Z", f"sha-{i}")
        for i in range(1, 8)
    ]
    assert MODULE.version_ids_to_delete(versions, set(), keep=5) == [2, 1]


def test_keeps_protected_rollback_tag_even_when_old():
    versions = [
        version(i, f"2026-08-{i:02d}T00:00:00Z", f"sha-{i}")
        for i in range(1, 8)
    ]
    assert MODULE.version_ids_to_delete(
        versions, {"sha-1"}, keep=5
    ) == [2]


def test_keeps_untagged_version_if_it_is_among_five_newest():
    versions = [
        version(6, "2026-08-06T00:00:00Z"),
        version(5, "2026-08-05T00:00:00Z", "sha-5"),
        version(4, "2026-08-04T00:00:00Z", "sha-4"),
        version(3, "2026-08-03T00:00:00Z", "sha-3"),
        version(2, "2026-08-02T00:00:00Z", "sha-2"),
        version(1, "2026-08-01T00:00:00Z", "sha-1"),
    ]
    assert MODULE.version_ids_to_delete(versions, set(), keep=5) == [1]


def test_keeps_old_manifest_referenced_by_retained_index():
    child_digest = "sha256:" + "a" * 64
    versions = [
        version(
            7,
            "2026-08-07T00:00:00Z",
            "sha-current",
            referenced_digests=(child_digest,),
        ),
        version(6, "2026-08-06T00:00:00Z"),
        version(5, "2026-08-05T00:00:00Z"),
        version(4, "2026-08-04T00:00:00Z"),
        version(3, "2026-08-03T00:00:00Z"),
        version(2, "2026-08-02T00:00:00Z"),
        version(1, "2026-08-01T00:00:00Z", name=child_digest),
    ]

    assert MODULE.version_ids_to_delete(versions, set(), keep=5) == [2]


def test_protected_revision_tags_keeps_all_active_revision_tags(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_az",
        lambda *args: [
            revision(
                "2026-08-04T00:00:00Z",
                "ghcr.io/owner/app:sha-4",
                active=True,
                health_state="Healthy",
                running_state="Running",
                provisioning_state="Provisioned",
            ),
            revision(
                "2026-08-03T00:00:00Z",
                "ghcr.io/owner/app:sha-3",
                active=True,
                health_state="Healthy",
                running_state="Scale to 0",
                provisioning_state="Provisioned",
            ),
            revision(
                "2026-08-02T00:00:00Z",
                "ghcr.io/owner/app:sha-2",
                active=False,
                health_state="Healthy",
                running_state="Scale to 0",
                provisioning_state="Provisioned",
            ),
        ],
    )

    assert MODULE.protected_revision_tags("rg-env", "app-name") == {
        "sha-4",
        "sha-3",
        "sha-2",
    }


def test_protected_revision_tags_skips_newer_failed_revision_for_rollback(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_az",
        lambda *args: [
            revision(
                "2026-08-04T00:00:00Z",
                "ghcr.io/owner/app:sha-4",
                active=False,
                health_state="Unhealthy",
                running_state="Failed",
                provisioning_state="Provisioning failed",
            ),
            revision(
                "2026-08-03T00:00:00Z",
                "ghcr.io/owner/app:sha-3",
                active=True,
                health_state="Healthy",
                running_state="Running",
                provisioning_state="Provisioned",
            ),
            revision(
                "2026-08-02T00:00:00Z",
                "ghcr.io/owner/app:sha-2",
                active=False,
                health_state="Healthy",
                running_state="Scale to 0",
                provisioning_state="Provisioned",
            ),
            revision(
                "2026-08-01T00:00:00Z",
                "ghcr.io/owner/app:sha-1",
                active=False,
                health_state="Healthy",
                running_state="Scale to 0",
                provisioning_state="Provisioned",
            ),
        ],
    )

    assert MODULE.protected_revision_tags("rg-env", "app-name") == {"sha-3", "sha-2"}


def test_protected_revision_tags_extracts_tag_from_digest_pinned_images(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_az",
        lambda *args: [
            revision(
                "2026-08-03T00:00:00Z",
                "ghcr.io/owner/app:sha-tag@sha256:deadbeef",
                active=True,
                health_state="Healthy",
                running_state="Running",
                provisioning_state="Provisioned",
            ),
            revision(
                "2026-08-02T00:00:00Z",
                "registry.example:5443/owner/app:port-tag@sha256:beadfeed",
                active=False,
                health_state="Healthy",
                running_state="Scale to 0",
                provisioning_state="Provisioned",
            ),
        ],
    )

    assert MODULE.protected_revision_tags("rg-env", "app-name") == {
        "sha-tag",
        "port-tag",
    }


def test_protected_revision_tags_rejects_images_without_tags(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_az",
        lambda *args: [
            revision(
                "2026-08-03T00:00:00Z",
                "ghcr.io/owner/app@sha256:deadbeef",
                active=True,
            )
        ],
    )

    with pytest.raises(RuntimeError, match="no immutable tag"):
        MODULE.protected_revision_tags("rg-env", "app-name")


def test_protected_revision_tags_protects_ambiguous_revisions_until_healthy_rollback_found(
    monkeypatch,
):
    monkeypatch.setattr(
        MODULE,
        "run_az",
        lambda *args: [
            revision(
                "2026-08-04T00:00:00Z",
                "ghcr.io/owner/app:sha-4",
                active=True,
                health_state="Healthy",
                running_state="Running",
                provisioning_state="Provisioned",
            ),
            revision(
                "2026-08-03T00:00:00Z",
                "ghcr.io/owner/app:sha-3",
                active=False,
            ),
            revision(
                "2026-08-02T00:00:00Z",
                "ghcr.io/owner/app:sha-2",
                active=False,
                health_state="Healthy",
                running_state="Scale to 0",
                provisioning_state="Provisioned",
            ),
            revision(
                "2026-08-01T00:00:00Z",
                "ghcr.io/owner/app:sha-1",
                active=False,
                health_state="Healthy",
                running_state="Scale to 0",
                provisioning_state="Provisioned",
            ),
        ],
    )

    assert MODULE.protected_revision_tags("rg-env", "app-name") == {
        "sha-4",
        "sha-3",
        "sha-2",
    }


def test_find_app_names_rejects_zero_matches(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_az",
        lambda *args: [{"name": "aca-unrelated"}],
    )

    with pytest.raises(
        RuntimeError,
        match="Expected one backend Container App, found \\[\\]",
    ):
        MODULE.find_app_names("rg-env")


def test_find_app_names_rejects_multiple_matches(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_az",
        lambda *args: [
            {"name": "aca-backend-primary"},
            {"name": "aca-backend-secondary"},
            {"name": "aca-frontend"},
        ],
    )

    with pytest.raises(RuntimeError, match="Expected one backend Container App"):
        MODULE.find_app_names("rg-env")


def test_list_package_versions_paginates_until_final_page(monkeypatch):
    requests = []

    def fake_package_request(url, token, method="GET"):
        requests.append((url, token, method))
        if url.endswith("page=1"):
            return [version(i, "2026-08-01T00:00:00Z", f"sha-{i}") for i in range(100)]
        if url.endswith("page=2"):
            return [version(100, "2026-08-02T00:00:00Z", "sha-100")]
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(MODULE, "package_request", fake_package_request)

    versions = MODULE.list_package_versions(
        "freeman9844", "jjflipbook-azure-backend", "token"
    )

    assert len(versions) == 101
    assert requests == [
        (
            "https://api.github.com/users/freeman9844/packages/container/"
            "jjflipbook-azure-backend/versions?per_page=100&page=1",
            "token",
            "GET",
        ),
        (
            "https://api.github.com/users/freeman9844/packages/container/"
            "jjflipbook-azure-backend/versions?per_page=100&page=2",
            "token",
            "GET",
        ),
    ]


def test_main_keeps_manifest_referenced_by_retained_tag(monkeypatch):
    child_digest = "sha256:" + "a" * 64
    versions = [
        version(7, "2026-08-07T00:00:00Z", "sha-current"),
        version(6, "2026-08-06T00:00:00Z"),
        version(5, "2026-08-05T00:00:00Z"),
        version(4, "2026-08-04T00:00:00Z"),
        version(3, "2026-08-03T00:00:00Z"),
        version(2, "2026-08-02T00:00:00Z"),
        version(1, "2026-08-01T00:00:00Z", name=child_digest),
    ]
    deleted = []
    inspected = []

    def fake_run(command, **kwargs):
        inspected.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"manifests": [{"digest": child_digest}]}),
            stderr="",
        )

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "owner")
    monkeypatch.setenv("AZURE_ENV_NAME", "env")
    monkeypatch.setattr(MODULE, "PACKAGES", {"backend": "app"})
    monkeypatch.setattr(MODULE, "find_app_names", lambda resource_group: {"backend": "ca"})
    monkeypatch.setattr(
        MODULE,
        "protected_revision_images",
        lambda resource_group, app_name: {"ghcr.io/owner/app:sha-current"},
    )
    monkeypatch.setattr(
        MODULE,
        "list_package_versions",
        lambda owner, package, token: versions,
    )
    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(
        MODULE,
        "delete_package_version",
        lambda owner, package, version_id, token: deleted.append(version_id),
    )

    MODULE.main()

    assert inspected == [
        ["docker", "manifest", "inspect", "ghcr.io/owner/app:sha-current"]
    ]
    assert deleted == [2]


def test_main_keeps_digest_pinned_revision_manifest_graph(monkeypatch):
    current_index = "sha256:" + "1" * 64
    current_child = "sha256:" + "2" * 64
    pinned_index = "sha256:" + "a" * 64
    pinned_child = "sha256:" + "b" * 64
    versions = [
        version(
            8,
            "2026-08-08T00:00:00Z",
            "sha-current",
            name=current_index,
        ),
        version(7, "2026-08-07T00:00:00Z", name=current_child),
        version(6, "2026-08-06T00:00:00Z"),
        version(5, "2026-08-05T00:00:00Z"),
        version(4, "2026-08-04T00:00:00Z"),
        version(3, "2026-08-03T00:00:00Z"),
        version(2, "2026-08-02T00:00:00Z", name=pinned_index),
        version(1, "2026-08-01T00:00:00Z", name=pinned_child),
    ]
    protected_image = f"ghcr.io/owner/app:sha-current@{pinned_index}"
    deleted = []
    inspected = []

    def fake_run(command, **kwargs):
        inspected.append(command)
        image = command[-1]
        digest = pinned_child if image.endswith(pinned_index) else current_child
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"manifests": [{"digest": digest}]}),
            stderr="",
        )

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "owner")
    monkeypatch.setenv("AZURE_ENV_NAME", "env")
    monkeypatch.setattr(MODULE, "PACKAGES", {"backend": "app"})
    monkeypatch.setattr(MODULE, "find_app_names", lambda resource_group: {"backend": "ca"})
    monkeypatch.setattr(
        MODULE,
        "protected_revision_images",
        lambda resource_group, app_name: {protected_image},
    )
    monkeypatch.setattr(
        MODULE,
        "list_package_versions",
        lambda owner, package, token: versions,
    )
    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(
        MODULE,
        "delete_package_version",
        lambda owner, package, version_id, token: deleted.append(version_id),
    )

    MODULE.main()

    assert inspected == [
        ["docker", "manifest", "inspect", "ghcr.io/owner/app:sha-current"],
        ["docker", "manifest", "inspect", f"ghcr.io/owner/app@{pinned_index}"],
    ]
    assert deleted == [3]


def test_run_az_propagates_cli_errors(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=2, cmd=["az"])

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        MODULE.run_az("containerapp", "list")


def test_package_request_propagates_github_errors(monkeypatch):
    error = urllib.error.HTTPError(
        "https://api.github.com/failure",
        500,
        "boom",
        hdrs=None,
        fp=None,
    )

    def fake_urlopen(request):
        raise error

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(urllib.error.HTTPError):
        MODULE.package_request("https://api.github.com/failure", "token")


def test_package_request_sends_bearer_token_header(monkeypatch):
    captured = {}

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request):
        captured["authorization"] = request.get_header("Authorization")
        return FakeResponse()

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)

    assert MODULE.package_request("https://api.github.com/success", "token") is None
    assert captured["authorization"] == "Bearer" + " " + "token"
    assert captured["authorization"] != "******"

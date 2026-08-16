import importlib.util
from pathlib import Path
import subprocess
import urllib.error

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_ghcr_versions.py"
SPEC = importlib.util.spec_from_file_location("cleanup_ghcr_versions", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def version(version_id, created_at, *tags):
    return {
        "id": version_id,
        "created_at": created_at,
        "metadata": {"container": {"tags": list(tags)}},
    }


def revision(created_at, *images):
    return {
        "properties": {
            "createdTime": created_at,
            "template": {
                "containers": [{"image": image} for image in images],
            },
        }
    }


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


def test_protected_revision_tags_uses_two_newest_revisions(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "run_az",
        lambda *args: [
            revision("2026-08-01T00:00:00Z", "ghcr.io/owner/app:sha-1"),
            revision("2026-08-03T00:00:00Z", "ghcr.io/owner/app:sha-3"),
            revision("2026-08-02T00:00:00Z", "ghcr.io/owner/app:sha-2"),
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
            ),
            revision(
                "2026-08-02T00:00:00Z",
                "registry.example:5443/owner/app:port-tag@sha256:beadfeed",
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
            )
        ],
    )

    with pytest.raises(RuntimeError, match="no immutable tag"):
        MODULE.protected_revision_tags("rg-env", "app-name")


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
    assert captured["authorization"] == "Bearer token"

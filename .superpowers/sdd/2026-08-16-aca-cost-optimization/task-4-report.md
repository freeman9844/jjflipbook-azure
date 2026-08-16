# Task 4 Report

## Summary
- Added `scripts/cleanup_ghcr_versions.py` using only Python standard-library modules.
- Added `backend/tests/test_ghcr_cleanup.py` for rollback-safe retention selection, ACA revision tag protection, pagination, and Azure/GitHub error propagation.
- Left workflow files untouched and did not run live GitHub package deletion.

## TDD Evidence
1. Added the initial retention tests first.
2. Ran `pytest tests/test_ghcr_cleanup.py -v` from `backend/` and confirmed collection failed because `scripts/cleanup_ghcr_versions.py` did not exist.
3. Implemented minimal retention logic and got the first three tests green.
4. Added failing tests for revision-tag protection, version pagination, and Azure/GitHub error propagation.
5. Implemented the remaining script functions and reran the targeted test file to green.

## Validation
- `cd backend && pytest tests/test_ghcr_cleanup.py -v`
- `python3 -m py_compile scripts/cleanup_ghcr_versions.py backend/tests/test_ghcr_cleanup.py`
- `git diff --check`

## Self-Review
- Verified user-scoped GHCR package endpoints are used for flat packages.
- Confirmed deletion candidates always exclude the newest five versions and any versions tagged by the newest two ACA revisions.
- Confirmed pagination continues until the final short page.
- Confirmed Azure CLI and GitHub API exceptions are not swallowed.

## Commit
- `edcf48a` — `chore: retain rollback-safe ghcr images`

## Concerns
- The script is intentionally destructive when `main()` runs in CI, so workflow integration should continue to guard execution behind the existing fail-closed deployment checks from Task 3.

---

## Task 4 Fix Round 1

### Summary
- Added `immutable_tag_from_image_ref()` so revision protection strips any `@digest`, inspects only the final image path segment, and rejects untagged or digest-only references.
- Updated `protected_revision_tags()` to use the helper without changing retention-selection behavior.
- Added regression coverage for digest-pinned image refs, registry-port image refs, and zero/multiple `find_app_names()` matches.

### Validation Evidence
- `cd backend && PYTHONPATH=. python3 -m pytest tests/test_ghcr_cleanup.py -v`

```text
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /home/jungwoonlee/.copilot/session-state/872f4a12-c6b3-420a-a3c9-dfe173c5f2ad/files/jjflipbook-azure/.worktrees/aca-cost-optimization/backend
configfile: pytest.ini
plugins: anyio-4.14.2
collecting ... collected 12 items

tests/test_ghcr_cleanup.py::test_keeps_five_newest_versions PASSED       [  8%]
tests/test_ghcr_cleanup.py::test_keeps_protected_rollback_tag_even_when_old PASSED [ 16%]
tests/test_ghcr_cleanup.py::test_keeps_untagged_version_if_it_is_among_five_newest PASSED [ 25%]
tests/test_ghcr_cleanup.py::test_protected_revision_tags_uses_two_newest_revisions PASSED [ 33%]
tests/test_ghcr_cleanup.py::test_protected_revision_tags_extracts_tag_from_digest_pinned_images PASSED [ 41%]
tests/test_ghcr_cleanup.py::test_protected_revision_tags_rejects_images_without_tags PASSED [ 50%]
tests/test_ghcr_cleanup.py::test_find_app_names_rejects_zero_matches PASSED [ 58%]
tests/test_ghcr_cleanup.py::test_find_app_names_rejects_multiple_matches PASSED [ 66%]
tests/test_ghcr_cleanup.py::test_list_package_versions_paginates_until_final_page PASSED [ 75%]
tests/test_ghcr_cleanup.py::test_run_az_propagates_cli_errors PASSED     [ 83%]
tests/test_ghcr_cleanup.py::test_package_request_propagates_github_errors PASSED [ 91%]
tests/test_ghcr_cleanup.py::test_package_request_sends_bearer_token_header PASSED [100%]

============================== 12 passed in 0.02s ==============================
```

- `python3 -m py_compile scripts/cleanup_ghcr_versions.py backend/tests/test_ghcr_cleanup.py`
- `git diff --check`

Both completed successfully with no output.

### Self-Review
- Verified `ghcr.io/owner/image:sha-tag@sha256:deadbeef` protects `sha-tag` instead of the digest suffix.
- Verified digest-only refs such as `ghcr.io/owner/image@sha256:deadbeef` fail closed with `RuntimeError`.
- Verified registry ports do not interfere because tag parsing is limited to the final path segment.
- Verified `find_app_names()` now has explicit failure coverage for zero and multiple matches.
- Confirmed package retention semantics remain unchanged outside the safer revision-tag parsing.

### Concerns
- None.

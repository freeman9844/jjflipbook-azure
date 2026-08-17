# JJFlipBook Azure 구독 이전 배포 계획

Status: Planned
Mode: Parallel rebuild and verified cutover
Source: 8dd0dabf-d8c0-4651-a846-5b13e18e05eb
Target: 43ab425a-c793-4f2e-b71a-0af7a14f26d2
Tenant: 1716e63d-ed31-49bf-aa16-5effd27bc340
Environment/RG: jjflipbook-p2 / rg-jjflipbook-p2
Location: koreacentral

## References

- Design: `docs/superpowers/specs/2026-08-17-azure-subscription-migration-design.md`
- Execution plan: `docs/superpowers/plans/2026-08-17-azure-subscription-migration.md`
- Deployment workflow: `.github/workflows/azure-dev.yml`

## Local proof files

- `.azure/migration/source-freeze.json`
- `.azure/migration/data-verification.json`
- `.azure/migration/smoke-attestation.json`

## Planned runbook

1. Confirm GitHub deployment variables now target subscription `43ab425a-c793-4f2e-b71a-0af7a14f26d2` in tenant `1716e63d-ed31-49bf-aa16-5effd27bc340`.
2. Run the `validate_only=true` workflow preview and inspect the log before any full deployment.
3. Execute one full target workflow only after data sync is ready; rely on workflow concurrency to queue the same subscription/environment instead of overlapping the `resources` ARM deployment.
4. Resolve the target Frontend Container App URL, verify `/` and `/api/backend/healthz`, then run the operator-visible smoke test.
5. Keep `.azure/migration/` local-only and retain the proof files above until the source environment deletion gate is explicitly approved.
6. After verified cutover and approval, update this file to `Status: Deployed` with the final workflow IDs, commit SHA, target URL, verification digests, and source cleanup proof.

## Guardrails

- Do not commit secrets, SAS tokens, copied data, or attestation payload contents.
- Do not push or run GitHub/Azure side-effect steps from this local preparation task.

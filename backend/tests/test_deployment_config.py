import json
import os
import shutil
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "azure-dev.yml"
BASH = shutil.which("bash")
AZURE_TENANT_ID = "1716e63d-ed31-49bf-aa16-5effd27bc340"
SYNC_BLOBS_SCRIPT = ROOT / "scripts" / "sync_subscription_blobs.sh"


def _load_generated_template():
    return json.loads((ROOT / "infra" / "main.json").read_text())


def _load_workflow():
    return WORKFLOW.read_text()


def _workflow_job_env(workflow):
    start = workflow.index("    env:\n") + len("    env:\n")
    end = workflow.index("    steps:\n", start)
    return workflow[start:end]


def _workflow_step(workflow, step_name):
    marker = f"      - name: {step_name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - name: ", start + len(marker))
    if end == -1:
        return workflow[start:]
    return workflow[start:end]


def _assert_in_order(text, *needles):
    positions = [text.index(needle) for needle in needles]
    assert positions == sorted(positions)


def _iter_resource_tree(resource):
    yield resource

    for child in resource.get("resources", []):
        yield from _iter_resource_tree(child)

    nested_template = resource.get("properties", {}).get("template")
    if isinstance(nested_template, dict):
        yield from _iter_resources(nested_template)


def _iter_resources(template):
    for resource in template.get("resources", []):
        yield from _iter_resource_tree(resource)


def _resources_of_type(template, resource_type):
    return [
        resource
        for resource in _iter_resources(template)
        if resource.get("type") == resource_type
    ]


def _find_container_app(template, container_name):
    matches = [
        resource
        for resource in _resources_of_type(template, "Microsoft.App/containerApps")
        if any(
            container.get("name") == container_name
            for container in resource["properties"]["template"]["containers"]
        )
    ]

    assert len(matches) == 1
    return matches[0]


def _find_scale_rule(app, rule_name):
    rules = app["properties"]["template"]["scale"]["rules"]
    matches = [rule for rule in rules if rule.get("name") == rule_name]

    assert len(matches) == 1
    return matches[0]


def _write_fake_azcopy(fake_bin, log_file):
    fake_azcopy = fake_bin / "azcopy"
    fake_azcopy.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

{{
  printf 'argv:'
  for arg in "$@"; do
    printf ' [%s]' "$arg"
  done
  printf '\\n'
  printf 'AZCOPY_AUTO_LOGIN_TYPE=%s\\n' "${{AZCOPY_AUTO_LOGIN_TYPE-}}"
  printf 'AZCOPY_TENANT_ID=%s\\n' "${{AZCOPY_TENANT_ID-}}"
}} >> "{log_file}"
"""
    )
    fake_azcopy.chmod(0o755)


def _blob_sync_env(
    tmp_path,
    mode,
    *,
    with_azcopy=True,
    env_overrides=None,
    unset_env=(),
):
    workdir = tmp_path / mode
    fake_bin = workdir / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    log_file = workdir / "azcopy.log"

    if with_azcopy:
        _write_fake_azcopy(fake_bin, log_file)

    env = os.environ.copy()
    env.update(
        {
            "AZURE_TENANT_ID": AZURE_TENANT_ID,
            "SOURCE_STORAGE_ACCOUNT": "sourceaccount",
            "TARGET_STORAGE_ACCOUNT": "targetaccount",
            "BLOB_CONTAINER_NAME": "flipbooks",
        }
    )
    if env_overrides:
        env.update(env_overrides)

    for variable in unset_env:
        env.pop(variable, None)

    if with_azcopy:
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
    else:
        env["PATH"] = str(fake_bin)

    return env, log_file


def _run_blob_sync_result(
    tmp_path,
    mode,
    *,
    with_azcopy=True,
    env_overrides=None,
    unset_env=(),
):
    if BASH is None:
        raise RuntimeError("bash is required for blob sync tests")

    env, log_file = _blob_sync_env(
        tmp_path,
        mode,
        with_azcopy=with_azcopy,
        env_overrides=env_overrides,
        unset_env=unset_env,
    )
    result = subprocess.run(
        [BASH, str(SYNC_BLOBS_SCRIPT), mode],
        env=env,
        capture_output=True,
        text=True,
    )
    return result, log_file


def _run_blob_sync(
    tmp_path,
    mode,
    *,
    env_overrides=None,
    unset_env=(),
):
    result, log_file = _run_blob_sync_result(
        tmp_path,
        mode,
        env_overrides=env_overrides,
        unset_env=unset_env,
    )
    assert result.returncode == 0, result.stderr
    assert log_file.exists()
    return log_file.read_text()


def test_blob_sync_uses_azure_cli_identity_and_final_exact_mirror(tmp_path):
    initial = _run_blob_sync(tmp_path, "initial")
    final = _run_blob_sync(tmp_path, "final")

    assert "--from-to=BlobBlob" in initial
    assert "--recursive=true" in initial
    assert "--delete-destination=false" in initial
    assert "--delete-destination=true" in final
    assert "AZCOPY_AUTO_LOGIN_TYPE=AZCLI" in final
    assert f"AZCOPY_TENANT_ID={AZURE_TENANT_ID}" in final


def test_blob_sync_rejects_invalid_mode(tmp_path):
    result, log_file = _run_blob_sync_result(tmp_path, "bogus")

    assert result.returncode == 1
    assert "Mode must be initial or final." in result.stderr
    assert not log_file.exists()


def test_blob_sync_rejects_same_source_and_target_account(tmp_path):
    result, log_file = _run_blob_sync_result(
        tmp_path,
        "initial",
        env_overrides={
            "SOURCE_STORAGE_ACCOUNT": "sameaccount",
            "TARGET_STORAGE_ACCOUNT": "sameaccount",
        },
    )

    assert result.returncode == 1
    assert "Source and target Storage Accounts must differ." in result.stderr
    assert not log_file.exists()


def test_blob_sync_requires_azcopy(tmp_path):
    result, log_file = _run_blob_sync_result(
        tmp_path,
        "initial",
        with_azcopy=False,
    )

    assert result.returncode == 1
    assert "azcopy v10 is required." in result.stderr
    assert not log_file.exists()


@pytest.mark.parametrize(
    ("unset_env", "expected_error"),
    [
        (("AZURE_TENANT_ID",), "AZURE_TENANT_ID is required"),
        (("SOURCE_STORAGE_ACCOUNT",), "SOURCE_STORAGE_ACCOUNT is required"),
        (("TARGET_STORAGE_ACCOUNT",), "TARGET_STORAGE_ACCOUNT is required"),
        (("BLOB_CONTAINER_NAME",), "BLOB_CONTAINER_NAME is required"),
    ],
)
def test_blob_sync_requires_environment_variables(
    tmp_path,
    unset_env,
    expected_error,
):
    result, log_file = _run_blob_sync_result(
        tmp_path,
        "initial",
        unset_env=unset_env,
    )

    assert result.returncode == 1
    assert expected_error in result.stderr
    assert not log_file.exists()


def test_backend_disables_uvicorn_access_log():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
    assert '"--no-access-log"' in dockerfile


def test_images_link_to_source_repository():
    expected = (
        'LABEL org.opencontainers.image.source='
        '"https://github.com/freeman9844/jjflipbook-azure"'
    )
    assert expected in (ROOT / "backend" / "Dockerfile").read_text()
    assert expected in (ROOT / "frontend" / "Dockerfile").read_text()


def test_frontend_backend_url_is_runtime_only():
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text()
    assert "ARG NEXT_PUBLIC_BACKEND_URL" not in dockerfile
    assert "ENV NEXT_PUBLIC_BACKEND_URL" not in dockerfile


def test_frontend_container_uses_reproducible_node_22_build():
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text()
    node_image = (
        "node:22-alpine@"
        "sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32"
    )
    assert dockerfile.count(f"FROM {node_image}") == 2
    assert "RUN npm ci --legacy-peer-deps --loglevel=error" in dockerfile
    assert "RUN npm install" not in dockerfile
    assert "ENV NODE_ENV=production" in dockerfile


def test_backend_base_image_and_runtime_dependencies_are_pinned():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
    python_image = (
        "python:3.11-slim@"
        "sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1"
    )
    assert dockerfile.count(f"FROM {python_image}") == 2

    runtime_requirements = (
        ROOT / "backend" / "requirements.txt"
    ).read_text().splitlines()
    runtime_packages = {
        line.split("==", 1)[0].lower()
        for line in runtime_requirements
        if line and not line.startswith("#")
    }
    assert all(
        "==" in line
        for line in runtime_requirements
        if line and not line.startswith("#")
    )
    assert "pytest" not in runtime_packages
    assert "httpx" not in runtime_packages
    assert "pygments" not in runtime_packages
    assert "python-dotenv" not in runtime_packages
    assert "packaging" in runtime_packages

    development_requirements = (
        ROOT / "backend" / "requirements-dev.txt"
    ).read_text()
    assert "-r requirements.txt" in development_requirements
    assert "pytest==9.1.1" in development_requirements
    assert "httpx==0.28.1" in development_requirements


def test_frontend_runtime_removes_sharp_after_disabling_image_optimization():
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text()
    next_config = (ROOT / "frontend" / "next.config.ts").read_text()

    assert ".next/standalone/node_modules/@img" in dockerfile
    assert ".next/standalone/node_modules/sharp" in dockerfile
    assert "test ! -e .next/standalone/node_modules/@img" in dockerfile
    assert "test ! -e .next/standalone/node_modules/sharp" in dockerfile
    assert "unoptimized: true" in next_config


def test_bicep_uses_ghcr_image_parameters_and_has_no_acr():
    main = (ROOT / "infra" / "main.bicep").read_text()
    resources = (ROOT / "infra" / "resources.bicep").read_text()
    template = _load_generated_template()
    backend_app = _find_container_app(template, "backend")
    frontend_app = _find_container_app(template, "frontend")

    assert "param backendImage string" in main
    assert "param frontendImage string" in main
    assert "param backendImage string" in resources
    assert "param frontendImage string" in resources
    assert "image: backendImage" in resources
    assert "image: frontendImage" in resources
    assert "Microsoft.ContainerRegistry/registries" not in resources
    assert "AcrPull" not in resources
    assert "id-frontend-" not in resources
    assert "AZURE_CONTAINER_REGISTRY_ENDPOINT" not in main
    assert not _resources_of_type(template, "Microsoft.ContainerRegistry/registries")
    assert backend_app["identity"]["type"] == "UserAssigned"
    assert backend_app["identity"]["userAssignedIdentities"]
    assert "registries" not in backend_app["properties"]["configuration"]
    assert "identity" not in frontend_app
    assert "registries" not in frontend_app["properties"]["configuration"]


def test_bicep_defines_selected_scaling_policy():
    template = _load_generated_template()
    backend_app = _find_container_app(template, "backend")
    frontend_app = _find_container_app(template, "frontend")

    managed_environments = _resources_of_type(
        template, "Microsoft.App/managedEnvironments"
    )
    container_apps = _resources_of_type(template, "Microsoft.App/containerApps")
    assert len(managed_environments) == 1
    assert managed_environments[0]["apiVersion"] == "2026-01-01"
    assert len(container_apps) == 2
    assert {app["apiVersion"] for app in container_apps} == {"2026-01-01"}

    backend_ingress = backend_app["properties"]["configuration"]["ingress"]
    frontend_ingress = frontend_app["properties"]["configuration"]["ingress"]
    assert backend_ingress["external"] is False
    assert frontend_ingress["external"] is True

    backend_container = backend_app["properties"]["template"]["containers"][0]
    frontend_container = frontend_app["properties"]["template"]["containers"][0]
    backend_probes = backend_container["probes"]
    assert backend_container["resources"]["cpu"] == "[json('1.0')]"
    assert backend_container["resources"]["memory"] == "2Gi"
    assert frontend_container["resources"]["cpu"] == "[json('0.25')]"
    assert frontend_container["resources"]["memory"] == "0.5Gi"
    assert {probe["httpGet"]["path"] for probe in backend_probes} == {"/healthz"}

    backend_scale = backend_app["properties"]["template"]["scale"]
    frontend_scale = frontend_app["properties"]["template"]["scale"]
    for scale in (backend_scale, frontend_scale):
        assert scale["minReplicas"] == 0
        assert scale["maxReplicas"] == 2
        assert scale["cooldownPeriod"] == 60
        assert scale["pollingInterval"] == 30

    assert (
        _find_scale_rule(backend_app, "http-single")["http"]["metadata"][
            "concurrentRequests"
        ]
        == "1"
    )
    backend_cron_rule = _find_scale_rule(
        backend_app, "daily-warm-window"
    )["custom"]
    assert backend_cron_rule["type"] == "cron"
    assert backend_cron_rule["metadata"] == {
        "timezone": "Asia/Seoul",
        "start": "55 9 * * *",
        "end": "5 20 * * *",
        "desiredReplicas": "1",
    }
    assert _find_scale_rule(frontend_app, "http")["http"]["metadata"] == {
        "concurrentRequests": "10"
    }

    cron_rule = _find_scale_rule(frontend_app, "daily-warm-window")["custom"]
    assert cron_rule["type"] == "cron"
    assert cron_rule["metadata"] == {
        "timezone": "Asia/Seoul",
        "start": "55 9 * * *",
        "end": "5 20 * * *",
        "desiredReplicas": "1",
    }


def test_backend_excludes_health_from_application_telemetry():
    main_source = (ROOT / "backend" / "main.py").read_text()
    assert 'FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz")' in main_source


def test_bicep_disables_defender_only_at_storage_scope():
    resources = (ROOT / "infra" / "resources.bicep").read_text()
    template = _load_generated_template()
    defender_resources = _resources_of_type(
        template, "Microsoft.Security/defenderForStorageSettings"
    )

    assert "Microsoft.Security/defenderForStorageSettings@2025-06-01" in resources
    assert "scope: storage" in resources
    assert len(defender_resources) == 1
    assert defender_resources[0]["name"] == "current"
    assert defender_resources[0]["properties"] == {
        "isEnabled": False,
        "overrideSubscriptionLevelSettings": True,
    }
    assert "Microsoft.Storage/storageAccounts" in defender_resources[0]["scope"]


def test_parameter_file_maps_immutable_images():
    parameters = json.loads((ROOT / "infra" / "main.parameters.json").read_text())[
        "parameters"
    ]
    assert parameters["backendImage"]["value"] == "${BACKEND_IMAGE}"
    assert parameters["frontendImage"]["value"] == "${FRONTEND_IMAGE}"


def test_azd_uses_prebuilt_ghcr_images():
    azure_yaml = (ROOT / "azure.yaml").read_text()
    assert "image: ${BACKEND_IMAGE}" in azure_yaml
    assert "image: ${FRONTEND_IMAGE}" in azure_yaml
    assert "remoteBuild:" not in azure_yaml
    assert "project:" not in azure_yaml


def test_workflow_builds_ghcr_and_previews_before_provisioning():
    workflow = _load_workflow()
    assert "packages: write" in workflow
    assert "actions/checkout@v5" in workflow
    assert "Azure/setup-azd@v2.3.0" in workflow
    assert "docker/setup-buildx-action@v3" in workflow
    assert "docker/login-action@v3" in workflow
    assert workflow.count("docker/build-push-action@v6") == 2
    assert (
        "ghcr.io/freeman9844/jjflipbook-azure-backend:${{ github.sha }}" in workflow
    )
    assert (
        "ghcr.io/freeman9844/jjflipbook-azure-frontend:${{ github.sha }}" in workflow
    )
    assert "azd provision --preview --no-prompt" in workflow
    assert "azd provision --no-prompt" in workflow
    assert "azd deploy" not in workflow
    _assert_in_order(
        workflow,
        "azd provision --preview --no-prompt",
        "azd provision --no-prompt",
    )


def test_workflow_supports_preview_only_manual_runs():
    workflow = _load_workflow()

    assert "validate_only:" in workflow
    assert "type: boolean" in workflow
    assert "default: false" in workflow

    deploy_condition = (
        "if: ${{ github.event_name != 'workflow_dispatch' "
        "|| inputs.validate_only != true }}"
    )
    for step_name in (
        "Provision optimized infrastructure",
        "Wait for revision convergence",
        "Resolve frontend URL",
        "Smoke test deployment",
        "Clean up legacy Azure resources",
        "Clean up GHCR versions",
    ):
        assert deploy_condition in _workflow_step(workflow, step_name)


def test_workflow_uses_separate_buildkit_cache_scopes():
    workflow = _load_workflow()
    backend_step = _workflow_step(workflow, "Build and push backend image")
    frontend_step = _workflow_step(workflow, "Build and push frontend image")

    assert "cache-from: type=gha,scope=backend" in backend_step
    assert "cache-to: type=gha,mode=max,scope=backend" in backend_step
    assert "cache-from: type=gha,scope=frontend" in frontend_step
    assert "cache-to: type=gha,mode=max,scope=frontend" in frontend_step


def test_workflow_exports_smoke_attestation_through_github_env():
    workflow = _load_workflow()
    job_env = _workflow_job_env(workflow)
    export_step = _workflow_step(workflow, "Export smoke attestation path")

    assert "SMOKE_ATTESTATION_FILE:" not in job_env
    assert 'SMOKE_ATTESTATION_FILE: ${{ runner.temp }}/jjflipbook-smoke-attestation.json' not in workflow
    assert (
        'echo "SMOKE_ATTESTATION_FILE=$RUNNER_TEMP/jjflipbook-smoke-attestation.json" >> "$GITHUB_ENV"'
        in export_step
    )


def test_workflow_requires_public_gate_before_azure_auth_and_direct_az_use():
    workflow = _load_workflow()
    verify_step = _workflow_step(workflow, "Verify images are public")
    azure_cli_login_step = _workflow_step(workflow, "Log in to Azure CLI")
    azd_login_step = _workflow_step(workflow, "Log in with Azure (Federated Credentials)")
    resolve_frontend_step = _workflow_step(workflow, "Resolve frontend URL")

    assert "docker logout ghcr.io" in verify_step
    _assert_in_order(
        verify_step,
        "docker logout ghcr.io",
        'docker manifest inspect "$BACKEND_IMAGE" >/dev/null',
        'docker manifest inspect "$FRONTEND_IMAGE" >/dev/null',
    )
    assert "uses: azure/login@v2" in azure_cli_login_step
    assert "client-id: ${{ vars.AZURE_CLIENT_ID }}" in azure_cli_login_step
    assert "tenant-id: ${{ vars.AZURE_TENANT_ID }}" in azure_cli_login_step
    assert "subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}" in azure_cli_login_step
    assert "azd auth login" in azd_login_step
    assert "az containerapp list" in resolve_frontend_step
    assert 'echo "FRONTEND_URL=https://${frontend_fqdns[0]}" >> "$GITHUB_ENV"' in resolve_frontend_step
    _assert_in_order(
        workflow,
        "      - name: Verify images are public\n",
        "      - name: Log in to Azure CLI\n",
        "      - name: Log in with Azure (Federated Credentials)\n",
        "      - name: Preview infrastructure changes\n",
        "      - name: Provision optimized infrastructure\n",
        "      - name: Resolve frontend URL\n",
    )


def test_workflow_wires_smoke_and_legacy_cleanup_with_shared_environment():
    workflow = _load_workflow()
    convergence_step = _workflow_step(workflow, "Wait for revision convergence")
    smoke_step = _workflow_step(workflow, "Smoke test deployment")
    legacy_cleanup_step = _workflow_step(workflow, "Clean up legacy Azure resources")

    assert "bash scripts/wait_for_revision_convergence.sh" in convergence_step
    shared_assignments = (
        'FRONTEND_URL="$FRONTEND_URL"',
        'SMOKE_ATTESTATION_FILE="$SMOKE_ATTESTATION_FILE"',
    )
    for assignment in shared_assignments:
        assert assignment in smoke_step
        assert assignment in legacy_cleanup_step
    assert 'ADMIN_PASSWORD="${{ secrets.ADMIN_PASSWORD }}"' in smoke_step
    assert "bash scripts/smoke_test_deployment.sh" in smoke_step
    assert "bash scripts/cleanup_legacy_azure_resources.sh" in legacy_cleanup_step
    _assert_in_order(
        workflow,
        "      - name: Provision optimized infrastructure\n",
        "      - name: Wait for revision convergence\n",
        "      - name: Resolve frontend URL\n",
        "      - name: Smoke test deployment\n",
        "      - name: Clean up legacy Azure resources\n",
        "      - name: Clean up GHCR versions\n",
    )


def test_workflow_wires_ghcr_cleanup_environment():
    workflow = _load_workflow()
    ghcr_cleanup_step = _workflow_step(workflow, "Clean up GHCR versions")

    assert "python3 scripts/cleanup_ghcr_versions.py" in ghcr_cleanup_step
    assert "AZURE_ENV_NAME: ${{ env.AZURE_ENV_NAME }}" in ghcr_cleanup_step
    assert "GITHUB_REPOSITORY_OWNER: ${{ github.repository_owner }}" in ghcr_cleanup_step
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in ghcr_cleanup_step


def test_legacy_cleanup_waits_for_active_revisions_to_converge(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    counter = tmp_path / "revision-calls"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

if [[ "$1 $2" == "containerapp list" ]]; then
  printf '%s\n' '[{{"name":"ca-backend"}}]'
elif [[ "$1 $2 $3" == "containerapp revision list" ]]; then
  calls=0
  [[ -f "{counter}" ]] && calls="$(cat "{counter}")"
  calls=$((calls + 1))
  printf '%s' "$calls" > "{counter}"
  if (( calls == 1 )); then
    printf '%s\n' '[{{"properties":{{"active":true,"template":{{"containers":[{{"image":"acr.example/legacy:old"}}]}}}}}},{{"properties":{{"active":true,"template":{{"containers":[{{"image":"ghcr.io/freeman9844/backend:new"}}]}}}}}}]'
  else
    printf '%s\n' '[{{"properties":{{"active":true,"template":{{"containers":[{{"image":"ghcr.io/freeman9844/backend:new"}}]}}}}}}]'
  fi
elif [[ "$1 $2" == "acr list" || "$1 $2" == "identity list" ]]; then
  printf '%s\n' '[]'
else
  printf 'Unexpected az invocation: %s\n' "$*" >&2
  exit 2
fi
"""
    )
    fake_az.chmod(0o755)

    attestation = tmp_path / "attestation.json"
    attestation.write_text(
        json.dumps(
            {
                "completed": True,
                "FRONTEND_URL": "https://frontend.example",
            }
        )
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "AZURE_ENV_NAME": "jjflipbook",
            "FRONTEND_URL": "https://frontend.example",
            "SMOKE_ATTESTATION_FILE": str(attestation),
            "REVISION_VERIFY_ATTEMPTS": "2",
            "REVISION_VERIFY_DELAY_SECONDS": "0",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "cleanup_legacy_azure_resources.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert counter.read_text() == "2"


def test_revision_gate_waits_for_exact_healthy_images(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    backend_counter = tmp_path / "backend-calls"
    fake_az = fake_bin / "az"
    fake_az.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

if [[ "$1 $2" == "containerapp list" ]]; then
  printf '%s\n' '[{{"name":"ca-backend","tags":{{"azd-service-name":"backend"}}}},{{"name":"ca-frontend","tags":{{"azd-service-name":"frontend"}}}}]'
elif [[ "$1 $2 $3" == "containerapp revision list" ]]; then
  app=""
  while (( $# > 0 )); do
    if [[ "$1" == "--name" ]]; then
      app="$2"
      break
    fi
    shift
  done
  if [[ "$app" == "ca-backend" ]]; then
    calls=0
    [[ -f "{backend_counter}" ]] && calls="$(cat "{backend_counter}")"
    calls=$((calls + 1))
    printf '%s' "$calls" > "{backend_counter}"
    if (( calls == 1 )); then
      printf '%s\n' '[{{"properties":{{"active":true,"healthState":"Healthy","provisioningState":"Provisioned","template":{{"containers":[{{"image":"ghcr.io/freeman9844/backend:old"}}]}}}}}},{{"properties":{{"active":true,"healthState":"Healthy","provisioningState":"Provisioned","template":{{"containers":[{{"image":"ghcr.io/freeman9844/backend:new"}}]}}}}}}]'
    else
      printf '%s\n' '[{{"properties":{{"active":true,"healthState":"Healthy","provisioningState":"Provisioned","template":{{"containers":[{{"image":"ghcr.io/freeman9844/backend:new"}}]}}}}}}]'
    fi
  else
    printf '%s\n' '[{{"properties":{{"active":true,"healthState":"Healthy","provisioningState":"Provisioned","template":{{"containers":[{{"image":"ghcr.io/freeman9844/frontend:new"}}]}}}}}}]'
  fi
else
  printf 'Unexpected az invocation: %s\n' "$*" >&2
  exit 2
fi
"""
    )
    fake_az.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "AZURE_ENV_NAME": "jjflipbook",
            "BACKEND_IMAGE": "ghcr.io/freeman9844/backend:new",
            "FRONTEND_IMAGE": "ghcr.io/freeman9844/frontend:new",
            "REVISION_VERIFY_ATTEMPTS": "2",
            "REVISION_VERIFY_DELAY_SECONDS": "0",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "wait_for_revision_convergence.sh")],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert backend_counter.read_text() == "2"

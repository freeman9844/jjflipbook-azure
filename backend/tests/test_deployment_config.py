import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_generated_template():
    return json.loads((ROOT / "infra" / "main.json").read_text())


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
    assert backend_container["resources"]["cpu"] == "[json('1.0')]"
    assert backend_container["resources"]["memory"] == "2Gi"
    assert frontend_container["resources"]["cpu"] == "[json('0.25')]"
    assert frontend_container["resources"]["memory"] == "0.5Gi"

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
    workflow = (ROOT / ".github" / "workflows" / "azure-dev.yml").read_text()
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
    assert "docker manifest inspect" in workflow
    assert 'SMOKE_ATTESTATION_FILE: ${{ runner.temp }}/jjflipbook-smoke-attestation.json' in workflow
    assert "az containerapp list" in workflow
    assert '>> "$GITHUB_ENV"' in workflow
    assert workflow.count("ADMIN_PASSWORD: ${{ secrets.ADMIN_PASSWORD }}") >= 2
    assert workflow.count("INTERNAL_API_KEY: ${{ secrets.INTERNAL_API_KEY }}") >= 2
    assert workflow.count("SESSION_SECRET: ${{ secrets.SESSION_SECRET }}") >= 2
    assert "azd provision --preview --no-prompt" in workflow
    assert "azd provision --no-prompt" in workflow
    assert "azd deploy" not in workflow
    assert workflow.index("azd provision --preview --no-prompt") < workflow.index(
        "azd provision --no-prompt"
    )
    assert workflow.index("azd provision --no-prompt") < workflow.index(
        "az containerapp list"
    )
    assert workflow.index("az containerapp list") < workflow.index(
        "scripts/smoke_test_deployment.sh"
    )
    assert workflow.index("scripts/smoke_test_deployment.sh") < workflow.index(
        "scripts/cleanup_legacy_azure_resources.sh"
    )
    assert workflow.index("scripts/cleanup_legacy_azure_resources.sh") < workflow.index(
        "scripts/cleanup_ghcr_versions.py"
    )
    assert "scripts/smoke_test_deployment.sh" in workflow
    assert "scripts/cleanup_legacy_azure_resources.sh" in workflow
    assert "scripts/cleanup_ghcr_versions.py" in workflow
    assert "GITHUB_REPOSITORY_OWNER: ${{ github.repository_owner }}" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow

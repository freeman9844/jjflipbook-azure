import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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


def test_bicep_defines_selected_scaling_policy():
    resources = (ROOT / "infra" / "resources.bicep").read_text()

    assert "cpu: json('0.25')" in resources
    assert "memory: '0.5Gi'" in resources
    assert "cooldownPeriod: 60" in resources
    assert "timezone: 'Asia/Seoul'" in resources
    assert "start: '55 9 * * *'" in resources
    assert "end: '5 20 * * *'" in resources
    assert "desiredReplicas: '1'" in resources
    assert resources.count("type: 'cron'") == 1


def test_bicep_disables_defender_only_at_storage_scope():
    resources = (ROOT / "infra" / "resources.bicep").read_text()

    assert "Microsoft.Security/defenderForStorageSettings@2025-06-01" in resources
    assert "scope: storage" in resources
    assert "name: 'current'" in resources
    assert "isEnabled: false" in resources
    assert "overrideSubscriptionLevelSettings: true" in resources


def test_parameter_file_maps_immutable_images():
    parameters = json.loads((ROOT / "infra" / "main.parameters.json").read_text())[
        "parameters"
    ]
    assert parameters["backendImage"]["value"] == "${BACKEND_IMAGE}"
    assert parameters["frontendImage"]["value"] == "${FRONTEND_IMAGE}"

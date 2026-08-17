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
DELETE_SOURCE_ENVIRONMENT_SCRIPT = ROOT / "scripts" / "delete_source_environment.sh"
APPROVED_SOURCE_SUBSCRIPTION_ID = "8dd0dabf-d8c0-4651-a846-5b13e18e05eb"
APPROVED_TARGET_SUBSCRIPTION_ID = "43ab425a-c793-4f2e-b71a-0af7a14f26d2"
APPROVED_RESOURCE_GROUP = "rg-jjflipbook-p2"
TARGET_FRONTEND_URL = "https://jjflipbook-target.example"
EXPECTED_GITHUB_SHA = "0123456789abcdef0123456789abcdef01234567"
TARGET_WORKFLOW_RUN_ID = "424242"
AZURE_CLIENT_ID = "b94f6e8e-f306-4922-9649-f35f8dcf77b7"
MIGRATION_PRINCIPAL_OBJECT_ID = "3a403f87-69cc-4ac8-bca3-c30b687d8b7d"
BACKEND_PRINCIPAL_ID = "0d25dd84-70a8-4e79-8a79-319e6432cef1"
OIDC_SP_OBJECT_ID = "d4cf309e-8f89-44c3-916b-c3278ff8fb58"
TARGET_STORAGE_RESOURCE_ID = (
    f"/subscriptions/{APPROVED_TARGET_SUBSCRIPTION_ID}"
    f"/resourceGroups/{APPROVED_RESOURCE_GROUP}"
    "/providers/Microsoft.Storage/storageAccounts/stjjflipbooktarget"
)
TARGET_COSMOS_ACCOUNT = "cosmos-jjflipbook-target"
TARGET_COSMOS_ROLE_ASSIGNMENT_ID = "4b5d0fca-b579-4612-a62d-95fbfdd1ce91"
TARGET_LOG_WORKSPACE = "0f35cfd2-6d59-4cfe-9963-f8a935fa84a1"
CONFIRM_DELETE_SOURCE_RG = (
    f"delete:{APPROVED_SOURCE_SUBSCRIPTION_ID}:{APPROVED_RESOURCE_GROUP}"
)


def _deep_copy_json(data):
    return json.loads(json.dumps(data))


def _deep_update(target, overrides):
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
    return target


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _default_migration_attestation():
    return {
        "schema_version": 1,
        "completed": True,
        "source_subscription_id": APPROVED_SOURCE_SUBSCRIPTION_ID,
        "target_subscription_id": APPROVED_TARGET_SUBSCRIPTION_ID,
        "source_resource_group": APPROVED_RESOURCE_GROUP,
        "target_resource_group": APPROVED_RESOURCE_GROUP,
        "source_storage_account": "stjjflipbooksource",
        "target_storage_account": "stjjflipbooktarget",
        "blob": {"matched": True},
        "cosmos": {
            "matched": True,
            "source_url_references_remaining": 0,
            "containers": {},
        },
    }


def _default_smoke_attestation():
    return {
        "FRONTEND_URL": TARGET_FRONTEND_URL,
        "completed": True,
    }


def _default_freeze_state():
    return {
        "schema_version": 1,
        "subscription_id": APPROVED_SOURCE_SUBSCRIPTION_ID,
        "resource_group": APPROVED_RESOURCE_GROUP,
        "frozen": True,
        "apps": [
            {
                "service": "backend",
                "name": "ca-backend-source",
                "ingress": {
                    "external": False,
                    "targetPort": 8000,
                    "transport": "Auto",
                    "allowInsecure": False,
                },
                "active_revisions": ["ca-backend-source--000001"],
            },
            {
                "service": "frontend",
                "name": "ca-frontend-source",
                "ingress": {
                    "external": True,
                    "targetPort": 3000,
                    "transport": "Auto",
                    "allowInsecure": False,
                },
                "active_revisions": ["ca-frontend-source--000001"],
            },
        ],
    }


def _target_app(name, service):
    if service == "backend":
        http_rule = {
            "name": "http-single",
            "http": {"metadata": {"concurrentRequests": "1"}},
        }
    else:
        http_rule = {
            "name": "http",
            "http": {"metadata": {"concurrentRequests": "10"}},
        }
    return {
        "name": name,
        "tags": {"azd-service-name": service},
        "properties": {
            "template": {
                "scale": {
                    "rules": [
                        {
                            "name": "daily-warm-window",
                            "custom": {
                                "type": "cron",
                                "metadata": {
                                    "timezone": "Asia/Seoul",
                                    "start": "55 9 * * *",
                                    "end": "5 20 * * *",
                                    "desiredReplicas": "1",
                                },
                            },
                        },
                        http_rule,
                    ]
                }
            }
        },
    }


def _source_live_app(name, service):
    return {
        "name": name,
        "tags": {"azd-service-name": service},
        "properties": {"configuration": {}},
    }


def _revision(
    image,
    created_time,
    *,
    name=None,
    active=True,
    health="Healthy",
    provisioning="Provisioned",
):
    return {
        "name": name or image.rsplit("/", 1)[-1].replace(":", "--"),
        "properties": {
            "active": active,
            "createdTime": created_time,
            "healthState": health,
            "provisioningState": provisioning,
            "template": {
                "containers": [
                    {
                        "image": image,
                    }
                ]
            },
        },
    }


def _default_gh_run():
    return {
        "status": "completed",
        "conclusion": "success",
        "headSha": EXPECTED_GITHUB_SHA,
        "workflowName": "Azure deployment",
    }


def _default_az_scenario():
    backend_image = (
        f"ghcr.io/freeman9844/jjflipbook-azure-backend:{EXPECTED_GITHUB_SHA}"
    )
    frontend_image = (
        f"ghcr.io/freeman9844/jjflipbook-azure-frontend:{EXPECTED_GITHUB_SHA}"
    )
    return {
        "expected": {
            "source_subscription_id": APPROVED_SOURCE_SUBSCRIPTION_ID,
            "target_subscription_id": APPROVED_TARGET_SUBSCRIPTION_ID,
            "source_resource_group": APPROVED_RESOURCE_GROUP,
            "target_resource_group": APPROVED_RESOURCE_GROUP,
            "target_storage_resource_id": TARGET_STORAGE_RESOURCE_ID,
            "target_cosmos_account": TARGET_COSMOS_ACCOUNT,
            "target_cosmos_role_assignment_id": TARGET_COSMOS_ROLE_ASSIGNMENT_ID,
            "migration_principal_object_id": MIGRATION_PRINCIPAL_OBJECT_ID,
            "azure_client_id": AZURE_CLIENT_ID,
        },
        "freeze_state_verification": {
            "subscription_id": APPROVED_SOURCE_SUBSCRIPTION_ID,
            "resource_group": APPROVED_RESOURCE_GROUP,
        },
        "target_apps": [
            _target_app("ca-backend-target", "backend"),
            _target_app("ca-frontend-target", "frontend"),
        ],
        "target_revisions": {
            "ca-backend-target": [
                _revision(
                    backend_image,
                    "2026-08-17T01:23:45Z",
                    name="ca-backend-target--000001",
                )
            ],
            "ca-frontend-target": [
                _revision(
                    frontend_image,
                    "2026-08-17T01:24:00Z",
                    name="ca-frontend-target--000001",
                )
            ],
        },
        "target_revision_created_times": {
            "ca-backend-target": "2026-08-17T01:23:45Z",
            "ca-frontend-target": "2026-08-17T01:24:00Z",
        },
        "source_apps": [
            _source_live_app("ca-backend-source", "backend"),
            _source_live_app("ca-frontend-source", "frontend"),
        ],
        "source_revisions": {
            "ca-backend-source": [
                {
                    "name": "ca-backend-source--000001",
                    "properties": {"active": False},
                }
            ],
            "ca-frontend-source": [
                {
                    "name": "ca-frontend-source--000001",
                    "properties": {"active": False},
                }
            ],
        },
        "backend_identity_name": "id-backend-jjflipbook-p2",
        "backend_principal_id": BACKEND_PRINCIPAL_ID,
        "storage_role_count": "1",
        "backend_role_names": "Storage Blob Data Contributor",
        "cosmos_role_count": "1",
        "log_workspace": TARGET_LOG_WORKSPACE,
        "error_count": "0",
        "oidc_sp_object_id": OIDC_SP_OBJECT_ID,
    }


FAKE_AZ_SCRIPT = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ARGS = sys.argv[1:]
LOG_PATH = Path(os.environ["FAKE_AZ_LOG"])
STATE_DIR = Path(os.environ["FAKE_AZ_STATE_DIR"])
SCENARIO = json.loads(Path(os.environ["FAKE_AZ_SCENARIO"]).read_text(encoding="utf-8"))
EXPECTED = SCENARIO["expected"]
FREEZE_STATE_VERIFICATION = SCENARIO.get("freeze_state_verification", {})
SOURCE_VERIFICATION_SUBSCRIPTION_ID = FREEZE_STATE_VERIFICATION.get(
    "subscription_id", EXPECTED["source_subscription_id"]
)
SOURCE_VERIFICATION_RESOURCE_GROUP = FREEZE_STATE_VERIFICATION.get(
    "resource_group", EXPECTED["source_resource_group"]
)
STATE_DIR.mkdir(parents=True, exist_ok=True)


def write_log(line):
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\\n")


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)


def marker(name):
    marker_path = STATE_DIR / name.replace(" ", "_")
    if not marker_path.exists():
        marker_path.write_text("1", encoding="utf-8")
        write_log(name)


def arg_value(flag):
    if flag not in ARGS:
        fail(f"Missing {flag}: {' '.join(ARGS)}")
    index = ARGS.index(flag)
    if index + 1 >= len(ARGS):
        fail(f"Missing value for {flag}: {' '.join(ARGS)}")
    return ARGS[index + 1]


def print_json(value):
    print(json.dumps(value))


write_log("az " + " ".join(ARGS).replace("\\n", "\\\\n"))

if ARGS[:2] == ["containerapp", "list"]:
    subscription = arg_value("--subscription")
    resource_group = arg_value("--resource-group")
    if (
        subscription == EXPECTED["target_subscription_id"]
        and resource_group == EXPECTED["target_resource_group"]
    ):
        marker("verify target")
        print_json(SCENARIO["target_apps"])
        raise SystemExit(0)
    if (
        subscription == SOURCE_VERIFICATION_SUBSCRIPTION_ID
        and resource_group == SOURCE_VERIFICATION_RESOURCE_GROUP
    ):
        marker("verify source frozen")
        print_json(SCENARIO["source_apps"])
        raise SystemExit(0)
    fail(f"Unexpected containerapp list scope: {subscription}/{resource_group}")

if ARGS[:3] == ["containerapp", "revision", "list"]:
    subscription = arg_value("--subscription")
    resource_group = arg_value("--resource-group")
    app_name = arg_value("--name")
    if (
        subscription == EXPECTED["target_subscription_id"]
        and resource_group == EXPECTED["target_resource_group"]
    ):
        if "--query" in ARGS:
            query = arg_value("--query")
            if query != "[?properties.active].properties.createdTime | [0]":
                fail(f"Unexpected target revision query: {query}")
            print(SCENARIO["target_revision_created_times"][app_name])
            raise SystemExit(0)
        print_json(SCENARIO["target_revisions"][app_name])
        raise SystemExit(0)
    if (
        subscription == SOURCE_VERIFICATION_SUBSCRIPTION_ID
        and resource_group == SOURCE_VERIFICATION_RESOURCE_GROUP
    ):
        print_json(SCENARIO["source_revisions"][app_name])
        raise SystemExit(0)
    fail(f"Unexpected revision scope for {app_name}: {subscription}/{resource_group}")

if ARGS[:2] == ["identity", "list"]:
    if arg_value("--subscription") != EXPECTED["target_subscription_id"]:
        fail("Unexpected identity list subscription")
    if arg_value("--resource-group") != EXPECTED["target_resource_group"]:
        fail("Unexpected identity list resource group")
    if arg_value("--query") != "[?starts_with(name, 'id-backend-')].name | [0]":
        fail("Unexpected identity list query")
    print(SCENARIO["backend_identity_name"])
    raise SystemExit(0)

if ARGS[:2] == ["identity", "show"]:
    if arg_value("--subscription") != EXPECTED["target_subscription_id"]:
        fail("Unexpected identity show subscription")
    if arg_value("--resource-group") != EXPECTED["target_resource_group"]:
        fail("Unexpected identity show resource group")
    if arg_value("--name") != SCENARIO["backend_identity_name"]:
        fail("Unexpected identity show name")
    if arg_value("--query") != "principalId":
        fail("Unexpected identity show query")
    print(SCENARIO["backend_principal_id"])
    raise SystemExit(0)

if ARGS[:3] == ["role", "assignment", "list"]:
    if arg_value("--subscription") != EXPECTED["target_subscription_id"]:
        fail("Unexpected role assignment list subscription")
    if arg_value("--assignee-object-id") != SCENARIO["backend_principal_id"]:
        fail("Unexpected backend principal for role listing")
    if "--all" in ARGS:
        if arg_value("--query") != "[].roleDefinitionName | sort(@) | join(`,`, @)":
            fail("Unexpected all-role query")
        print(SCENARIO["backend_role_names"])
        raise SystemExit(0)
    if arg_value("--scope") != EXPECTED["target_storage_resource_id"]:
        fail("Unexpected storage scope")
    if (
        arg_value("--query")
        != "[?roleDefinitionName=='Storage Blob Data Contributor'] | length(@)"
    ):
        fail("Unexpected scoped storage role query")
    print(SCENARIO["storage_role_count"])
    raise SystemExit(0)

if ARGS[:5] == ["cosmosdb", "sql", "role", "assignment", "list"]:
    if arg_value("--subscription") != EXPECTED["target_subscription_id"]:
        fail("Unexpected cosmos role list subscription")
    if arg_value("--resource-group") != EXPECTED["target_resource_group"]:
        fail("Unexpected cosmos role list resource group")
    if arg_value("--account-name") != EXPECTED["target_cosmos_account"]:
        fail("Unexpected cosmos account name")
    expected_query = (
        "[?principalId=='"
        + SCENARIO["backend_principal_id"]
        + "' && ends_with(roleDefinitionId, '00000000-0000-0000-0000-000000000002')] | length(@)"
    )
    if arg_value("--query") != expected_query:
        fail("Unexpected cosmos role list query")
    print(SCENARIO["cosmos_role_count"])
    raise SystemExit(0)

if ARGS[:4] == ["monitor", "log-analytics", "workspace", "list"]:
    if arg_value("--subscription") != EXPECTED["target_subscription_id"]:
        fail("Unexpected workspace list subscription")
    if arg_value("--resource-group") != EXPECTED["target_resource_group"]:
        fail("Unexpected workspace list resource group")
    if arg_value("--query") != "[0].customerId":
        fail("Unexpected workspace list query")
    print(SCENARIO["log_workspace"])
    raise SystemExit(0)

if ARGS[:3] == ["monitor", "log-analytics", "query"]:
    if arg_value("--subscription") != EXPECTED["target_subscription_id"]:
        fail("Unexpected log query subscription")
    if arg_value("--workspace") != SCENARIO["log_workspace"]:
        fail("Unexpected log workspace id")
    query = arg_value("--analytics-query")
    if "datetime(2026-08-17T01:23:45Z)" not in query:
        fail("Final revision start missing from log query")
    if "(error|exception|traceback)" not in query:
        fail("Error filter missing from log query")
    if (
        "union withsource=SourceTable isfuzzy=true" not in query
        or 'SourceTable == "ContainerAppSystemLogs_CL"' not in query
        or "Error provisioning revision" not in query
        or "| where not(" not in query
    ):
        fail("Allowed platform provisioning filter missing from log query")
    for revisions in SCENARIO["target_revisions"].values():
        revision = next(
            item["name"]
            for item in revisions
            if item["properties"].get("active") is True
        )
        if revision not in query:
            fail(f"Active revision {revision} missing from log query")
    if arg_value("--query") != "[0].Count":
        fail("Unexpected log analytics output query")
    print(SCENARIO["error_count"])
    raise SystemExit(0)

if ARGS[:3] == ["ad", "sp", "show"]:
    if arg_value("--id") != EXPECTED["azure_client_id"]:
        fail("Unexpected Azure client id")
    if arg_value("--query") != "id":
        fail("Unexpected service principal query")
    print(SCENARIO["oidc_sp_object_id"])
    raise SystemExit(0)

if ARGS[:2] == ["group", "delete"]:
    if arg_value("--subscription") != EXPECTED["source_subscription_id"]:
        fail("Unexpected group delete subscription")
    if arg_value("--name") != EXPECTED["source_resource_group"]:
        fail("Unexpected group delete resource group")
    if "--yes" not in ARGS or "--no-wait" not in ARGS:
        fail("Group delete must use --yes --no-wait")
    marker("group delete")
    print_json({})
    raise SystemExit(0)

if ARGS[:2] == ["group", "wait"]:
    if arg_value("--subscription") != EXPECTED["source_subscription_id"]:
        fail("Unexpected group wait subscription")
    if arg_value("--name") != EXPECTED["source_resource_group"]:
        fail("Unexpected group wait resource group")
    if "--deleted" not in ARGS:
        fail("Group wait must require --deleted")
    if arg_value("--interval") != "15":
        fail("Unexpected group wait interval")
    if arg_value("--timeout") != "1800":
        fail("Unexpected group wait timeout")
    marker("group wait")
    print_json({})
    raise SystemExit(0)

if ARGS[:3] == ["role", "assignment", "delete"]:
    role = arg_value("--role")
    assignee = arg_value("--assignee-object-id")
    scope = arg_value("--scope")
    if role == "Contributor":
        if assignee != SCENARIO["oidc_sp_object_id"]:
            fail("Unexpected Contributor assignee")
        if scope != "/subscriptions/" + EXPECTED["source_subscription_id"]:
            fail("Unexpected Contributor scope")
        marker("delete source Contributor")
        print_json({})
        raise SystemExit(0)
    if role == "Role Based Access Control Administrator":
        if assignee != SCENARIO["oidc_sp_object_id"]:
            fail("Unexpected RBAC Administrator assignee")
        if scope != "/subscriptions/" + EXPECTED["source_subscription_id"]:
            fail("Unexpected RBAC Administrator scope")
        marker("delete source RBAC Administrator")
        print_json({})
        raise SystemExit(0)
    if role == "Storage Blob Data Contributor":
        if assignee != EXPECTED["migration_principal_object_id"]:
            fail("Unexpected storage cleanup assignee")
        if scope != EXPECTED["target_storage_resource_id"]:
            fail("Unexpected storage cleanup scope")
        marker("delete target temporary Storage role")
        print_json({})
        raise SystemExit(0)
    fail(f"Unexpected role assignment delete for role {role}")

if ARGS[:5] == ["cosmosdb", "sql", "role", "assignment", "delete"]:
    if arg_value("--subscription") != EXPECTED["target_subscription_id"]:
        fail("Unexpected cosmos delete subscription")
    if arg_value("--resource-group") != EXPECTED["target_resource_group"]:
        fail("Unexpected cosmos delete resource group")
    if arg_value("--account-name") != EXPECTED["target_cosmos_account"]:
        fail("Unexpected cosmos delete account")
    if arg_value("--role-assignment-id") != EXPECTED["target_cosmos_role_assignment_id"]:
        fail("Unexpected cosmos delete role assignment id")
    if "--yes" not in ARGS:
        fail("Cosmos delete must use --yes")
    marker("delete target temporary Cosmos role")
    print_json({})
    raise SystemExit(0)

fail("Unexpected az invocation: " + " ".join(ARGS))
"""


FAKE_GH_SCRIPT = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ARGS = sys.argv[1:]
LOG_PATH = Path(os.environ["FAKE_GH_LOG"])
RUN_DATA = json.loads(Path(os.environ["FAKE_GH_RESPONSE"]).read_text(encoding="utf-8"))
with LOG_PATH.open("a", encoding="utf-8") as handle:
    handle.write("gh " + " ".join(ARGS) + "\\n")

expected = [
    "run",
    "view",
    os.environ["EXPECTED_TARGET_WORKFLOW_RUN_ID"],
    "--repo",
    "freeman9844/jjflipbook-azure",
    "--json",
    "conclusion,headSha,status,workflowName",
]
if ARGS != expected:
    print("Unexpected gh invocation: " + " ".join(ARGS), file=sys.stderr)
    raise SystemExit(2)

print(json.dumps(RUN_DATA))
"""


def _log_text(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _apply_file_mode(path, mode):
    if mode == "missing":
        if path.exists() or path.is_symlink():
            path.unlink()
        return

    if mode == "symlink":
        original_text = path.read_text(encoding="utf-8")
        real_path = path.with_name(f"{path.name}.real")
        real_path.write_text(original_text, encoding="utf-8")
        path.unlink()
        path.symlink_to(real_path)
        return

    if mode == "directory":
        path.unlink()
        path.mkdir()
        return

    raise ValueError(f"Unsupported file mode: {mode}")


def _run_delete_source_environment(
    tmp_path,
    *,
    migration_attestation_overrides=None,
    smoke_attestation_overrides=None,
    freeze_state_overrides=None,
    gh_run_overrides=None,
    az_scenario_overrides=None,
    env_overrides=None,
    unset_env=(),
    file_modes=None,
):
    if BASH is None:
        raise RuntimeError("bash is required for source deletion tests")

    workdir = tmp_path / "delete-source-environment"
    fake_bin = workdir / "bin"
    fake_state_dir = workdir / "state"
    fake_bin.mkdir(parents=True, exist_ok=True)
    fake_state_dir.mkdir(parents=True, exist_ok=True)

    az_log = workdir / "az.log"
    gh_log = workdir / "gh.log"
    migration_attestation = workdir / "migration-attestation.json"
    smoke_attestation = workdir / "smoke-attestation.json"
    freeze_state = workdir / "source-freeze.json"
    gh_response = workdir / "gh-run.json"
    az_scenario_path = workdir / "az-scenario.json"

    migration_payload = _default_migration_attestation()
    smoke_payload = _default_smoke_attestation()
    freeze_payload = _default_freeze_state()
    gh_payload = _default_gh_run()
    az_scenario = _default_az_scenario()

    for payload, overrides in (
        (migration_payload, migration_attestation_overrides),
        (smoke_payload, smoke_attestation_overrides),
        (freeze_payload, freeze_state_overrides),
        (gh_payload, gh_run_overrides),
        (az_scenario, az_scenario_overrides),
    ):
        if overrides:
            _deep_update(payload, _deep_copy_json(overrides))

    migration_attestation.write_text(
        json.dumps(migration_payload),
        encoding="utf-8",
    )
    smoke_attestation.write_text(
        json.dumps(smoke_payload),
        encoding="utf-8",
    )
    freeze_state.write_text(
        json.dumps(freeze_payload),
        encoding="utf-8",
    )
    gh_response.write_text(
        json.dumps(gh_payload),
        encoding="utf-8",
    )
    az_scenario_path.write_text(
        json.dumps(az_scenario),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_AZ_LOG": str(az_log),
            "FAKE_AZ_STATE_DIR": str(fake_state_dir),
            "FAKE_AZ_SCENARIO": str(az_scenario_path),
            "FAKE_GH_LOG": str(gh_log),
            "FAKE_GH_RESPONSE": str(gh_response),
            "EXPECTED_TARGET_WORKFLOW_RUN_ID": TARGET_WORKFLOW_RUN_ID,
            "SOURCE_SUBSCRIPTION_ID": APPROVED_SOURCE_SUBSCRIPTION_ID,
            "TARGET_SUBSCRIPTION_ID": APPROVED_TARGET_SUBSCRIPTION_ID,
            "SOURCE_RESOURCE_GROUP": APPROVED_RESOURCE_GROUP,
            "TARGET_RESOURCE_GROUP": APPROVED_RESOURCE_GROUP,
            "TARGET_FRONTEND_URL": TARGET_FRONTEND_URL,
            "EXPECTED_GITHUB_SHA": EXPECTED_GITHUB_SHA,
            "TARGET_WORKFLOW_RUN_ID": TARGET_WORKFLOW_RUN_ID,
            "MIGRATION_ATTESTATION_FILE": str(migration_attestation),
            "SMOKE_ATTESTATION_FILE": str(smoke_attestation),
            "SOURCE_FREEZE_STATE_FILE": str(freeze_state),
            "AZURE_CLIENT_ID": AZURE_CLIENT_ID,
            "MIGRATION_PRINCIPAL_OBJECT_ID": MIGRATION_PRINCIPAL_OBJECT_ID,
            "TARGET_STORAGE_RESOURCE_ID": TARGET_STORAGE_RESOURCE_ID,
            "TARGET_COSMOS_ACCOUNT": TARGET_COSMOS_ACCOUNT,
            "TARGET_COSMOS_ROLE_ASSIGNMENT_ID": TARGET_COSMOS_ROLE_ASSIGNMENT_ID,
            "CONFIRM_DELETE_SOURCE_RG": CONFIRM_DELETE_SOURCE_RG,
        }
    )
    if env_overrides:
        env.update(env_overrides)
    for variable in unset_env:
        env.pop(variable, None)

    if file_modes:
        file_paths = {
            "MIGRATION_ATTESTATION_FILE": migration_attestation,
            "SMOKE_ATTESTATION_FILE": smoke_attestation,
            "SOURCE_FREEZE_STATE_FILE": freeze_state,
        }
        for variable, mode in file_modes.items():
            _apply_file_mode(file_paths[variable], mode)

    _write_executable(fake_bin / "az", FAKE_AZ_SCRIPT)
    _write_executable(fake_bin / "gh", FAKE_GH_SCRIPT)

    result = subprocess.run(
        [BASH, str(DELETE_SOURCE_ENVIRONMENT_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )
    return result, az_log, gh_log


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
    expected_source = (
        "https://sourceaccount.blob.core.windows.net/flipbooks"
    )
    expected_target = (
        "https://targetaccount.blob.core.windows.net/flipbooks"
    )

    assert f"argv: [sync] [{expected_source}] [{expected_target}]" in initial
    assert f"argv: [sync] [{expected_source}] [{expected_target}]" in final
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


def test_workflow_serializes_each_azure_environment():
    workflow = _load_workflow()

    assert workflow.startswith("name: Azure deployment\n")
    assert "concurrency:" in workflow
    assert (
        "group: azure-${{ vars.AZURE_SUBSCRIPTION_ID }}-"
        "${{ vars.AZURE_ENV_NAME }}" in workflow
    )
    assert "cancel-in-progress: false" in workflow


def test_migration_runbook_pins_target_region():
    deployment_plan = (ROOT / ".azure" / "deployment-plan.md").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Location: koreacentral" in deployment_plan
    assert "- 대상 리전: `koreacentral`" in readme
    assert (
        "gh variable list | awk '$1 == \"AZURE_LOCATION\" { print $2 }' "
        "| grep -Fx 'koreacentral'"
        in readme
    )


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


@pytest.mark.parametrize(
    ("variable", "mode"),
    [
        ("MIGRATION_ATTESTATION_FILE", "missing"),
        ("SMOKE_ATTESTATION_FILE", "symlink"),
        ("SOURCE_FREEZE_STATE_FILE", "directory"),
    ],
)
def test_delete_source_environment_rejects_non_regular_proof_files(
    tmp_path, variable, mode
):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        file_modes={variable: mode},
    )

    assert result.returncode != 0
    assert "must be a regular file" in result.stderr
    assert "group delete" not in _log_text(az_log)


@pytest.mark.parametrize(
    "env_overrides",
    [
        {"SOURCE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000"},
        {"TARGET_SUBSCRIPTION_ID": "11111111-1111-1111-1111-111111111111"},
    ],
)
def test_delete_source_environment_rejects_unapproved_subscription_ids(
    tmp_path, env_overrides
):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        env_overrides=env_overrides,
    )

    assert result.returncode != 0
    assert "approved subscription" in result.stderr
    assert "group delete" not in _log_text(az_log)


@pytest.mark.parametrize(
    "migration_overrides",
    [
        {"blob": {"matched": False}},
        {"cosmos": {"matched": False}},
    ],
)
def test_delete_source_environment_rejects_unmatched_migration_attestation(
    tmp_path, migration_overrides
):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        migration_attestation_overrides=migration_overrides,
    )

    assert result.returncode != 0
    assert "matched blob and cosmos" in result.stderr
    assert "group delete" not in _log_text(az_log)


def test_delete_source_environment_rejects_remaining_source_urls(tmp_path):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        migration_attestation_overrides={
            "cosmos": {"source_url_references_remaining": 1}
        },
    )

    assert result.returncode != 0
    assert "source_url_references_remaining" in result.stderr
    assert "group delete" not in _log_text(az_log)


def test_delete_source_environment_rejects_frontend_url_mismatch(tmp_path):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        smoke_attestation_overrides={"FRONTEND_URL": "https://wrong.example"},
    )

    assert result.returncode != 0
    assert "FRONTEND_URL proof" in result.stderr
    assert "group delete" not in _log_text(az_log)


@pytest.mark.parametrize(
    "gh_run_overrides",
    [
        {"status": "in_progress"},
        {"conclusion": "failure"},
        {"headSha": "ffffffffffffffffffffffffffffffffffffffff"},
        {"workflowName": "Different deployment"},
    ],
)
def test_delete_source_environment_rejects_non_matching_github_run(
    tmp_path, gh_run_overrides
):
    result, az_log, gh_log = _run_delete_source_environment(
        tmp_path,
        gh_run_overrides=gh_run_overrides,
    )

    assert result.returncode != 0
    assert "GitHub Actions run" in result.stderr
    gh_command = _log_text(gh_log)
    assert "--repo freeman9844/jjflipbook-azure" in gh_command
    assert "--json conclusion,headSha,status,workflowName" in gh_command
    assert "group delete" not in _log_text(az_log)


def test_delete_source_environment_rejects_source_not_marked_frozen(tmp_path):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        freeze_state_overrides={"frozen": False},
    )

    assert result.returncode != 0
    assert "State file is not marked frozen." in result.stderr
    assert "group delete" not in _log_text(az_log)


@pytest.mark.parametrize(
    ("freeze_state_overrides", "az_scenario_overrides"),
    [
        (
            {
                "subscription_id": "22222222-2222-2222-2222-222222222222",
            },
            {
                "freeze_state_verification": {
                    "subscription_id": "22222222-2222-2222-2222-222222222222",
                }
            },
        ),
        (
            {
                "resource_group": "rg-jjflipbook-other",
            },
            {
                "freeze_state_verification": {
                    "resource_group": "rg-jjflipbook-other",
                }
            },
        ),
    ],
)
def test_delete_source_environment_rejects_mismatched_freeze_state_scope(
    tmp_path, freeze_state_overrides, az_scenario_overrides
):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        freeze_state_overrides=freeze_state_overrides,
        az_scenario_overrides=az_scenario_overrides,
    )

    assert result.returncode != 0
    assert (
        "Source freeze state file must match SOURCE_SUBSCRIPTION_ID "
        "and SOURCE_RESOURCE_GROUP."
    ) in result.stderr
    assert "verify source frozen" not in _log_text(az_log)
    assert "group delete" not in _log_text(az_log)


@pytest.mark.parametrize(
    ("az_scenario_overrides", "expected_error"),
    [
        (
            {
                "target_apps": [
                    {
                        "name": "ca-backend-target",
                        "tags": {"azd-service-name": "backend"},
                        "properties": {
                            "template": {
                                "scale": {
                                    "rules": [
                                        {
                                            "name": "http-single",
                                            "http": {
                                                "metadata": {
                                                    "concurrentRequests": "1"
                                                }
                                            },
                                        }
                                    ]
                                }
                            }
                        },
                    },
                    _target_app("ca-frontend-target", "frontend"),
                ]
            },
            "scale rules",
        ),
        (
            {
                "target_revisions": {
                    "ca-backend-target": [
                        _revision(
                            "ghcr.io/freeman9844/jjflipbook-azure-backend:stale",
                            "2026-08-17T01:23:45Z",
                        )
                    ]
                }
            },
            "active revision proof",
        ),
    ],
)
def test_delete_source_environment_rejects_target_scale_and_revision_failures(
    tmp_path, az_scenario_overrides, expected_error
):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        az_scenario_overrides=az_scenario_overrides,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert "group delete" not in _log_text(az_log)


@pytest.mark.parametrize(
    ("az_scenario_overrides", "expected_error"),
    [
        ({"storage_role_count": "0"}, "Storage Blob Data Contributor"),
        (
            {
                "backend_role_names": (
                    "Storage Blob Data Contributor,Contributor"
                )
            },
            "no extra target Azure RBAC roles",
        ),
        ({"cosmos_role_count": "0"}, "Cosmos DB data-plane role"),
        ({"error_count": "3"}, "post-revision unexplained error logs"),
    ],
)
def test_delete_source_environment_rejects_backend_rbac_and_log_failures(
    tmp_path, az_scenario_overrides, expected_error
):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        az_scenario_overrides=az_scenario_overrides,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert "group delete" not in _log_text(az_log)


def test_delete_source_environment_rejects_wrong_confirmation(tmp_path):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        env_overrides={"CONFIRM_DELETE_SOURCE_RG": "delete:wrong"},
    )

    assert result.returncode != 0
    assert CONFIRM_DELETE_SOURCE_RG in result.stderr
    assert "group delete" not in _log_text(az_log)


@pytest.mark.parametrize(
    "missing_variable",
    [
        "TARGET_COSMOS_ACCOUNT",
        "TARGET_COSMOS_ROLE_ASSIGNMENT_ID",
    ],
)
def test_delete_source_environment_requires_target_cosmos_cleanup_identifiers(
    tmp_path, missing_variable
):
    result, az_log, _ = _run_delete_source_environment(
        tmp_path,
        unset_env=(missing_variable,),
    )

    assert result.returncode != 0
    assert missing_variable in result.stderr
    assert "group delete" not in _log_text(az_log)


def test_delete_source_environment_deletes_source_and_exact_cleanup_roles_in_order(
    tmp_path,
):
    result, az_log, gh_log = _run_delete_source_environment(tmp_path)

    assert result.returncode == 0, result.stderr
    az_events = [
        line
        for line in _log_text(az_log).splitlines()
        if not line.startswith("az ")
    ]
    assert az_events == [
        "verify target",
        "verify source frozen",
        "group delete",
        "group wait",
        "delete source Contributor",
        "delete source RBAC Administrator",
        "delete target temporary Storage role",
        "delete target temporary Cosmos role",
    ]
    assert "--json conclusion,headSha,status,workflowName" in _log_text(gh_log)

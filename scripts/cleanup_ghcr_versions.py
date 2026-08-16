import json
import os
import subprocess
import urllib.parse
import urllib.request


PACKAGES = {
    "backend": "jjflipbook-azure-backend",
    "frontend": "jjflipbook-azure-frontend",
}

ROLLBACK_USABLE = "usable"
ROLLBACK_AMBIGUOUS = "ambiguous"
ROLLBACK_UNUSABLE = "unusable"

HEALTHY_HEALTH_STATES = {"healthy"}
FAILED_HEALTH_STATES = {"unhealthy"}

USABLE_RUNNING_STATES = {
    "running",
    "running (at max)",
    "scale to 0",
    "scaling / processing",
}
FAILED_RUNNING_STATES = {
    "activation failed",
    "degraded",
    "deprovisioning",
    "failed",
}

USABLE_PROVISIONING_STATES = {"provisioned", "succeeded"}
FAILED_PROVISIONING_STATES = {"failed", "provisioning failed"}


def version_ids_to_delete(
    versions: list[dict], protected_tags: set[str], keep: int = 5
) -> list[int]:
    ordered = sorted(
        versions,
        key=lambda item: item["created_at"],
        reverse=True,
    )
    protected_ids = {item["id"] for item in ordered[:keep]}
    for item in ordered:
        tags = set(item.get("metadata", {}).get("container", {}).get("tags", []))
        if tags & protected_tags:
            protected_ids.add(item["id"])
    return [item["id"] for item in ordered if item["id"] not in protected_ids]


def run_az(*args: str) -> list[dict]:
    completed = subprocess.run(
        ["az", *args, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def package_request(url: str, token: str, method: str = "GET") -> dict | list | None:
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer" + " " + token,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request) as response:
        if response.status == 204:
            return None
        return json.load(response)


def find_app_names(resource_group: str) -> dict[str, str]:
    apps = run_az("containerapp", "list", "--resource-group", resource_group)
    result = {}
    for service in PACKAGES:
        matches = [app["name"] for app in apps if service in app["name"]]
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one {service} Container App, found {matches}"
            )
        result[service] = matches[0]
    return result


def immutable_tag_from_image_ref(image: str) -> str:
    reference = image.split("@", 1)[0]
    final_segment = reference.rsplit("/", 1)[-1]
    repository, separator, tag = final_segment.partition(":")
    if not repository or not separator or not tag:
        raise RuntimeError(f"Revision image has no immutable tag: {image}")
    return tag


def normalize_status(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.strip().lower().split())


def rollback_state(revision: dict) -> str:
    properties = revision.get("properties", {})
    health = normalize_status(properties.get("healthState"))
    running = normalize_status(properties.get("runningState"))
    provisioning = normalize_status(properties.get("provisioningState"))

    if (
        health in FAILED_HEALTH_STATES
        or running in FAILED_RUNNING_STATES
        or provisioning in FAILED_PROVISIONING_STATES
    ):
        return ROLLBACK_UNUSABLE

    if (
        health in HEALTHY_HEALTH_STATES
        and (
            running in USABLE_RUNNING_STATES
            or provisioning in USABLE_PROVISIONING_STATES
        )
    ) or (
        running in USABLE_RUNNING_STATES
        and provisioning in USABLE_PROVISIONING_STATES
    ):
        return ROLLBACK_USABLE

    return ROLLBACK_AMBIGUOUS


def revision_tags(revision: dict) -> set[str]:
    containers = revision["properties"]["template"]["containers"]
    return {
        immutable_tag_from_image_ref(container["image"])
        for container in containers
    }


def protected_revision_tags(resource_group: str, app_name: str) -> set[str]:
    revisions = run_az(
        "containerapp",
        "revision",
        "list",
        "--resource-group",
        resource_group,
        "--name",
        app_name,
    )
    revisions.sort(
        key=lambda item: item.get("properties", {}).get("createdTime", ""),
        reverse=True,
    )
    tags = set()
    for revision in revisions:
        if revision.get("properties", {}).get("active") is True:
            tags.update(revision_tags(revision))
    for revision in revisions:
        if revision.get("properties", {}).get("active") is True:
            continue
        state = rollback_state(revision)
        if state == ROLLBACK_UNUSABLE:
            continue
        tags.update(revision_tags(revision))
        if state == ROLLBACK_USABLE:
            break
    return tags


def list_package_versions(owner: str, package: str, token: str) -> list[dict]:
    encoded = urllib.parse.quote(package, safe="")
    versions = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/users/{owner}/packages/container/"
            f"{encoded}/versions?per_page=100&page={page}"
        )
        batch = package_request(url, token)
        assert isinstance(batch, list)
        versions.extend(batch)
        if len(batch) < 100:
            return versions
        page += 1


def delete_package_version(
    owner: str, package: str, version_id: int, token: str
) -> None:
    encoded = urllib.parse.quote(package, safe="")
    package_request(
        (
            f"https://api.github.com/users/{owner}/packages/container/"
            f"{encoded}/versions/{version_id}"
        ),
        token,
        method="DELETE",
    )


def main() -> None:
    token = os.environ["GITHUB_TOKEN"]
    owner = os.environ["GITHUB_REPOSITORY_OWNER"]
    resource_group = f"rg-{os.environ['AZURE_ENV_NAME']}"
    app_names = find_app_names(resource_group)

    for service, package in PACKAGES.items():
        protected = protected_revision_tags(resource_group, app_names[service])
        versions = list_package_versions(owner, package, token)
        delete_ids = version_ids_to_delete(versions, protected, keep=5)
        print(
            f"{package}: retaining {len(versions) - len(delete_ids)} versions; "
            f"protected tags={sorted(protected)}"
        )
        for version_id in delete_ids:
            delete_package_version(owner, package, version_id, token)
            print(f"{package}: deleted version {version_id}")


if __name__ == "__main__":
    main()

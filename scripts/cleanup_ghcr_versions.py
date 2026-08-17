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
    versions: list[dict],
    protected_tags: set[str],
    keep: int = 5,
    protected_digests: set[str] | None = None,
) -> list[int]:
    ordered = sorted(
        versions,
        key=lambda item: item["created_at"],
        reverse=True,
    )
    protected_ids = protected_version_ids(
        ordered,
        protected_tags,
        keep,
        protected_digests or set(),
    )
    referenced_digests = {
        digest.lower()
        for item in ordered
        if item["id"] in protected_ids
        for digest in item.get("metadata", {})
        .get("container", {})
        .get("referenced_digests", [])
    }
    for item in ordered:
        name = item.get("name", "").lower()
        if name in referenced_digests:
            protected_ids.add(item["id"])
    return [item["id"] for item in ordered if item["id"] not in protected_ids]


def protected_version_ids(
    versions: list[dict],
    protected_tags: set[str],
    keep: int,
    protected_digests: set[str] | None = None,
) -> set[int]:
    protected_ids = {item["id"] for item in versions[:keep]}
    normalized_digests = {
        digest.lower()
        for digest in (protected_digests or set())
    }
    for item in versions:
        tags = set(item.get("metadata", {}).get("container", {}).get("tags", []))
        if (
            tags & protected_tags
            or item.get("name", "").lower() in normalized_digests
        ):
            protected_ids.add(item["id"])
    return protected_ids


def manifest_references(image: str) -> set[str]:
    completed = subprocess.run(
        ["docker", "manifest", "inspect", image],
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads(completed.stdout)
    return {
        descriptor["digest"].lower()
        for descriptor in manifest.get("manifests", [])
    }


def attach_referenced_digests(
    versions: list[dict],
    protected_tags: set[str],
    protected_digests: set[str],
    owner: str,
    package: str,
    keep: int = 5,
) -> None:
    ordered = sorted(
        versions,
        key=lambda item: item["created_at"],
        reverse=True,
    )
    protected_ids = protected_version_ids(
        ordered,
        protected_tags,
        keep,
        protected_digests,
    )
    retained_tags = {
        tag
        for item in ordered
        if item["id"] in protected_ids
        for tag in item.get("metadata", {}).get("container", {}).get("tags", [])
    }
    referenced_digests = set()
    for tag in sorted(retained_tags):
        referenced_digests.update(
            manifest_references(f"ghcr.io/{owner}/{package}:{tag}")
        )
    for digest in sorted(protected_digests):
        referenced_digests.update(
            manifest_references(f"ghcr.io/{owner}/{package}@{digest}")
        )
    for item in ordered:
        if item["id"] in protected_ids:
            item.setdefault("metadata", {}).setdefault("container", {})[
                "referenced_digests"
            ] = sorted(referenced_digests)


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


def immutable_digest_from_image_ref(image: str) -> str | None:
    _, separator, digest = image.partition("@")
    if not separator:
        return None
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise RuntimeError(f"Revision image has invalid digest: {image}")
    return digest.lower()


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


def protected_revision_images(resource_group: str, app_name: str) -> set[str]:
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
    images = set()
    for revision in revisions:
        if revision.get("properties", {}).get("active") is True:
            images.update(
                container["image"]
                for container in revision["properties"]["template"]["containers"]
            )
    for revision in revisions:
        if revision.get("properties", {}).get("active") is True:
            continue
        state = rollback_state(revision)
        if state == ROLLBACK_UNUSABLE:
            continue
        images.update(
            container["image"]
            for container in revision["properties"]["template"]["containers"]
        )
        if state == ROLLBACK_USABLE:
            break
    return images


def protected_revision_tags(resource_group: str, app_name: str) -> set[str]:
    return {
        immutable_tag_from_image_ref(image)
        for image in protected_revision_images(resource_group, app_name)
    }


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
        protected_images = protected_revision_images(
            resource_group,
            app_names[service],
        )
        protected = {
            immutable_tag_from_image_ref(image)
            for image in protected_images
        }
        protected_digests = {
            digest
            for image in protected_images
            if (digest := immutable_digest_from_image_ref(image)) is not None
        }
        versions = list_package_versions(owner, package, token)
        attach_referenced_digests(
            versions,
            protected,
            protected_digests,
            owner,
            package,
            keep=5,
        )
        delete_ids = version_ids_to_delete(
            versions,
            protected,
            keep=5,
            protected_digests=protected_digests,
        )
        print(
            f"{package}: retaining {len(versions) - len(delete_ids)} versions; "
            f"protected tags={sorted(protected)}"
        )
        for version_id in delete_ids:
            delete_package_version(owner, package, version_id, token)
            print(f"{package}: deleted version {version_id}")


if __name__ == "__main__":
    main()

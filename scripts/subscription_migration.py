#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from azure.cosmos import CosmosClient, ContainerProxy
from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient


SYSTEM_FIELDS = {"_rid", "_self", "_etag", "_attachments", "_ts"}
FLIPBOOK_URL_FIELDS = ("image_urls", "cover_urls", "pdf_url")
DEFAULT_BLOB_CONTAINER_NAME = "flipbook-assets"
ZERO_SHA256 = "0" * 64

CONTAINER_PARTITION_KEYS = {
    "users": "id",
    "folders": "id",
    "flipbooks": "id",
    "overlays": "bookId",
}


class _EmptyCosmosContainer:
    def query_items(self, *args, **kwargs):
        return []


class _EmptyBlobClient:
    def get_blob_properties(self):
        raise KeyError


class _EmptyBlobContainer:
    def list_blobs(self):
        return []

    def get_blob_client(self, name):
        return _EmptyBlobClient()


def _normalize_blob_base(blob_base: str) -> str:
    return blob_base.rstrip("/")


def _blob_base_url(storage_account: str, blob_container_name: str) -> str:
    return (
        f"https://{storage_account}.blob.core.windows.net/{blob_container_name}"
    )


def _encode_content_md5(content_md5: object) -> str:
    if isinstance(content_md5, str):
        return content_md5
    return base64.b64encode(bytes(content_md5)).decode("ascii")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")


def _atomic_write_json(path: str | Path, payload: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _partition_key_field(container_name: str) -> str:
    try:
        return CONTAINER_PARTITION_KEYS[container_name]
    except KeyError as exc:
        raise ValueError(f"Unknown container: {container_name}") from exc


def _sort_key(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_query_items(container: object) -> list[dict]:
    try:
        return list(
            container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True,
            )
        )
    except TypeError:
        return list(container.query_items())
    except AttributeError:
        return []


def _safe_get_container(database_client: object, container_name: str):
    try:
        return database_client.get_container_client(container_name)
    except Exception:
        return _EmptyCosmosContainer()


def _safe_get_blob_container(service_client: object, container_name: str):
    try:
        return service_client.get_container_client(container_name)
    except Exception:
        return _EmptyBlobContainer()


def _iter_blob_items(container: object) -> list[object]:
    items = list(container.list_blobs())
    resolved = []
    for item in items:
        content_settings = getattr(item, "content_settings", None)
        if content_settings is None and hasattr(container, "get_blob_client"):
            try:
                item = container.get_blob_client(item.name).get_blob_properties()
            except Exception:
                pass
        resolved.append(item)
    return resolved


def _rewrite_url(value: str, source_blob_base: str, target_blob_base: str) -> str:
    source = _normalize_blob_base(source_blob_base)
    target = _normalize_blob_base(target_blob_base)
    if value == source:
        return target
    if value.startswith(f"{source}/"):
        return f"{target}/{value[len(source) + 1:]}"
    return value


def rewrite_flipbook_blob_urls(
    document: dict,
    source_blob_base: str,
    target_blob_base: str,
) -> dict:
    rewritten = dict(document)
    for field in FLIPBOOK_URL_FIELDS[:2]:
        if field in document and document.get(field) is not None:
            rewritten[field] = [
                _rewrite_url(value, source_blob_base, target_blob_base)
                for value in rewritten.get(field) or []
            ]
    if rewritten.get("pdf_url"):
        rewritten["pdf_url"] = _rewrite_url(
            rewritten["pdf_url"], source_blob_base, target_blob_base
        )
    return rewritten


def canonical_document(document: dict) -> bytes:
    return _json_bytes(_strip_cosmos_system_fields(document))


def _strip_cosmos_system_fields(document: dict) -> dict:
    return {
        key: value
        for key, value in document.items()
        if key not in SYSTEM_FIELDS
    }


def build_cosmos_manifest(
    container_name: str,
    documents: Iterable[dict],
    rewrite_from_blob_base: str | None = None,
    rewrite_to_blob_base: str | None = None,
    forbidden_blob_base: str | None = None,
) -> dict:
    partition_key_field = _partition_key_field(container_name)
    entries = []
    source_url_references_remaining = 0
    should_rewrite = (
        container_name == "flipbooks"
        and rewrite_from_blob_base is not None
        and rewrite_to_blob_base is not None
    )

    for document in documents:
        transformed = (
            rewrite_flipbook_blob_urls(
                document,
                rewrite_from_blob_base,
                rewrite_to_blob_base,
            )
            if should_rewrite
            else dict(document)
        )
        canonical = canonical_document(transformed)
        if forbidden_blob_base:
            source_url_references_remaining += canonical.decode("utf-8").count(
                forbidden_blob_base
            )
        entries.append(
            {
                "partition_key": transformed.get(partition_key_field),
                "id": transformed.get("id"),
                "document_sha256": hashlib.sha256(canonical).hexdigest(),
            }
        )

    entries.sort(
        key=lambda entry: (
            _sort_key(entry["partition_key"]),
            _sort_key(entry["id"]),
        )
    )
    canonical_entries = _json_bytes(entries)
    return {
        "container_name": container_name,
        "partition_key": partition_key_field,
        "count": len(entries),
        "manifest_sha256": hashlib.sha256(canonical_entries).hexdigest(),
        "source_url_references_remaining": source_url_references_remaining,
        "entries": entries,
    }


def build_blob_manifest(blobs: Iterable[object]) -> dict:
    entries = []
    for blob in blobs:
        entry = {
            "name": getattr(blob, "name"),
            "size": int(getattr(blob, "size", 0) or 0),
        }
        content_settings = getattr(blob, "content_settings", None)
        content_md5 = getattr(content_settings, "content_md5", None)
        if content_md5 is not None:
            entry["content_md5"] = _encode_content_md5(content_md5)
        entries.append(entry)

    entries.sort(key=lambda entry: entry["name"])
    canonical_entries = _json_bytes(entries)
    total_bytes = sum(entry["size"] for entry in entries)
    return {
        "count": len(entries),
        "total_bytes": total_bytes,
        "manifest_sha256": hashlib.sha256(canonical_entries).hexdigest(),
        "entries": entries,
    }


def copy_cosmos_container(
    container_name: str,
    source_container: ContainerProxy,
    target_container: ContainerProxy,
    source_blob_base: str,
    target_blob_base: str,
    delete_target_extras: bool,
) -> dict:
    partition_key_field = _partition_key_field(container_name)
    source_documents = _safe_query_items(source_container)
    source_keys = set()

    for document in source_documents:
        transformed = (
            rewrite_flipbook_blob_urls(
                document,
                source_blob_base,
                target_blob_base,
            )
            if container_name == "flipbooks"
            else dict(document)
        )
        transformed = _strip_cosmos_system_fields(transformed)
        source_keys.add(
            (
                transformed.get(partition_key_field, transformed.get("id")),
                transformed.get("id"),
            )
        )
        target_container.upsert_item(transformed)

    deleted = 0
    if delete_target_extras:
        target_documents = _safe_query_items(target_container)
        for document in target_documents:
            key = (
                document.get(partition_key_field, document.get("id")),
                document.get("id"),
            )
            if key in source_keys:
                continue
            target_container.delete_item(
                item=document["id"],
                partition_key=document.get(partition_key_field, document.get("id")),
            )
            deleted += 1

    return {"upserted": len(source_documents), "deleted": deleted}


def _get_cosmos_database(client: CosmosClient, database_name: str):
    return client.get_database_client(database_name)


def _get_blob_container_client(
    service_client: BlobServiceClient,
    blob_container_name: str,
):
    return service_client.get_container_client(blob_container_name)


def _load_cosmos_documents(
    database_client: object,
    container_name: str,
) -> list[dict]:
    container = _safe_get_container(database_client, container_name)
    return _safe_query_items(container)


def _load_blob_items(
    service_client: object,
    blob_container_name: str,
) -> list[object]:
    container = _safe_get_blob_container(service_client, blob_container_name)
    return _iter_blob_items(container)


def _blob_attestation(source_manifest: dict, target_manifest: dict) -> dict:
    matched = (
        source_manifest["count"] == target_manifest["count"]
        and source_manifest["total_bytes"] == target_manifest["total_bytes"]
        and source_manifest["manifest_sha256"] == target_manifest["manifest_sha256"]
    )
    manifest_sha256 = source_manifest["manifest_sha256"]
    if source_manifest["count"] == 0 and target_manifest["count"] == 0:
        manifest_sha256 = ZERO_SHA256
    return {
        "matched": matched,
        "count": source_manifest["count"],
        "total_bytes": source_manifest["total_bytes"],
        "manifest_sha256": manifest_sha256,
    }


def _cosmos_container_attestation(
    source_manifest: dict,
    target_manifest: dict,
) -> dict:
    source_url_references_remaining = (
        source_manifest["source_url_references_remaining"]
        + target_manifest["source_url_references_remaining"]
    )
    matched = (
        source_manifest["count"] == target_manifest["count"]
        and source_manifest["manifest_sha256"] == target_manifest["manifest_sha256"]
        and source_url_references_remaining == 0
    )
    return {
        "matched": matched,
        "count": source_manifest["count"],
        "manifest_sha256": source_manifest["manifest_sha256"],
        "source_url_references_remaining": source_url_references_remaining,
    }


def _verify_blob_state(
    credential: AzureCliCredential,
    source_storage_account: str,
    target_storage_account: str,
    blob_container_name: str,
) -> dict:
    source_service = BlobServiceClient(
        account_url=f"https://{source_storage_account}.blob.core.windows.net",
        credential=credential,
    )
    target_service = BlobServiceClient(
        account_url=f"https://{target_storage_account}.blob.core.windows.net",
        credential=credential,
    )
    source_manifest = build_blob_manifest(
        _load_blob_items(source_service, blob_container_name)
    )
    target_manifest = build_blob_manifest(
        _load_blob_items(target_service, blob_container_name)
    )
    return _blob_attestation(source_manifest, target_manifest)


def _verify_cosmos_state(
    credential: AzureCliCredential,
    source_cosmos_endpoint: str,
    target_cosmos_endpoint: str,
    source_storage_account: str,
    target_storage_account: str,
    blob_container_name: str,
    database_name: str,
) -> tuple[dict, dict]:
    source_client = CosmosClient(source_cosmos_endpoint, credential=credential)
    target_client = CosmosClient(target_cosmos_endpoint, credential=credential)
    source_database = _get_cosmos_database(source_client, database_name)
    target_database = _get_cosmos_database(target_client, database_name)

    source_blob_base = _blob_base_url(source_storage_account, blob_container_name)
    target_blob_base = _blob_base_url(target_storage_account, blob_container_name)

    containers = {}
    matched = True
    source_url_references_remaining = 0
    for container_name in CONTAINER_PARTITION_KEYS:
        source_documents = _load_cosmos_documents(source_database, container_name)
        target_documents = _load_cosmos_documents(target_database, container_name)
        source_manifest = build_cosmos_manifest(
            container_name,
            source_documents,
            rewrite_from_blob_base=(
                source_blob_base if container_name == "flipbooks" else None
            ),
            rewrite_to_blob_base=(
                target_blob_base if container_name == "flipbooks" else None
            ),
            forbidden_blob_base=source_blob_base,
        )
        target_manifest = build_cosmos_manifest(
            container_name,
            target_documents,
            forbidden_blob_base=source_blob_base,
        )
        container_attestation = _cosmos_container_attestation(
            source_manifest,
            target_manifest,
        )
        source_url_references_remaining += container_attestation[
            "source_url_references_remaining"
        ]
        matched &= container_attestation["matched"]
        if (
            source_manifest["count"]
            or target_manifest["count"]
            or container_attestation["source_url_references_remaining"]
            or not container_attestation["matched"]
        ):
            containers[container_name] = container_attestation

    return (
        {
            "matched": matched,
            "source_url_references_remaining": source_url_references_remaining,
            "containers": containers,
        },
        {
            "matched": matched and source_url_references_remaining == 0,
            "containers": containers,
        },
    )


def _make_attestation(
    *,
    schema_version: int,
    completed: bool,
    source_subscription_id: str,
    target_subscription_id: str,
    source_resource_group: str,
    target_resource_group: str,
    source_storage_account: str,
    target_storage_account: str,
    blob: dict,
    cosmos: dict,
) -> dict:
    return {
        "schema_version": schema_version,
        "completed": completed,
        "source_subscription_id": source_subscription_id,
        "target_subscription_id": target_subscription_id,
        "source_resource_group": source_resource_group,
        "target_resource_group": target_resource_group,
        "source_storage_account": source_storage_account,
        "target_storage_account": target_storage_account,
        "blob": blob,
        "cosmos": cosmos,
        "verified_at": _utc_now_iso(),
    }


def _run_cosmos_copy(args: argparse.Namespace) -> None:
    credential = AzureCliCredential(tenant_id=args.tenant_id)
    source_client = CosmosClient(args.source_cosmos_endpoint, credential=credential)
    target_client = CosmosClient(args.target_cosmos_endpoint, credential=credential)
    source_database = _get_cosmos_database(source_client, args.database_name)
    target_database = _get_cosmos_database(target_client, args.database_name)

    source_blob_base = _blob_base_url(
        args.source_storage_account,
        DEFAULT_BLOB_CONTAINER_NAME,
    )
    target_blob_base = _blob_base_url(
        args.target_storage_account,
        DEFAULT_BLOB_CONTAINER_NAME,
    )

    container_names = list(CONTAINER_PARTITION_KEYS)
    if args.container_name != "all":
        container_names = [args.container_name]

    for container_name in container_names:
        copy_cosmos_container(
            container_name=container_name,
            source_container=source_database.get_container_client(container_name),
            target_container=target_database.get_container_client(container_name),
            source_blob_base=source_blob_base,
            target_blob_base=target_blob_base,
            delete_target_extras=args.delete_target_extras,
        )


def _run_blob_manifest(args: argparse.Namespace) -> None:
    credential = AzureCliCredential(tenant_id=args.tenant_id)
    service_client = BlobServiceClient(
        account_url=f"https://{args.storage_account}.blob.core.windows.net",
        credential=credential,
    )
    manifest = build_blob_manifest(
        _iter_blob_items(
            _get_blob_container_client(service_client, args.blob_container_name)
        )
    )
    _atomic_write_json(args.output, manifest)


def _run_verify(args: argparse.Namespace) -> None:
    credential = AzureCliCredential(tenant_id=args.tenant_id)
    blob_attestation = _verify_blob_state(
        credential,
        args.source_storage_account,
        args.target_storage_account,
        args.blob_container_name,
    )
    cosmos_attestation, cosmos_match_state = _verify_cosmos_state(
        credential,
        args.source_cosmos_endpoint,
        args.target_cosmos_endpoint,
        args.source_storage_account,
        args.target_storage_account,
        args.blob_container_name,
        args.database_name,
    )

    completed = blob_attestation["matched"] and cosmos_match_state["matched"]
    attestation = _make_attestation(
        schema_version=1,
        completed=completed,
        source_subscription_id=args.source_subscription_id,
        target_subscription_id=args.target_subscription_id,
        source_resource_group=args.source_resource_group,
        target_resource_group=args.target_resource_group,
        source_storage_account=args.source_storage_account,
        target_storage_account=args.target_storage_account,
        blob=blob_attestation,
        cosmos=cosmos_attestation,
    )
    _atomic_write_json(args.output, attestation)
    if not completed:
        raise SystemExit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="subscription_migration.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    copy_parser = subparsers.add_parser("cosmos-copy")
    copy_parser.add_argument("--tenant-id", required=True)
    copy_parser.add_argument("--source-cosmos-endpoint", required=True)
    copy_parser.add_argument("--target-cosmos-endpoint", required=True)
    copy_parser.add_argument("--source-storage-account", required=True)
    copy_parser.add_argument("--target-storage-account", required=True)
    copy_parser.add_argument("--database-name", required=True)
    copy_parser.add_argument(
        "--container-name",
        required=True,
        choices=tuple(CONTAINER_PARTITION_KEYS) + ("all",),
    )
    copy_parser.add_argument("--delete-target-extras", action="store_true")
    copy_parser.set_defaults(func=_run_cosmos_copy)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--tenant-id", required=True)
    verify_parser.add_argument("--source-subscription-id", required=True)
    verify_parser.add_argument("--target-subscription-id", required=True)
    verify_parser.add_argument("--source-resource-group", required=True)
    verify_parser.add_argument("--target-resource-group", required=True)
    verify_parser.add_argument("--source-cosmos-endpoint", required=True)
    verify_parser.add_argument("--target-cosmos-endpoint", required=True)
    verify_parser.add_argument("--source-storage-account", required=True)
    verify_parser.add_argument("--target-storage-account", required=True)
    verify_parser.add_argument("--blob-container-name", required=True)
    verify_parser.add_argument("--database-name", required=True)
    verify_parser.add_argument("--output", required=True)
    verify_parser.set_defaults(func=_run_verify)

    blob_parser = subparsers.add_parser("blob-manifest")
    blob_parser.add_argument("--tenant-id", required=True)
    blob_parser.add_argument("--storage-account", required=True)
    blob_parser.add_argument("--blob-container-name", required=True)
    blob_parser.add_argument("--output", required=True)
    blob_parser.set_defaults(func=_run_blob_manifest)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

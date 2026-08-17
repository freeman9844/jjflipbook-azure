import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "subscription_migration.py"
SPEC = importlib.util.spec_from_file_location("subscription_migration", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def blob(name, size, content_md5=None):
    return SimpleNamespace(
        name=name,
        size=size,
        content_settings=SimpleNamespace(content_md5=content_md5),
    )


class FakeContainer:
    def __init__(self, documents):
        self.documents = [dict(item) for item in documents]
        self.upserted = []
        self.deleted = []

    def query_items(self, *args, **kwargs):
        return [dict(item) for item in self.documents]

    def upsert_item(self, item):
        copied = dict(item)
        self.upserted.append(copied)
        key = (copied.get("bookId", copied.get("id")), copied.get("id"))
        self.documents = [
            existing
            for existing in self.documents
            if (existing.get("bookId", existing.get("id")), existing.get("id"))
            != key
        ]
        self.documents.append(copied)

    def delete_item(self, item, partition_key):
        self.deleted.append((item, partition_key))
        self.documents = [
            existing
            for existing in self.documents
            if not (
                existing.get("id") == item
                and existing.get("bookId", existing.get("id")) == partition_key
            )
        ]


class FakeDatabaseClient:
    def __init__(self, containers):
        self.containers = containers

    def get_container_client(self, name):
        return self.containers.setdefault(name, FakeContainer([]))


class FakeCosmosClient:
    def __init__(self, endpoint, credential=None):
        self.endpoint = endpoint

    def get_database_client(self, name):
        return FAKE_COSMOS_DATABASES[self.endpoint][name]


class FakeBlobClient:
    def __init__(self, blob_properties):
        self.blob_properties = blob_properties

    def get_blob_properties(self):
        return self.blob_properties


class FakeBlobContainer:
    def __init__(self, blobs):
        self._blobs = {item.name: item for item in blobs}

    def list_blobs(self):
        return list(self._blobs.values())

    def get_blob_client(self, name):
        return FakeBlobClient(self._blobs[name])


class FakeBlobServiceClient:
    def __init__(self, account_url, credential=None):
        self.account_url = account_url

    def get_container_client(self, name):
        return FAKE_BLOB_CONTAINERS[self.account_url].setdefault(
            name, FakeBlobContainer([])
        )


FAKE_COSMOS_DATABASES = {}
FAKE_BLOB_CONTAINERS = {}


def test_rewrites_only_owned_flipbook_blob_urls():
    source = "https://stsource.blob.core.windows.net/flipbook-assets"
    target = "https://sttarget.blob.core.windows.net/flipbook-assets"
    document = {
        "id": "book-1",
        "image_urls": [f"{source}/flipbooks/book-1/page_1.webp"],
        "cover_urls": [f"{source}/flipbooks/book-1/cover_384.webp"],
        "pdf_url": f"{source}/flipbooks/book-1/original.pdf",
        "external_url": "https://example.com/keep",
        "_etag": "system",
    }

    rewritten = MODULE.rewrite_flipbook_blob_urls(document, source, target)

    assert rewritten["image_urls"] == [
        f"{target}/flipbooks/book-1/page_1.webp"
    ]
    assert rewritten["cover_urls"] == [
        f"{target}/flipbooks/book-1/cover_384.webp"
    ]
    assert rewritten["pdf_url"] == f"{target}/flipbooks/book-1/original.pdf"
    assert rewritten["external_url"] == "https://example.com/keep"
    assert document["image_urls"][0].startswith(source)


def test_canonical_document_removes_only_cosmos_system_fields():
    document = {
        "id": "book-1",
        "title": "Book",
        "_rid": "rid",
        "_self": "self",
        "_etag": "etag",
        "_attachments": "attachments/",
        "_ts": 123,
    }

    assert MODULE.canonical_document(document) == (
        b'{"id":"book-1","title":"Book"}'
    )


def test_cosmos_manifest_hashes_transformed_source_documents():
    source = "https://stsource.blob.core.windows.net/flipbook-assets"
    target = "https://sttarget.blob.core.windows.net/flipbook-assets"
    source_docs = [
        {
            "id": "book-1",
            "image_urls": [f"{source}/flipbooks/book-1/page_1.webp"],
        }
    ]
    target_docs = [
        {
            "id": "book-1",
            "image_urls": [f"{target}/flipbooks/book-1/page_1.webp"],
        }
    ]

    source_manifest = MODULE.build_cosmos_manifest(
        "flipbooks",
        source_docs,
        rewrite_from_blob_base=source,
        rewrite_to_blob_base=target,
        forbidden_blob_base=source,
    )
    target_manifest = MODULE.build_cosmos_manifest(
        "flipbooks",
        target_docs,
        forbidden_blob_base=source,
    )

    assert source_manifest["manifest_sha256"] == target_manifest["manifest_sha256"]
    assert source_manifest["source_url_references_remaining"] == 0
    assert target_manifest["source_url_references_remaining"] == 0


def test_blob_manifest_uses_name_size_and_available_md5():
    blobs = [
        blob("bgm/song.mp3", 12, b"\x01\x02"),
        blob("flipbooks/book/page.webp", 34, None),
    ]

    manifest = MODULE.build_blob_manifest(blobs)

    assert manifest["count"] == 2
    assert manifest["total_bytes"] == 46
    assert manifest["entries"][0] == {
        "name": "bgm/song.mp3",
        "size": 12,
        "content_md5": "AQI=",
    }


def test_copy_cosmos_container_upserts_transformed_docs_and_deletes_extras():
    source = FakeContainer(
        [
            {
                "id": "book-1",
                "image_urls": [
                    "https://stsource.blob.core.windows.net/"
                    "flipbook-assets/flipbooks/book-1/page_1.webp"
                ],
            }
        ]
    )
    target = FakeContainer([{"id": "old-book", "image_urls": []}])

    result = MODULE.copy_cosmos_container(
        container_name="flipbooks",
        source_container=source,
        target_container=target,
        source_blob_base=(
            "https://stsource.blob.core.windows.net/flipbook-assets"
        ),
        target_blob_base=(
            "https://sttarget.blob.core.windows.net/flipbook-assets"
        ),
        delete_target_extras=True,
    )

    assert result == {"upserted": 1, "deleted": 1}
    assert target.upserted[0]["image_urls"][0].startswith(
        "https://sttarget.blob.core.windows.net/"
    )
    assert target.deleted == [("old-book", "old-book")]


def test_blob_manifest_cli_writes_output_file(monkeypatch, tmp_path):
    account_url = "https://stsource.blob.core.windows.net"
    output = tmp_path / "blob-manifest.json"
    blobs = [blob("flipbooks/book/page.webp", 34, b"\x01\x02")]

    FAKE_BLOB_CONTAINERS.clear()
    FAKE_BLOB_CONTAINERS[account_url] = {
        "flipbook-assets": FakeBlobContainer(blobs),
    }

    credential_calls = []

    class FakeAzureCliCredential:
        def __init__(self, tenant_id=None):
            credential_calls.append(tenant_id)

    monkeypatch.setattr(MODULE, "AzureCliCredential", FakeAzureCliCredential)
    monkeypatch.setattr(MODULE, "BlobServiceClient", FakeBlobServiceClient)
    monkeypatch.setattr(
        MODULE.sys,
        "argv",
        [
            "subscription_migration.py",
            "blob-manifest",
            "--tenant-id",
            "tenant-1",
            "--storage-account",
            "stsource",
            "--blob-container-name",
            "flipbook-assets",
            "--output",
            str(output),
        ],
    )

    MODULE.main()

    assert credential_calls == ["tenant-1"]
    data = json.loads(output.read_text())
    assert data["count"] == 1
    assert data["total_bytes"] == 34
    assert data["entries"][0]["name"] == "flipbooks/book/page.webp"


def test_verify_cli_writes_success_attestation(monkeypatch, tmp_path):
    source_blob_base = "https://stsource.blob.core.windows.net/flipbook-assets"
    target_blob_base = "https://sttarget.blob.core.windows.net/flipbook-assets"
    source_cosmos_endpoint = "https://source.documents.azure.com:443/"
    target_cosmos_endpoint = "https://target.documents.azure.com:443/"
    source_storage_url = "https://stsource.blob.core.windows.net"
    target_storage_url = "https://sttarget.blob.core.windows.net"
    output = tmp_path / "verification.json"

    source_flipbooks = FakeContainer(
        [
            {
                "id": "book-1",
                "image_urls": [f"{source_blob_base}/flipbooks/book-1/page_1.webp"],
            }
        ]
    )
    target_flipbooks = FakeContainer(
        [
            {
                "id": "book-1",
                "image_urls": [f"{target_blob_base}/flipbooks/book-1/page_1.webp"],
            }
        ]
    )

    source_database = FakeDatabaseClient({"flipbooks": source_flipbooks})
    target_database = FakeDatabaseClient({"flipbooks": target_flipbooks})

    source_blob_container = FakeBlobContainer(
        [blob("flipbooks/book-1/page_1.webp", 11, b"\x10\x11")]
    )
    target_blob_container = FakeBlobContainer(
        [blob("flipbooks/book-1/page_1.webp", 11, b"\x10\x11")]
    )

    FAKE_COSMOS_DATABASES.clear()
    FAKE_COSMOS_DATABASES[source_cosmos_endpoint] = {"jjflipbook": source_database}
    FAKE_COSMOS_DATABASES[target_cosmos_endpoint] = {"jjflipbook": target_database}
    FAKE_BLOB_CONTAINERS.clear()
    FAKE_BLOB_CONTAINERS[source_storage_url] = {
        "flipbook-assets": source_blob_container,
    }
    FAKE_BLOB_CONTAINERS[target_storage_url] = {
        "flipbook-assets": target_blob_container,
    }

    credential_calls = []

    class FakeAzureCliCredential:
        def __init__(self, tenant_id=None):
            credential_calls.append(tenant_id)

    monkeypatch.setattr(MODULE, "AzureCliCredential", FakeAzureCliCredential)
    monkeypatch.setattr(MODULE, "CosmosClient", FakeCosmosClient)
    monkeypatch.setattr(MODULE, "BlobServiceClient", FakeBlobServiceClient)
    monkeypatch.setattr(
        MODULE.sys,
        "argv",
        [
            "subscription_migration.py",
            "verify",
            "--tenant-id",
            "tenant-1",
            "--source-subscription-id",
            "source-sub",
            "--target-subscription-id",
            "target-sub",
            "--source-resource-group",
            "rg-source",
            "--target-resource-group",
            "rg-target",
            "--source-cosmos-endpoint",
            source_cosmos_endpoint,
            "--target-cosmos-endpoint",
            target_cosmos_endpoint,
            "--source-storage-account",
            "stsource",
            "--target-storage-account",
            "sttarget",
            "--blob-container-name",
            "flipbook-assets",
            "--database-name",
            "jjflipbook",
            "--output",
            str(output),
        ],
    )

    MODULE.main()

    assert credential_calls == ["tenant-1"]
    data = json.loads(output.read_text())
    assert data["schema_version"] == 1
    assert data["completed"] is True
    assert data["source_subscription_id"] == "source-sub"
    assert data["target_subscription_id"] == "target-sub"
    assert data["blob"]["matched"] is True
    assert data["blob"]["count"] == 1
    assert data["blob"]["total_bytes"] == 11
    assert data["cosmos"]["matched"] is True
    assert data["cosmos"]["source_url_references_remaining"] == 0
    assert "flipbooks" in data["cosmos"]["containers"]

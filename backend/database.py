import os
import threading
from datetime import datetime, timezone, timedelta
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient, ContainerProxy
from urllib.parse import unquote, urlsplit
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContainerClient,
    generate_blob_sas,
)

COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "https://localhost:8081")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME", "jjflipbook")
STORAGE_ACCOUNT_NAME = os.getenv("STORAGE_ACCOUNT_NAME", "devstorageaccount")
BLOB_CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME", "flipbook-assets")

BLOB_BASE_URL = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{BLOB_CONTAINER_NAME}"

_lock = threading.Lock()
_credential = None
_cosmos_db = None
_blob_container = None

_delegation_key = None
_delegation_key_expiry: datetime | None = None
_sas_cache_lock = threading.Lock()
_signed_url_cache: dict[str, tuple[str, datetime]] = {}
_SIGNED_URL_CACHE_TTL = timedelta(minutes=90)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_credential() -> DefaultAzureCredential:
    """로컬은 az login 토큰, Azure 배포 시 Managed Identity를 자동 사용."""
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def get_container(name: str) -> ContainerProxy:
    """Cosmos DB 컨테이너 프록시를 lazy 초기화하여 반환한다. Thread-safe."""
    global _cosmos_db
    if _cosmos_db is None:
        with _lock:
            if _cosmos_db is None:
                client = CosmosClient(COSMOS_ENDPOINT, credential=_get_credential())
                _cosmos_db = client.get_database_client(COSMOS_DB_NAME)
    return _cosmos_db.get_container_client(name)


def get_blob_container() -> ContainerClient:
    """Blob 컨테이너 클라이언트를 lazy 초기화하여 반환한다. Thread-safe."""
    global _blob_container
    if _blob_container is None:
        with _lock:
            if _blob_container is None:
                _blob_container = ContainerClient(
                    account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net",
                    container_name=BLOB_CONTAINER_NAME,
                    credential=_get_credential(),
                )
    return _blob_container


def _get_user_delegation_key():
    global _delegation_key, _delegation_key_expiry
    now = datetime.now(timezone.utc)
    with _lock:
        if (
            _delegation_key is None
            or _delegation_key_expiry is None
            or (_delegation_key_expiry - now) < timedelta(hours=2, minutes=10)
        ):
            start = now - timedelta(minutes=5)
            expiry = now + timedelta(hours=8)
            service = BlobServiceClient(
                account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net",
                credential=_get_credential(),
            )
            _delegation_key = service.get_user_delegation_key(
                key_start_time=start,
                key_expiry_time=expiry,
            )
            _delegation_key_expiry = expiry
    return _delegation_key


def sign_url(url: str) -> str:
    if not url:
        return url

    parsed = urlsplit(url)
    expected_host = f"{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    container_prefix = f"/{BLOB_CONTAINER_NAME}/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected_host
        or not parsed.path.startswith(container_prefix)
    ):
        return url

    blob_name = unquote(parsed.path[len(container_prefix):])
    if not blob_name:
        return url

    now = _utc_now()
    with _sas_cache_lock:
        cached = _signed_url_cache.get(blob_name)
        if cached and cached[1] > now:
            return cached[0]

    token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT_NAME,
        container_name=BLOB_CONTAINER_NAME,
        blob_name=blob_name,
        user_delegation_key=_get_user_delegation_key(),
        permission=BlobSasPermissions(read=True),
        start=now - timedelta(minutes=5),
        expiry=now + timedelta(hours=2),
    )
    unsigned_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    signed_url = f"{unsigned_url}?{token}"
    with _sas_cache_lock:
        _signed_url_cache[blob_name] = (
            signed_url,
            now + _SIGNED_URL_CACHE_TTL,
        )
    return signed_url

import os
import threading
from datetime import datetime, timezone, timedelta
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient, ContainerProxy
from azure.storage.blob import (
    ContainerClient,
    BlobServiceClient,
    generate_container_sas,
    ContainerSasPermissions,
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

_sas_token: str | None = None
_sas_expiry: datetime | None = None


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


def get_container_sas() -> str:
    """컨테이너 수준 user-delegation SAS 쿼리 문자열을 반환한다 (선행 '?' 없음).

    토큰은 모듈 전역으로 캐시되며 만료 10분 전에 자동 갱신된다.
    """
    global _sas_token, _sas_expiry
    now = datetime.now(timezone.utc)
    with _lock:
        if _sas_token is None or _sas_expiry is None or (_sas_expiry - now) < timedelta(minutes=10):
            start = now - timedelta(minutes=5)
            expiry = now + timedelta(hours=2)
            account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
            svc = BlobServiceClient(account_url=account_url, credential=_get_credential())
            udk = svc.get_user_delegation_key(key_start_time=start, key_expiry_time=expiry)
            _sas_token = generate_container_sas(
                account_name=STORAGE_ACCOUNT_NAME,
                container_name=BLOB_CONTAINER_NAME,
                user_delegation_key=udk,
                permission=ContainerSasPermissions(read=True, list=True),
                start=start,
                expiry=expiry,
            )
            _sas_expiry = expiry
    return _sas_token


def sign_url(url: str) -> str:
    """BLOB_BASE_URL로 시작하는 URL에 SAS 쿼리 문자열을 붙여 반환한다."""
    if not url or not url.startswith(BLOB_BASE_URL):
        return url
    return f"{url}?{get_container_sas()}"


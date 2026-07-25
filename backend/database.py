import os
import threading
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient, ContainerProxy
from azure.storage.blob import ContainerClient

COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "https://localhost:8081")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME", "jjflipbook")
STORAGE_ACCOUNT_NAME = os.getenv("STORAGE_ACCOUNT_NAME", "devstorageaccount")
BLOB_CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME", "flipbook-assets")

BLOB_BASE_URL = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{BLOB_CONTAINER_NAME}"

# Backward compatibility constants
GCS_BUCKET_NAME = BLOB_CONTAINER_NAME
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
FIRESTORE_DB_NAME = COSMOS_DB_NAME

_lock = threading.Lock()
_credential = None
_cosmos_db = None
_blob_container = None


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


def get_db():
    """Backward compatibility: Cosmos DB client (GCP Firestore migration stub)."""
    return get_container("documents")


def get_bucket():
    """Backward compatibility: Blob container client (GCP Storage migration stub)."""
    return get_blob_container()


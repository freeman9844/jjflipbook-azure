import os
import threading
from google.cloud import storage, firestore

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "jjflipbook-gcs-001")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "jwlee-argolis-202104")
FIRESTORE_DB_NAME = os.getenv("FIRESTORE_DB_NAME", "jjflipbook")

_lock = threading.Lock()
_db = None
_bucket = None


def get_db() -> firestore.Client:
    """Firestore 클라이언트를 lazy 초기화하여 반환한다. Thread-safe."""
    global _db
    if _db is None:
        with _lock:
            if _db is None:
                _db = firestore.Client(
                    project=GOOGLE_CLOUD_PROJECT,
                    database=FIRESTORE_DB_NAME
                )
    return _db


def get_bucket() -> storage.Bucket:
    """GCS Bucket을 lazy 초기화하여 반환한다. Thread-safe."""
    global _bucket
    if _bucket is None:
        with _lock:
            if _bucket is None:
                client = storage.Client(project=GOOGLE_CLOUD_PROJECT)
                _bucket = client.bucket(GCS_BUCKET_NAME)
    return _bucket

import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import database


def test_sign_url_generates_read_only_blob_sas():
    url = f"{database.BLOB_BASE_URL}/flipbooks/20260815/book/page_1.webp"

    with (
        patch.object(database, "_get_user_delegation_key", return_value=object()),
        patch.object(database, "generate_blob_sas", return_value="sp=r&sr=b&sig=test") as generate,
    ):
        signed = database.sign_url(url)

    assert signed == f"{url}?sp=r&sr=b&sig=test"
    kwargs = generate.call_args.kwargs
    assert kwargs["blob_name"] == "flipbooks/20260815/book/page_1.webp"
    assert kwargs["permission"].read is True
    assert getattr(kwargs["permission"], "list", False) is False


def test_sign_url_does_not_sign_other_storage_urls():
    external = "https://other.blob.core.windows.net/flipbook-assets/private.pdf"
    assert database.sign_url(external) == external


def test_sign_url_does_not_sign_sibling_container():
    sibling = (
        f"https://{database.STORAGE_ACCOUNT_NAME}.blob.core.windows.net/"
        "other-container/private.pdf"
    )
    assert database.sign_url(sibling) == sibling


def test_sign_url_reuses_cached_sas_until_refresh_window():
    database._signed_url_cache.clear()
    now = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    url = f"{database.BLOB_BASE_URL}/flipbooks/book/page_1.webp"

    with (
        patch.object(database, "_utc_now", return_value=now),
        patch.object(database, "_get_user_delegation_key", return_value=object()),
        patch.object(
            database,
            "generate_blob_sas",
            return_value="sp=r&sig=first",
        ) as generate,
    ):
        first = database.sign_url(url)
        second = database.sign_url(url)

    assert first == second
    assert generate.call_count == 1


def test_sign_url_refreshes_after_cache_ttl():
    database._signed_url_cache.clear()
    start = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    url = f"{database.BLOB_BASE_URL}/flipbooks/book/page_1.webp"

    with (
        patch.object(
            database,
            "_utc_now",
            side_effect=[start, start + timedelta(minutes=91)],
        ),
        patch.object(database, "_get_user_delegation_key", return_value=object()),
        patch.object(
            database,
            "generate_blob_sas",
            side_effect=["sp=r&sig=first", "sp=r&sig=second"],
        ) as generate,
    ):
        first = database.sign_url(url)
        second = database.sign_url(url)

    assert first != second
    assert generate.call_count == 2


def test_sign_url_does_not_cache_external_urls():
    database._signed_url_cache.clear()
    external = "https://other.blob.core.windows.net/container/file.mp3"

    assert database.sign_url(external) == external
    assert database._signed_url_cache == {}


def test_sign_url_race_returns_newer_cached_sas():
    database._signed_url_cache.clear()
    url = f"{database.BLOB_BASE_URL}/flipbooks/book/page_1.webp"
    older_now = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    newer_now = older_now + timedelta(minutes=1)
    older_started = threading.Event()
    newer_finished = threading.Event()
    results = {}

    def fake_now():
        if threading.current_thread().name == "older-worker":
            return older_now
        return newer_now

    def fake_generate_blob_sas(**_kwargs):
        if threading.current_thread().name == "older-worker":
            older_started.set()
            assert newer_finished.wait(timeout=1), "newer signer did not finish in time"
            return "sp=r&sig=older"
        return "sp=r&sig=newer"

    def sign_in_thread(name: str):
        results[name] = database.sign_url(url)
        if name == "newer":
            newer_finished.set()

    with (
        patch.object(database, "_utc_now", side_effect=fake_now),
        patch.object(database, "_get_user_delegation_key", return_value=object()),
        patch.object(database, "generate_blob_sas", side_effect=fake_generate_blob_sas),
    ):
        older = threading.Thread(target=sign_in_thread, args=("older",), name="older-worker")
        newer = threading.Thread(target=sign_in_thread, args=("newer",), name="newer-worker")
        older.start()
        assert older_started.wait(timeout=1), "older signer did not start in time"
        newer.start()
        newer.join(timeout=1)
        older.join(timeout=1)

    assert not older.is_alive()
    assert not newer.is_alive()
    assert results["newer"].endswith("sig=newer")
    assert results["older"] == results["newer"]
    assert database._signed_url_cache["flipbooks/book/page_1.webp"][0] == results["newer"]


def test_delegation_key_is_reused_until_refresh_window():
    database._delegation_key = None
    database._delegation_key_expiry = None
    service = MagicMock()
    service.get_user_delegation_key.return_value = object()

    with patch.object(database, "BlobServiceClient", return_value=service):
        first = database._get_user_delegation_key()
        second = database._get_user_delegation_key()

    assert first is second
    assert service.get_user_delegation_key.call_count == 1

from datetime import datetime, timezone
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

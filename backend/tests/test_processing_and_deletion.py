from unittest.mock import MagicMock, patch

import pytest

from services.errors import (
    AssetDeletionError,
    PdfProcessingError,
    PDF_PROCESSING_FAILED_MESSAGE,
)
from pdf_utils import create_cover_thumbnails
from services.flipbook_service import delete_single_flipbook, process_pdf_task


RAW_FAILURE_TEXT = "poppler failed with secret token abc123"


def test_create_cover_thumbnails_writes_responsive_webp_files(tmp_path):
    from PIL import Image

    source = tmp_path / "page_1.webp"
    Image.new("RGB", (1000, 1400), color=(25, 75, 125)).save(
        source,
        "WEBP",
        quality=75,
    )

    filenames = create_cover_thumbnails(str(source), str(tmp_path))

    assert filenames == ["cover_384.webp", "cover_640.webp"]
    with Image.open(tmp_path / "cover_384.webp") as cover_384:
        assert cover_384.size == (384, 538)
        assert cover_384.format == "WEBP"
    with Image.open(tmp_path / "cover_640.webp") as cover_640:
        assert cover_640.size == (640, 896)
        assert cover_640.format == "WEBP"


@patch(
    "pdf_utils.create_cover_thumbnails",
    return_value=["cover_384.webp", "cover_640.webp"],
)
@patch("pdf_utils.convert_pdf_to_images", return_value=["page_1.webp"])
@patch("services.flipbook_service.get_blob_container")
@patch("services.flipbook_service.get_container")
def test_processing_persists_responsive_covers_without_counting_them_as_pages(
    mock_get_container,
    mock_blob_container,
    _convert,
    _create_covers,
    tmp_path,
):
    flipbooks = MagicMock()
    mock_get_container.return_value = flipbooks
    blob_container = MagicMock()
    mock_blob_container.return_value = blob_container

    work_dir = tmp_path / "book"
    work_dir.mkdir()
    pdf_path = work_dir / "original.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    for filename in ("page_1.webp", "cover_384.webp", "cover_640.webp"):
        (work_dir / filename).write_bytes(b"webp")

    process_pdf_task(
        str(pdf_path),
        str(work_dir),
        "book-id",
        "20260817",
        True,
    )

    operations = flipbooks.patch_item.call_args.kwargs["patch_operations"]
    assert {
        "op": "set",
        "path": "/page_count",
        "value": 1,
    } in operations
    assert {
        "op": "set",
        "path": "/image_urls",
        "value": [
            "https://devstorageaccount.blob.core.windows.net/"
            "flipbook-assets/flipbooks/20260817/book-id/page_1.webp"
        ],
    } in operations
    assert {
        "op": "set",
        "path": "/cover_urls",
        "value": [
            "https://devstorageaccount.blob.core.windows.net/"
            "flipbook-assets/flipbooks/20260817/book-id/cover_384.webp",
            "https://devstorageaccount.blob.core.windows.net/"
            "flipbook-assets/flipbooks/20260817/book-id/cover_640.webp",
        ],
    } in operations


@patch("pdf_utils.convert_pdf_to_images", side_effect=RuntimeError(RAW_FAILURE_TEXT))
@patch("services.flipbook_service.get_container")
def test_processing_failure_records_failed_and_raises(mock_get_container, _convert, tmp_path):
    flipbooks = MagicMock()
    mock_get_container.return_value = flipbooks
    pdf_path = tmp_path / "original.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    work_dir = tmp_path / "book"
    work_dir.mkdir()

    with pytest.raises(PdfProcessingError, match="PDF processing failed"):
        process_pdf_task(
            str(pdf_path),
            str(work_dir),
            "book-id",
            "20260815",
            True,
        )

    operations = flipbooks.patch_item.call_args.kwargs["patch_operations"]
    assert {"op": "set", "path": "/status", "value": "failed"} in operations
    assert {"op": "set", "path": "/error_message", "value": PDF_PROCESSING_FAILED_MESSAGE} in operations
    assert all(op["value"] != RAW_FAILURE_TEXT for op in operations if op["path"] == "/error_message")
    assert not work_dir.exists()


@patch("services.flipbook_service.get_blob_container")
@patch("services.flipbook_service.get_container")
def test_blob_delete_failure_preserves_cosmos_metadata(mock_get_container, mock_blob):
    overlays = MagicMock()
    flipbooks = MagicMock()
    mock_get_container.side_effect = lambda name: {
        "overlays": overlays,
        "flipbooks": flipbooks,
    }[name]
    blob = MagicMock()
    blob.list_blobs.return_value = [MagicMock(name="flipbooks/20260815/id/page.webp")]
    blob.delete_blob.side_effect = RuntimeError("storage unavailable")
    mock_blob.return_value = blob

    with pytest.raises(AssetDeletionError):
        delete_single_flipbook("id", "20260815")

    overlays.query_items.assert_not_called()
    overlays.delete_item.assert_not_called()
    flipbooks.delete_item.assert_not_called()


@patch("services.flipbook_service.get_blob_container")
@patch("services.flipbook_service.get_container")
def test_retry_after_partial_blob_cleanup_deletes_metadata(mock_get_container, mock_blob):
    overlays = MagicMock()
    overlays.query_items.return_value = [{"id": "overlay-1"}]
    flipbooks = MagicMock()
    mock_get_container.side_effect = lambda name: {
        "overlays": overlays,
        "flipbooks": flipbooks,
    }[name]
    blob = MagicMock()
    blob.list_blobs.return_value = []
    mock_blob.return_value = blob

    delete_single_flipbook("id", "20260815")

    overlays.delete_item.assert_called_once_with(
        item="overlay-1",
        partition_key="id",
    )
    flipbooks.delete_item.assert_called_once_with(item="id", partition_key="id")

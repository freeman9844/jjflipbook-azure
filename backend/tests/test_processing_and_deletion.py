from unittest.mock import MagicMock, patch

import pytest

from services.errors import PdfProcessingError, PDF_PROCESSING_FAILED_MESSAGE
from services.flipbook_service import process_pdf_task


RAW_FAILURE_TEXT = "poppler failed with secret token abc123"


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

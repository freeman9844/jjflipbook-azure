"""
Test fixtures — generates test_data/sample.pdf so the suite works
from a clean clone where test_data/ is git-ignored.
"""
import os
import shutil
import pytest

os.environ.setdefault("APP_ENV", "test")

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "test_data")
SAMPLE_PDF = os.path.join(TEST_DATA_DIR, "sample.pdf")

# Minimal valid single-page PDF (no external dependencies needed)
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n"
    b"0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n"
    b"197\n"
    b"%%EOF\n"
)


@pytest.fixture(scope="session", autouse=True)
def ensure_sample_pdf():
    """Create tests/test_data/sample.pdf if absent; clean up after session."""
    created_dir = not os.path.isdir(TEST_DATA_DIR)
    os.makedirs(TEST_DATA_DIR, exist_ok=True)

    created_file = not os.path.exists(SAMPLE_PDF)
    if created_file:
        with open(SAMPLE_PDF, "wb") as f:
            f.write(_MINIMAL_PDF)

    yield

    # Remove only what we created so we don't destroy a developer's real files
    if created_file and os.path.exists(SAMPLE_PDF):
        os.remove(SAMPLE_PDF)
    if created_dir and os.path.isdir(TEST_DATA_DIR):
        shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)

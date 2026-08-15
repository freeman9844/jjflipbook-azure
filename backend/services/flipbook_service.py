import os
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.storage.blob import ContentSettings
from database import get_container, get_blob_container, BLOB_BASE_URL
from services.errors import PdfProcessingError, PDF_PROCESSING_FAILED_MESSAGE

logger = logging.getLogger(__name__)

_CONTENT_TYPES = {
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".mp3": "audio/mpeg",
}


def _content_settings(filename: str) -> ContentSettings:
    ext = os.path.splitext(filename)[1].lower()
    return ContentSettings(content_type=_CONTENT_TYPES.get(ext, "application/octet-stream"))


def delete_single_flipbook(uuid_key: str, date_str: str = ""):
    # 1. Overlays 삭제 (파티션 단위)
    overlays = get_container("overlays")
    overlay_ids = [
        item["id"]
        for item in overlays.query_items(
            query="SELECT c.id FROM c", partition_key=uuid_key
        )
    ]
    for oid in overlay_ids:
        overlays.delete_item(item=oid, partition_key=uuid_key)

    # 2. 메인 플립북 문서 삭제
    try:
        get_container("flipbooks").delete_item(item=uuid_key, partition_key=uuid_key)
    except CosmosResourceNotFoundError:
        pass

    # 3. Blob 소거 (Prefix 기반) - 멀티스레딩 병렬 삭제 적용
    try:
        prefix_path = f"flipbooks/{date_str}/{uuid_key}/" if date_str else f"flipbooks/{uuid_key}/"
        container = get_blob_container()
        blob_names = [b.name for b in container.list_blobs(name_starts_with=prefix_path)]

        if blob_names:
            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(lambda name: container.delete_blob(name), blob_names))

    except Exception as e:
        logger.warning(
            "⚠️ [Delete] Blob cleanup failed for book-%s (%s)",
            uuid_key,
            e.__class__.__name__,
        )


def process_pdf_task(pdf_path: str, book_storage: str, uuid_key: str, date_str: str, split_pages: bool = True):
    """백그라운드에서 PDF를 이미지로 변환하고 Blob Storage에 업로드 후 Cosmos 업데이트."""
    try:
        # pdf_utils는 실제 변환 시점에만 임포트 (cold start 임포트 오버헤드 제거)
        from pdf_utils import convert_pdf_to_images
        filenames = convert_pdf_to_images(pdf_path, book_storage, split_pages=split_pages)

        container = get_blob_container()

        def upload_worker(fname: str):
            local_path = os.path.join(book_storage, fname)
            blob_name = f"flipbooks/{date_str}/{uuid_key}/{fname}"
            with open(local_path, "rb") as f:
                container.upload_blob(
                    name=blob_name, data=f, overwrite=True,
                    content_settings=_content_settings(fname),
                )
            return f"{BLOB_BASE_URL}/{blob_name}"

        with ThreadPoolExecutor(max_workers=5) as executor:
            uploaded_urls = list(executor.map(upload_worker, filenames))

        pdf_blob_name = f"flipbooks/{date_str}/{uuid_key}/original.pdf" if date_str else f"flipbooks/{uuid_key}/original.pdf"
        with open(pdf_path, "rb") as f:
            container.upload_blob(
                name=pdf_blob_name, data=f, overwrite=True,
                content_settings=_content_settings("original.pdf"),
            )
        pdf_url = f"{BLOB_BASE_URL}/{pdf_blob_name}"

        get_container("flipbooks").patch_item(
            item=uuid_key,
            partition_key=uuid_key,
            patch_operations=[
                {"op": "set", "path": "/page_count", "value": len(filenames)},
                {"op": "set", "path": "/image_urls", "value": uploaded_urls},
                {"op": "set", "path": "/pdf_url", "value": pdf_url},
                {"op": "set", "path": "/status", "value": "success"},
            ],
        )
        logger.info(f"✅ [Background] Flipbook-{uuid_key} Cosmos updated successfully. ({len(filenames)} pages)")

    except Exception as e:
        logger.error(
            "❌ [Background] Error processing PDF-%s (%s)",
            uuid_key,
            e.__class__.__name__,
        )
        logger.error(
            "❌ [Background] PDF-%s traceback:\n%s",
            uuid_key,
            "".join(traceback.format_tb(e.__traceback__)),
        )
        try:
            get_container("flipbooks").patch_item(
                item=uuid_key,
                partition_key=uuid_key,
                patch_operations=[
                    {"op": "set", "path": "/status", "value": "failed"},
                    {"op": "set", "path": "/error_message", "value": PDF_PROCESSING_FAILED_MESSAGE},
                ],
            )
        except Exception as fe:
            logger.error(
                "❌ [Background] Failed to update fail status for %s (%s)",
                uuid_key,
                fe.__class__.__name__,
            )
        raise PdfProcessingError(PDF_PROCESSING_FAILED_MESSAGE) from e
    finally:
        import shutil
        if os.path.exists(book_storage):
            shutil.rmtree(book_storage)

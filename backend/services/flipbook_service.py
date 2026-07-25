import os
import logging
from concurrent.futures import ThreadPoolExecutor
from database import get_db, get_bucket, GCS_BUCKET_NAME

logger = logging.getLogger(__name__)


def delete_single_flipbook(uuid_key: str, date_str: str = ""):
    db = get_db()
    doc_ref = db.collection("flipbooks").document(uuid_key)

    # 1. 서브 컬렉션 (Overlays) 삭제
    overlays = doc_ref.collection("overlays").stream()
    batch = db.batch()
    for d in overlays:
        batch.delete(d.reference)
    batch.commit()

    # 2. 메인 플립북 문서 삭제
    doc_ref.delete()

    # 3. GCS 블롭 소거 (Prefix 기반) - 멀티스레딩 병렬 삭제 적용
    try:
        prefix_path = f"flipbooks/{date_str}/{uuid_key}/" if date_str else f"flipbooks/{uuid_key}/"
        blobs = list(get_bucket().list_blobs(prefix=prefix_path))

        if blobs:
            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(lambda b: b.delete(), blobs))

    except Exception as e:
        logger.warning(f"⚠️ [Delete] GCS cleanup failed for book-{uuid_key}: {str(e)}")


def process_pdf_task(pdf_path: str, book_storage: str, uuid_key: str, date_str: str, split_pages: bool = True):
    """백그라운드에서 PDF를 이미지로 변환하고 GCS에 업로드 후 Firestore 업데이트."""
    try:
        # pdf_utils는 실제 변환 시점에만 임포트 (cold start 임포트 오버헤드 제거)
        from pdf_utils import convert_pdf_to_images
        filenames = convert_pdf_to_images(pdf_path, book_storage, split_pages=split_pages)

        bucket = get_bucket()

        def upload_worker(fname: str):
            local_path = os.path.join(book_storage, fname)
            blob = bucket.blob(f"flipbooks/{date_str}/{uuid_key}/{fname}")
            blob.upload_from_filename(local_path)
            return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/flipbooks/{date_str}/{uuid_key}/{fname}"

        with ThreadPoolExecutor(max_workers=5) as executor:
            uploaded_urls = list(executor.map(upload_worker, filenames))

        pdf_blob_name = f"flipbooks/{date_str}/{uuid_key}/original.pdf" if date_str else f"flipbooks/{uuid_key}/original.pdf"
        pdf_blob = bucket.blob(pdf_blob_name)
        pdf_blob.upload_from_filename(pdf_path)
        pdf_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{pdf_blob_name}"

        get_db().collection("flipbooks").document(uuid_key).update({
            "page_count": len(filenames),
            "image_urls": uploaded_urls,
            "pdf_url": pdf_url,
            "status": "success"
        })
        logger.info(f"✅ [Background] Flipbook-{uuid_key} Firestore Updated successfully. ({len(filenames)} pages)")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ [Background] Error processing PDF-{uuid_key}: {error_msg}", exc_info=True)
        try:
            get_db().collection("flipbooks").document(uuid_key).update({
                "status": "failed",
                "error_message": error_msg
            })
        except Exception as fe:
            logger.error(f"❌ [Background] Failed to update fail status for {uuid_key}: {str(fe)}")
    finally:
        import shutil
        if os.path.exists(book_storage):
            shutil.rmtree(book_storage)

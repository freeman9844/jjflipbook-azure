PDF_PROCESSING_FAILED_MESSAGE = "PDF processing failed"


class PdfProcessingError(RuntimeError):
    pass


class AssetDeletionError(RuntimeError):
    def __init__(self, uuid_key: str):
        super().__init__(f"Asset deletion failed for flipbook {uuid_key}")
        self.uuid_key = uuid_key

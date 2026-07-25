import uuid
from fastapi import APIRouter, Depends, HTTPException
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from database import get_container
from models import Folder
from utils import verify_api_key
from services.flipbook_service import delete_single_flipbook

router = APIRouter(tags=["Folders"])


@router.post("/folder")
def create_folder(folder: Folder, validated: bool = Depends(verify_api_key)):
    folder_id = str(uuid.uuid4())
    folder.id = folder_id
    get_container("folders").create_item(folder.model_dump(mode="json"))
    return {"status": "ok", "folder_id": folder_id}


@router.get("/folders")
def get_folders():
    docs = get_container("folders").query_items(
        query="SELECT * FROM c", enable_cross_partition_query=True
    )
    results = list(docs)
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results


@router.delete("/folder/{folder_id}")
def delete_folder(folder_id: str, validated: bool = Depends(verify_api_key)):
    folders = get_container("folders")
    try:
        folders.read_item(item=folder_id, partition_key=folder_id)
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Folder not found")

    flipbooks = get_container("flipbooks").query_items(
        query="SELECT c.id, c.date_folder FROM c WHERE c.folder_id = @folder_id",
        parameters=[{"name": "@folder_id", "value": folder_id}],
        enable_cross_partition_query=True,
    )
    deleted_count = 0
    for fb in flipbooks:
        # date_folder를 함께 넘겨 날짜 경로의 blob까지 정리 (기존 GCP 코드의 누락 수정)
        delete_single_flipbook(fb["id"], fb.get("date_folder", ""))
        deleted_count += 1

    folders.delete_item(item=folder_id, partition_key=folder_id)
    return {"status": "ok", "message": f"Folder deleted with {deleted_count} flipbooks cascade deleted."}

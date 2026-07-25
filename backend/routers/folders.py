import uuid
from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from models import Folder
from utils import verify_api_key

router = APIRouter(tags=["Folders"])

from services.flipbook_service import delete_single_flipbook

@router.post("/folder")
def create_folder(folder: Folder, validated: bool = Depends(verify_api_key)):
    folder_id = str(uuid.uuid4())
    folder.id = folder_id
    get_db().collection("folders").document(folder_id).set(folder.model_dump())
    return {"status": "ok", "folder_id": folder_id}

@router.get("/folders")
def get_folders():
    docs = get_db().collection("folders").stream()
    results = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results.append(d)
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results

@router.delete("/folder/{folder_id}")
def delete_folder(folder_id: str, validated: bool = Depends(verify_api_key)):
    folder_ref = get_db().collection("folders").document(folder_id)
    if not folder_ref.get().exists:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    flipbooks = get_db().collection("flipbooks").where("folder_id", "==", folder_id).stream()
    deleted_count = 0
    for fb in flipbooks:
        delete_single_flipbook(fb.id)
        deleted_count += 1
        
    folder_ref.delete()
    return {"status": "ok", "message": f"Folder deleted with {deleted_count} flipbooks cascade deleted."}

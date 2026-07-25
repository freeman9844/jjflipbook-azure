from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_db
from utils import verify_password

router = APIRouter(tags=["Auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
def login(req: LoginRequest):
    user_ref = get_db().collection("users").document(req.username)
    doc = user_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=401, detail="존재하지 않는 사용자입니다.")
        
    user_data = doc.to_dict()
    if not verify_password(req.password, user_data.get("password_hash")):
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
        
    return {"status": "ok", "authenticated": True, "username": req.username}

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from database import get_container
from utils import verify_password

router = APIRouter(tags=["Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest):
    try:
        user_data = get_container("users").read_item(
            item=req.username, partition_key=req.username
        )
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=401, detail="존재하지 않는 사용자입니다.")

    if not verify_password(req.password, user_data.get("password_hash")):
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")

    return {"status": "ok", "authenticated": True, "username": req.username}

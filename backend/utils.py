import os
import bcrypt
from fastapi import Header, HTTPException

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def verify_api_key(x_api_key: str = Header(None)):
    expected = os.getenv("INTERNAL_API_KEY", "secret_dev_key")
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Internal API Key")
    return True

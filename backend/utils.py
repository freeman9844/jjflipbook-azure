import hmac
import os
import bcrypt
from fastapi import Header, HTTPException

_INSECURE_DEFAULTS = {
    "ADMIN_PASSWORD": {"admin"},
    "INTERNAL_API_KEY": {"secret_dev_key"},
}


def required_setting(name: str, development_default: str | None = None) -> str:
    app_env = os.getenv("APP_ENV", "development")
    value = os.getenv(name)
    if app_env in {"development", "test"}:
        if value:
            return value
        if development_default is not None:
            return development_default
    if not value or value in _INSECURE_DEFAULTS.get(name, set()):
        raise RuntimeError(f"{name} must be configured securely")
    return value


def validate_runtime_config() -> None:
    required_setting("ADMIN_PASSWORD", "admin")
    required_setting("INTERNAL_API_KEY", "secret_dev_key")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def verify_api_key(x_api_key: str = Header(None)):
    expected = required_setting("INTERNAL_API_KEY", "secret_dev_key")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Internal API Key")
    return True

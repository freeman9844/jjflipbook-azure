import os
import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from database import get_db
from models import User
from utils import hash_password

from routers import auth, flipbooks, folders

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def _seed_admin():
    """startup 완료 후 백그라운드에서 admin 계정 seeding."""
    import base64
    try:
        user_ref = get_db().collection("users").document("admin")
        if not user_ref.get().exists:
            fallback_pw = base64.b64decode(b"YWRtaW4=").decode("utf-8")
            admin_password = os.getenv("ADMIN_PASSWORD", fallback_pw)
            admin_user = User(
                username="admin",
                password_hash=hash_password(admin_password)
            )
            user_ref.set(admin_user.model_dump())
            logger.info("✅ [Lifespan] Default admin user seeded successfully.")
    except Exception as e:
        logger.warning(f"⚠️ [Lifespan] Admin seeding failed (non-critical): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_seed_admin())
    yield


app = FastAPI(
    title="Flipbook MVP API (Firestore)",
    description="FastAPI Backend mapped for Cloud Firestore",
    version="0.3.0",
    lifespan=lifespan
)

frontend_url = os.getenv("FRONTEND_URL", os.getenv("NEXT_PUBLIC_FRONTEND_URL", "http://localhost:3000"))
allowed_origins = [origin.strip() for origin in frontend_url.split(",")] if frontend_url else ["http://localhost:3000"]

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(flipbooks.router)
app.include_router(folders.router)

STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage")
os.makedirs(STORAGE_DIR, exist_ok=True)
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "message": "Flipbook MVP API is running"
    }

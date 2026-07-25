import os
import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from database import get_container
from models import User
from utils import hash_password

from routers import auth, flipbooks, folders, music

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Application Insights (OpenTelemetry) — 연결 문자열이 있을 때만 활성화 (로컬/테스트는 no-op)
_APPINSIGHTS_ENABLED = bool(os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"))
if _APPINSIGHTS_ENABLED:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor()  # traces/metrics/logs → App Insights
        logger.info("✅ Application Insights telemetry enabled.")
    except Exception as e:  # 계측 실패가 앱 기동을 막지 않도록 방어
        _APPINSIGHTS_ENABLED = False
        logger.warning(f"⚠️ Application Insights setup failed (non-critical): {e}")


async def _seed_admin():
    """startup 완료 후 백그라운드에서 admin 계정 seeding."""
    import base64
    from azure.cosmos.exceptions import CosmosResourceNotFoundError
    try:
        users = get_container("users")
        try:
            users.read_item(item="admin", partition_key="admin")
        except CosmosResourceNotFoundError:
            fallback_pw = base64.b64decode(b"YWRtaW4=").decode("utf-8")
            admin_password = os.getenv("ADMIN_PASSWORD", fallback_pw)
            admin_user = User(
                id="admin",
                username="admin",
                password_hash=hash_password(admin_password),
            )
            users.create_item(admin_user.model_dump(mode="json"))
            logger.info("✅ [Lifespan] Default admin user seeded successfully.")
    except Exception as e:
        logger.warning(f"⚠️ [Lifespan] Admin seeding failed (non-critical): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_seed_admin())
    yield


app = FastAPI(
    title="Flipbook MVP API (Cosmos DB)",
    description="FastAPI Backend mapped for Cosmos DB",
    version="0.3.0",
    lifespan=lifespan
)

if _APPINSIGHTS_ENABLED:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    except Exception as e:
        logger.warning(f"⚠️ FastAPI instrumentation failed (non-critical): {e}")

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
app.include_router(music.router)

STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage")
os.makedirs(STORAGE_DIR, exist_ok=True)
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "message": "Flipbook MVP API is running"
    }

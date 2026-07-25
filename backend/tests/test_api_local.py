import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from utils import hash_password

from main import app
client = TestClient(app)

def test_local_health_check():
    """1. 헬스체크는 GCP 호출 없이 즉시 200을 반환해야 한다"""
    response = client.get("/")
    assert response.status_code == 200, "API 서버 내부 라우팅 동작 실패"
    data = response.json()
    assert data.get("status") == "ok", "status 필드가 'ok' 여야 합니다"
    assert "services" not in data, "경량화된 헬스체크에 services 항목이 없어야 합니다"

def _fake_users_container(password: str):
    container = MagicMock()
    container.read_item.return_value = {
        "id": "admin",
        "username": "admin",
        "password_hash": hash_password(password),
    }
    return container


@patch("routers.auth.get_container")
def test_local_login_failure(mock_get_container):
    """2. 로그인 실패 (잘못된 비밀번호) — Cosmos mock 검증"""
    mock_get_container.return_value = _fake_users_container("correct_password")
    response = client.post("/login", json={"username": "admin", "password": "wrong_password"})
    assert response.status_code == 401, "잘못된 비밀번호에 대해 401 에러를 반환해야 합니다."


@patch("routers.auth.get_container")
def test_local_login_success(mock_get_container):
    """3. 로그인 성공 (관리자) — Cosmos mock 검증"""
    mock_get_container.return_value = _fake_users_container("test_password")
    response = client.post("/login", json={"username": "admin", "password": "test_password"})
    assert response.status_code == 200, "올바른 비밀번호에 대해 로그인이 실패했습니다."
    data = response.json()
    assert data.get("authenticated") is True


@patch("routers.auth.get_container")
def test_local_login_unknown_user(mock_get_container):
    """3-1. 존재하지 않는 사용자 → 401 (Cosmos 404 매핑 검증)"""
    container = MagicMock()
    container.read_item.side_effect = CosmosResourceNotFoundError(status_code=404, message="not found")
    mock_get_container.return_value = container
    response = client.post("/login", json={"username": "ghost", "password": "x"})
    assert response.status_code == 401

def test_db_lazy_init_state():
    """5. database 모듈이 Azure 클라이언트 팩토리를 제공하는지 확인"""
    import database
    assert callable(database.get_container), "get_container 함수가 존재해야 합니다"
    assert callable(database.get_blob_container), "get_blob_container 함수가 존재해야 합니다"
    assert database.BLOB_BASE_URL.startswith("https://"), "BLOB_BASE_URL은 https URL이어야 합니다"

@patch("routers.flipbooks.process_pdf_task")
@patch("routers.flipbooks.get_container")
def test_local_pdf_upload(mock_get_container, mock_process):
    """4. 인메모리 업로드 시나리오 (Azure 연결 없이 라우팅 통과 여부 검증)"""
    test_pdf_path = os.path.join(os.path.dirname(__file__), "test_data", "sample.pdf")
    assert os.path.exists(test_pdf_path), "Test data missing: sample.pdf"

    mock_container = MagicMock()
    mock_get_container.return_value = mock_container

    with open(test_pdf_path, "rb") as f:
        files = {"file": ("E2E_TEST_local_test.pdf", f, "application/pdf")}
        headers = {"x-api-key": os.getenv("INTERNAL_API_KEY", "secret_dev_key")}
        response = client.post("/upload", files=files, headers=headers)
        assert response.status_code == 200, f"로컬 업로드 라우터 통과 실패: {response.text}"
        data = response.json()
        assert "book_id" in data

    # Cosmos create_item에 전달된 문서 검증
    created_doc = mock_container.create_item.call_args[0][0]
    assert created_doc["id"] == created_doc["uuid_key"], "id는 uuid_key와 같아야 합니다"
    assert created_doc["status"] == "processing"
    assert isinstance(created_doc["created_at"], str), "created_at은 ISO 문자열이어야 합니다 (Cosmos 직렬화)"

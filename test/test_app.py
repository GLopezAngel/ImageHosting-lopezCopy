import json
import pytest
import app

# --- 1. NEW IMPORT HERE ---
from infrastructure.redis_client import RedisClient

@pytest.fixture
def client():
    app.app.config["TESTING"] = True
    with app.app.test_client() as client:
        yield client

def _auth_header(uid="u_test"):
    token = app.signer.dumps({"uid": uid})
    return {"X-API-Key": token}

def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"data": {"status": "ok"}} or resp.get_json() == {"status": "ok"}

def test_issue_key_uses_auth_service(client, monkeypatch):
    monkeypatch.setattr(app.AuthService, "create_new_user", lambda: {"uid": "u_1", "username": "test"})

    resp = client.post("/api/v1/dev/issue-key")
    
    json_body = resp.get_json()
    payload = json_body.get("data", json_body)

    assert resp.status_code == 200
    assert payload["uid"] == "u_1"
    assert payload["api_key"]

def test_request_upload_requires_api_key(client):
    resp = client.post("/api/v1/upload/request", json={"filename": "x", "mime_type": "image/png"})
    assert resp.status_code == 401
    
    json_body = resp.get_json()
    # Check for 'error' key or use body if it's already the error object
    if "error" in json_body:
        code = json_body["error"]["code"]
    else:
        code = json_body.get("code")
        
    assert code == "auth"

def test_request_upload_success(client, monkeypatch):
    expected = {"iid": "img_1", "key": "k", "presigned_url": "url", "filename": "f"}

    def fake_initiate(uid, filename, mime_type):
        assert uid == "u_owner"
        assert filename == "photo.png"
        assert mime_type == "image/png"
        return expected

    monkeypatch.setattr(app.ImageService, "initiate_upload", fake_initiate)

    resp = client.post(
        "/api/v1/upload/request",
        json={"filename": "photo.png", "mime_type": "image/png"},
        headers=_auth_header(uid="u_owner"),
    )

    assert resp.status_code == 200
    
    json_body = resp.get_json()
    payload = json_body.get("data", json_body)
    assert payload == expected

# --- 2. UPDATED TEST FUNCTION ---
def test_redis_check_handles_failure(client, monkeypatch):
    # 'self' is required because we are patching the Class method now
    def broken_ping(self):
        raise RuntimeError("boom")

    # Patch the Class directly. This is the safest way.
    monkeypatch.setattr(RedisClient, "ping", broken_ping)
    
    resp = client.get("/redis-check")

    assert resp.status_code == 500
    body = resp.get_json()
    
    if "error" in body:
        err = body["error"]
    else:
        err = body
        
    assert err["code"] == "redis_unreachable"
    assert "boom" in err["message"]

def test_get_image_redirects(client, monkeypatch):
    monkeypatch.setattr(app.ImageService, "get_image_download_url", lambda iid: "http://example.com/img.jpg")
    resp = client.get("/api/v1/image/i1")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "http://example.com/img.jpg"
"""
Image Host – Flask + Redis (Dev Version)
This app:
- Serves static files (index.html, script.js, style.css)
- Loads environment variables from .env
- Connects to Redis
- Issues a dev API key (X-API-Key)
- Lets you create fake images and list them before adding S3
"""
#AngelClayJalil-ImageHosting

from __future__ import annotations
import os, time, uuid, redis
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from itsdangerous import URLSafeSerializer

# Load environment variables first
load_dotenv()

app = Flask(__name__)

# Setup Flask + Redis
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "dev-secret")
signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="api-key")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

# Helper functions
def now(): return int(time.time())
def ok(payload, status=200): return jsonify(payload), status
def err(code, message, status): return jsonify({"error": {"code": code, "message": message}}), status
def k_user(uid): return f"user:{uid}"
def k_user_images(uid): return f"user:{uid}:images"
def k_img(iid): return f"img:{iid}"

# Serve static files
@app.get("/")
def serve_index():
    root = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(root, "index.html")

@app.get("/script.js")
def serve_script():
    root = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(root, "script.js")

@app.get("/style.css")
def serve_style():
    root = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(root, "style.css")

@app.get("/health")
def health_check():
    return ok({"status": "ok"})

# Redis test routes
@app.get("/redis-check")
def redis_check():
    try:
        return ok({"redis": bool(r.ping())})
    except Exception as e:
        return err("redis_unreachable", str(e), 500)

@app.get("/redis-demo")
def redis_demo():
    r.set("demo:key", "Hello Redis!")
    return ok({"stored_value": r.get("demo:key")})

# Authentication helper
def require_api_key():
    token = (request.headers.get("X-API-Key") or "").strip()
    if not token:
        return None
    try:
        return signer.loads(token)
    except Exception:
        return None

# Create a dev API key so you can test with a fake user
@app.post("/api/v1/dev/issue-key")
def issue_key():
    username = (request.json or {}).get("username", "demo").strip() or "demo"
    uid = f"u_{username}"
    r.hsetnx(k_user(uid), "username", username)
    r.hset(k_user(uid), mapping={"uid": uid, "created_at": now()})
    token = signer.dumps({"uid": uid})
    return ok({"api_key": token, "uid": uid})

# Create a fake image record (for dev testing)
@app.post("/api/v1/dev/seed-image")
def dev_seed_image():
    auth = require_api_key()
    if not auth:
        return err("auth", "invalid api key", 401)
    uid = auth["uid"]
    iid = f"img_{uuid.uuid4().hex[:8]}"
    filename = "demo.png"
    fake_url = f"https://example.com/{iid}/{filename}"
    r.hset(k_img(iid), mapping={
        "id": iid,
        "owner_uid": uid,
        "key": f"uploads/{uid}/{iid}/{filename}",
        "url": fake_url,
        "filename": filename,
        "mime": "image/png",
        "private": 0,
        "created_at": now(),
        "views": 0
    })
    r.zadd(k_user_images(uid), {iid: now()})
    return ok({"seeded": True, "id": iid, "url": fake_url}, 201)

# List all images for a user (fake data for now)
@app.get("/api/v1/me/images")
def me_images():
    auth = require_api_key()
    if not auth:
        return err("auth", "invalid api key", 401)
    uid = auth["uid"]
    iids = r.zrevrange(k_user_images(uid), 0, 49)
    items = []
    for iid in iids:
        data = r.hgetall(k_img(iid))
        if data:
            data["id"] = iid
            items.append(data)
    return ok({"items": items})

# Run the app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)

from __future__ import annotations
import os
import time
import uuid
from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template, url_for, redirect
from itsdangerous import URLSafeSerializer
from storage import redis_client, s3_client

# --- Setup ---
load_dotenv()
app = Flask(__name__, template_folder="template", static_folder="static")

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "dev-secret")
signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="api-key")

# --- Helper functions ---
def now(): return int(time.time())
def ok(payload, status=200): return jsonify(payload), status
def err(code, message, status): return jsonify({"error": {"code": code, "message": message}}), status

# --- Frontend Route ---
@app.get("/")
def serve_index():
    return render_template("index.html")

@app.get("/health")
def health_check():
    return ok({"status": "ok"})

@app.get("/redis-check")
def redis_check():
    try:
        return ok({"redis": bool(redis_client.ping_redis())})
    except Exception as e:
        return err("redis_unreachable", str(e), 500)

# --- Auth Routes ---
def require_api_key():
    token = (request.headers.get("X-API-Key") or "").strip()
    if not token:
        return None
    try:
        return signer.loads(token)
    except Exception:
        return None

@app.post("/api/v1/dev/issue-key")
def issue_key():
    username = f"user_{uuid.uuid4().hex[:8]}"
    uid = f"u_{username}"
    redis_client.create_user(uid, username, now())
    token = signer.dumps({"uid": uid})
    return ok({"api_key": token, "uid": uid})

# --- S3 Upload Endpoints ---

@app.post("/api/v1/upload/request")
def request_upload():
    auth = require_api_key()
    if not auth:
        return err("auth", "invalid api key", 401)
    
    uid = auth["uid"]
    req_data = request.json or {}
    filename = req_data.get("filename")
    mime_type = req_data.get("mime_type")

    if not all([filename, mime_type]):
        return err("validation", "filename and mime_type are required", 400)
    
    iid = f"img_{uuid.uuid4().hex[:12]}"
    key = f"uploads/{uid}/{iid}/{filename}"

    try:
        presigned_url = s3_client.generate_presigned_upload_url(key, mime_type)
        return ok({
            "iid": iid,
            "key": key,
            "presigned_url": presigned_url,
        })
    except Exception as e:
        print(f"S3 Error: {e}")
        return err("s3_error", "Could not generate S3 upload URL.", 500)

@app.post("/api/v1/upload/complete")
def complete_upload():
    auth = require_api_key()
    if not auth:
        return err("auth", "invalid api key", 401)
    
    uid = auth["uid"]
    req_data = request.json or {}
    iid = req_data.get("iid")
    key = req_data.get("key")
    filename = req_data.get("filename")
    mime_type = req_data.get("mime_type")

    if not all([iid, key, filename, mime_type]):
        return err("validation", "iid, key, filename, and mime_type are required", 400)

    img_url_ref = s3_client.get_public_url(key)
    redis_client.store_image(iid, uid, key, img_url_ref, filename, mime_type, now())

    return ok({"id": iid, "url": img_url_ref}, 201)

# --- Gallery Endpoints ---

@app.get("/api/v1/me/images")
def me_images():
    auth = require_api_key()
    if not auth:
        return err("auth", "invalid api key", 401)
    
    uid = auth["uid"]
    iids = redis_client.get_user_images(uid, limit=50)
    results = redis_client.get_images_batch(iids)
    
    items = []
    for data in results:
        if data:
            if not data.get("url"):
                data['url'] = f"/api/v1/image/{data['id']}"
            items.append(data)
            
    return ok({"items": items})

@app.get("/api/v1/image/<iid>")
def get_image(iid):
    img_data = redis_client.get_image(iid)
    if not img_data:
        return err("not_found", "Image not found", 404)
        
    s3_key = img_data.get("key")
    if not s3_key:
        return err("invalid_record", "Image record is corrupt", 500)

    try:
        view_url = s3_client.generate_presigned_download_url(s3_key)
        return redirect(view_url, code=302)
        
    except Exception as e:
        print(f"S3 GET Error: {e}")
        return err("s3_error", "Could not get image URL", 500)

# --- Delete Image Endpoint ---

@app.delete("/api/v1/image/<iid>")
def delete_image(iid):
    # 1. Check if user is authenticated
    auth = require_api_key()
    if not auth:
        return err("auth", "invalid api key", 401)
    
    uid = auth["uid"]
    
    # 2. Get image data from Redis
    img_data = redis_client.get_image(iid)
    if not img_data:
        return err("not_found", "Image not found", 404)
        
    # 3. Check if this user owns the image
    if img_data.get("owner_uid") != uid:
        return err("auth", "You do not have permission to delete this image", 403)
        
    s3_key = img_data.get("key")
    if not s3_key:
        return err("invalid_record", "Image record is corrupt", 500)

    try:
        # 4. Delete the object from S3
        s3_client.delete_object(s3_key)
        
        # 5. Delete the data from Redis
        redis_client.delete_image_from_redis(iid, uid)
        
        return ok({"status": "deleted", "id": iid})
        
    except Exception as e:
        print(f"S3 DELETE Error: {e}")
        # If S3 fails, we don't delete from Redis
        return err("s3_error", "Could not delete image from S3", 500)

# --- Run the app ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
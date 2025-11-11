from __future__ import annotations
import os, time, uuid, redis, boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, url_for, redirect

# --- Setup ---
load_dotenv()
app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "dev-secret")
signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="api-key")

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- S3 Setup ---
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")

if not AWS_S3_BUCKET_NAME:
    print("Error: AWS_S3_BUCKET_NAME environment variable not set.")
    
s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    config=Config(signature_version="s3v4"),
)

# --- Helper functions ---
def now(): return int(time.time())
def ok(payload, status=200): return jsonify(payload), status
def err(code, message, status): return jsonify({"error": {"code": code, "message": message}}), status
def k_user(uid): return f"user:{uid}"
def k_user_images(uid): return f"user:{uid}:images"
def k_img(iid): return f"img:{iid}"

# --- (MODIFIED) This helper is no longer used to build public URLs ---
# We will generate presigned GET URLs instead.
def get_s3_url(key):
    # This is just a reference, not a working public URL
    return f"s3://{AWS_S3_BUCKET_NAME}/{key}"

# --- Static file routes (HTML, CSS, JS) ---
# ... (These are all unchanged) ...
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

@app.get("/redis-check")
def redis_check():
    try:
        return ok({"redis": bool(r.ping())})
    except Exception as e:
        return err("redis_unreachable", str(e), 500)

# --- Auth Routes (Unchanged) ---
# ... (require_api_key and issue_key are unchanged) ...
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
    username = (request.json or {}).get("username", "demo").strip() or "demo"
    uid = f"u_{username}"
    r.hsetnx(k_user(uid), "username", username)
    r.hset(k_user(uid), mapping={"uid": uid, "created_at": now()})
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
        # --- (MODIFIED) ---
        # We no longer ask for "ACL": "public-read".
        # The file will be uploaded as private.
        presigned_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": AWS_S3_BUCKET_NAME,
                "Key": key,
                "ContentType": mime_type,
            },
            ExpiresIn=3600,
        )
        return ok({
            "iid": iid,
            "key": key,
            "presigned_url": presigned_url,
        })
    except ClientError as e:
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

    # The URL saved here is just a reference, not a public link
    img_url_ref = get_s3_url(key)
    pipe = r.pipeline()
    pipe.hset(k_img(iid), mapping={
        "id": iid,
        "owner_uid": uid,
        "key": key, # This is the important part
        "url": img_url_ref, # Just a reference
        "filename": filename,
        "mime": mime_type,
        "private": 1, # Mark as private
        "created_at": now(),
        "views": 0
    })
    pipe.zadd(k_user_images(uid), {iid: now()})
    pipe.execute()

    # Return the *image ID*, not a direct URL
    return ok({"id": iid, "url": f"/api/v1/image/{iid}"}, 201)

# --- Gallery Endpoints ---

@app.get("/api/v1/me/images")
def me_images():
    auth = require_api_key()
    if not auth:
        return err("auth", "invalid api key", 401)
    
    uid = auth["uid"]
    iids = r.zrevrange(k_user_images(uid), 0, 49)
    items = []
    
    pipe = r.pipeline()
    for iid in iids:
        pipe.hgetall(k_img(iid))
    results = pipe.execute()
    
    for data in results:
        if data:
            # (MODIFIED) We send our *own* app's URL, not the S3 URL
            data['url'] = f"/api/v1/image/{data['id']}"
            items.append(data)
            
    return ok({"items": items})

# --- (NEW) Image Serving Route ---
@app.get("/api/v1/image/<iid>")
def get_image(iid):
    """
    Serves a private S3 file by generating a temporary
    presigned GET URL and redirecting the user to it.
    """
    # We don't require an API key here, so links can be shared
    # (but they will only work for 1 hour)
    
    # 1. Get the S3 key from Redis
    img_data = r.hgetall(k_img(iid))
    if not img_data:
        return err("not_found", "Image not found", 404)
        
    s3_key = img_data.get("key")
    if not s3_key:
        return err("invalid_record", "Image record is corrupt", 500)

    try:
        # 2. Generate a temporary (1 hour) URL to *read* the object
        view_url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": AWS_S3_BUCKET_NAME,
                "Key": s3_key,
            },
            ExpiresIn=3600
        )
        # 3. Redirect the browser to that temporary URL
        return redirect(view_url, code=302)
        
    except ClientError as e:
        print(f"S3 GET Error: {e}")
        return err("s3_error", "Could not get image URL", 500)


# --- Run the app ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
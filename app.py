from __future__ import annotations
import os, time, uuid, redis, boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, url_for
from itsdangerous import URLSafeSerializer

# --- Setup ---
load_dotenv()
app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "dev-secret")
signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="api-key")

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- S3 Setup ---
# Boto3 will automatically find the Learner Lab credentials!
# We just need to tell it the bucket name and region.
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")

if not AWS_S3_BUCKET_NAME:
    print("Error: AWS_S3_BUCKET_NAME environment variable not set.")
    # You might want to exit or raise an error here
    
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

# This helper calculates the final, permanent S3 URL
def get_s3_url(key):
    return f"https://{AWS_S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}"

# --- Static file routes (HTML, CSS, JS) ---
# These are unchanged
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
# These replace the old /api/v1/upload route

@app.post("/api/v1/upload/request")
def request_upload():
    """
    Asks for permission to upload a file.
    Returns a one-time-use S3 URL.
    """
    auth = require_api_key()
    if not auth:
        return err("auth", "invalid api key", 401)
    
    uid = auth["uid"]
    req_data = request.json or {}
    filename = req_data.get("filename")
    mime_type = req_data.get("mime_type")

    if not all([filename, mime_type]):
        return err("validation", "filename and mime_type are required", 400)
    
    # Create a unique ID and key for S3
    iid = f"img_{uuid.uuid4().hex[:12]}"
    key = f"uploads/{uid}/{iid}/{filename}"

    try:
        # Generate the presigned URL
        presigned_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": AWS_S3_BUCKET_NAME,
                "Key": key,
                "ContentType": mime_type,
                "ACL": "public-read", # Make the file public
            },
            ExpiresIn=3600,  # 1 hour
        )
        return ok({
            "iid": iid,
            "key": key,
            "presigned_url": presigned_url,
        })
    except ClientError as e:
        print(f"S3 Error: {e}")
        # This will fail if the LabUserRole doesn't have 's3:PutObject'
        return err("s3_error", "Could not generate S3 upload URL. Check permissions.", 500)

@app.post("/api/v1/upload/complete")
def complete_upload():
    """
    Called by the browser *after* the S3 upload is done.
    Saves the final data to Redis.
    """
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

    # Save the final image data to Redis
    img_url = get_s3_url(key)
    pipe = r.pipeline()
    pipe.hset(k_img(iid), mapping={
        "id": iid,
        "owner_uid": uid,
        "key": key,
        "url": img_url,
        "filename": filename,
        "mime": mime_type,
        "private": 0,
        "created_at": now(),
        "views": 0
    })
    pipe.zadd(k_user_images(uid), {iid: now()})
    pipe.execute()

    return ok({"id": iid, "url": img_url}, 201)

# --- Gallery Endpoint (Unchanged) ---
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
            items.append(data)
            
    return ok({"items": items})

# --- Run the app ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
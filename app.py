from __future__ import annotations
import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template, redirect
from itsdangerous import URLSafeSerializer
from services import AuthService, ImageService
from infrastructure import redis_client # Only imported for the health check route

# --- Setup ---
load_dotenv()
app = Flask(__name__, template_folder="template", static_folder="static")

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "dev-secret")
signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="api-key")

# --- HTTP Helper functions ---
def ok(payload, status=200): return jsonify(payload), status
def err(code, message, status): return jsonify({"error": {"code": code, "message": message}}), status

# --- Auth Middleware (HTTP Concern) ---
def require_api_key():
    token = (request.headers.get("X-API-Key") or "").strip()
    if not token:
        return None
    try:
        return signer.loads(token)
    except Exception:
        return None

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
        return ok({"redis": bool(redis_client.redis())})
    except Exception as e:
        return err("redis_unreachable", str(e), 500)

# --- Auth Routes ---
@app.post("/api/v1/dev/issue-key")
def issue_key():
    # App asks Service to create user
    user_data = AuthService.create_new_user()
    
    # App handles the delivery-specific logic (creating the token)
    token = signer.dumps({"uid": user_data["uid"]})
    return ok({"api_key": token, "uid": user_data["uid"]})

# --- S3 Upload Routes ---

@app.post("/api/v1/upload/request")
def request_upload():
    auth = require_api_key()
    if not auth: return err("auth", "invalid api key", 401)
    
    req_data = request.json or {}
    filename = req_data.get("filename")
    mime_type = req_data.get("mime_type")

    if not all([filename, mime_type]):
        return err("validation", "filename and mime_type are required", 400)
    
    try:
        # Delegate to Service Layer
        result = ImageService.initiate_upload(auth["uid"], filename, mime_type)
        return ok(result)
    except Exception as e:
        print(f"Error: {e}")
        return err("service_error", "Could not initiate upload.", 500)

@app.post("/api/v1/upload/complete")
def complete_upload():
    auth = require_api_key()
    if not auth: return err("auth", "invalid api key", 401)
    
    req_data = request.json or {}
    
    # Validation
    required = ["iid", "key", "filename", "mime_type"]
    if not all(k in req_data for k in required):
        return err("validation", "missing required fields", 400)

    try:
        # Delegate to Service Layer
        result = ImageService.finalize_upload(
            auth["uid"], 
            req_data["iid"], 
            req_data["key"], 
            req_data["filename"], 
            req_data["mime_type"]
        )
        return ok(result, 201)
    except Exception as e:
        print(f"Error: {e}")
        return err("save_error", "Could not save upload metadata", 500)

# --- Gallery Routes ---

@app.get("/api/v1/me/images")
def me_images():
    auth = require_api_key()
    if not auth: return err("auth", "invalid api key", 401)
    
    # App Layer just asks for the data. 
    # Service Layer handles the complex URL formatting logic.
    items = ImageService.get_user_gallery(auth["uid"])
            
    return ok({"items": items})

@app.get("/api/v1/image/<iid>")
def get_image(iid):
    try:
        view_url = ImageService.get_image_download_url(iid)
        if not view_url:
             return err("not_found", "Image not found", 404)
        
        return redirect(view_url, code=302)
    except ValueError:
        return err("invalid_record", "Image record is corrupt", 500)
    except Exception:
        return err("s3_error", "Could not get image URL", 500)

# --- Delete Route ---

@app.delete("/api/v1/image/<iid>")
def delete_image(iid):
    auth = require_api_key()
    if not auth: return err("auth", "invalid api key", 401)
    
    # Delegate logic (including ownership check) to Service
    result = ImageService.delete_image(iid, auth["uid"])
    
    if "error" in result:
        return err(result["error"], "Operation failed", result.get("code", 500))
        
    return ok({"status": "deleted", "id": iid})

# --- Run the app ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
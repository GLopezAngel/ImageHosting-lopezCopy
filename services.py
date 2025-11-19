import uuid
import os
import re
import unicodedata
import time
from infrastructure import redis_client, s3_client

# Helper for timestamps
def now(): return int(time.time())

class Utils:
    @staticmethod
    def sanitize_filename(filename: str, max_len: int = 120) -> str:
        """Normalize filenames so S3 keys are URL-safe and consistent."""
        filename = filename or "file"
        name, ext = os.path.splitext(filename)

        def normalize(value: str) -> str:
            normalized = unicodedata.normalize("NFKD", value)
            return normalized.encode("ascii", "ignore").decode()

        safe_name = normalize(name)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", safe_name).strip("-._").lower()
        if not safe_name:
            safe_name = "file"
        safe_name = safe_name[:max_len]

        safe_ext = normalize(ext).lower()
        safe_ext = re.sub(r"[^a-z0-9]", "", safe_ext)
        safe_ext = f".{safe_ext}" if safe_ext else ""

        return f"{safe_name}{safe_ext}"

class AuthService:
    @staticmethod
    def create_new_user():
        """Generates a new user identity and saves to DB."""
        username = f"user_{uuid.uuid4().hex[:8]}"
        uid = f"u_{username}"
        redis_client.create_user(uid, username, now())
        return {"uid": uid, "username": username}

class ImageService:
    @staticmethod
    def initiate_upload(uid: str, filename: str, mime_type: str):
        """
        Prepares the system for an upload.
        1. Generates ID and clean filename.
        2. Generates the storage path (Key).
        3. Asks S3 for a presigned upload URL.
        """
        safe_filename = Utils.sanitize_filename(filename)
        iid = f"img_{uuid.uuid4().hex[:12]}"
        
        # File structure is uploads/uid/iid/filename
        key = f"uploads/{uid}/{iid}/{safe_filename}"

        presigned_url = s3_client.generate_presigned_upload_url(key, mime_type)
        
        return {
            "iid": iid,
            "key": key,
            "filename": safe_filename,
            "presigned_url": presigned_url,
        }

    @staticmethod
    def finalize_upload(uid: str, iid: str, key: str, filename: str, mime_type: str):
        """
        Confirm upload is done and save metadata to DB.
        """
        # Generate the public read URL reference
        img_url_ref = s3_client.get_public_url(key)
        
        # Save to Redis
        redis_client.store_image(iid, uid, key, img_url_ref, filename, mime_type, now())
        
        return {"id": iid, "url": img_url_ref}

    @staticmethod
    def get_user_gallery(uid: str):
        """
        Fetches user's images and ensures URLs are viewable.
        """
        iids = redis_client.get_user_images(uid, limit=50)
        results = redis_client.get_images_batch(iids)
        
        clean_items = []
        for data in results:
            if not data: continue

            url = data.get("url")
            key = data.get("key")

            # Logic: If the stored URL isn't directly usable, generate a fresh signed one
            # or the public equivalent.
            if key and url and (url.startswith("s3://") or "#" in url):
                data["url"] = s3_client.get_public_url(key)
            elif not url and key:
                data["url"] = s3_client.get_public_url(key)
            elif not data.get("url"):
                # Fallback to application proxy if no external URL exists
                data["url"] = f"/api/v1/image/{data['id']}"

            clean_items.append(data)
            
        return clean_items

    @staticmethod
    def get_image_download_url(iid: str):
        """
        Gets a single image record and generates a temporary download link.
        """
        img_data = redis_client.get_image(iid)
        if not img_data:
            return None
            
        s3_key = img_data.get("key")
        if not s3_key:
            raise ValueError("Image record corrupt: missing key")

        return s3_client.generate_presigned_download_url(s3_key)

    @staticmethod
    def delete_image(iid: str, requester_uid: str):
        """
        Business Logic for deletion:
        1. Check existence.
        2. Check ownership (Security/Business Rule).
        3. Delete from Storage (S3).
        4. Delete from DB (Redis).
        """
        img_data = redis_client.get_image(iid)
        if not img_data:
            return {"error": "not_found", "code": 404}
            
        if img_data.get("owner_uid") != requester_uid:
            return {"error": "forbidden", "code": 403}
            
        s3_key = img_data.get("key")
        if not s3_key:
            return {"error": "corrupt_record", "code": 500}

        # Execute deletion
        try:
            s3_client.delete_object(s3_key)
            redis_client.delete_image_from_redis(iid, requester_uid)
            return {"status": "success"}
        except Exception as e:
            print(f"Service Error: {e}")
            return {"error": "storage_error", "code": 500}
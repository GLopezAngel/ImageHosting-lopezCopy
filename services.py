"""
Service layer: This is where the *actual business logic* lives.
The Flask app shouldn’t be doing heavy lifting — it should just forward requests here.
"""

import uuid
import os
import re
import unicodedata
import time

# These are our infrastructure-level clients (Redis + S3)
# They handle the "how" of storage. Services decide the "when/why".
from infrastructure.redis_client import RedisClient
from infrastructure.s3_client import S3Client

redis_client = RedisClient()
s3_client = S3Client()
# Just a tiny helper to get timestamps in seconds
def now():
    return int(time.time())


class Utils:
    """
    Just a small toolbox class.
    Mostly used so we can clean filenames before uploading to S3.
    """

    @staticmethod
    def sanitize_filename(filename: str, max_len: int = 120) -> str:
        """Normalize filenames so S3 keys are URL-safe and consistent."""
        filename = filename or "file"
        name, ext = os.path.splitext(filename)

        # Normalize / strip accents
        def normalize(value: str) -> str:
            normalized = unicodedata.normalize("NFKD", value)
            return normalized.encode("ascii", "ignore").decode()

        # Clean the base name
        safe_name = normalize(name)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", safe_name).strip("-._").lower()
        if not safe_name:
            safe_name = "file"

        safe_name = safe_name[:max_len]

        # Clean the extension
        safe_ext = normalize(ext).lower()
        safe_ext = re.sub(r"[^a-z0-9]", "", safe_ext)
        safe_ext = f".{safe_ext}" if safe_ext else ""

        return f"{safe_name}{safe_ext}"


class AuthService:
    """
    Handles anything related to creating or managing user identities.
    The Flask app should NOT be talking to Redis directly.
    """

    @staticmethod
    def create_new_user():
        """Generate a new user ID and save it into Redis."""
        username = f"user_{uuid.uuid4().hex[:8]}"
        uid = f"u_{username}"

        # This uses our redis client class, not raw redis
        redis_client.create_user(uid, username, now())

        return {
            "uid": uid,
            "username": username,
        }


class ImageService:
    """
    Handles all image-related business logic.
    Flask calls into this anytime you upload, view, or delete an image.
    """

    @staticmethod
    def initiate_upload(uid: str, filename: str, mime_type: str):
        """
        Step 1 of uploading:
        - clean filename
        - generate image ID
        - build the S3 key path
        - ask S3 for a presigned upload URL
        """
        safe_filename = Utils.sanitize_filename(filename)
        iid = f"img_{uuid.uuid4().hex[:12]}"

        # Storing everything under uploads/<user>/<imageID>/<filename>
        key = f"uploads/{uid}/{iid}/{safe_filename}"

        # Ask S3 to give us a “temporary upload link”
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
        Step 2 of uploading:
        The image is already in S3 — now we save the metadata to Redis.
        """
        public_url = s3_client.get_public_url(key)

        redis_client.store_image(
            iid,
            uid,
            key,
            public_url,
            filename,
            mime_type,
            now()
        )

        return {"id": iid, "url": public_url}

    @staticmethod
    def get_user_gallery(uid: str):
        """
        Pull all images for the user and make sure URLs are actually usable.
        Redis might store older URLs, so we fix/refresh as needed.
        """
        iids = redis_client.get_user_images(uid, limit=50)
        results = redis_client.get_images_batch(iids)

        clean_items = []
        for data in results:
            if not data:
                continue

            url = data.get("url")
            key = data.get("key")

            # Clean or rebuild URLs when needed
            if key and (not url or url.startswith("s3://") or "#" in url):
                data["url"] = s3_client.get_public_url(key)

            # If URL is completely missing, fallback to app proxy
            if not data.get("url"):
                data["url"] = f"/api/v1/image/{data['id']}"

            clean_items.append(data)

        return clean_items

    @staticmethod
    def get_image_download_url(iid: str):
        """
        Fetch an individual image record and generate a temporary download link.
        """
        img_data = redis_client.get_image(iid)
        if not img_data:
            return None

        s3_key = img_data.get("key")
        if not s3_key:
            raise ValueError("Image record missing S3 key — this means it's corrupted.")

        return s3_client.generate_presigned_download_url(s3_key)

    @staticmethod
    def delete_image(iid: str, requester_uid: str):
        """
        Full delete logic:
        - make sure image exists
        - make sure the person deleting it actually owns it
        - delete from S3 first
        - delete from Redis second
        """
        img_data = redis_client.get_image(iid)
        if not img_data:
            return {"error": "not_found", "code": 404}

        if img_data.get("owner_uid") != requester_uid:
            return {"error": "forbidden", "code": 403}

        s3_key = img_data.get("key")
        if not s3_key:
            return {"error": "corrupt_record", "code": 500}

        # Try removing from both storage layers
        try:
            s3_client.delete_object(s3_key)
            redis_client.delete_image(iid, requester_uid)
            return {"status": "success"}
        except Exception as e:
            print(f"Service Error: {e}")
            return {"error": "storage_error", "code": 500}

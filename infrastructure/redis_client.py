import os
from typing import List, Dict, Any, Optional
import redis
from dotenv import load_dotenv

load_dotenv()

class RedisClient:
    """
    This class is the little wrapper around Redis so our whole project doesn't
    have random functions floating around. Everything Redis-related now lives here.
    """

    def __init__(self, url: Optional[str] = None, decode_responses: bool = True):
        # Either use the env variable, or just assume Redis is running locally
        self.redis_url = url or os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # This is the actual Redis connection the whole app uses
        self._r = redis.from_url(self.redis_url, decode_responses=decode_responses)

 
    # Internal key helpers
    
    # ---------------------------
    @staticmethod
    def _k_user(uid: str) -> str:
        return f"user:{uid}"

    @staticmethod
    def _k_user_images(uid: str) -> str:
        return f"user:{uid}:images"

    @staticmethod
    def _k_img(iid: str) -> str:
        return f"img:{iid}"

    
    # User Operations
    # ---------------------------
    def create_user(self, uid: str, username: str, created_at: float) -> None:
        """
        Creates a user record in Redis. There's no "tables" so we just stuff it
        into a Redis hash.
        """
        # hsetnx = only set the username if it doesn't already exist
        self._r.hsetnx(self._k_user(uid), "username", username)

        # Store other info (uid and created_at)
        self._r.hset(self._k_user(uid), mapping={
            "uid": uid,
            "created_at": created_at
        })

   
    # Image Operations
    # ---------------------------
    def store_image(
        self,
        iid: str,
        owner_uid: str,
        key: str,
        url: str,
        filename: str,
        mime_type: str,
        created_at: float,
    ) -> None:
        """
        Saves image metadata AND links it to the user.
        Pipeline is used so Redis runs everything in one go.
        """
        pipe = self._r.pipeline()

        # Save the image metadata
        pipe.hset(self._k_img(iid), mapping={
            "id": iid,
            "owner_uid": owner_uid,
            "key": key,
            "url": url,
            "filename": filename,
            "mime": mime_type,
            "private": 1,
            "created_at": created_at,
            "views": 0
        })

        # Add it to the user's sorted set for gallery order
        pipe.zadd(self._k_user_images(owner_uid), {iid: created_at})

        pipe.execute()

    def get_image(self, iid: str) -> Dict[str, Any]:
        """Gets one image and returns its data as a dict."""
        return self._r.hgetall(self._k_img(iid))

    def get_user_images(self, uid: str, limit: int = 50) -> List[str]:
        """Gets a list of image IDs sorted newest-first."""
        return self._r.zrevrange(self._k_user_images(uid), 0, limit - 1)

    def get_images_batch(self, iids: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch multiple images at once.
        This is way faster than doing hgetall() one at a time.
        """
        if not iids:
            return []

        pipe = self._r.pipeline()
        for iid in iids:
            pipe.hgetall(self._k_img(iid))
        return pipe.execute()

    def delete_image(self, iid: str, uid: str) -> None:
        """
        Deletes image metadata AND removes it from the user's list.
        Both happen inside the same pipeline.
        """
        pipe = self._r.pipeline()
        pipe.delete(self._k_img(iid))
        pipe.zrem(self._k_user_images(uid), iid)
        pipe.execute()

    def ping(self) -> bool:
        """Simple check to confirm Redis is up and alive."""
        return self._r.ping()





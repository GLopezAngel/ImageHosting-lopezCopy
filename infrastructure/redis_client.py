"""Redis client and operations for data storage."""
import os
import redis
from dotenv import load_dotenv

load_dotenv()

# Redis connection setup
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

# --- Redis key helpers ---
def k_user(uid):
    """Get Redis key for user data."""
    return f"user:{uid}"

def k_user_images(uid):
    """Get Redis key for user's images sorted set."""
    return f"user:{uid}:images"

def k_img(iid):
    """Get Redis key for image data."""
    return f"img:{iid}"

# --- User operations ---
def create_user(uid, username, created_at):
    """Create a new user in Redis."""
    r.hsetnx(k_user(uid), "username", username)
    r.hset(k_user(uid), mapping={"uid": uid, "created_at": created_at})

# --- Image operations ---
def store_image(iid, owner_uid, key, url, filename, mime_type, created_at):
    """Store image metadata in Redis."""
    pipe = r.pipeline()
    pipe.hset(k_img(iid), mapping={
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
    pipe.zadd(k_user_images(owner_uid), {iid: created_at})
    pipe.execute()

def get_image(iid):
    """Get image data from Redis."""
    return r.hgetall(k_img(iid))

def get_user_images(uid, limit=50):
    """Get list of image IDs for a user, ordered by most recent."""
    return r.zrevrange(k_user_images(uid), 0, limit - 1)

def get_images_batch(iids):
    """Get image data for multiple image IDs."""
    if not iids:
        return []
    pipe = r.pipeline()
    for iid in iids:
        pipe.hgetall(k_img(iid))
    return pipe.execute()

def delete_image_from_redis(iid, uid):
    """Delete image data from Redis."""
    pipe = r.pipeline()
    pipe.delete(k_img(iid))
    pipe.zrem(k_user_images(uid), iid)
    pipe.execute()

def ping_redis():
    """Check if Redis is reachable."""
    return r.ping()



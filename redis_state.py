import redis
import json
import os

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")  # Default to localhost for WSL host
r = redis.Redis(host=REDIS_HOST, port=6379, db=2, decode_responses=True)

def redis_key(user_id, url):
    """Generate a user-scoped Redis key."""
    return f"user:{user_id}:url:{url}"

def get_url_state(user_id, url):
    """Get state for a specific user's URL."""
    key = redis_key(user_id, url)
    data = r.get(key)
    return json.loads(data) if data else None

def set_url_state(user_id, url, state):
    """Set state for a specific user's URL."""
    key = redis_key(user_id, url)
    r.set(key, json.dumps(state))

def update_url_state(user_id, url, **kwargs):
    """Update state for a specific user's URL."""
    state = get_url_state(user_id, url) or {}
    state.update(kwargs)
    set_url_state(user_id, url, state)
# status_store.py
import redis
import json
from datetime import datetime

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def set_status(url, status, **fields):
    key = f"doc:{url}"
    data = {"status": status, "last_update": datetime.utcnow().isoformat()}
    data.update(fields)
    r.hset(key, mapping=data)

def get_status(url):
    key = f"doc:{url}"
    return r.hgetall(key)

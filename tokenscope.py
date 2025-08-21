import jwt
import json

# Load your token string (access token) from file or var
with open("token_cache.json") as f:
    cache = json.load(f)
token = cache['access_token']  # adjust key if stored differently

decoded = jwt.decode(token, options={"verify_signature": False})
print(json.dumps(decoded, indent=2))



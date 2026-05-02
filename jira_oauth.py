import os
import json
import time
import requests
from requests.auth import AuthBase, HTTPBasicAuth

from my_utils import user_config_file, _CONFIG_DIR

ATLASSIAN_AUTH_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

JIRA_OAUTH_SCOPES = "read:jira-work write:jira-work offline_access"

# Server-side credentials file — never exposed to the browser
JIRA_APP_CREDENTIALS_FILE = os.path.join(_CONFIG_DIR, "jira_oauth_app.json")


class BearerAuth(AuthBase):
    """requests auth adapter for OAuth 2.0 Bearer tokens."""
    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r


def load_jira_app_credentials():
    """Load OAuth app client_id and client_secret from the server-side config file."""
    if not os.path.exists(JIRA_APP_CREDENTIALS_FILE):
        print(f"❌ Jira OAuth app credentials file not found: {JIRA_APP_CREDENTIALS_FILE}")
        return None, None
    with open(JIRA_APP_CREDENTIALS_FILE, "r") as f:
        data = json.load(f)
    return data.get("client_id"), data.get("client_secret")


def get_token_file(userlogin):
    return user_config_file(userlogin, "jira_token.json")


def save_jira_token(token_data, userlogin):
    token_file = get_token_file(userlogin)
    with open(token_file, "w") as f:
        json.dump(token_data, f)
    print(f"✅ Saved Jira OAuth token for user={userlogin} to {token_file}")


def _refresh_jira_token(token_data):
    client_id, client_secret = load_jira_app_credentials()
    refresh_token = token_data.get("refresh_token")
    if not client_id or not client_secret or not refresh_token:
        print("❌ Cannot refresh Jira token: missing app credentials or refresh token")
        return None
    resp = requests.post(ATLASSIAN_TOKEN_URL, json={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    if resp.status_code != 200:
        print(f"❌ Jira token refresh failed ({resp.status_code}): {resp.text}")
        return None
    new_data = resp.json()
    token_data["access_token"] = new_data["access_token"]
    if "refresh_token" in new_data:
        token_data["refresh_token"] = new_data["refresh_token"]
    token_data["expires_at"] = time.time() + new_data.get("expires_in", 3600)
    return token_data


def load_jira_token(userlogin):
    """Load Jira OAuth token, auto-refreshing if expired. Returns token dict or None."""
    token_file = get_token_file(userlogin)
    if not os.path.exists(token_file):
        return None
    with open(token_file, "r") as f:
        token_data = json.load(f)
    if time.time() > token_data.get("expires_at", 0) - 60:
        token_data = _refresh_jira_token(token_data)
        if not token_data:
            return None
        save_jira_token(token_data, userlogin)
    return token_data


def is_jira_oauth_logged_in(userlogin):
    try:
        return load_jira_token(userlogin) is not None
    except Exception as e:
        print(f"⚠️ Error checking Jira OAuth for {userlogin}: {e}")
        return False


def logout_jira_oauth(userlogin):
    token_file = get_token_file(userlogin)
    if os.path.exists(token_file):
        os.remove(token_file)
        print(f"🧹 Removed Jira OAuth token for user={userlogin}")


def fetch_cloud_id(access_token):
    """Fetch the first accessible Jira Cloud instance ID and URL."""
    resp = requests.get(
        ATLASSIAN_RESOURCES_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if resp.status_code == 200:
        resources = resp.json()
        print(f"🔍 Jira accessible-resources returned {len(resources)} site(s):")
        for r in resources:
            print(f"   id={r.get('id')}  url={r.get('url')}  name={r.get('name')}")
        if resources:
            return resources[0].get("id"), resources[0].get("url")
    print(f"❌ Failed to fetch Jira cloud ID ({resp.status_code}): {resp.text}")
    return None, None


def exchange_code_for_token(code, redirect_uri):
    """Exchange an authorization code for access+refresh tokens using server-side credentials."""
    client_id, client_secret = load_jira_app_credentials()
    if not client_id or not client_secret:
        return None, "Jira OAuth app credentials not configured (jira_oauth_app.json missing)"
    resp = requests.post(ATLASSIAN_TOKEN_URL, json={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    })
    if resp.status_code != 200:
        return None, f"Token exchange failed ({resp.status_code}): {resp.text}"
    return resp.json(), None


def create_jira_client(userlogin, jira_url, jira_email=None, jira_api_token=None):
    """
    Returns (jira_client, requests_auth) using the best available auth method.
    Tries OAuth token first, falls back to API token.
    Returns (None, None) if no auth is available.
    """
    from jira import JIRA

    token_data = load_jira_token(userlogin)
    if token_data:
        access_token = token_data["access_token"]
        print(f"🔑 Using Jira OAuth for user={userlogin}")
        jira_client = JIRA(server=jira_url, token_auth=access_token)
        return jira_client, BearerAuth(access_token)

    if jira_api_token and jira_email:
        print(f"🔑 Using Jira API token for user={userlogin}")
        jira_client = JIRA(server=jira_url, basic_auth=(jira_email, jira_api_token))
        return jira_client, HTTPBasicAuth(jira_email, jira_api_token)

    print(f"❌ No Jira auth available for user={userlogin}")
    return None, None

# google_oauth.py
import os
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request



from googleapiclient.discovery import build
from google_oauth import load_google_token

def get_google_drive_filename(userlogin: str, file_id: str) -> str | None:
    """
    Returns the filename (title) of a Google Drive file given its ID.
    Works for Google Sheets, Docs, Slides, etc.
    """
    creds = load_google_token(userlogin)
    if not creds or not creds.valid:
        raise Exception(f"❌ User {userlogin} not logged in to Google Drive")

    # Build Drive API service
    service = build("drive", "v3", credentials=creds)

    # Retrieve file metadata (name)
    file = service.files().get(fileId=file_id, fields="name").execute()
    return file.get("name")


# 2 different CONFIG DIRs used in different functions
# when authorizing and saving token use ./config because it's called by appnew.py whose workdir is not user/logs path
# when loading token use ../../../config because it's called by scope.py whose workdir is user/logs folderpath
#CONFIG_DIR = "../../../config"
CONFIG_DIR = "./config"
GOOGLE_CLIENT_SECRETS_FILE = os.path.join(CONFIG_DIR, "google_credentials.json")

#REDIRECT_URI = 'http://localhost:5000/google/callback'
#CREDENTIALS_FILE = './config/google_credentials.json'

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',           # Full Sheets access
    'https://www.googleapis.com/auth/drive.metadata.readonly', # Can read file metadata
    'https://www.googleapis.com/auth/drive',                  # Full Drive access
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

def get_token_file(userlogin):
    """Return per-user token file path"""
    return os.path.join(CONFIG_DIR, f"google_token_{userlogin}.json")


def get_google_flow(userlogin):
    """Initialize Google OAuth flow for this user"""
    return Flow.from_client_secrets_file(
        GOOGLE_CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:5000/google/callback"
    )


def save_google_token(creds, userlogin):
    """Save OAuth token to per-user JSON file"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    token_file = get_token_file(userlogin)
    with open(token_file, "w") as token:
        token.write(creds.to_json())
    print(f"✅ Saved Google token for user={userlogin} to {token_file}")

def save_google_token(creds, userlogin):
    """Save OAuth token to per-user JSON file"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    token_file = get_token_file(userlogin)
    with open(token_file, "w") as token:
        token.write(creds.to_json())
    print(f"✅ Saved Google token for user={userlogin} to {token_file}")

from google.auth.exceptions import RefreshError

def load_google_token(userlogin):
    print(f"called load_google_token({userlogin})")
    token_file = get_token_file(userlogin)
    if not os.path.exists(token_file):
        print(f"❌ No Google token file={token_file} for user={userlogin} cwd={os.getcwd()}")
        return None

    with open(token_file, "r") as f:
        print(f"🔑 Loading Google token for user={userlogin} from {token_file}")
        creds_data = json.load(f)

    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_google_token(creds, userlogin)
            print(f"🔄 Refreshed Google token for user={userlogin}")
        except RefreshError as e:
            print(f"❌ Failed to refresh Google token for user={userlogin}: {e}")
            return None

    return creds


from google.auth.exceptions import RefreshError

def is_google_logged_in(userlogin):
    """Check if user already has a valid Google token"""
    print(f"called is_google_logged_in({userlogin})")

    try:
        creds = load_google_token(userlogin)
        valid = creds and creds.valid
        print(f"✅ is_google_logged_in({userlogin}) determined that Google token valid for user={userlogin}: {valid}")
        return valid
    except RefreshError as e:
        print(f"❌ Google token refresh failed for user={userlogin}: {e}")
        return False
    except Exception as e:
        print(f"⚠️ Unexpected error checking Google login for user={userlogin}: {e}")
        return False

def logout_google(userlogin):
    """Delete per-user token file"""
    token_file = get_token_file(userlogin)
    if os.path.exists(token_file):
        os.remove(token_file)
        print(f"🧹 Removed Google token for user={userlogin}")

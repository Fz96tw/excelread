# google_oauth.py
import os
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from my_utils import user_config_file, _CONFIG_DIR
GOOGLE_CLIENT_SECRETS_FILE = os.path.join(_CONFIG_DIR, "google_credentials.json")

#REDIRECT_URI = 'http://localhost:5000/google/callback'
#CREDENTIALS_FILE = './config/google_credentials.json'

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',             # files opened/created by this app
    'https://www.googleapis.com/auth/drive.metadata.readonly', # read file metadata
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]



import httplib2
from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp
#from google_oauth import load_google_token

_GOOGLE_API_TIMEOUT = 30  # seconds

def get_google_drive_filename(userlogin: str, file_id: str) -> str | None:
    """
    Returns the filename (title) of a Google Drive file given its ID.
    Works for Google Sheets, Docs, Slides, etc.
    """
    creds = load_google_token(userlogin)
    if not creds or not creds.valid:
        raise Exception(f"❌ User {userlogin} not logged in to Google Drive")

    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=_GOOGLE_API_TIMEOUT))
    service = build("drive", "v3", http=http)

    # Retrieve file metadata (name)
    file = service.files().get(fileId=file_id, fields="name").execute()
    return file.get("name")


def get_token_file(userlogin):
    """Return per-user token file path"""
    return user_config_file(userlogin, "google_token.json")


    
def get_google_flow(userlogin,redirectpath):
    """Initialize Google OAuth flow for this user"""
    print(f"inside get_google_flow params userlogin={userlogin} redirectpath={redirectpath}")
    return Flow.from_client_secrets_file(
        GOOGLE_CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_url = f"{redirectpath}/google/callback"
    )


def save_google_token(creds, userlogin):
    """Save OAuth token to per-user JSON file"""
    token_file = get_token_file(userlogin)
    with open(token_file, "w") as token:
        token.write(creds.to_json())
    print(f"✅ Saved Google token for user={userlogin} to {token_file}")


def load_google_token(userlogin):
    """Load and refresh Google token if exists"""
    token_file = get_token_file(userlogin)
    if not os.path.exists(token_file):
        print(f"❌ No Google token file={token_file} for user={userlogin} cwd={os.getcwd()}")
        return None

    with open(token_file, "r") as f:
        print(f"🔑 Loading Google token for user={userlogin} from {token_file}")
        creds_data = json.load(f)

    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_google_token(creds, userlogin)
        print(f"🔄 Refreshed Google token for user={userlogin}")

    return creds


def is_google_logged_in(userlogin):
    """Check if user already has a valid token"""
    creds = load_google_token(userlogin)
    print(f"✅ is_google_logged_in({userlogin}) determined that Google token valid for user={userlogin}: {creds and creds.valid}")
    return creds and creds.valid


def logout_google(userlogin):
    """Delete per-user token file"""
    token_file = get_token_file(userlogin)
    if os.path.exists(token_file):
        os.remove(token_file)
        print(f"🧹 Removed Google token for user={userlogin}")

import os
import sys
import json
import requests
import msal
from dotenv import load_dotenv
from urllib.parse import urlparse, quote, unquote
import shutil



# -------------------------------
# Config from environment variables
# -------------------------------
#ENV_PATH = "../../../config/.env"
ENV_PATH = "./config/.env"
load_dotenv(dotenv_path=ENV_PATH)

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"] # only needed for app-only auth. Not used for delegated user auth.
TENANT_ID = os.environ["TENANT_ID"]
SCOPES = ["https://graph.microsoft.com/.default"] # only neded for app-only auth. Delegated user-auth needs to override SCOPES to use user-specific scopes (see SCOPES further donw) 
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

TOKEN_CACHE_FILE = "./config/token_cache.json"


# -------------------------------
# used user-specific OAuth token cache.
# NOTE: FIX LATER - for now persistent between run across ALL files 
#  and ALL users regardless of which user is downloading whatever file.  Not good security-wise.)
def load_cache():
    print("load_cache()")
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
        print(f"loaded cache from file '{TOKEN_CACHE_FILE}'")
    else:
        print(f"load_cahce failed to find path '{TOKEN_CACHE_FILE}'")
    return cache

# -------------------------------
# used user-specific OAuth token cache.
# NOTE: FIX LATER - for now persistent between run across ALL files 
#  and ALL users regardless of which user is downloading whatever file.  Not good security-wise.)
def save_cache(cache):
    if cache.has_state_changed:
        print(f"saved cache from file '{TOKEN_CACHE_FILE}'")
        open(TOKEN_CACHE_FILE, "w").write(cache.serialize())


# -------------------------------
# used user-specific OAuth token cache.
def get_user_token():
    print("🔑 Acquiring delegated user token...")
    SCOPES = ["Files.Read", "Sites.Read.All", "User.Read"]  # override default SCOPE from above to use user-specific instead of application auth
    cache = load_cache()
    pca = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # Try to get a cached token first
    accounts = pca.get_accounts()
    if accounts:
        result = pca.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print("✅ Using cached token.")
            return result["access_token"]

    # No cached token, perform interactive login
    result = pca.acquire_token_interactive(SCOPES)
    if "access_token" not in result:
        raise Exception(f"❌ Failed to get delegated token: {result}")

    save_cache(cache)
    print("✅ Delegated token acquired and cached.")
    return result["access_token"]

def get_app_token_delegated():
    print("🔑 Acquiring app token...")
    cache = load_cache()  # ✅ Load the cache here

    cca = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache  # ✅ Attach cache
    )

    accounts = cca.get_accounts()
    if accounts:
        print(f"Found {len(accounts)} accounts in cache. Trying silent acquire...")
        result = cca.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print("✅ Using cached user token.")
            return result["access_token"]

    raise Exception("❌ No cached user token found. Please log in through the Flask app first.")

# -------------------------------
# MSAL: get application token using CLIENT CREDENTIALS flow.  Not user-specific OAuth token.
# -------------------------------
'''def get_app_token():
    print("🔑 Acquiring app token...")
    cca = msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )
    result = cca.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"❌ Failed to get token: {result}")
    print("✅ Access token acquired.")
    return result["access_token"]
'''
# ----------
# 
# ---------------------
# Resolve site ID from SharePoint URL
# -------------------------------
def get_site_id(site_url, token):
    print(f"📂 Resolving site ID for {site_url}...")
    headers = {"Authorization": f"Bearer {token}"}
    parsed = urlparse(site_url)
    path = parsed.path.rstrip("/")
    api_url = f"https://graph.microsoft.com/v1.0/sites/{parsed.netloc}:{path}"
    
    r = requests.get(api_url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"❌ Failed to get site ID: {r.status_code} {r.text}")
    site_id = r.json()["id"]
    print(f"✅ Site ID resolved: {site_id}")
    return site_id

def graph_encode_path(path):
    return "/".join(quote(part) for part in path.split("/"))

# -------------------------------
# Download Excel file + metadata
# -------------------------------

def download_excel_with_meta(site_url, file_path):

    if delegated_auth:
        token = get_app_token_delegated()
    else:
        token = get_app_token()
    
    site_id = get_site_id(site_url, token)
    headers = {"Authorization": f"Bearer {token}"}

    file_path_encoded = graph_encode_path(file_path)
    print(f"📄 Fetching metadata for {file_path}...")

    # 1. Get file metadata (etag, lastModifiedDateTime, download URL, etc.)
    meta_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{file_path_encoded}"
    meta_resp = requests.get(meta_url, headers=headers)
    if meta_resp.status_code != 200:
        raise Exception(f"❌ Failed to get metadata: {meta_resp.status_code} {meta_resp.text}")
    meta = meta_resp.json()

    etag = meta["eTag"]
    last_modified = meta["lastModifiedDateTime"]
    download_url = meta["@microsoft.graph.downloadUrl"]

    print(f"✅ Metadata retrieved. eTag={etag}, lastModified={last_modified}")

    # 2. Download actual file content
    print("⬇️  Downloading file content...")
    content_resp = requests.get(download_url)
    if content_resp.status_code != 200:
        raise Exception(f"❌ Failed to download Excel: {content_resp.status_code} {content_resp.text}")
    excel_bytes = content_resp.content

    # 3. Save file
    filename = file_path.replace("/", "_")  # file may be inside sharepoint folders so keep the folder names in the filename but replace / with _ 
    with open(filename, "wb") as f:
        f.write(excel_bytes)
    print(f"✅ File saved locally as {filename}")

    # 4. Save metadata sidecar JSON
    meta_filename = filename + "." + timestamp + ".meta.json"
    with open(meta_filename, "w") as f:
        json.dump({"etag": etag, "lastModified": last_modified}, f, indent=2)
    print(f"✅ Metadata saved as {meta_filename}")

    return filename, meta_filename



def copy_excel_to_working_directory(filepath: str) -> str:
    
    #Copy an Excel file from `filepath` into the current working directory.
    #Handles URL-encoded paths (spaces as %20).
    #Returns the destination path.
    #Raises FileNotFoundError if source does not exist.
    
    filepath = unquote(filepath)  # decode %20 → space

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Source file does not exist: {filepath}")

    filename = os.path.basename(filepath)
    dest_path = os.path.join(os.getcwd(), filename)

    shutil.copy(filepath, dest_path)
    print(f"Copied file from {filepath} ---> {dest_path}")
    return dest_path




# -------------------------------
# Example usage
# -------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python download.py <sharepoint_file_url> <timestamp>")
        sys.exit(1)

    full_url = sys.argv[1]
    timestamp = sys.argv[2]

    full_url = unquote(full_url)  # decode %20 → space
    parsed_url = urlparse(full_url)

    delegated_auth = False  # set to False to use app-only auth (no user context)

    if len(sys.argv) == 4:
        auth_param = sys.argv[3]
        if "user_auth" in auth_param:
            print(f"detected argument '{auth_param}' so will use delegated authorization instead of app auth flow")
            delegated_auth = True
            CLIENT_ID = os.environ["CLIENT_ID2"]
            CLIENT_SECRET = os.environ["CLIENT_SECRET2"] # only needed for app-only auth. Not used for delegated user auth.
            TENANT_ID = os.environ["TENANT_ID"]
            # Do NOT include reserved scopes here — MSAL adds them automatically
            SCOPES = ["User.Read","Files.ReadWrite.All", "Sites.ReadWrite.All"]
            AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
            print (f"Tenant id: {TENANT_ID}")
            print (f"Client id: {CLIENT_ID}")
            print (f"Client secret: {CLIENT_SECRET}")
            print (f"Authority: {AUTHORITY}")
    else:
        print(f"defaulting to application authorization since user_auth argument not specified")

    if "http" in full_url:
        print(f"http found in full_url={full_url}")
        path_parts = parsed_url.path.strip("/").split("/")
        if len(path_parts) < 2:
            print("Invalid URL format. Expected site path and file path.")
            sys.exit(1)

        site_url = f"{parsed_url.scheme}://{parsed_url.netloc}/{path_parts[0]}/{path_parts[1]}"
        file_path = "/".join(path_parts[2:])

        print("site_url:", site_url)
        print("file_path:", file_path)

        download_excel_with_meta(site_url, file_path)
    else:
        # assume local file
        print(f"assumed to be local file, full_url={full_url}")
        copy_excel_to_working_directory(full_url)


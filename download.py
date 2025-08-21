import os
import sys
import json
import requests
import msal
from dotenv import load_dotenv
from urllib.parse import urlparse, quote

# -------------------------------
# Config from environment variables
# -------------------------------
load_dotenv()
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
TENANT_ID = os.environ["TENANT_ID"]
SCOPES = ["https://graph.microsoft.com/.default"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

TOKEN_CACHE_FILE = "token_cache.json"

# -------------------------------
# MSAL: get application token
# -------------------------------
def get_app_token():
    print("🔑 Acquiring app token...")
    cca = msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )
    result = cca.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"❌ Failed to get token: {result}")
    print("✅ Access token acquired.")
    return result["access_token"]

# -------------------------------
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
    filename = file_path.replace("/", "_")
    with open(filename, "wb") as f:
        f.write(excel_bytes)
    print(f"✅ File saved locally as {filename}")

    # 4. Save metadata sidecar JSON
    meta_filename = filename + ".meta.json"
    with open(meta_filename, "w") as f:
        json.dump({"etag": etag, "lastModified": last_modified}, f, indent=2)
    print(f"✅ Metadata saved as {meta_filename}")

    return filename, meta_filename

# -------------------------------
# Example usage
# -------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <sharepoint_file_url>")
        sys.exit(1)

    full_url = sys.argv[1]
    parsed_url = urlparse(full_url)

    path_parts = parsed_url.path.strip("/").split("/")
    if len(path_parts) < 2:
        print("Invalid URL format. Expected site path and file path.")
        sys.exit(1)

    site_url = f"{parsed_url.scheme}://{parsed_url.netloc}/{path_parts[0]}/{path_parts[1]}"
    file_path = "/".join(path_parts[2:])

    print("site_url:", site_url)
    print("file_path:", file_path)

    download_excel_with_meta(site_url, file_path)

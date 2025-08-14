import os
import requests
import msal
from dotenv import load_dotenv
from urllib.parse import urlparse


import os
import requests
import msal
from urllib.parse import urlparse

# -------------------------------
# Config from environment variables
# -------------------------------
# Load env vars
load_dotenv()
SCOPES = ["https://graph.microsoft.com/.default"]  # Required for client credentials flow
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
TENANT_ID = os.environ["TENANT_ID"]
SCOPES = ["https://graph.microsoft.com/.default"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# -------------------------------
# MSAL: get application token
# -------------------------------
def get_app_token():
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    cca = msal.ConfidentialClientApplication(
        CLIENT_ID, authority=authority, client_credential=CLIENT_SECRET
    )
    result = cca.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"Failed to get token: {result}")
    return result["access_token"]

# -------------------------------
# Resolve site ID from SharePoint URL
# -------------------------------
def get_site_id(site_url):
    token = get_app_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Convert https://tenant.sharepoint.com/sites/Engineering
    # to cloudcurio.sharepoint.com:/sites/Engineering for Graph
    parsed = urlparse(site_url)
    path = parsed.path.rstrip("/")
    api_url = f"https://graph.microsoft.com/v1.0/sites/{parsed.netloc}:{path}"
    
    print(f"Getting site ID for {site_url} using URL: {api_url}")
    r = requests.get(api_url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"Failed to get site ID: {r.status_code} {r.text}")
    return r.json()["id"]

from urllib.parse import quote
def graph_encode_path(path):
    return "/".join(quote(part) for part in path.split("/"))

# -------------------------------
# Download Excel file from SharePoint
# -------------------------------
def download_excel(site_url, file_path):
    token = get_app_token()
    site_id = get_site_id(site_url)
    headers = {"Authorization": f"Bearer {token}"}

    # URL-encode the file path
    #file_path_encoded = requests.utils.quote(file_path)
    file_path_encoded = graph_encode_path(file_path)

    print(f"Downloading file from {file_path_encoded} in site {site_id}")

    #url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root/children"
    #r = requests.get(url, headers=headers)
    #print(r.status_code, r.json())
   
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{file_path_encoded}:/content"

   
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"Failed to download Excel: {r.status_code} {r.text}")
    
    return r.content

# -------------------------------
# Example usage
# -------------------------------
import sys
from urllib.parse import urlparse

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <sharepoint_url>")
        sys.exit(1)

    full_url = sys.argv[1]

    # Parse the URL
    parsed_url = urlparse(full_url)

    # Extract site_url (scheme + netloc + first path segment(s))
    path_parts = parsed_url.path.strip("/").split("/")
    if len(path_parts) < 2:
        print("Invalid URL format. Expected site path and file path.")
        sys.exit(1)

    # Example: 'sites/Engineering/Milestones.xlsx'
    site_url = f"{parsed_url.scheme}://{parsed_url.netloc}/{path_parts[0]}/{path_parts[1]}"

    # Everything after the site path is the file path
    file_path = "/".join(path_parts[2:])

    # Create a safe filename by replacing '/' with '_'
    filename = file_path.replace("/", "_")


    print("site_url:", site_url)
    print("file_path:", file_path)


    excel_bytes = download_excel(site_url, file_path)
    with open(filename, "wb") as f:
        f.write(excel_bytes)
    print("Download complete!")



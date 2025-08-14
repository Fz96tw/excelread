import requests
from collections import defaultdict
import argparse
from urllib.parse import urlparse, quote
import msal
import os


# -------------------------------
# Config from environment variables
# -------------------------------
# Load env vars
from dotenv import load_dotenv
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

# --- PARSE COMMAND-LINE ARGUMENTS ---
parser = argparse.ArgumentParser(description="Update Excel file on SharePoint with changes from a file")
parser.add_argument("file_url", help="Full URL to the Excel file in SharePoint")
parser.add_argument("changes_file", help="Path to the local changes file")
#parser.add_argument("--access_token", required=True, help="Application-level access token for Graph API")
parser.add_argument("--worksheet_name", default="Sheet1", help="Worksheet name to update (default: Sheet1)")
args = parser.parse_args()


file_url = args.file_url
changes_file = args.changes_file
#access_token = args.access_token
access_token = get_app_token()  # Use the function to get the token
worksheet_name = args.worksheet_name

jira_base_url = "https://fz96tw.atlassian.net"




# --- HELPER FUNCTIONS ---
def is_valid_jira_id(value):
    return value.startswith("TES-")

def is_jql(value):
    return value.strip().upper().startswith("JQL")

def create_hyperlink(value):
    if is_valid_jira_id(value):
        return f"{jira_base_url}/browse/{value}"
    elif is_jql(value):
        jql_query = value.replace("JQL", "").strip()
        return f"{jira_base_url}/issues/?jql={jql_query}"
    return None

# --- PARSE CHANGES FILE ---
row_values = defaultdict(dict)
with open(changes_file, "r") as f:
    print("Parsing changes file:", changes_file)
    for line in f:
        line = line.strip()
        print(f"Processing line: {line}")
        if not line or line.startswith("Changes"):
            continue
        if "=" not in line:
            continue
        cell, value_pair = line.split("=", 1)
        if "||" in value_pair:
            new_value, old_value = value_pair.split("||", 1)
        else:
            new_value, old_value = value_pair, ""
        col_letter = ''.join(filter(str.isalpha, cell))
        row_num = int(''.join(filter(str.isdigit, cell)))
        row_values[row_num][col_letter.upper()] = {
            "new": new_value.strip(),
            "old": old_value.strip()  # empty string if no old value
        }
        print(f"Parsed {cell}: new='{new_value.strip()}', old='{old_value.strip()}'")

# --- GRAPH API BASE ---
headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

# --- EXTRACT SITE AND FILE PATH FROM URL ---
parsed = urlparse(file_url)
# Example: https://contoso.sharepoint.com/sites/mysite/Shared%20Documents/ExcelFile.xlsx
hostname = parsed.netloc
path_parts = parsed.path.strip("/").split("/", 2)
if len(path_parts) < 3:
    raise ValueError("Invalid SharePoint URL format. Must include /sites/.../file.xlsx")
site_path = f"/{path_parts[0]}/{path_parts[1]}"
file_path = "/" + path_parts[2]

# Get site ID
site_api_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}"
resp_site = requests.get(site_api_url, headers=headers)
resp_site.raise_for_status()
site_id = resp_site.json()["id"]

# Get file ID
file_api_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:{quote(file_path)}"
resp_file = requests.get(file_api_url, headers=headers)
resp_file.raise_for_status()
item_id = resp_file.json()["id"]

# --- ITERATE AND UPDATE SAFELY ---
for row_num, cols in row_values.items():
    skip_row = False
    for col_letter, values in cols.items():
        cell_address = f"{col_letter}{row_num}"
        url_get = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')"
        resp_get = requests.get(url_get, headers=headers)
        resp_get.raise_for_status()
        current_value = resp_get.json().get("values", [[None]])[0][0]
        current_value = "" if current_value is None else str(current_value)
        current_value = current_value.replace("\n", ";")  # Normalize newlines to semicolons for comparison

        expected_old = values["old"]
        new_value = values["new"]
        if expected_old == "":
            expected_old = ""  # Treat missing old value as blank

        if current_value != expected_old:
            print(f"Skipping row {row_num} because {cell_address} has value '{current_value}' instead of expected '{expected_old}'")
            skip_row = True
            break

        if old_value == new_value:
            print(f"Skipping row {row_num} because {cell_address} (no change reqd) already has the new value '{new_value}'")
            skip_row = True
            break
        
    if skip_row:
        continue

    # Update all cells in the row
    for col_letter, values in cols.items():
        cell_address = f"{col_letter}{row_num}"
        new_value = values["new"]
        if ";" in new_value:
            new_value = new_value.replace(";", "\n")

        # Update cell value
        url_patch = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')"
        payload_value = {"values": [[new_value]]}
        resp_patch = requests.patch(url_patch, json=payload_value, headers=headers)
        print(f"Updated {cell_address}: {resp_patch.status_code}")

        # Add hyperlink if Jira key or JQL
        hyperlink = create_hyperlink(new_value)
        if hyperlink:
            url_hyperlink = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')/format/hyperlink"
            payload_hyperlink = {"hyperlink": hyperlink}
            resp_link = requests.patch(url_hyperlink, json=payload_hyperlink, headers=headers)
            print(f"Hyperlink set for {cell_address}: {resp_link.status_code}")

        # Enable text wrap
        url_wrap = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')/format/wrapText"
        payload_wrap = {"wrapText": True}
        resp_wrap = requests.patch(url_wrap, json=payload_wrap, headers=headers)
        print(f"Wrap text enabled for {cell_address}: {resp_wrap.status_code}")

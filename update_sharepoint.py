import requests
from collections import defaultdict
import argparse
from urllib.parse import urlparse, quote
import msal
import os
import json
import string


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

'''
if "import" in changes_file.lower():
    print("Import mode detected based on changes file name.")
    import_mode = True
else:
    import_mode = False
'''
import_mode = False

import re

def read_jira_url(filename: str) -> str:
    """
    Reads the JIRA_URL value from a config-style file.

    Args:
        filename (str): Path to the file containing JIRA settings.

    Returns:
        str: The JIRA URL, or None if not found.
    """
    jira_url = None
    pattern = re.compile(r'^JIRA_URL\s*=\s*["\'](.+?)["\']')

    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            match = pattern.match(line.strip())
            if match:
                jira_url = match.group(1)
                break

    return jira_url

#jira_base_url = "https://fz96tw.atlassian.net"

# --- HELPER FUNCTIONS ---
def is_valid_jira_id(value):
    if not isinstance(value, str):
        return False
    # Match PROJECTKEY-123 (PROJECTKEY = at least 2 uppercase letters/numbers)
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", value))

#def is_valid_hyperlink(value):
#    return value.startswith("http://") or value.startswith("https://")

def is_jql(value):
    return value.strip().upper().startswith("JQL")

def create_hyperlink(value, jira_base_url):
    if value.startswith("URL "):
        value = value.replace("URL", "").strip()  # Remove "URL" prefix if present
        if is_valid_jira_id(value):
            return f"{jira_base_url}/browse/{value}"
        elif is_jql(value):
            jql_query = value.replace("JQL", "").strip()
            return f"{jira_base_url}/issues/?jql={jql_query}"
    return None


def _excel_escape_quotes(s: str) -> str:
    # Excel doubles double-quotes inside string literals
    return s.replace('"', '""')

def _make_hyperlink_formula(url: str, text: str) -> str:
    # Keep it simple: replace newlines for display; wrap handles line breaks visually
    text = text.replace("\n", " ")
    return f'=HYPERLINK("{_excel_escape_quotes(url)}","{_excel_escape_quotes(text)}")'

def set_cell_hyperlink(site_id, item_id, worksheet_name, cell_address, display_text, url, headers):
    formula = _make_hyperlink_formula(url, display_text)
    url_patch = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}"
        f"/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')"
    )
    # Write formula, not values
    resp = requests.patch(url_patch, json={"formulas": [[formula]]}, headers=headers)
    resp.raise_for_status()
    return resp.status_code


# --- Row-level updater (sparse cells handled) ---
def update_sparse_row(site_id, item_id, worksheet_name, row_num, cols, headers, jira_base_url):
    col_letters = sorted(cols.keys(), key=lambda c: string.ascii_uppercase.index(c))
    start_col, end_col = col_letters[0], col_letters[-1]
    row_range = f"{start_col}{row_num}:{end_col}{row_num}"

    # --- 1. GET the full row range ---
    url_get = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{row_range}')"
    resp_get = requests.get(url_get, headers=headers)
    resp_get.raise_for_status()
    current_values = resp_get.json().get("values", [[]])[0]

    # --- 2. Merge in updates ---
    all_cols = list(range(ord(start_col), ord(end_col) + 1))
    new_values = []
    for i, col_ascii in enumerate(all_cols):
        col_letter = chr(col_ascii)
        if col_letter in cols:
            new_val = cols[col_letter]["new"]
            new_val = new_val.replace(";", "\n") if ";" in new_val else new_val
            new_values.append(new_val)
        else:
            new_values.append(current_values[i])

    # --- 3. PATCH back the updated row ---
    payload = {"values": [new_values]}
    resp_patch = requests.patch(url_get, json=payload, headers=headers)
    resp_patch.raise_for_status()
    print(f"✅ Row {row_num} updated with range {row_range}: {resp_patch.status_code}")

    
# --- 4. Post-process hyperlinks + wrap ---
    for i, col_ascii in enumerate(all_cols):
        col_letter = chr(col_ascii)
        if col_letter not in cols:
            continue
        cell_address = f"{col_letter}{row_num}"
        new_value = new_values[i]

        hyperlink = create_hyperlink(new_value, jira_base_url)
        if hyperlink:
            new_value = new_value.replace("URL", "").strip()  # Clean up "URL" prefix
            new_value = new_value.replace("JQL", "").strip()  # Clean up "JQL" prefix
            new_value = "🔗" #"🐞" "🌐"
            code = set_cell_hyperlink(
                site_id, item_id, worksheet_name, cell_address, new_value, hyperlink, headers
            )
            print(f"   🔗 Hyperlink set for {cell_address}: {code}")
    

    '''        
        url_wrap = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')/format/wrapText"
        payload_wrap = {"wrapText": True}
        resp_wrap = requests.patch(url_wrap, json=payload_wrap, headers=headers)
        print(f"   ↩ Wrap text enabled for {cell_address}: {resp_wrap.status_code}")
    '''


def insert_row_batch(site_id, item_id, worksheet_name, row_num, cols, headers, import_mode=True):
    batch_url = "https://graph.microsoft.com/v1.0/$batch"
    requests_list = []
    req_id = 1
    all_requests = []

    for col_letter, values in cols.items():
        cell_address = f"{col_letter}{row_num}"
        new_value = values["new"].replace(";", "\n")
        print(f"Preparing insert for {cell_address} to '{new_value}'")

        # 1. Value update
        requests_list.append({
            "id": str(req_id),
            "method": "PATCH",
            "url": f"/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')",
            "headers": {"Content-Type": "application/json"},
            "body": {"values": [[new_value]]}
        })
        req_id += 1

        '''
        # 2. Hyperlink (if applicable)
        hyperlink = create_hyperlink(new_value)
        if hyperlink:
            requests_list.append({
                "id": str(req_id),
                "method": "PATCH",
                "url": f"/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')/format/hyperlink",
                "headers": {"Content-Type": "application/json"},
                "body": {"hyperlink": hyperlink}
            })
            req_id += 1

        
        # 3. Wrap text
        requests_list.append({
            "id": str(req_id),
            "method": "PATCH",
            "url": f"/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{cell_address}')/format/wrapText",
            "headers": {"Content-Type": "application/json"},
            "body": {"wrapText": True}
        })
        req_id += 1
        '''
        # If we hit 20 requests, flush them into all_requests and start fresh
        if len(requests_list) >= 20:
            all_requests.append(requests_list)
            requests_list = []

    # Push any remaining requests
    if requests_list:
        all_requests.append(requests_list)

    # --- Execute all batches ---
    for batch_num, batch in enumerate(all_requests, 1):
        batch_body = {"requests": batch}
        resp = requests.post(batch_url, headers=headers, json=batch_body)

        if resp.status_code != 200:
            print(f"Batch {batch_num} failed: {resp.status_code} {resp.text}")
            resp.raise_for_status()

        results = resp.json().get("responses", [])
        for r in results:
            status = r.get("status")
            sub_id = r.get("id")
            if status >= 400:
                print(f"Batch {batch_num}, request {sub_id} failed with {status}: {r}")
            else:
                print(f"Batch {batch_num}, request {sub_id} succeeded with {status}")


import requests


# Example usage:
#values = ["TES-123", "TES-124", "TES-125"]
#update_column(site_id, item_id, "Sheet1", "A2", values, headers)
def update_column(site_id, item_id, worksheet_name, start_cell, values, headers):
    """
    Update a column in Excel starting at `start_cell` with new values using Microsoft Graph.
    
    Args:
        site_id (str): SharePoint site ID
        item_id (str): Excel file item ID
        worksheet_name (str): Worksheet name
        start_cell (str): Starting cell address, e.g. "A2"
        values (list): List of values to write
        headers (dict): Auth headers (with Bearer token)
    """
    # Extract column letter and row number
    col_letter = ''.join([c for c in start_cell if c.isalpha()])
    start_row = int(''.join([c for c in start_cell if c.isdigit()]))

    # Compute end row
    end_row = start_row + len(values) - 1

    # Build full range address, e.g. "A2:A5"
    range_address = f"{col_letter}{start_row}:{col_letter}{end_row}"

    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{range_address}')"

    # Convert values into 2D list (Graph requires [[row1], [row2], ...])
    body = {"values": [[v] for v in values]}

    resp = requests.patch(url, headers=headers, json=body)
    if resp.status_code != 200:
        print(f"Failed to update column: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    else:
        print(f"Successfully updated {range_address} with {len(values)} rows.")



jira_base_url = read_jira_url("./.env")
print(f"Using JIRA base URL: {jira_base_url}")

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

        
        if import_mode:
            print("Import mode: removing the INSERT prefix from column letter read from changes file")
            col_letter = col_letter.upper().replace("INSERT","").strip()

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

# Build meta filename from file_path
meta_filename = file_path.strip("/").replace("/", "_") + ".meta.json"
if not os.path.exists(meta_filename):
    raise FileNotFoundError(f"Metadata file {meta_filename} not found. Run download script first.")

# --- LOAD SAVED ETAG ---
with open(meta_filename, "r") as f:
    saved_meta = json.load(f)
saved_etag = saved_meta.get("etag")
print(f"📂 Loaded saved eTag: {saved_etag} from {meta_filename}")

# Get site ID
site_api_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}"
resp_site = requests.get(site_api_url, headers=headers)
resp_site.raise_for_status()
site_id = resp_site.json()["id"]

# Get file ID
file_api_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:{quote(file_path)}"
resp_file = requests.get(file_api_url, headers=headers)
resp_file.raise_for_status()
file_meta = resp_file.json()
item_id = file_meta["id"]
current_etag = file_meta["eTag"]

print(f"🔎 Current eTag: {current_etag}")

# --- COMPARE ETAG ---
if current_etag != saved_etag:
    print("❌ eTag mismatch! File has been modified since last download.")
    print("👉 Aborting update to prevent overwriting newer changes.")
    exit(1)

print("✅ eTag matches. Safe to apply updates.")

# --- ITERATE AND UPDATE SAFELY ---
if import_mode:
    print("Import mode ON")
    # Get the first row number (smallest key)
    first_row_num = min(row_values.keys())

    # Get the dict of column values for that row
    first_row_data = row_values[first_row_num]

    # Get the only column letter
    first_col_letter = next(iter(first_row_data.keys()))

    # Access its new/old values
    first_cell_new = first_row_data[first_col_letter]["new"]
    first_cell_old = first_row_data[first_col_letter]["old"]

    print(f"First row: {first_row_num}, first column: {first_col_letter}")
    print(f"New value: {first_cell_new}, Old value: {first_cell_old}")

    start_cell = f"{first_col_letter}{first_row_num}"
    #start_cell = start_cell.replace("INSERT","").strip()
    print(f"Import mode: updating column at {start_cell}")

    # Sort row numbers to maintain order
    all_row_nums = sorted(row_values.keys())
    # Extract new values from each row
    new_values_list = [row_values[row_num][next(iter(row_values[row_num].keys()))]["new"]
                    for row_num in all_row_nums]
    print("All new values by row:", new_values_list)


    # Example usage:
    #values = ["TES-123", "TES-124", "TES-125"]
    #update_column(site_id, item_id, "Sheet1", "A2", values, headers)
    #def update_column(site_id, item_id, worksheet_name, start_cell, values, headers):

    update_column(site_id, item_id, worksheet_name, start_cell, new_values_list, headers)

else:
    for row_num, cols in row_values.items():
        
        '''
        skip_row = False
        
        for col_letter, values in cols.items():

            if import_mode:
                col_letter = col_letter.replace("INSERT","").strip()
                col_letter = col_letter.replace("DELETE","").strip()

            cell_address = f"{col_letter}{row_num}"
            print("Cell to update:", cell_address)
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

            
            #if current_value != expected_old:
            #    print(f"Skipping row {row_num} because {cell_address} has unexpected value '{current_value}' instead of expected '{expected_old}'")
            #    skip_row = True
            #    break

            #if old_value == new_value:
            #    print(f"Skipping row {row_num} because {cell_address} (no change reqd) already has the new value '{new_value}'")
            #    skip_row = True
            #    break
        

        if skip_row:
            continue
        '''

        print(f"Updating row {row_num} with values: {cols}")
        update_sparse_row(site_id, item_id, worksheet_name, row_num, cols, headers, jira_base_url)

        '''# Update all cells in the row
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
        '''
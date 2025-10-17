import requests
from collections import defaultdict
import argparse
from urllib.parse import urlparse, quote, unquote
import msal
import os
import json
import string
import shutil
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

# -------------------------------
# Config from environment variables
# -------------------------------
# Load env vars
from dotenv import load_dotenv
#load_dotenv()
ENV_PATH = "../../../config/env.system"
load_dotenv(dotenv_path=ENV_PATH)

SCOPES = ["https://graph.microsoft.com/.default"]  # Required for client credentials flow
CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
TENANT_ID = os.environ["TENANT_ID"]
SCOPES = ["https://graph.microsoft.com/.default"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

TOKEN_CACHE_FILE = "../../../config/token_cache.json"




# -------------------------------
# used user-specific OAuth token cache.
# NOTE: FIX LATER - for now persistent between run across ALL files 
#  and ALL users regardless of which user is downloading whatever file.  Not good security-wise.)
def load_cache(userlogin=None):
    global TOKEN_CACHE_FILE
    if userlogin:
        TOKEN_CACHE_FILE = f"../../../config/token_cache_{userlogin}.json"

    print(f"load_cache({userlogin})")
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
def save_cache(cache, userLogin=None):
    if cache.has_state_changed:
        global TOKEN_CACHE_FILE
        if userlogin:
            TOKEN_CACHE_FILE = f"../../../config/token_cache_{userlogin}.json"
        print(f"saved cache to file '{TOKEN_CACHE_FILE}'")
        open(TOKEN_CACHE_FILE, "w").write(cache.serialize())


def get_app_token_delegated():
    print(f"🔑 Acquiring delegated user app token for user={userlogin}")
    cache = load_cache(userlogin)  # ✅ Load the cache here

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
parser.add_argument("timestamp", help="string tag (timestamp) for local output temp files")
parser.add_argument("userlogin", help="string userlogin")
parser.add_argument("worksheet", help="string worksheet name")

# Optional flag (no value needed — just true/false)
parser.add_argument("--user_auth", action="store_true", help="Enable delgated user auth flow output")
#parser.add_argument("--auth_user", help="string tag to force delelated auth flow")

#parser.add_argument("--access_token", required=True, help="Application-level access token for Graph API")
#parser.add_argument("--worksheet", default="Sheet1", help="Worksheet name to update (default: Sheet1)")
args = parser.parse_args()

auth_user = args.user_auth
userlogin = args.userlogin
worksheet_name = args.worksheet

print (f"worksheet name = {worksheet_name}")

delegated_auth = False  # set to False to use app-only auth (no user context)


import sys

if userlogin is None:
    print("ERROR! required 'userlogin' commandline arg is missing.")
    sys.exit(1)

if auth_user and userlogin:
    userlogin = args.userlogin

    print(f"detected argument '{auth_user}' for user:{userlogin} so will use delegated authorization instead of app auth flow")
    delegated_auth = True
    CLIENT_ID = os.environ["CLIENT_ID2"]
    CLIENT_SECRET = os.environ["CLIENT_SECRET2"] # only needed for app-only auth. Not used for delegated user auth.
    TENANT_ID = os.environ["TENANT_ID"]
    # Do NOT include reserved scopes here — MSAL adds them automatically
    SCOPES = ["User.Read","Files.ReadWrite.All", "Sites.ReadWrite.All"]
    #AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
    AUTHORITY = "https://login.microsoftonline.com/common"   # to allow users from any tenant to authorize my app
    print (f"Tenant id: {TENANT_ID}")
    print (f"Client id: {CLIENT_ID}")
    print (f"Client secret: {CLIENT_SECRET}")
    print (f"Authority: {AUTHORITY}")
else:
    print(f"defaulting to application authorization since user_auth argument not specified")
    delegated_auth = False


# load user settings from config folder
ENV_PATH_USER = os.path.join(os.path.dirname(__file__), "config", f"env.{userlogin}")
load_dotenv(dotenv_path=ENV_PATH_USER)



file_url = args.file_url
changes_file = args.changes_file
timestamp = args.timestamp
#access_token = args.access_token

#access_token = get_app_token()  # Use the function to get the token

if delegated_auth:
    access_token = get_app_token_delegated()
else:
    access_token = get_app_token()
    


import_mode = False


import re

def read_jira_url_not_used(filename: str) -> str:
    jira_url = os.environ["JIRA_URL"]
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
            jql_query = str(value).lower().replace("jql", "").strip()
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
def update_sparse_row(site_id, item_id, worksheet_name, row_num, cols, headers, jira_base_url, import_mode = False, runrates=False):
    print("enter update_sparse_row(...)")
    print("some of the function args:")
    print(f"row_num={row_num}")
    print(f"cols={cols}")

    col_letters = sorted(cols.keys(), key=lambda c: string.ascii_uppercase.index(c))
    start_col, end_col = col_letters[0], col_letters[-1]
    row_range = f"{start_col}{row_num}:{end_col}{row_num}"

    # --- 1. GET the full row range ---
    url_get = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{row_range}')"
    if not runrates:  # avoid unnecessary rest call to sharepoint
        resp_get = requests.get(url_get, headers=headers)
        resp_get.raise_for_status()
        current_values = resp_get.json().get("values", [[]])[0]

    strikeout = False
    # --- 2. Merge in updates ---
    all_cols = list(range(ord(start_col), ord(end_col) + 1))
    new_values = []
    for i, col_ascii in enumerate(all_cols):
        col_letter = chr(col_ascii)
        if col_letter in cols:
            new_val = cols[col_letter]["new"]
            #print(f"checking if {new_val} is hyperlink ") 
            if new_val.startswith("URL "):
                hyperlink = create_hyperlink(new_val, jira_base_url)
                if hyperlink:
                    print(f"new value is hyperlink = {hyperlink}")
                    new_val = new_val.replace("URL", "").strip()  # Clean up "URL" prefix
                    if "jql" in str(new_val).lower(): 
                        #new_val = str(new_val).lower().replace("jql", "").strip()  # Clean up "JQL" prefix
                        new_val = "Link" 
                    new_val = _make_hyperlink_formula(hyperlink, new_val)
                 
            else:
                new_val = new_val.replace(";", "\n") if ";" in new_val else new_val
                
            new_values.append(new_val)
            if "!!" in new_val:
                print(f"   ⚠ Warning: '!!' found in new value for {col_letter}{row_num}. Need to strikeout cell")
                strikeout = True
        else:
            if not runrates:
                new_values.append(current_values[i])
            else:
                # for runrate tables we do not want to blank about any cells that we are not writing to
                # incase they have old data from previous runrate resync
                new_values.append(" ")

    # --- 3. PATCH back the updated row ---
    payload = {"values": [new_values]}
    resp_patch = requests.patch(url_get, json=payload, headers=headers)
    resp_patch.raise_for_status()
    print(f"✅ Row {row_num} updated with range {row_range}: {resp_patch.status_code}")

      # --- 4. If strikeout triggered, apply to entire row ---
    '''if strikeout:
        url_strike = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}/workbook/worksheets('{worksheet_name}')/range(address='{row_range}')/format/font"
        strike_payload = {"strikethrough": True}
        resp_strike = requests.patch(url_strike, json=strike_payload, headers=headers)
        resp_strike.raise_for_status()
        print(f"✍️ Applied strikeout to row {row_num}")
        print(f"✍️ Applied strikeout to row_range {row_range}")


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
def update_column_old(site_id, item_id, worksheet_name, start_cell, values, headers):

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



def update_column(site_id, item_id, worksheet_name, start_cell, values, headers):
    print ("enter update_column(...)")
    # Extract column letter and row number
    col_letter = ''.join([c for c in start_cell if c.isalpha()])
    start_row = int(''.join([c for c in start_cell if c.isdigit()]))

    # Compute how many rows to insert
    rows_to_insert = len(values)

    # Define range for inserting blank rows, e.g. "5:7" for 3 rows starting at row 5
    insert_end_row = start_row + rows_to_insert - 1
    insert_range = f"{start_row}:{insert_end_row}"

    insert_url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}"
        f"/workbook/worksheets('{worksheet_name}')/range(address='{insert_range}')/insert"
    )

    # 1️⃣ Insert blank rows
    insert_body = {"shift": "Down"}
    insert_resp = requests.post(insert_url, headers=headers, json=insert_body)
    if insert_resp.status_code not in (200, 201):
        print(f"⚠️ Failed to insert blank rows: {insert_resp.status_code} {insert_resp.text}")
        insert_resp.raise_for_status()
    else:
        print(f"✅ Inserted {rows_to_insert} blank rows at row {start_row}")

    # 2️⃣ Compute new range (the original start_cell now refers to the top of the inserted region)
    end_row = start_row + rows_to_insert - 1
    range_address = f"{col_letter}{start_row}:{col_letter}{end_row}"

    # 3️⃣ Write values into the blank rows
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}"
        f"/workbook/worksheets('{worksheet_name}')/range(address='{range_address}')"
    )

    body = {"values": [[v] for v in values]}  # Graph requires 2D list
    resp = requests.patch(url, headers=headers, json=body)
    if resp.status_code != 200:
        print(f"❌ Failed to update column: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    else:
        print(f"✅ Successfully updated {range_address} with {len(values)} rows.")



def insert_blank_rows(site_id, item_id, worksheet_name, start_row, count, headers):
    """
    Inserts `count` blank rows into an Excel worksheet in SharePoint using Microsoft Graph API.

    Parameters:
        site_id (str): SharePoint site ID
        item_id (str): Drive item ID (the Excel file)
        worksheet_name (str): Name of the worksheet
        start_row (int): Row number before which to insert new rows
        count (int): Number of blank rows to insert
        headers (dict): Graph API authorization headers, e.g. {"Authorization": "Bearer <token>"}

    Returns:
        None (prints status messages)
    """
    print(f"enter insert_blank_rows(...) at row={start_row} count={count} ")
    if count <= 0:
        print("⚠️ Count must be greater than 0. No rows inserted.")
        return

    # Example: inserting 3 rows before row 5 means range "5:7"
    end_row = start_row + count - 1
    insert_range = f"{start_row}:{end_row}"

    url = (
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{item_id}"
        f"/workbook/worksheets('{worksheet_name}')/range(address='{insert_range}')/insert"
    )

    body = {"shift": "Down"}

    print(f"➡️ Inserting {count} blank rows before row {start_row} in sheet '{worksheet_name}'...")
    resp = requests.post(url, headers=headers, json=body)

    if resp.status_code in (200, 201):
        print(f"✅ Successfully inserted {count} blank row(s) starting at row {start_row}")
    else:
        print(f"❌ Failed to insert rows: {resp.status_code} {resp.text}")
        resp.raise_for_status()


print(f"parameter file_url = {file_url}")



jira_base_url =  os.environ["JIRA_URL"]
print(f"Using JIRA base URL: {jira_base_url}")

if "import.changes.txt" in changes_file:
    print (f"import mode enabled since file = {changes_file}")
    import_mode = True
else:
    print (f"import mode disabled since file = ")
    import_mode = False

if "rate.import.changes.txt" in changes_file:
    runrate_mode = True
else:
    runrate_mode = False

# --- PARSE CHANGES FILE ---

# will contain INSERT row. This is proceed separated below 
#because we need to insert single BLANK rows in the sheet for each of these
insert_row_values = defaultdict(dict)  

# will contain all other rows but not INSERT.
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

        # if new value is too long then we want to make sure if fits in a cell and easily readable
        col_letter = ''.join(filter(str.isalpha, cell))
        row_num = int(''.join(filter(str.isdigit, cell)))

        
        if import_mode and "INSERT" in new_value.upper():
            print("Import mode: removing the INSERT prefix from column letter read from changes file")
            #col_letter = col_letter.upper().replace("INSERT","").strip()
            new_value = new_value.replace("INSERT","").strip()  # we know INSERT is in there so no need to new_value.upper() again. Don't do it here, otherwise the cells will all upper case for INSERTs!
            insert_row_values[row_num][col_letter.upper()] = {
                "new": new_value.strip(),
                "old": old_value.strip()  # empty string if no old value
            }
        else:
            row_values[row_num][col_letter.upper()] = {
                "new": new_value.strip(),
                "old": old_value.strip()  # empty string if no old value
            }
        print(f"Processed {cell}: new='{new_value.strip()}', old='{old_value.strip()}'")

file_url = unquote(file_url)  # decode %20 → space if there are space chars in filename 

if "http" in file_url:
    print(f"sharepoint path in file_url={file_url}")

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
    meta_filename = file_path.strip("/").replace("/", "_") + "." + timestamp + ".meta.json"
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
    if import_mode and insert_row_values:
        print("Import mode ON")
        # Get the first row number (smallest key)
        '''first_row_num = min(insert_row_values.keys())
        #insert_blank_rows(site_id, item_id, worksheet_name, first_row_num ,len(insert_row_values), headers)  

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

        #update_column(site_id, item_id, worksheet_name, start_cell, new_values_list, headers)
        '''
    #else:

    # Going to update the inserted rows first - but not sure if this really matters
    for row_num, cols in insert_row_values.items():
        print(f"Inserting row {row_num} with values: {cols}")
        #first_row_num = row_num
        insert_blank_rows(site_id, item_id, worksheet_name, row_num , 1, headers)  
        update_sparse_row(site_id, item_id, worksheet_name, row_num, cols, headers, jira_base_url, import_mode)

    # Now update the existing rows, ie not insert
    for row_num, cols in row_values.items():
        print(f"Updating row {row_num} with values: {cols}")
        update_sparse_row(site_id, item_id, worksheet_name, row_num, cols, headers, jira_base_url, import_mode, runrate_mode)
    
    if runrate_mode:
        # insert blank rows until i figure out way to delete the remaining rows of old data rows
        insert_blank_rows(site_id, item_id, worksheet_name, row_num + 1 , 2, headers)  

else:

    print(f"Assuming local file based on file_url={file_url}")

    file_url = unquote(file_url)  # decode %20 → space if there are space chars in filename    

    #Make an incremental backup of the Excel file, then update cells with 'new' values from row_values.
    if not os.path.isfile(file_url):
        raise FileNotFoundError(f"Excel file not found: {file_url}")
    
    # Create backup file path
    base, ext = os.path.splitext(file_url)
    backup_path = f"{base}.{timestamp}{ext}"
    
    if not os.path.exists(backup_path):
        shutil.copy(file_url, backup_path)

    print(f"{file_url} backup file = {backup_path}")


    # Load workbook
    wb = load_workbook(file_url)
    sheet_name = None
    ws = wb[sheet_name] if sheet_name else wb.active

    for row_num, cols in row_values.items():
        for col_key, val_dict in cols.items():
            new_val = val_dict.get("new")
            if new_val is not None:
                # Convert row to int (if it’s string)
                row_idx = int(row_num)

                # Convert column letter to number if necessary
                if isinstance(col_key, str) and col_key.isalpha():
                    col_idx = column_index_from_string(col_key)
                else:
                    col_idx = int(col_key)

                ws.cell(row=row_idx, column=col_idx).value = new_val


    # Save back to the same file
    print(f"Saving updated file {file_url}")
    wb.save(file_url)

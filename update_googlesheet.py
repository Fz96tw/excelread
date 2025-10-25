import argparse
import os
import re
import shutil
import string
from collections import defaultdict
from urllib.parse import unquote
from dotenv import load_dotenv
from google_oauth import load_google_token, get_google_drive_filename
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError








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
import re
from dotenv import load_dotenv

# -------------------------------
# Config from environment variables
# -------------------------------
ENV_PATH = "../../../config/env.system"
load_dotenv(dotenv_path=ENV_PATH)

# --- PARSE COMMAND-LINE ARGUMENTS ---
parser = argparse.ArgumentParser(description="Update Google Sheet with changes from a file")
parser.add_argument("file_url", help="Google Sheets URL or file ID")
parser.add_argument("changes_file", help="Path to the local changes file")
parser.add_argument("timestamp", help="String tag (timestamp) for local output temp files")
parser.add_argument("userlogin", help="String userlogin")
parser.add_argument("worksheet", help="String worksheet name or index")
parser.add_argument("--user_auth", action="store_true", help="Enable delgated user auth flow output")

args = parser.parse_args()

userlogin = args.userlogin
worksheet_name = args.worksheet
file_url = args.file_url
changes_file = args.changes_file
timestamp = args.timestamp

print(f"Worksheet name = {worksheet_name}")
print(f"User login = {userlogin}")

# Load user settings from config folder
ENV_PATH_USER = os.path.join(os.path.dirname(__file__), "config", f"env.{userlogin}")
load_dotenv(dotenv_path=ENV_PATH_USER)

# Check for import mode
import_mode = "import.changes.txt" in changes_file
runrate_mode = "rate.import.changes.txt" in changes_file

if import_mode:
    print(f"Import mode enabled since file = {changes_file}")
else:
    print(f"Import mode disabled")

if runrate_mode:
    print(f"Runrate mode enabled")

# Get JIRA base URL from environment
jira_base_url = os.environ.get("JIRA_URL", "")
print(f"Using JIRA base URL: {jira_base_url}")

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------

def is_valid_jira_id(value):
    """Check if value matches JIRA ID pattern (e.g., PROJ-123)"""
    if not isinstance(value, str):
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", value))

def is_jql(value):
    """Check if value is a JQL query"""
    return value.strip().upper().startswith("JQL")

def create_hyperlink(value, jira_base_url):
    """Create JIRA hyperlink from value"""
    if value.startswith("URL "):
        value = value.replace("URL", "").strip()
        if is_valid_jira_id(value):
            return f"{jira_base_url}/browse/{value}"
        elif is_jql(value):
            jql_query = str(value).lower().replace("jql", "").strip()
            return f"{jira_base_url}/issues/?jql={jql_query}"
    return None

def extract_sheet_id(url_or_id):
    """Extract Google Sheets ID from URL or return as-is if already an ID"""
    if "docs.google.com/spreadsheets" in url_or_id:
        parts = url_or_id.split("/d/")
        if len(parts) > 1:
            sheet_id = parts[1].split("/")[0]
            return sheet_id
    return url_or_id

def column_letter_to_index(col_letter):
    """Convert column letter (A, B, AA, etc.) to 0-based index"""
    num = 0
    for c in col_letter:
        num = num * 26 + (ord(c.upper()) - ord('A')) + 1
    return num - 1

def column_index_to_letter(col_index):
    """Convert 0-based column index to letter (0->A, 25->Z, 26->AA)"""
    result = ""
    col_index += 1  # Convert to 1-based
    while col_index > 0:
        col_index -= 1
        result = chr(col_index % 26 + ord('A')) + result
        col_index //= 26
    return result

def get_sheet_id_by_name(service, spreadsheet_id, sheet_name):
    """Get the sheet ID (gid) for a given sheet name - CACHED"""
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        for sheet in spreadsheet.get('sheets', []):
            if sheet['properties']['title'] == sheet_name:
                return sheet['properties']['sheetId']
        raise ValueError(f"Sheet '{sheet_name}' not found in spreadsheet")
    except HttpError as e:
        print(f"Error getting sheet ID: {e}")
        raise

# -------------------------------
# OPTIMIZED BATCH UPDATE FUNCTIONS
# -------------------------------

def build_all_updates(all_rows, sheet_id, sheet_name, jira_base_url):
    """
    Build all value updates and formatting requests in a single pass.
    Returns: (value_data_list, formatting_requests_list)
    """
    all_value_data = []
    all_format_requests = []
    
    for row_num in sorted(all_rows.keys()):
        cols = all_rows[row_num]
        
        for col_letter, values in cols.items():
            col_index = column_letter_to_index(col_letter)
            new_val = values["new"]
            
            # Handle hyperlinks
            if new_val.startswith("URL "):
                hyperlink = create_hyperlink(new_val, jira_base_url)
                if hyperlink:
                    new_val = new_val.replace("URL", "").strip()
                    if "jql" in str(new_val).lower():
                        new_val = "Link"
                    
                    cell_range = f"{sheet_name}!{col_letter}{row_num}"
                    all_value_data.append({
                        'range': cell_range,
                        'values': [[f'=HYPERLINK("{hyperlink}","{new_val}")']],
                    })
                    continue
            
            # Handle regular values with semicolon to newline conversion
            new_val = new_val.replace(";", "\n") if ";" in new_val else new_val
            
            cell_range = f"{sheet_name}!{col_letter}{row_num}"
            all_value_data.append({
                'range': cell_range,
                'values': [[new_val]],
            })
            
            # Add text wrapping format request
            all_format_requests.append({
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': row_num - 1,
                        'endRowIndex': row_num,
                        'startColumnIndex': col_index,
                        'endColumnIndex': col_index + 1,
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'wrapStrategy': 'WRAP'
                        }
                    },
                    'fields': 'userEnteredFormat.wrapStrategy'
                }
            })
    
    return all_value_data, all_format_requests

def insert_blank_rows_batch(sheet_id, rows_to_insert):
    """
    Build insert dimension requests for multiple rows.
    Returns list of requests to be added to a batch.
    """
    requests = []
    
    # Sort rows in descending order to avoid index shifting issues
    sorted_rows = sorted(rows_to_insert.items(), reverse=True)
    print(f"🔍 Processing inserts in descending order: {sorted_rows}")
    
    for row_num, count in sorted_rows:
        start_idx = row_num - 1  # Convert to 0-based
        end_idx = row_num - 1 + count
        
        print(f"   📍 Insert {count} row(s) at position {row_num} (startIndex={start_idx}, endIndex={end_idx})")
        
        requests.append({
            'insertDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'ROWS',
                    'startIndex': start_idx,
                    'endIndex': end_idx,
                },
                'inheritFromBefore': False
            }
        })
    
    print(f"✅ Created {len(requests)} insert requests")
    return requests

def execute_all_updates(service, spreadsheet_id, value_data, format_requests):
    """Execute all updates in minimal API calls"""
    total_cells_updated = 0
    
    # Execute all value updates in ONE batch call
    if value_data:
        body = {
            'valueInputOption': 'USER_ENTERED',
            'data': value_data
        }
        try:
            result = service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body).execute()
            total_cells_updated = result.get('totalUpdatedCells', 0)
            print(f"✅ Updated {total_cells_updated} cells in single batch call")
        except HttpError as e:
            print(f"Error updating values: {e}")
            raise
    
    # Execute all formatting in ONE batch call
    if format_requests:
        body = {'requests': format_requests}
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body).execute()
            print(f"✅ Applied formatting to {len(format_requests)} cells in single batch call")
        except HttpError as e:
            print(f"Error applying formatting: {e}")
            raise
    
    return total_cells_updated

# -------------------------------
# MAIN LOGIC
# -------------------------------

# Load Google credentials
creds = load_google_token(userlogin)
if not creds or not creds.valid:
    raise Exception(f"❌ User {userlogin} not logged in to Google. Please authenticate first.")

print(f"✅ Loaded valid Google credentials for user={userlogin}")

# Build Google Sheets service
service = build('sheets', 'v4', credentials=creds)

# Extract sheet ID from URL
file_url = unquote(file_url)
spreadsheet_id = extract_sheet_id(file_url)
print(f"📊 Spreadsheet ID: {spreadsheet_id}")

# Get filename for display
try:
    filename = get_google_drive_filename(userlogin, spreadsheet_id)
    print(f"📄 File name: {filename}")
except Exception as e:
    print(f"⚠️ Could not retrieve filename: {e}")

# GET SHEET ID ONCE at the start (CRITICAL OPTIMIZATION)
sheet_id = get_sheet_id_by_name(service, spreadsheet_id, worksheet_name)
print(f"📋 Sheet ID for '{worksheet_name}': {sheet_id}")

# -------------------------------
# PARSE CHANGES FILE
# -------------------------------

insert_row_values = defaultdict(dict)
row_values = defaultdict(dict)

with open(changes_file, "r") as f:
    print(f"📖 Parsing changes file: {changes_file}")
    for line in f:
        line = line.strip()
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
        
        if import_mode and "INSERT" in new_value.upper():
            print(f"Import mode: removing INSERT prefix from value")
            new_value = new_value.replace("INSERT", "").replace("insert", "").strip()
            insert_row_values[row_num][col_letter.upper()] = {
                "new": new_value.strip(),
                "old": old_value.strip()
            }
        else:
            row_values[row_num][col_letter.upper()] = {
                "new": new_value.strip(),
                "old": old_value.strip()
            }
        
        print(f"Processed {cell}: new='{new_value.strip()}'")

# -------------------------------
# APPLY ALL UPDATES IN OPTIMIZED BATCHES
# -------------------------------

print(f"\n🚀 Starting optimized batch updates to Google Sheet...")
print(f"📊 Debug: insert_row_values has {len(insert_row_values)} rows: {list(insert_row_values.keys())}")
print(f"📊 Debug: row_values has {len(row_values)} rows: {list(row_values.keys())}")

all_requests = []

# Step 1: Build insert row requests (if any)
if insert_row_values:
    # Check for consecutive row inserts and optimize them into bulk operations
    sorted_insert_rows = sorted(insert_row_values.keys())
    
    # Group consecutive rows together
    insert_groups = []
    current_group_start = sorted_insert_rows[0]
    current_group_count = 1
    
    for i in range(1, len(sorted_insert_rows)):
        if sorted_insert_rows[i] == sorted_insert_rows[i-1] + 1:
            # Consecutive row
            current_group_count += 1
        else:
            # Gap found, save current group
            insert_groups.append((current_group_start, current_group_count))
            current_group_start = sorted_insert_rows[i]
            current_group_count = 1
    
    # Don't forget the last group
    insert_groups.append((current_group_start, current_group_count))
    
    print(f"🔍 Optimized {len(sorted_insert_rows)} individual inserts into {len(insert_groups)} bulk operations:")
    for start, count in insert_groups:
        print(f"   📍 Insert {count} rows starting at position {start}")
    
    # Build requests from groups (in descending order)
    rows_to_insert = {start: count for start, count in insert_groups}
    insert_requests = insert_blank_rows_batch(sheet_id, rows_to_insert)
    all_requests.extend(insert_requests)
    print(f"📝 Prepared {len(insert_requests)} bulk insertion requests")
else:
    print(f"ℹ️ No insert rows found")

# Step 2: Build runrate blank rows (if needed)
if runrate_mode and row_values:
    last_row = max(row_values.keys())
    runrate_requests = insert_blank_rows_batch(sheet_id, {last_row + 1: 2})
    all_requests.extend(runrate_requests)
    print(f"🧹 Prepared runrate blank row requests")

# Step 3: Execute all insert operations in ONE batch call
if all_requests:
    body = {'requests': all_requests}
    print(f"🚀 Sending batch request with {len(all_requests)} operations:")
    for i, req in enumerate(all_requests):
        if 'insertDimension' in req:
            r = req['insertDimension']['range']
            print(f"   Request {i+1}: Insert rows at startIndex={r['startIndex']}, endIndex={r['endIndex']}")
    
    try:
        response = service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body).execute()
        print(f"✅ Executed all {len(all_requests)} insert operations in single batch call")
        print(f"📋 Response: {response}")
    except HttpError as e:
        print(f"❌ Error inserting rows: {e}")
        print(f"📄 Request body: {json.dumps(body, indent=2)}")
        raise
else:
    print(f"ℹ️ No insert operations to execute")

# Step 4: Merge insert and update rows (handling conflicts properly)
all_rows = {}

print(f"\n🔄 Merging dictionaries...")
print(f"   insert_row_values: {dict(insert_row_values)}")
print(f"   row_values: {dict(row_values)}")

for row_num, cols in insert_row_values.items():
    if row_num not in all_rows:
        all_rows[row_num] = {}
    all_rows[row_num].update(cols)  # Add insert columns
    print(f"📥 Added insert row {row_num} with columns: {list(cols.keys())}")

for row_num, cols in row_values.items():
    if row_num not in all_rows:
        all_rows[row_num] = {}
    all_rows[row_num].update(cols)  # Add/merge update columns
    print(f"✏️ Added/merged update row {row_num} with columns: {list(cols.keys())}")

print(f"📦 Final merged rows: {list(all_rows.keys())}")
print(f"📦 Merged {len(insert_row_values)} insert rows and {len(row_values)} update rows into {len(all_rows)} total rows")

# Step 5: Build ALL value and format updates together
all_value_data, all_format_requests = build_all_updates(
    all_rows, sheet_id, worksheet_name, jira_base_url
)

print(f"📦 Prepared {len(all_value_data)} value updates and {len(all_format_requests)} format updates")

# Step 6: Execute all value and format updates in TWO batch calls (minimum possible)
total_updated = execute_all_updates(service, spreadsheet_id, all_value_data, all_format_requests)

print(f"\n✅ All updates completed successfully!")
print(f"📊 Summary: {total_updated} cells updated with {len(all_format_requests)} formatted")
print(f"🎯 Total API calls: ~{3 + (1 if all_requests else 0) + 2} (down from potentially 100+)")
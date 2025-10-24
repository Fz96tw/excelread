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

# Optional flag (no value needed — just true/false)
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
        # Extract ID from URL like: https://docs.google.com/spreadsheets/d/SHEET_ID/edit
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
    """Get the sheet ID (gid) for a given sheet name"""
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
# GOOGLE SHEETS UPDATE FUNCTIONS
# -------------------------------

def update_sparse_row(service, spreadsheet_id, sheet_name, row_num, cols, jira_base_url, 
                     import_mode=False, runrate_mode=False):
    """Update specific cells in a row"""
    print(f"Updating row {row_num} with columns: {list(cols.keys())}")
    
    # Prepare batch update requests
    requests = []
    data = []
    
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
                
                # Create hyperlink formula
                cell_range = f"{sheet_name}!{col_letter}{row_num}"
                data.append({
                    'range': cell_range,
                    'values': [[f'=HYPERLINK("{hyperlink}","{new_val}")']],
                })
                continue
        
        # Handle regular values with semicolon to newline conversion
        new_val = new_val.replace(";", "\n") if ";" in new_val else new_val
        
        cell_range = f"{sheet_name}!{col_letter}{row_num}"
        data.append({
            'range': cell_range,
            'values': [[new_val]],
        })
        
        # Enable text wrapping for the cell
        sheet_id = get_sheet_id_by_name(service, spreadsheet_id, sheet_name)
        requests.append({
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
    
    # Execute batch value update
    if data:
        body = {
            'valueInputOption': 'USER_ENTERED',
            'data': data
        }
        try:
            result = service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body).execute()
            print(f"✅ Updated {result.get('totalUpdatedCells')} cells in row {row_num}")
        except HttpError as e:
            print(f"Error updating values: {e}")
            raise
    
    # Execute formatting requests
    if requests:
        body = {'requests': requests}
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body).execute()
            print(f"✅ Applied formatting to row {row_num}")
        except HttpError as e:
            print(f"Error applying formatting: {e}")
            raise

def insert_blank_rows(service, spreadsheet_id, sheet_name, start_row, count):
    """Insert blank rows at the specified position"""
    print(f"Inserting {count} blank row(s) at row {start_row}")
    
    sheet_id = get_sheet_id_by_name(service, spreadsheet_id, sheet_name)
    
    requests = [{
        'insertDimension': {
            'range': {
                'sheetId': sheet_id,
                'dimension': 'ROWS',
                'startIndex': start_row - 1,  # 0-based
                'endIndex': start_row - 1 + count,
            },
            'inheritFromBefore': False
        }
    }]
    
    body = {'requests': requests}
    
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body).execute()
        print(f"✅ Successfully inserted {count} blank row(s) at row {start_row}")
    except HttpError as e:
        print(f"Error inserting rows: {e}")
        raise

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

# -------------------------------
# PARSE CHANGES FILE
# -------------------------------

# Separate INSERT rows from regular updates
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
# APPLY UPDATES TO GOOGLE SHEET
# -------------------------------

print(f"\n🚀 Starting updates to Google Sheet...")

# Process INSERT rows first
for row_num in sorted(insert_row_values.keys()):
    cols = insert_row_values[row_num]
    print(f"📝 Inserting row {row_num} with values: {cols}")
    insert_blank_rows(service, spreadsheet_id, worksheet_name, row_num, 1)
    update_sparse_row(service, spreadsheet_id, worksheet_name, row_num, cols, 
                     jira_base_url, import_mode)

# Process regular updates
for row_num in sorted(row_values.keys()):
    cols = row_values[row_num]
    print(f"✏️ Updating row {row_num} with values: {cols}")
    update_sparse_row(service, spreadsheet_id, worksheet_name, row_num, cols, 
                     jira_base_url, import_mode, runrate_mode)

# For runrate mode, insert blank rows at the end
if runrate_mode and row_values:
    last_row = max(row_values.keys())
    print(f"🧹 Runrate mode: inserting blank rows after row {last_row}")
    insert_blank_rows(service, spreadsheet_id, worksheet_name, last_row + 1, 2)

print(f"\n✅ All updates completed successfully!")
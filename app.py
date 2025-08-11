from flask import Flask, render_template, request, redirect, url_for
import os
import re
import json
import requests
import msal
import uuid
from dotenv import load_dotenv

app = Flask(__name__)

FOO_FILE = '.env'
BAR_FILE = '.bar'
BANNER_PATH = '/static/banner2.jpg'  # put banner.jpg in static folder

# -------------------------------
# TOKEN MANAGEMENT
# -------------------------------
load_dotenv()
CLIENT_ID = os.environ.get("CLIENT_ID")  # From Azure AD app registration
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")  # From Azure AD app registration
TENANT_ID = os.environ.get("TENANT_ID")  # From Azure AD app registration

AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Files.ReadWrite.All", "Sites.ReadWrite.All", "offline_access"]

TOKEN_CACHE_FILE = "msal_token_cache.bin"

def load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
    return cache

def save_cache(cache):
    if cache.has_state_changed:
        open(TOKEN_CACHE_FILE, "w").write(cache.serialize())

def get_access_token():
    print("Loading MSAL cache...")
    if not CLIENT_ID or not CLIENT_SECRET or not TENANT_ID:
        raise Exception("Please set CLIENT_ID, CLIENT_SECRET, and TENANT_ID in your .env file.")
    
    cache = load_cache()
    print("Creating MSAL PublicClientApplication...")
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # Try silent login first
    print("Trying to acquire token silently...")
    accounts = app.get_accounts()
    if accounts:
        print(f"Found {len(accounts)} accounts in cache.")
        # Use the first account
        print(f"Using account: {accounts[0]['username']}")
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    else:
        print("No accounts found in cache. Need to log in interactively.")
        result = None

    # If no valid token, prompt user
    if not result:
        print("No valid token found. Opening login popup...")
        result = app.acquire_token_interactive(SCOPES)

    print("Saving MSAL cache...")
    save_cache(cache)

    if "access_token" in result:
        print("Access token acquired successfully.")
        return result["access_token"]
    else:
        raise Exception("Failed to get access token: %s" % json.dumps(result, indent=2))



def read_file_lines(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return [line.strip() for line in f.readlines()]
    return []

def write_file_lines(path, lines):
    with open(path, 'w') as f:
        f.write("\n".join(lines))

@app.route('/', methods=['GET', 'POST'])
def index():
    # Load saved values
    foo_values = {}
    foo_lines = read_file_lines(FOO_FILE)

    
    # Extract text between the first pair of double quotes in each line
    foo_lines = [re.search(r'"(.*?)"', line).group(1) if re.search(r'"(.*?)"', line) else "" for line in foo_lines]

    if len(foo_lines) >= 3:
        foo_values = {
            "jira_url": foo_lines[0],
            "jira_user": foo_lines[1],
            "jira_token": foo_lines[2],
        }

    bar_values = read_file_lines(BAR_FILE)

    if request.method == 'POST':
        if 'save_foo' in request.form:
            jira_url = "JIRA_URL = \"" + request.form.get('jira_url', '') + "\""
            jira_user = "JIRA_EMAIL = \"" + request.form.get('jira_user', '') + "\""
            jira_token = "JIRA_API_TOKEN = \"" + request.form.get('jira_token', '') + "\""
            write_file_lines(FOO_FILE, [jira_url, jira_user, jira_token])
            return redirect(url_for('index'))

        elif 'add_bar' in request.form:
            new_val = request.form.get('bar_value', '').strip()
            if new_val:
                bar_values.append(new_val)
                write_file_lines(BAR_FILE, bar_values)
            return redirect(url_for('index'))

        elif 'remove_bar' in request.form:
            to_remove = request.form.get('remove_bar')
            if to_remove in bar_values:
                bar_values.remove(to_remove)
                write_file_lines(BAR_FILE, bar_values)
            return redirect(url_for('index'))
        
        elif 'login_bar' in request.form:
            get_access_token()  # Trigger login flow
            return redirect(url_for('index'))

    return render_template('form.html',
                           banner_path=BANNER_PATH,
                           foo_values=foo_values,
                           bar_values=bar_values)

if __name__ == '__main__':
    app.run(debug=True)

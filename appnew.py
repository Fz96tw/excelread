from flask import Flask, render_template, request, redirect, url_for,session
import os
import re
import json
import requests
import msal
import uuid
from pathlib import Path
from dotenv import load_dotenv
from refresh import *

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a-very-secret-key")  # Use a real secret in production


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
#SCOPES = ["Files.ReadWrite.All", "Sites.ReadWrite.All"] #, "offline_access"]
SCOPES = ["https://graph.microsoft.com/.default"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_PATH = "/getAToken"
REDIRECT_URI = f"http://localhost:5000{REDIRECT_PATH}"

TOKEN_CACHE_FILE = "token_cache.json"


def load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        print("Loading token cache from file...")
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
    return cache


def save_cache(cache):
    if cache.has_state_changed:
        print("Saving token cache to file...")
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())



def read_file_lines(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return [line.strip() for line in f.readlines()]
    return []

def write_file_lines(path, lines):
    with open(path, 'w') as f:
        f.write("\n".join(lines))



import time

def is_logged_in():

    # Try silent token acquisition (from cache)
    result = cca.acquire_token_silent(scopes=SCOPES, account=None)

    if result and "access_token" in result:
        print("Valid token found in cache.")
        return True
    else:
        result = cca.acquire_token_for_client(scopes=SCOPES)
        if "access_token" not in result:
            raise Exception(f"Failed to get token: {result}")
            return False
        else:
            print("Access token acquired successfully.")
            save_cache(cache)
            print("Valid token found after acquiring new token.")
            return True




def build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache
    )


# -------------------------------
# MSAL: get application token
# -------------------------------
def get_app_token():
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    #cca = msal.ConfidentialClientApplication(
    #    CLIENT_ID, 
    #    authority=authority, 
    #    client_credential=CLIENT_SECRET
    #)
    cache = load_cache()
    cca = build_msal_app(cache)
    result = cca.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"Failed to get token: {result}")
    print("Access token acquired successfully.")
    save_cache(cache)
    return result["access_token"]


cache = load_cache()
cca = build_msal_app(cache)


@app.route("/login")
def login():
    cache = load_cache()
    print("Building MSAL app for login...")
    cca = build_msal_app(cache)
 
    #auth_url = cca.get_authorization_request_url(
    #    scopes=SCOPES,
    #    redirect_uri=REDIRECT_URI
    #)
    #save_cache(cache)
    #return redirect(auth_url)
    result = cca.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise Exception(f"Failed to get token: {result}")
    print("Access token acquired successfully.")
    save_cache(cache)

    if "access_token" in result:
        session["is_logged_in"] = True
        return """
            <html>
            <body style="font-family: sans-serif; text-align: center; padding: 40px;">
                <h2>✅ Login Successful</h2>
                <p>You can keep this window open or close it.</p>

                <button onclick="window.opener && window.opener.postMessage('login-success', '*'); window.close();"
                        style="padding:10px 20px; font-size:16px; cursor:pointer;">
                Close Window
                </button>

                <script>
                // Notify the opener immediately so the button updates even if user doesn't click Close yet
                try { window.opener && window.opener.postMessage('login-success', '*'); } catch (e) {}
                </script>
            </body>
            </html>
        """
    else:
        session["is_logged_in"] = False
        err = result.get("error_description", "Unknown error")
        return f"""
            <html>
            <body style="font-family: sans-serif; text-align: center; padding: 40px;">
                <h2>❌ Login Failed</h2>
                <pre style="white-space:pre-wrap; text-align:left; display:inline-block;">{err}</pre>
                <br>
                <button onclick="window.opener && window.opener.postMessage('login-failed', '*'); window.close();"
                        style="padding:10px 20px; font-size:16px; cursor:pointer;">
                Close Window
                </button>
            </body>
            </html>
        """
    return "No code provided."
#    return result["access_token"]


import os
from flask import Flask, render_template, jsonify, send_from_directory, request


LOG_FOLDER = "logs"

from pathlib import Path
from datetime import datetime

def get_folder_tree(folder):
    """Return a list of files with name and last modified timestamp."""
    tree = []
    for f in os.listdir(folder):
        path = os.path.join(folder, f)
        if os.path.isfile(path):
            mtime = os.path.getmtime(path)
            modified_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            tree.append({
                "name": f,
                "path": path,
                "modified": modified_time
            })
    return tree

@app.route('/logs', methods=['GET', 'POST'])
def logs():
    log_content = ""
    viewed_log = ""
    print("entering logs route")
    if request.method == 'POST' and 'view_log' in request.form:
        viewed_log = request.form['view_log']
        print(f"Viewing log: {viewed_log}")
        path = os.path.join(LOG_FOLDER, viewed_log)
        if os.path.exists(path):
            with open(path, 'r') as f:
                log_content = f.read()

    folder_tree = get_folder_tree(LOG_FOLDER)
    return render_template('logs.html', folder_tree=folder_tree,
                           log_content=log_content, viewed_log=viewed_log)



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

    # Synchronize session login status with real token state every request
    print("Checking login status...")
    logged_in_state = is_logged_in()  # returns True or False
    print(f"Login status: {logged_in_state}")
    session["is_logged_in"] = logged_in_state
    logged_in = logged_in_state


    folder_tree = get_folder_tree(LOG_FOLDER)
   
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
        elif 'resync_bar' in request.form:
            print("Resyncing file values...")
            val = request.form["resync_bar"]
            resync(val)  # call your function with the string value
            return redirect(url_for('index'))
        
        elif 'login_bar':
            print("Logging in via bar value...")
            if not logged_in:
                return redirect(url_for('login'))
            else:
                print("Already logged in, no action needed.")

        elif 'app_token' in request.form:
            print("Getting application token...")
            if get_app_token():
                print("Application token retrieved successfully.")
            else:
                print("Failed to retrieve application token.")

        return redirect(url_for('index'))

    
    print(f"Logged in status: {logged_in}")

    return render_template('form.html',
                            banner_path=BANNER_PATH,
                            foo_values=foo_values,
                            bar_values=bar_values,
                            logged_in=logged_in,
                            folder_tree=folder_tree) 

if __name__ == '__main__':
    app.run(debug=True)

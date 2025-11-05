from flask import Flask, render_template, request, redirect, url_for,session, send_from_directory
import os
import re
import json
import requests
import msal
import uuid
from pathlib import Path
from dotenv import load_dotenv, set_key 
from flask import flash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR 

# my modules
from refresh import *
from my_scheduler import *
from my_utils import *

import logging
from flask import Flask, request, g
from datetime import datetime

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Allow HTTP for local dev

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a-very-secret-key")  # Use a real secret in production

from flask_login import LoginManager, current_user

# --- Flask-Login setup ---
login_manager = LoginManager()
login_manager.init_app(app)

    
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,       # client IP
    x_proto=1,     # scheme (http/https)
    x_host=1,      # host header
    x_port=1,
    x_prefix=1
)


'''app.config.update(
    SESSION_COOKIE_SECURE=True,    # only sent over HTTPS
    SESSION_COOKIE_SAMESITE="None", # allow cross-site redirects (OAuth)
    SESSION_PERMANENT=False
)'''

app.config.update(
    SESSION_COOKIE_SECURE=True,  # only send cookie over HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',  # prevents CSRF issues
)


#---------------------------------------------------------
# Configure Flask's logger (single centralized log file)
# ---------------------------------------------------------
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | USER=%(user)s | METHOD=%(method)s | PATH=%(path)s | STATUS=%(status)s | %(message)s"
)

# --------------------------
# Ensure logs directory exists
# --------------------------
log_dir = "./logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "user_activity.log")

# --------------------------
# Custom request filter
# --------------------------
class RequestFilter(logging.Filter):
    def filter(self, record):
        # Skip static files, favicon, and OPTIONS requests
        path = getattr(request, "path", "")
        method = getattr(request, "method", "")
        if path.startswith("/static/") or path.startswith("/tasks/status") or path == "/favicon.ico" or method == "OPTIONS":
            return False

        # Add user info (string) to the log
        record.user = getattr(g, "current_user", "anonymous")
        record.method = method or "-"
        record.path = path or "-"
        record.status = getattr(g, "last_status", "-")
        return True

# --------------------------
# Configure RotatingFileHandler
# --------------------------
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=1*1024*1024,  # 1 MB per file
    backupCount=5,         # keep last 5 rotated logs
    encoding="utf-8",
    delay=True             # create file on first log
)

file_handler.setFormatter(formatter)
file_handler.addFilter(RequestFilter())

app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)



# ---------------------------------------------------------
# Example middleware hooks
# ---------------------------------------------------------
@app.before_request
def before_request_logging():
    # Assume you set g.current_user from your auth layer
    #g.current_user = request.headers.get("X-User", "anonymous")  # demo only
    if current_user.is_authenticated:
        g.current_user = current_user.username
    else:
        g.current_user = "anonymous"
    app.logger.info("Request started")


@app.after_request
def after_request_logging(response):
    g.last_status = response.status_code
    app.logger.info("Request completed")
    return response




#FOO_FILE = './config/.env'
#BAR_FILE = './config/.bar'
BANNER_PATH = '/static/banner3.jpg'  # put banner.jpg in static folder
#GOOGLE_FILE = './config/.google'

# -------------------------------
# TOKEN MANAGEMENT
# -------------------------------
#load_dotenv()
# load system level settings first from system.env from config folder
ENV_PATH = os.path.join(os.path.dirname(__file__), "config", "system.env")
#ENV_PATH = os.path.join(os.path.dirname(__file__), "system.env")
#ENV_PATH = "config/system.env"

print(f"current working dir = {os.getcwd()}")

print(f" {ENV_PATH} Exists? : {os.path.exists(ENV_PATH)}  Size: {os.path.getsize(ENV_PATH) if os.path.exists(ENV_PATH) else 0}")

with open(ENV_PATH, "rb") as f:
    head = f.read(100)
print(f"First 100 bytes: {head!r}")

print (f"loading environment var settings from {ENV_PATH}")
loaded = load_dotenv(dotenv_path=ENV_PATH)
print(f"load_dotenv returned: {loaded}")
print(f"Loaded keys: {list(os.environ.keys())}")

CLIENT_ID = os.environ.get("CLIENT_ID")  # From Azure AD app registration
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")  # From Azure AD app registration
TENANT_ID = os.environ.get("TENANT_ID")  # From Azure AD app registration

# SCOPES = ["Files.ReadWrite.All", "Sites.ReadWrite.All"] #, "offline_access"]

# defaults to client auth but will be changed to user_auth farther down if user_auth cmdline argument found
SCOPES = ["https://graph.microsoft.com/.default"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
#AUTHORITY = "https://login.microsoftonline.com/common"   # to allow users from any tenant to authorize my app
REDIRECT_PATH = "/getAToken"
REDIRECT_URI = f"https://demo.cloudcurio.com{REDIRECT_PATH}"

# default token cache file used when private client auth flow. 
# file name is overwritten later if using delegated auth flow.
TOKEN_CACHE_FILE = "./config/token_cache.json"

print (f"CLIENT_ID = {CLIENT_ID}")
print (f"CLIENT_SECRET = {CLIENT_SECRET}")
print (f"TENANT_ID = {TENANT_ID}")
print (f"SCOPES = {SCOPES}")
print (f"AUTHORITY = {AUTHORITY}")



def load_cache(userlogin=None):
    global TOKEN_CACHE_FILE

    cache = msal.SerializableTokenCache()

    if userlogin:
        TOKEN_CACHE_FILE = f"./config/token_cache_{userlogin}.json"
    else:
        TOKEN_CACHE_FILE = "./config/token_cache.json"
    
    if os.path.exists(TOKEN_CACHE_FILE):
        print(f"Loading token cache from file={TOKEN_CACHE_FILE}")
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
    else:
        print(f"load_cache could not find token file {TOKEN_CACHE_FILE}")

    return cache
    

def save_cache(cache, userlogin=None):
    #global TOKEN_CACHE_FILE
    if cache.has_state_changed:

        if userlogin:
            TOKEN_CACHE_FILE = f"./config/token_cache_{userlogin}.json"
        else:
            TOKEN_CACHE_FILE = "./config/token_cache.json"

        print(f"Saving token cache to file={TOKEN_CACHE_FILE}")
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())


from urllib.parse import urlparse, quote, unquote

def read_file_lines(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return [unquote(line.strip()) for line in f.readlines()]
    return []


def write_file_lines(path, lines):
    with open(path, 'w') as f:
        f.write("\n".join(lines))
        print(f"Wrote {len(lines)} lines to {path}")



import time

def is_logged_in():
    #global logged_in
    global auth_user_info
    global auth_user_email
    global auth_user_name

    if session["is_logged_in"] == False:
        return False
    
    # Try silent token acquisition (from cache)
    result = cca.acquire_token_silent(scopes=SCOPES, account=None)

    if result and "access_token" in result:
        print("Valid token found in cache.")

        #logged_in = True
        session["is_logged_in"] = True
        session["user"] = result.get("id_token_claims")
        session["access_token"] = result["access_token"]
        auth_user_info = session.get("user")
        if auth_user_info:
            auth_user_email = auth_user_info.get("preferred_username")
            auth_user_name = auth_user_info.get("name")
        print(f"@@@@@@@ is_logged_in() setting the session = {session}")

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

            #logged_in = True
            session["is_logged_in"] = True
            session["user"] = result.get("id_token_claims")
            session["access_token"] = result["access_token"]
            print(f"@@@@@@@ is_logged_in() setting the session = {session}")
            auth_user_info = session.get("user")
            if auth_user_info:
                auth_user_email = auth_user_info.get("preferred_username")
                auth_user_name = auth_user_info.get("name")
            return True



# for user delegated Auth flow
def get_app_token_delegated():
    print("called get_app_token_delegated()... Acquiring app token...")
    #global userlogin
    userlogin = current_user.username
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


# for user delegated (saas appnew)
def _build_msal_app(cache=None):
    print("called _build_msal_app()")
    print(f"AUTHORITY={AUTHORITY}")
    print(f"CLIENT_ID={CLIENT_ID}")
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache
    )

# client auth (on-prem appnew)
def build_msal_app(cache=None):
    print("called build_msap_app()")
    print(f"AUTHORITY={AUTHORITY}")
    print(f"CLIENT_ID={CLIENT_ID}")
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
    print("called get_app_token()")
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


import json
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

#app = Flask(__name__)
#app.secret_key = "supersecretkey"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

from filelock import FileLock
import json
import os
from datetime import datetime

USERS_FILE = "./config/users.json"
LOCK_FILE = USERS_FILE + ".lock"

def load_users():
    lock = FileLock(LOCK_FILE)
    with lock:  # Only one process at a time
        if not os.path.exists(USERS_FILE):
            return []
        with open(USERS_FILE, "r") as f:
            return json.load(f)

def save_users(users):
    lock = FileLock(LOCK_FILE)
    with lock:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=4)


class User(UserMixin):
    def __init__(self, id, username, password, first_name, last_name, date_registered, email=None):
        self.id = id
        self.username = username
        self.password = password  # NOTE: hash in real life
        self.first_name = first_name
        self.last_name = last_name
        self.date_registered = date_registered
        self.email = email
    

@login_manager.user_loader
def load_user(user_id):
    users = load_users()
    for u in users:
        if u["id"] == user_id:
            return User(**u)
    return None


def load_llm_config(llm_config_file):
    print("Current working directory:", os.getcwd())  # <-- debug
    if os.path.exists(llm_config_file):
        with open(llm_config_file, "r") as f:
            print(f"loading llm config file = {llm_config_file}")
            llm_model_set = json.load(f)

            return llm_model_set
    else:
        print(f"ERROR: load_llm_config file {llm_config_file} was not found")
    
    return None

def load_schedules(sched_file, userlogin=None):
    if os.path.exists(sched_file):
        with open(sched_file, "r") as f:
            print(f"loading schedule file = {sched_file}")
            schedules = json.load(f)
            # Only return schedules belonging to this user
            '''
            if (userlogin is not None):
                return [s for s in schedules if s.get("userlogin") == userlogin]
            else:
                return schedules
            '''
            return schedules
            
    return []


def clear_schedule_file(sched_file, filename, userlogin):
    if not filename:
        return jsonify({"success": False, "message": "Filename missing"}), 400
    # Load existing schedules
    schedules = load_schedules(sched_file)
    # Remove the schedule for this filename if it exists
    new_schedules = [s for s in schedules if s["filename"] != filename or s["userlogin"] != userlogin]
    
    '''
    new_schedules = {}
    for s in schedules:
        if s["filename"] != filename or s["userlogin"] != userlogin:
            new_schedules.append(s)
    '''

    # Save back to file
    with open(sched_file, "w") as f:
        json.dump(new_schedules, f, indent=4)
        print(f"cleared schedule file = {sched_file}, removed {filename} replaced by {new_schedules}")

    #return jsonify({"success": True, "message": f"Schedule for '{filename}' cleared."})


def load_shared_files(filename):
    """
    Load shared_files from JSON file.
    
    Args:
        filename: Path to the JSON file
        
    Returns:
        List of dictionaries (hashes) if file exists, otherwise empty list
    """
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                shared_files = json.load(f)
            print(f"Loaded {len(shared_files)} entries from {filename}")
            return shared_files
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from {filename}: {e}")
            return []
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            return []
    else:
        print(f"File {filename} does not exist. Returning empty list.")
        return []
    

def save_shared_files(filename, shared_files):
    """
    Save shared_files list to JSON file.
    
    Args:
        filename: Path to the JSON file
        shared_files: List of dictionaries (hashes) to save
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Save to JSON file
        with open(filename, 'w') as f:
            json.dump(shared_files, f, indent=2)
        
        print(f"Saved {len(shared_files)} entries to {filename}")
        return True
    except Exception as e:
        print(f"Error saving to {filename}: {e}")
        return False


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        users = load_users()

        first_name = request.form["first_name"]
        last_name = request.form["last_name"]
        username = request.form["username"]
        password = request.form["password"]
        email = request.form["email"]

        # check if username already exists
        if any(u["username"] == username for u in users):
            return "Username already taken!", 400

        new_user = {
            "id": str(len(users) + 1),
            "username": username,
            "password": password,  # hash this in production
            "first_name": first_name,
            "last_name": last_name,
            "email":email,
            "date_registered": datetime.utcnow().isoformat()
        }

        users.append(new_user)
        save_users(users)
        app.logger.info(f"{username} registered successafully")

        print(f"✅ Registered {first_name} {last_name} ({username})")

        return redirect(url_for("index"))

    return render_template("register.html")


from flask_login import logout_user, login_required

@app.route("/logout")
@login_required
def logout():
    app.logger.info(f"{current_user.username} attempted logout")
    logout_user()          # Clears current_user
    session.clear()        # Optional: clear session data
    return redirect(url_for("home"))  # Redirect to login page


# DONT GET CONFUSED.  this route is for sharepoint authorization. Not user login to IAConnector (see /home route)
@app.route("/login")
def login():
    #global logged_in

    if delegated_auth:
        print (f"/login endpoint using delegated_auth flow for {current_user.username}")
        cache = load_cache(current_user.username)
        cca = _build_msal_app(cache)
        auth_url = cca.get_authorization_request_url(
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,  # url_for("authorized", _external=True)  <-------------------- 
            prompt="consent" # to make sure the user (or their admin) grants access the first time
        )
        save_cache(cache, current_user.username)
        #session["is_logged_in"] = True
        return redirect(auth_url)
    else:
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

        #logged_in = True
        session["is_logged_in"] = True

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
       # return "No code provided."
#    return result["access_token"]


from google_oauth_appnew import (
    get_google_flow,
    load_google_token,
    save_google_token,
    logout_google,
    is_google_logged_in,
)

from googleapiclient.discovery import build

@app.route("/google/login")
def google_login():
    if not current_user.is_authenticated:
        return redirect(url_for("home"))

    global callback_host
    if callback_host:
        redirectpath = f"{callback_host}"
    else:
        redirectpath = "https://trinket.cloudcurio.com"

    userlogin = current_user.username

    print(f"/google/login about to call get_googe_flow({userlogin},{redirectpath})")
    flow = get_google_flow(userlogin, redirectpath)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    session["google_oauth_state"] = state
    session["google_user"] = userlogin
    print(f"🌐 Redirecting {userlogin} to Google OAuth...")
    return redirect(auth_url)


@app.route("/google/callback")
def google_callback():
    userlogin = session.get("google_user")
    if not userlogin:
        return "Missing session user", 400
    
    global callback_host
    if callback_host:
        redirectpath = f"{callback_host}"
    else:
        redirectpath = "https://trinket.cloudcurio.com"

    print(f"/google/callback called.  userlogin ={userlogin}")
    flow = get_google_flow(userlogin, redirectpath)
    flow.fetch_token(authorization_response=request.url)
    print(f"proceeding after flow.fetch_token()")

    creds = flow.credentials
    save_google_token(creds, userlogin)

    return """
        <html><body style='font-family:sans-serif;text-align:center;padding:40px;'>
        <h2>✅ Google Login Successful</h2>
        <p>You may close this window.</p>
        <script>
            try { window.opener && window.opener.postMessage('google-login-success', '*'); } catch(e) {}
            setTimeout(() => window.close(), 1000);
        </script>
        </body></html>
    """


@app.route("/google/logout")
def google_logout():
    if not current_user.is_authenticated:
        return redirect(url_for("home"))

    userlogin = current_user.username
    logout_google(userlogin)
    return redirect(url_for("index"))


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



'''
def 
point_url(url: str) -> str:
    """
    Cleans a SharePoint file URL by removing 'Shared Documents' or 'Shared Folders'
    so it can be used directly with pandas.read_excel/read_csv.
    """
    # Replace encoded space with normal space for safety
    url = url.replace("%20", " ")

    # Remove "Shared Documents" or "Shared Folders" segments
    url = re.sub(r"/Shared (Documents|Folders)", "", url, flags=re.IGNORECASE)

    # Fix spaces back to %20 for proper HTTP request
    return url.replace(" ", "%20")
'''

'''@app.route('/logs', methods=['GET', 'POST'])
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
'''


#@app.route('/home')
#def home():
@app.route("/home", methods=["GET", "POST"])
def home():    
    if current_user.is_authenticated:
        print(f"current_user.is_authenticated TRUE")
        return redirect(url_for("index"))

    if request.method == "POST":
        users = load_users()
        username = request.form["username"]
        password = request.form["password"]
        print(f"Searching for user in users.json. username={username}")
        for u in users:
            if u["username"] == username and u["password"] == password:
                print(f"found {username} {password} in users.json")
                user = User(**u)
                login_user(user)
                app.logger.info(f"{username} logged in successfully ")
                return redirect(url_for("index"))
        
        app.logger.info(f"{username} attempted login failed - unregistered user")

    
        print(f"Invalid creds provided for {username} {password} in users.json")
        # ❌ Invalid credentials → flash message
        flash("Invalid username or password", "error")  # 'error' is the category
        return redirect(url_for("home"))    
    
    return render_template('login.html')  # Renders login.html from the templates folder


# these are globals

userlogin = None
llm_model = "Local"

# File to store schedules
SCHEDULE_FILE = "./config/schedules.json"
#LLMCONFIG_FILE = "./config/llmconfig.json"
#LOCAL_FILES = "./config/files_local.json"

# gloabals ^^^


# Ensure file exists
if not os.path.exists(SCHEDULE_FILE):
    with open(SCHEDULE_FILE, "w") as f:
        print(f"creating schedule file = {SCHEDULE_FILE}")
        json.dump([], f)
else:
    print(f"Schedule file already exists {SCHEDULE_FILE}")



import argparse

'''def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Flask application with configurable port')
    parser.add_argument('--port', type=int, default=5000, 
                        help='Port number to run the Flask server on (default: 5000)')
    parser.add_argument('--auth', '--auth-mode', dest='auth_mode', default=None,
                        help='Authentication mode (e.g., user_auth)')
    parser.add_argument('--callback', type=str, default=None,
                        help='OAuth2 Callback host (e.g., localhost:7000)')
    parser.add_argument('--env', type=str, default=None,
                        help='Gunitherwise gunicorn')

    return parser.parse_args()

# Parse arguments
args = parse_arguments()
PORT = args.port
callback_host = args.callback
env = args.env
'''


def get_args():
    # Check if running under Gunicorn (no CLI args)
    if "gunicorn" in os.environ.get("SERVER_SOFTWARE", ""):
        return {
            "port": int(os.environ.get("PORT", 5000)),
            "auth": os.environ.get("AUTH", ""),
            "callback": os.environ.get("CALLBACK", "https://trinket.cloudcurio.com"),
            "env": os.environ.get("ENV", ""),
        }
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument("--port", type=int, required=True)
        parser.add_argument("--auth", type=str, required=True)
        parser.add_argument("--callback", type=str, required=True)
        parser.add_argument("--env", type=str, default="dev")
        args = parser.parse_args()
        return vars(args)

args = get_args()

PORT = args["port"]
AUTH = args["auth"]
callback_host = args["callback"]
env = args["env"]

print(f"callback_host provided as: {callback_host}")


delegated_auth = False  # set to False to use app-only auth (no user context)


#if args.auth_mode and "user_auth" in args.auth_mode:
if "user_auth" in AUTH:
    print(f"detected argument '{AUTH}' so will use delegated authorization instead of app auth flow")
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
    cache = load_cache(userlogin)
    cca = _build_msal_app(cache)
else:
    print(f"defaulting to application authorization since user_auth argument not specified")
    cache = load_cache()
    print("calling build_msal_app(cache)")
    cca = build_msal_app(cache)




'''if len(sys.argv) == 2:
    auth_param = sys.argv[1]
    if "user_auth" in auth_param:
        print(f"detected argument '{auth_param}' so will use delegated authorization instead of app auth flow")
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
        cache = load_cache(userlogin)
        cca = _build_msal_app(cache)
else:
    print(f"defaulting to application authorization since user_auth argument not specified")   
    cache = load_cache()
    print("calling build_msal_app(cache)")
    cca = build_msal_app(cache)
'''

# -----------------------------------------------------------------------------
# Global scheduler
# -----------------------------------------------------------------------------
# solves the multiple instances of scheduler in flask debug
import os



def job_listener(event):
    if event.exception:
        logger.error(f"Job {event.job_id} failed: {event.exception}")
    else:
        runtime = event.scheduled_run_time
        actual = event.scheduled_run_time + (event.scheduled_run_time - event.scheduled_run_time)
        logger.info(
            f"(listener)Job {event.job_id} executed successfully. "
            f"(listener) Scheduled: {event.scheduled_run_time}, "
            f"(listener) Duration: {event.retval if hasattr(event, 'retval') else 'N/A'}"
        )


#if __name__ != "__main__" or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
scheduler = BackgroundScheduler()
if not scheduler.running:
    scheduler.start()
    '''scheduler.add_job(
        dump_job_status, 
        "interval", 
        minutes=5, 
        args=[scheduler], 
        id="__status_dumper__", 
        replace_existing = True,
        misfire_grace_time=300,  # 5 minutes to prevent skipping of jobs when delays occur)
        max_instances=1 )  # don't start new one if previous still running
    '''
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    
    # Add after your existing scheduler.start()
    # automatic cleanup of task queue every hour
    scheduler.add_job(
        func=lambda: task_queue.clear_completed_tasks(older_than_minutes=60),
        trigger='interval',
        hours=1,
        id='task_queue_cleanup',
        replace_existing=True
    )

    # Setup all the schedules since app is starting up
    schedule_jobs(scheduler,SCHEDULE_FILE, delegated_auth)



def map_windows_path_to_container(path: str) -> str:

    #Convert Windows-style path (C:\...) to container path (/mnt/c/...).
    #If already looks like a Linux path, return as-is.
    
    if len(path) > 2 and path[1:3] in [":\\", ":/"]:
        drive_letter = path[0].lower()
        relative_path = path[2:].lstrip("\\/").replace("\\", "/")
        return f"/mnt/{drive_letter}/{relative_path}"
    return path

def get_bar_values(userlogin):
    user_bar_file = f"./config/.bar_{userlogin}"
    return read_file_lines(user_bar_file)

def save_bar_values(userlogin, values):
    user_bar_file = f"./config/.bar_{userlogin}"
    write_file_lines(user_bar_file, values)



def read_json_list(path):
    """Read a list of file objects from a JSON file"""
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                # Ensure it's a list
                if isinstance(data, list):
                    return data
                else:
                    print(f"Warning: {path} does not contain a list, returning empty list")
                    return []
        except json.JSONDecodeError as e:
            print(f"Error reading JSON from {path}: {e}")
            return []
    return []


def write_json_list(path, items):
    """Write a list to a JSON file"""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        with open(path, 'w') as f:
            json.dump(items, f, indent=4)
            print(f"Wrote {len(items)} items to {path}")
    except Exception as e:
        print(f"Error writing JSON to {path}: {e}")


def extract_filename_from_url(url):
    """Extract filename from SharePoint URL"""
    # Remove query parameters
    url_without_params = url.split('?')[0]
    # Get the last part of the path
    filename = url_without_params.split('/')[-1]
    # URL decode
    from urllib.parse import unquote
    return unquote(filename)


def extract_worksheet_name(url):
    """Extract worksheet name from URL if present, otherwise return empty string"""
    # Look for worksheet parameter in URL
    if 'activeCell=' in url or 'worksheet=' in url:
        # This is a placeholder - adjust based on your actual URL structure
        return ""  # You can enhance this based on your needs
    return ""


def get_bar_values_json(userlogin):
    """Load bar values from JSON file - returns list of file objects"""
    user_bar_file = f"./config/.bar_{userlogin}.json"
    return read_json_list(user_bar_file)

def save_bar_values_json(userlogin, values):
    """Save bar values to JSON file - values should be list of file objects"""
    user_bar_file = f"./config/.bar_{userlogin}.json"
    write_json_list(user_bar_file, values)

def add_bar_entry(userlogin, file_url, worksheet_name=""):
    """Add a new file entry to bar_values with all metadata"""
    bar_values = get_bar_values(userlogin)
    
    # Check if URL already exists
    for entry in bar_values:
        if entry.get("file_url") == file_url:
            print(f"File URL {file_url} already exists in bar_values")
            return False
    
    # Create new entry
    new_entry = {
        "file_url": file_url,
        "filename": extract_filename_from_url(file_url),
        "worksheet_name": worksheet_name,
        "date_added": datetime.utcnow().isoformat(),
        "last_refresh": None
    }
    
    bar_values.append(new_entry)
    save_bar_values(userlogin, bar_values)
    print(f"Added new file entry: {new_entry}")
    return True

def remove_bar_entry(userlogin, file_url):
    """Remove a file entry from bar_values by file_url"""
    bar_values = get_bar_values(userlogin)
    original_count = len(bar_values)
    
    bar_values = [entry for entry in bar_values if entry.get("file_url") != file_url]
    
    if len(bar_values) < original_count:
        save_bar_values(userlogin, bar_values)
        print(f"Removed file entry with URL: {file_url}")
        return True
    else:
        print(f"File URL {file_url} not found in bar_values")
        return False

def update_bar_refresh_time(userlogin, file_url):
    """Update the last_refresh timestamp for a file entry"""
    bar_values = get_bar_values(userlogin)
    
    for entry in bar_values:
        if entry.get("file_url") == file_url:
            entry["last_refresh"] = datetime.utcnow().isoformat()
            save_bar_values(userlogin, bar_values)
            print(f"Updated last_refresh for {file_url}")
            return True
    
    print(f"File URL {file_url} not found in bar_values")
    return False

def get_bar_urls_only(userlogin):
    """Get just the file URLs from bar_values (for backward compatibility)"""
    bar_values = get_bar_values(userlogin)
    return [entry.get("file_url", "") for entry in bar_values]


def get_google_values(userlogin):
    user_bar_file = f"./config/.google_{userlogin}"
    return read_file_lines(user_bar_file)

def save_google_values(userlogin, values):
    user_bar_file = f"./config/.google_{userlogin}"
    write_file_lines(user_bar_file, values)


def get_local_values(userlogin):
    user_bar_file = f"./config/local_files_{userlogin}"
    return read_file_lines(user_bar_file)

def save_local_values(userlogin, values):
    user_bar_file = f"./config/local_files_{userlogin}"
    write_file_lines(user_bar_file, values)



#bar_values = []
#google_values = []
#local_file_values = []

#bar_values = read_file_lines(BAR_FILE)
#local_file_values = read_file_lines(LOCAL_FILES)
user_sched_file = SCHEDULE_FILE #f"./logs/{userlogin}/{SCHEDULE_FILE}"
shared_files_google = []
shared_files_sharepoint = []
shared_files_local = []

#logged_in = False

# --- OAuth callback ---
@app.route(REDIRECT_PATH)
def authorized():
    if not current_user.is_authenticated:
        return "User session lost. Make sure you are logged in."

    code = request.args.get("code")
    if not code:
        return "No code found in redirect."

    cache = load_cache(current_user.username)
    cca = _build_msal_app(cache)

    print(f"calling cca.acquire_token_by_authorization_code({code}), {SCOPES}, {REDIRECT_URI}")
    result = cca.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    save_cache(cache, current_user.username)

    if "access_token" in result:
        print("found access_token in result")
        session["access_token"] = result["access_token"]
        session["user"] = result.get("id_token_claims")
        return """
        <html>
        <body style="font-family:sans-serif;text-align:center;padding:40px;">
            <h2>✅ Login Successful</h2>
            <script>
                try { window.opener && window.opener.postMessage('login-success', '*'); } catch(e) {}
                window.close();
            </script>
            <p>You may close this window if it doesn’t close automatically.</p>
        </body>
        </html>
        """
    else:
        print(f"Error: {result.get('error_description')}")
        return f"Error: {result.get('error_description')}"


'''# REDIRECT_PATH callback only required when using user-delegated auth flow.  
# not needed/used for private client auth flow
@app.route(REDIRECT_PATH)
def authorized():
    #global logged_in

    userlogin = current_user.username
     # Handle redirect from Azure AD
    code = request.args.get("code")
    if not code:
        return "No code found in redirect."

    cache = load_cache(userlogin)
    cca = _build_msal_app(cache)
    if "code" in request.args:
        print ("received 'code' in OAuth callback")
        result = cca.acquire_token_by_authorization_code(
            code, # request.args["code"],
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI   # url_for("authorized", _external=True)
        )
        save_cache(cache, userlogin)
        if "access_token" in result:
            session["is_logged_in"] = True
            session["user"] = result.get("id_token_claims")
            session["access_token"] = result["access_token"]
            #logged_in = True
            session["is_logged_in"] = True
            #return redirect(url_for("index"))
            return """
                    <html>
                    <body style="font-family:sans-serif;text-align:center;padding:40px;">
                        <h2>✅ Login Successful</h2>
                        <script>
                            // Notify opener and close
                            try { window.opener && window.opener.postMessage('login-success', '*'); } catch(e) {}
                            window.close();
                        </script>
                        <p>You may close this window if it doesn’t close automatically.</p>
                    </body>
                    </html>
                    """
        else:
            return f"Error: {result.get('error_description')}"
    return "No code provided."
    '''


auth_user_email = ""
auth_user_name = ""
google_user_email = ""

@app.route('/', methods=['GET', 'POST'])
def index():

    # Make sure user is logged into AI Connector before showing main page
    #userlogin = None

    if current_user.is_authenticated:
        #global userlogin
        userlogin = current_user.username
        print(f"User logged in: {userlogin}")
    else:
        print("Not logged so redirecting to home for login")
        userlogin = None
        return redirect(url_for("home"))

    #logged_in
    global auth_user_email
    global auth_user_name
    global google_user_email
    global shared_files_google
    global shared_files_sharepoint
    global shared_files_local

    #global BAR_FILE
    #global GOOGLE_FILE
    #global LOCAL_FILES

    if (delegated_auth):
        print ("/ route is using delegated_auth flow")
        # Try silent token first
        print(f"Attempting to acquire token silently for {userlogin}...")
        cache = load_cache(userlogin)
        print(f"Loaded cache, checking for accounts for {userlogin}...")
        cca = _build_msal_app(cache)
        accounts = cca.get_accounts()
        if accounts:
            print(f"Found {len(accounts)} accounts in token cache")
            result = cca.acquire_token_silent(SCOPES, account=accounts[0])
            #result = cca.acquire_token_silent(SCOPES + ["openid", "profile"], account=accounts[0])
            
            print("called 'acquire_token_silent'")
            save_cache(cache, userlogin)
            if result:
                print (f"/ endpoint found valid user auth token = {result}")
                print(f"token claims = {result.get('token_claims')}")
                #logged_in = True
                session["is_logged_in"] = True
                session["user"] = result.get("id_token_claims")
                session["access_token"] = result["access_token"]
                auth_user_info = session.get("user")
                print(f"%%%%%%%%% session = {session}")
                
                if auth_user_info:
                    auth_user_email = auth_user_info.get("preferred_username")
                    auth_user_name = auth_user_info.get("name")
                    print(f"auth_user_info found in session, user = {auth_user_name}, email= {auth_user_email}")
                else:
                    print("No auth_user_info found in session!")

                #return f"Access token ready!<br>{result['access_token'][:40]}..."
            else:
                return "Failed acquire_token_silent <br>"
        else:
            print("No existing accounts found in token cache")
            #return '<a href="/login">Login with Microsoft</a>'
            #logged_in = False
            session["is_logged_in"] = False


    user_sched_file = SCHEDULE_FILE #f"./logs/{userlogin}/{SCHEDULE_FILE}"
    # Ensure file exists
    if not os.path.exists(user_sched_file):
        with open(user_sched_file, "w") as f:
            print(f"creating schedule file = {user_sched_file}")
            json.dump({}, f)
    else:
        print(f"Schedule file already exists {user_sched_file}")

    LLMCONFIG_FILE = f"./config/llmconfig_{current_user.username}.json"
    if not os.path.exists(LLMCONFIG_FILE):
        with open(LLMCONFIG_FILE, "w") as f:
            print(f"creating LLM config settings file = {LLMCONFIG_FILE}")
            json.dump({}, f)
    else:
        print(f"LLM config settings file already exists {LLMCONFIG_FILE}")


    # Load saved value
    #ENV_PATH_USER = os.path.join(os.path.dirname(__file__), "config", f"env.{userlogin}")
    ENV_PATH_USER = os.path.join(os.path.dirname(__file__), "config", f"env.{current_user.username}")

    foo_values = {}
    foo_values["jira_url"] = read_env("JIRA_URL", ENV_PATH_USER)
    foo_values["jira_user"] = read_env("JIRA_EMAIL", ENV_PATH_USER)
    foo_values["jira_token"] = read_env("JIRA_API_TOKEN", ENV_PATH_USER)
    foo_values["openai_token"] = read_env("OPENAI_API_KEY", ENV_PATH)       # for now keep openai token in system environment. move to user specific later

    print(f"Loaded following foo_values from {ENV_PATH}")
    for key, value in foo_values.items():
        print(f"{key}: {value}")

    #foo_lines = read_file_lines(FOO_FILE)
    schedules = load_schedules(user_sched_file,userlogin)

    llm_settings_from_config_file = load_llm_config(LLMCONFIG_FILE)
    if not llm_settings_from_config_file:
        llm_settings_from_config_file['model'] = "Local"  # default to local if file is empty

    if llm_settings_from_config_file:
        llm_model = llm_settings_from_config_file.get("model")  # This will be 'OpenAI'
        print(f"setting llm_model to {llm_model} from config file")
        llm_model = llm_model
    else:
        print(f"setting llm_model to default LOCAL")
        llm_model = "Local"
    
    schedule_dict = {}
    for s in schedules:  
         schedule_dict[s["filename"]] = s

 
    #if delegated_auth:
        #BAR_FILE = f"./config/.bar_{userlogin}"
        #LOCAL_FILES = f"./config/local_files_{userlogin}"
        #GOOGLE_FILE = f"./config/.google_{userlogin}"
        #print(f"using delegated auth so BAR_FILE = {BAR_FILE}, LOCAL_FILES = {LOCAL_FILES}, GOOGLE_FILE = {GOOGLE_FILE}")
   
    #bar_values = get_bar_values(userlogin)
    shared_files_sharepoint = load_shared_files(f"./config/shared_files_sharepoint_{userlogin}.json")
    shared_files_google = load_shared_files(f"./config/shared_files_google_{userlogin}.json")
    shared_files_local = load_shared_files(f"./config/shared_files_local_{userlogin}.json")
                                            
                                                

    #print(f"/ route loaded bar_values = {bar_values}")

    #local_file_values = read_file_lines(LOCAL_FILES)
    #local_file_values = get_local_values(userlogin)
    #print(f"/ route loaded local_file_values = {local_file_values}")    

    #google_values = read_file_lines(GOOGLE_FILE)
    #google_values = get_google_values(userlogin)

    #print(f"/ route loaded google_values = {google_values}")

    if not delegated_auth:
        # Synchronize session login status with real token state every request
        print("Checking login status...")
        logged_in_state = is_logged_in()  # returns True or False
        print(f"Login status: {logged_in_state}")
        session["is_logged_in"] = logged_in_state
        #logged_in = logged_in_state



    folder_tree = get_folder_tree(LOG_FOLDER)
   
    if request.method == 'POST':
        if 'save_foo' in request.form:
            #jira_url = "JIRA_URL = \"" + request.form.get('jira_url', '') + "\""
            #jira_user = "JIRA_EMAIL = \"" + request.form.get('jira_user', '') + "\""
            #jira_token = "JIRA_API_TOKEN = \"" + request.form.get('jira_token', '') + "\""
            jira_url = request.form.get('jira_url', '') 
            jira_user = request.form.get('jira_user', '') 
            jira_token = request.form.get('jira_token', '')
            print(f"saving new .env values {jira_url}, {jira_user}, {jira_token}")
#            write_file_lines(FOO_FILE, [jira_url, jira_user, jira_token])
            write_env("JIRA_URL",jira_url,ENV_PATH_USER)
            write_env("JIRA_EMAIL",jira_user,ENV_PATH_USER)
            write_env("JIRA_API_TOKEN",jira_token,ENV_PATH_USER)
            # load .env from config folder
            load_dotenv(dotenv_path=ENV_PATH)
            
            #return redirect(url_for('index'))
            return jsonify({"success": True, "message": "Jira settings updated successfully"})
        
        elif 'add_bar' in request.form:
            new_val = request.form.get('bar_value', '').strip()
            if new_val:
                print(f"add_bar with bar_value={new_val}")
                if new_val not in bar_values and new_val not in local_file_values:
                    print(f"{new_val} added to bar_values")   
                    bar_values.append(new_val)
                    #write_file_lines(BAR_FILE, bar_values)   
                    save_bar_values(userlogin, bar_values)
                    print(f"Updated BAR_FILE={BAR_FILE} with new value {new_val}")                     
                else:
                    print(f"{new_val} already present so no action needed")
                    return jsonify({"success": True, "message": "File already present, no action needed"})
                #return redirect(url_for('index', section="local"))
                return jsonify({"success": True, "message": "File added successfully"})

        elif 'remove_bar' in request.form:
            to_remove = request.form.get('remove_bar')
            print(f"remove_bar called with {to_remove}")
            if to_remove in bar_values:
                print(f"{to_remove} found and will be removed")
                bar_values.remove(to_remove)
                #write_file_lines(BAR_FILE, bar_values)
                save_bar_values(userlogin, bar_values)
                print(f"Removed from BAR_FILE={BAR_FILE} the value {to_remove}")                     

                # if file was scheduled for resync then remove from schedule.json 
                clear_schedule_file(user_sched_file, to_remove, userlogin) 
                schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)           
                return jsonify({"success": True, "message": "File removed successfully"})
            else:
                print(f"{to_remove} not found in bar_values, no action taken")
            #return redirect(url_for('index', section="local"))
            return jsonify({"success": False, "message": "File not found"})

        
        elif 'resync_bar' in request.form:
            print("Resyncing file values...")
            val = request.form["resync_bar"]
            val = clean_sharepoint_url(val)
            resync(val,userlogin, delegated_auth)  # call your function with the string value file URL and userlogin (used for working folder for script)
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

    
    print(f"Sharepoint Authorization status: {session['is_logged_in']}")


    # Check Google login status
    google_logged_in = is_google_logged_in(userlogin)
    if google_logged_in:
        from google.oauth2.credentials import Credentials
        google_creds = load_google_token(userlogin)
        if google_creds:
            try:
                # Get user info from Google
                from googleapiclient.discovery import build
                service = build('oauth2', 'v2', credentials=google_creds)
                user_info = service.userinfo().get().execute()
                google_user_email = user_info.get('email', '')
                print(f"Google user email: {google_user_email}")
            except Exception as e:
                print(f"Error fetching Google user info: {e}")
                google_user_email = ""
        else:
            google_user_email = ""
    else:
        google_user_email = ""



    #if(is_logged_in()):

    print(f"************Current session: {session}")

    auth_user_info = session.get("user")
    if auth_user_info:
        auth_user_email = auth_user_info.get("preferred_username")
        auth_user_name = auth_user_info.get("name")
        print(f"auth_user_info found in session, user = {auth_user_name}, email= {auth_user_email}")
    else:
        print("No auth_user_info found in session!")
        auth_user_email = "---"


    return render_template('form.html',
                           banner_path=BANNER_PATH,
                           foo_values=foo_values,
                           shared_files_sharepoint = shared_files_sharepoint,
                           shared_files_google = shared_files_google,
                           shared_files_local = shared_files_local,
                           #bar_values=bar_values,
                           #google_values=google_values,
                           #local_values=local_file_values,
                           logged_in=session["is_logged_in"],
                           google_logged_in=google_logged_in,
                           folder_tree=folder_tree,
                           schedule_dict=schedule_dict,
                           username=userlogin,
                           auth_username=auth_user_email,
                           google_username=google_user_email,
                           llm_default=llm_model)



@app.route("/logout_sharepoint", methods=["POST"])
def logout_sharepoint():
    #global logged_in
    userlogin = current_user.username
    print("recvd /logout_sharepoint endpoint called")
    #if session['logged_in'] == True:
    token_file = f"./config/token_cache_{userlogin}.json"
    print(f"Revoking sharepoint access token for user={userlogin} token_file={token_file}")

    if os.path.exists(token_file):
        os.remove(token_file)
        print(f"Deleted token file: {token_file}")
        #logged_in = False
        session["is_logged_in"] = False
    else:
        print(f"No token file {token_file} found for user={userlogin}")
  
    # Microsoft logout endpoint (kills AAD session cookies)
    ms_logout_url = "https://login.microsoftonline.com/common/oauth2/v2.0/logout"

    # After logout, redirect back to your app
    post_logout_redirect = url_for('index', section="section2", _external=True)

    # Redirect user through Microsoft logout then back to your app
    return redirect(f"{ms_logout_url}?post_logout_redirect_uri={post_logout_redirect}")


from flask import Flask, request, jsonify

@app.route("/save_jira", methods=["POST"])
def save_jira():
    data = request.get_json()
    jira_url = data.get("jira_url", "")
    jira_user = data.get("jira_user", "")
    jira_token = data.get("jira_token", "")
    jira_password = data.get("jira_password")

    ENV_PATH_USER = os.path.join(os.path.dirname(__file__), "config", f"env.{userlogin}")
    print(f"Saving new .env values {jira_url}, {jira_user}, {jira_token}, {jira_password}")
    write_env("JIRA_URL", jira_url, ENV_PATH_USER)
    write_env("JIRA_EMAIL", jira_user, ENV_PATH_USER)
    write_env("JIRA_API_TOKEN", jira_token, ENV_PATH_USER)
    write_env("JIRA_PASSWORD", jira_password, ENV_PATH_USER)

    return jsonify({"success": True, "message": "Jira settings updated successfully"})


@app.route("/setmodel", methods=["POST"])
def setmodel():
    print("/setmodel endpoint called")
    data = request.get_json()
    #llm_model = data.get("model")

    llm_model = data.get("llm_model")
    openai_token = data.get("openai_token")

    if not llm_model:
        return "LLM model value not received", 400
    
    print(f"/setmodel setting model to {llm_model}")

    LLMCONFIG_FILE = f"./config/llmconfig_{current_user.username}.json"
     # Ensure config folder exists
    os.makedirs(os.path.dirname(LLMCONFIG_FILE), exist_ok=True)

    # Save to JSON file
    with open(LLMCONFIG_FILE, 'w') as f:
        json.dump({"model": llm_model}, f, indent=4)

    write_env("OPENAI_API_KEY", openai_token,ENV_PATH)    
    load_dotenv(dotenv_path=ENV_PATH)

        
    return jsonify({"success": True, "message": "LLM Model updated successfully"})


@app.route("/add_sharepoint", methods=["POST"])
def add_sharepoint():
    new_val = request.form.get('bar_value', '').strip()
    new_val = unquote(new_val);      # remove %20, etc
    userlogin = current_user.username
    print(f"/add_sharepoint endpoint called with new_val = {new_val} by {userlogin}")
    shared_files_sharepoint= load_shared_files(f"./config/shared_files_sharepoint_{current_user.username}.json")

    if new_val:
        print(f"add_sharepoint with shared_files_sharepoint={new_val}")
       # if new_val not in shared_files_google and new_val not in bar_values and new_val not in local_file_values:
        if not is_location_in_shared_files(new_val, shared_files_sharepoint):
            # Add to shared_files_google list
            from datetime import date
            shared_files_sharepoint.append({
                "location": new_val,
                "user": current_user.username,
                "datetime": datetime.now().isoformat()            })            
            print(f"Added to shared_files_sharepoint: {shared_files_sharepoint[-1]}")

          # Save to JSON file
            json_filename = f"./config/shared_files_sharepoint_{current_user.username}.json"
            save_shared_files(json_filename, shared_files_sharepoint)
            print(f"Saved shared_files_sharepoint to {json_filename}")

        else:
            print(f"{new_val} already present so no action needed")
            return jsonify({"success": True, "message": "File already present, no action needed"})
        return jsonify({"success": True, "message": "Sharepoint file added successfully"})
    return jsonify({"success": False, "message": "No file URL provided"})

@app.route("/remove_sharepoint", methods=["POST"])
def remove_sharepoint():
    to_remove = request.form.get('remove_bar')
    userlogin = current_user.username
    print(f"remove_sharepoint called with {to_remove}")

    # Remove from shared_files_google list (independent check)
    json_filename = f"./config/shared_files_sharepoint_{userlogin}.json"
    shared_files_sharepoint = load_shared_files(json_filename)
    
    if shared_files_sharepoint:
        original_length = len(shared_files_sharepoint)
        
        # Filter out the entry with matching new_val and username
        shared_files_sharepoint = [
            entry for entry in shared_files_sharepoint 
            if not (entry.get('location') == to_remove and entry.get('user') == userlogin)
        ]
        
        # Check if anything was removed
        if len(shared_files_sharepoint) < original_length:
            # Save updated list back to disk
            save_shared_files(json_filename, shared_files_sharepoint)
            print(f"Removed from shared_files_sharepoint the entry with new_val={to_remove}")
            #return jsonify({"success": True, "message": "Google Sheet removed successfully"})

            # if file was scheduled for resync then remove from schedule.json 
            clear_schedule_file(user_sched_file, to_remove, userlogin) 
            schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)           
            return jsonify({"success": True, "message": "Sharepoint file removed successfully"})
        else:
                # this shoudl never happen because only way to trigger remove is from a listed file on gui
            print(f"{to_remove} not found in shared_files_sharepoint, no action taken")
    
    return jsonify({"success": False, "message": "Sharepoint file collection is empty"})


@app.route("/add_local", methods=["POST"])
def add_local():
    new_val = request.form.get('local_value', '').strip()
    userlogin = current_user.username
    print(f"/add_local endpoint called with new_val = {new_val} by {userlogin}")
    shared_files_local = load_shared_files(f"./config/shared_files_local_{current_user.username}.json")

    if new_val:
        print(f"add_local with shared_files_local={new_val}")
        # if new_val not in shared_files_google and new_val not in bar_values and new_val not in local_file_values:
        container_val = map_windows_path_to_container(new_val)
        if not is_location_in_shared_files(container_val, shared_files_local):
            # Add to shared_files_google list
            from datetime import date
            shared_files_local.append({
                "location": container_val,
                "user": current_user.username,
                "datetime": datetime.now().isoformat()            })            
            print(f"Added to shared_files_local: {shared_files_local[-1]}")

          # Save to JSON file
            json_filename = f"./config/shared_files_local_{current_user.username}.json"
            save_shared_files(json_filename, shared_files_local)
            print(f"Saved shared_files_local to {json_filename}")

        else:
            print(f"{new_val} already present so no action needed")
            return jsonify({"success": True, "message": "File already present, no action needed"})
        return jsonify({"success": True, "message": "Local file added successfully"})
    return jsonify({"success": False, "message": "No file provided"})



@app.route("/remove_local", methods=["POST"])
def remove_local():
    to_remove = request.form.get('remove_local')
    userlogin = current_user.username
    print(f"remove_local called with {to_remove}")

    # Remove from shared_files_google list (independent check)
    json_filename = f"./config/shared_files_local_{userlogin}.json"
    shared_files_local = load_shared_files(json_filename)
    
    if shared_files_local:
        original_length = len(shared_files_local)
        
        # Filter out the entry with matching new_val and username
        shared_files_local = [
            entry for entry in shared_files_local 
            if not (entry.get('location') == to_remove and entry.get('user') == userlogin)
        ]
        
        # Check if anything was removed
        if len(shared_files_local) < original_length:
            # Save updated list back to disk
            save_shared_files(json_filename, shared_files_local)
            print(f"Removed from shared_files_local the entry with new_val={to_remove}")
            #return jsonify({"success": True, "message": "Google Sheet removed successfully"})

            # if file was scheduled for resync then remove from schedule.json 
            clear_schedule_file(user_sched_file, to_remove, userlogin) 
            schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)           
            return jsonify({"success": True, "message": "Local file removed successfully"})
        else:
            print(f"{to_remove} not found in file collection, no action taken")
    
    return jsonify({"success": False, "message": "Local file collection is empty"})


@app.route("/schedule", methods=["POST"])
def schedule_file():
    filename = request.form.get("filename")
    time = request.form.get("time")
    interval = request.form.get("interval")
    mode = request.form.get("mode")  # <-- this will be "hourly", "daily", or "weekly", or None if not selected
    days = request.form.getlist("days")  # ["mon", "wed", "fri"]
    
    userlogin = current_user.username

    print(f"Schedule called filename={filename} time={time} mode={mode} interval={interval}")
    # Validate input
    if not filename:
        return "Filename missing", 400

    # Only one of time or interval should be filled
    if (time and interval) or (not time and not interval):
        return "Enter either time OR interval, not both", 400

    # Prepare schedule data
    schedule_entry = {
        "userlogin": userlogin,
        "filename": filename,
        "time": time if time else None,
        "mode": mode if mode else None,
        "interval": int(interval) if interval else None,
        "days": days if days else None
    }


    # Load existing schedules
    user_sched_file = SCHEDULE_FILE #f"./logs/{userlogin}/{SCHEDULE_FILE}"
    
    #with open(user_sched_file, "r") as f:
    #    print(f"loading schedule file = {user_sched_file}")
    #    schedules = json.load(f)

    schedules = load_schedules(user_sched_file) #we want to load for ALL users here

    # Check if this file already exists in schedules
    #existing = next((s for s in schedules if s["filename"] == filename and s.get("userlogin") == userlogin), None)
    existing = None
    for s in schedules:
        if s["filename"] == filename: #and s["userlogin"] == userlogin:
            existing = s

    if existing:
        # Update existing
        print(f"Updating existing schedule entry existing={existing}")
        existing["time"] = schedule_entry["time"]
        existing["interval"] = schedule_entry["interval"]
        existing["mode"] = schedule_entry["mode"]

        # reset days if this entry previously was set for weekly runs
        # The frontend passes the daya to this call to just alway reset days if Daily
        if existing["mode"] == "Daily":
            existing["days"] = []

    else:
        print(f"Appending new schedule_entry = {schedule_entry}")
        schedules.append(schedule_entry)

    # Save back to file
    with open(user_sched_file, "w") as f:
        print(f"saving to schedule file = {user_sched_file}")
        json.dump(schedules, f, indent=4)

    # update the scheduled jobs
    global delegated_auth
    schedule_jobs(scheduler, user_sched_file, delegated_auth, filename, userlogin)

    return jsonify({"success": True, "message": "Schedule saved successfully"})



@app.route("/schedule/clear", methods=["POST"])
def clear_schedule():
    data = request.get_json()
    filename = data.get("filename")

    if not filename:
        return jsonify({"success": False, "message": "Filename missing"}), 400

    # Load existing schedules
    user_sched_file = SCHEDULE_FILE #f"./logs/{userlogin}/{SCHEDULE_FILE}"
    schedules = []
    schedules = load_schedules(user_sched_file)  # must load for all userlogins
    '''
    if os.path.exists(user_sched_file):
        with open(user_sched_file, "r") as f:
            print(f"loading schedule file = {user_sched_file}")
            schedules = json.load(f)
    '''
    # Remove the schedule for this file
    #schedules = [s for s in schedules if s["filename"] != filename or s["userlogin"] != userlogin]
    schedules = [s for s in schedules if s["filename"] != filename]

    # Save back
    with open(user_sched_file, "w") as f:
        print(f"saving schedule file = {user_sched_file}")
        json.dump(schedules, f, indent=4)

    #update scheduled jobs
    schedule_job_clear(scheduler, user_sched_file,filename,userlogin)

    return jsonify({"success": True})



# Add this import at the top of your file
from task_queue import task_queue

# ... rest of your existing imports and code ...


# ============================================================================
# TASK QUEUE ROUTES - Add these new routes
# ============================================================================

@app.route("/tasks/status", methods=["GET"])
def get_task_status():
    #print("/tasks/status endpoint called")
    """Get status of all tasks or a specific task"""
    task_id = request.args.get("task_id")
    user = current_user.username if current_user.is_authenticated else None
    if task_id:
        task = task_queue.get_task(task_id)
        #print(f"get_task_status called with task_id={task_id} for user={user}")
        if task:
            #print(f"Returning status for task_id={task_id}: {task.to_dict()}")
            return jsonify({"success": True, "task": task.to_dict()})
        else:
            #print(f"Task with id={task_id} not found")
            return jsonify({"success": False, "message": "Task not found"}), 404
    else:
        # Return all tasks for this user
        tasks = task_queue.get_all_tasks(user=user)
        status = task_queue.get_queue_status()
        #print(f"Returning status for all tasks for user={user}: {tasks}")
        #print(f"Queue status: {status}")
        return jsonify({
            "success": True,
            "tasks": tasks,
            "queue_status": status
        })


@app.route("/tasks/cancel/<task_id>", methods=["POST"])
def cancel_task_route(task_id):
    """Cancel a pending task"""
    success = task_queue.cancel_task(task_id)
    if success:
        return jsonify({"success": True, "message": "Task cancelled"})
    else:
        return jsonify({
            "success": False, 
            "message": "Task not found or already running"
        }), 400


@app.route("/tasks/clear", methods=["POST"])
def clear_old_tasks():
    """Clear completed tasks older than 1 hour"""
    cleared = task_queue.clear_completed_tasks(older_than_minutes=60)
    return jsonify({"success": True, "cleared": cleared})



# ADD THIS NEW ROUTE INSTEAD:
@app.route("/resync_sharepoint", methods=["POST"])
def resync_sharepoint():
    """Queue a resync task (async)"""
    val = request.form.get('resync_bar')
    user = current_user.username if current_user.is_authenticated else None
    
    print(f"/resync_sharepoint endpoint called with val={val} for user={user}") 

    if not val:
        return jsonify({"success": False, "message": "No file specified"}), 400
    
    # Clean the URL
    val = clean_sharepoint_url(val)
    
    # Enqueue the task
    task_id = task_queue.enqueue(
        resync_task_worker,
        file_url=val,
        userlogin=user,
        delegated_auth=delegated_auth,
        #google_user_email=google_user_email,
        user=user
    )

    print(f"Resync task queued with task_id={task_id} for file={val} and user={user}")
    
    return jsonify({
        "success": True,
        "message": f"Resync started for {val}",
        "task_id": task_id
    })


def is_location_in_shared_files(location_string, shared_files_google):
    """
    Check if a location string exists in the shared_files_google list.
    
    Args:
        location_string: The string to search for
        shared_files_google: List of dictionaries containing file entries
        
    Returns:
        True if location_string is found in any entry's "location" field, False otherwise
    """
    for entry in shared_files_google:
        if entry.get('location') == location_string:
            return True
    return False



from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import re


def extract_sheet_id_and_name(url_or_id):
    """
    Extract Google Sheets ID and sheet name from URL or return ID as-is.
    Handles URLs with fragments (e.g., #sheetname or #gid=123).
    
    Args:
        url_or_id: Either a full Google Sheets URL or just the sheet ID
                   Example: https://docs.google.com/spreadsheets/d/1ABC.../edit#Sheet1
        
    Returns:
        tuple: (sheet_id, sheet_name) where sheet_name is None if not present
    """
    sheet_name = None
    
    # Extract sheet name from fragment if present
    if '#' in url_or_id:
        url_part, fragment = url_or_id.split('#', 1)
        # Check if it's a sheet name (not gid=...)
        if not fragment.startswith('gid='):
            sheet_name = fragment
    else:
        url_part = url_or_id
    
    # Extract sheet ID
    if "docs.google.com/spreadsheets" in url_part:
        parts = url_part.split("/d/")
        if len(parts) > 1:
            sheet_id = parts[1].split("/")[0]
            return sheet_id, sheet_name
    
    return url_part, sheet_name


def get_google_sheet_filename(creds, url_or_id):
    """
    Get the filename and sheet name of a Google Sheet from its URL or ID.
    
    Args:
        creds: Valid Google credentials object (from google.oauth2)
        url_or_id: Either a full Google Sheets URL or just the sheet ID
                   Example URL: https://docs.google.com/spreadsheets/d/1ABC.../edit
                   Example URL with sheet: https://docs.google.com/spreadsheets/d/1ABC.../edit#Sheet1
                   Example ID: 1ABC...
        
    Returns:
        dict: {
            'filename': str,  # The Google Drive filename
            'sheet_name': str or None  # The sheet name if present in URL fragment
        }
        
    Raises:
        ValueError: If the sheet ID cannot be extracted or sheet not found
        HttpError: If there's an API error accessing the sheet
    """
    # Extract the sheet ID and sheet name from URL if present
    sheet_id, sheet_name = extract_sheet_id_and_name(url_or_id)
    
    if not sheet_id:
        raise ValueError(f"Could not extract sheet ID from: {url_or_id}")
    
    try:
        # Build Google Drive service (not Sheets - we need file metadata)
        service = build('drive', 'v3', credentials=creds)
        
        # Get file metadata - only request the name field for efficiency
        file_metadata = service.files().get(
            fileId=sheet_id,
            fields='name'
        ).execute()
        
        filename = file_metadata.get('name')
        
        if not filename:
            raise ValueError(f"No filename found for sheet ID: {sheet_id}")
            
        return {
            'filename': filename,
            'sheet_name': sheet_name
        }
        
    except HttpError as e:
        if e.resp.status == 404:
            raise ValueError(f"Sheet not found with ID: {sheet_id}")
        else:
            raise


#--- Google Sheet routes ---
@app.route("/add_google", methods=["POST"])
def add_google():
    new_val = request.form.get('google_value', '').strip()
    userlogin = current_user.username
    print(f"/add_google endpoint called with new_val = {new_val} by {userlogin}")
    shared_files_google = load_shared_files(f"./config/shared_files_google_{current_user.username}.json")

    if new_val:

        # Load credentials
        creds = load_google_token(current_user.username)
        result = get_google_sheet_filename(creds, new_val)
        fname = result["filename"]
        sheet = result['sheet_name']

        print(f"add_google with shared_files_google={new_val} filename={fname} sheet={sheet}")
       # if new_val not in shared_files_google and new_val not in bar_values and new_val not in local_file_values:
        if not is_location_in_shared_files(new_val, shared_files_google):
            # Add to shared_files_google list
            from datetime import date
            shared_files_google.append({
                "filename": fname,
                "sheet": sheet,
                "location": new_val,
                "user": current_user.username,
                "datetime": datetime.now().isoformat()            })            
            print(f"Added to shared_files_google: {shared_files_google[-1]}")

          # Save to JSON file
            json_filename = f"./config/shared_files_google_{current_user.username}.json"
            save_shared_files(json_filename, shared_files_google)
            print(f"Saved shared_files_google to {json_filename}")

        else:
            print(f"{new_val} filename={fname} sheet={sheet} already present so no action needed")
            return jsonify({"success": True, "message": f"File {fname} {sheet} already present, no action needed"})
        return jsonify({"success": True, "message": f"Google Sheet {fname} {sheet} added successfully"})
    return jsonify({"success": False, "message": "No file URL provided"})


@app.route("/remove_google", methods=["POST"])
def remove_google():
    to_remove = request.form.get('remove_google')
    userlogin = current_user.username
    print(f"remove_google called with {to_remove}")

    # Remove from shared_files_google list (independent check)
    json_filename = f"./config/shared_files_google_{userlogin}.json"
    shared_files_google = load_shared_files(json_filename)
    
    if shared_files_google:
        original_length = len(shared_files_google)
        
        # Filter out the entry with matching new_val and username
        shared_files_google = [
            entry for entry in shared_files_google 
            if not (entry.get('location') == to_remove and entry.get('user') == userlogin)
        ]
        
        # Check if anything was removed
        if len(shared_files_google) < original_length:
            # Save updated list back to disk
            save_shared_files(json_filename, shared_files_google)
            print(f"Removed from shared_files_google the entry with new_val={to_remove}")
            #return jsonify({"success": True, "message": "Google Sheet removed successfully"})

            # if file was scheduled for resync then remove from schedule.json 
            clear_schedule_file(user_sched_file, to_remove, userlogin) 
            schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)           
            return jsonify({"success": True, "message": "Google Sheet removed successfully"})
        else:
            print(f"{to_remove} not found in google_values, no action taken")
    
    return jsonify({"success": False, "message": "Google sheet file collection is empty"})


# ============================================================================
# BACKGROUND WORKER FUNCTION - Add this new function
# ============================================================================

def resync_task_worker(file_url, userlogin, delegated_auth):
    """
    Background task that performs the actual resync.
    This runs in a separate thread via the task queue.
    """
    print(f"[Task Worker] Starting resync for {file_url}, user: {userlogin}")
    
    try:
        # Call your existing resync function
        result = resync(file_url, userlogin, delegated_auth) # no need to pass google_user_email for google sheets, it uses token instead
        
        print(f"[Task Worker] Resync completed successfully for {file_url}")
        return {
            "status": "success",
            "file": file_url,
            "result": result
        }
    
    except Exception as e:
        print(f"[Task Worker] Resync failed for {file_url}: {str(e)}")
        raise  # Re-raise so task queue marks it as failed


LOG_BASE_DIR = "./logs"

import re
from datetime import datetime
from flask import jsonify

@app.route("/logs")
def list_logs():
    user_dir = os.path.join(LOG_BASE_DIR, current_user.username)
    if not os.path.isdir(user_dir):
        return jsonify([])

    runs = os.listdir(user_dir)
    pattern = re.compile(r"(\d{8}_\d{6})")  # matches YYYYMMDD_HHMMSS

    def extract_datetime(name):
        m = pattern.search(name)
        if not m:
            return datetime.min  # fallback for invalid names
        try:
            return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            return datetime.min

    runs_sorted = sorted(runs, key=extract_datetime, reverse=True)
    print(f"Listing log runs for {current_user.username}: {runs_sorted}")
    return jsonify(runs_sorted)


@app.route("/logs/<run>")
def get_latest_log(run):
    """
    Automatically find and serve the first .log file inside the run folder.
    """
    user_dir = os.path.join(LOG_BASE_DIR, current_user.username)
    run_path = os.path.join(user_dir, run)

    if not os.path.isdir(run_path):
        abort(404, description="Log run not found")

    # Find any file ending with .log
    log_files = [f for f in os.listdir(run_path) if f.endswith(".log")]
    if not log_files:
        abort(404, description="No log files found")

    # Pick the most recent (sorted descending by name or modified time)
    log_files.sort(reverse=True)
    log_file = log_files[0]

    print(f"Serving log file {log_file} for {current_user.username}")
    return send_from_directory(run_path, log_file)


if __name__ == "__main__" and env == "dev":
    print(f"Starting Flask app on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)
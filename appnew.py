from flask import Flask, render_template, request, redirect, url_for,session, send_from_directory
import os
import re
import json
import shutil
import requests
import msal
import uuid
from pathlib import Path
from dotenv import load_dotenv, set_key 
from flask import flash
#from apscheduler.schedulers.background import BackgroundScheduler
#from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR 

# my modules
from refresh import *
#from my_scheduler import *
from my_utils import *

import logging
from flask import Flask, request, g
from datetime import datetime

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Allow HTTP for local dev
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'  # Allow Google to return a superset of requested scopes

from flask_cors import CORS

from vector_worker import resync_task_worker, process_url

app = Flask(__name__)
# Allow requests from your frontend domain
CORS(app, origins=["https://www.cloudcurio.com"])

from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)



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

    if request.path == "/metrics":  # exlucde /metrics since prmomethus pings it repeatedly and we dont want to log those requests
        return
    
    # Assume you set g.current_user from your auth layer
    #g.current_user = request.headers.get("X-User", "anonymous")  # demo only
    if current_user.is_authenticated:
        g.current_user = current_user.username
    else:
        g.current_user = "anonymous"
    app.logger.info("Request started")


@app.after_request
def after_request_logging(response):
    if request.path != "/metrics":
    #    duration = time.time() - request.start_time
    #    app.logger.info(f"{request.path} took {duration:.3f}s")

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
ENV_PATH = os.path.join(os.path.dirname(__file__), "config", "env.system")
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
REDIRECT_URI = f"https://demo.cloudcurio.com{REDIRECT_PATH}"  # overwritten after args parsed below

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
        TOKEN_CACHE_FILE = user_config_file(userlogin, "token_cache.json")
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
            TOKEN_CACHE_FILE = user_config_file(userlogin, "token_cache.json")
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
login_manager.login_view = "home"

from filelock import FileLock
import json
import os
from datetime import datetime

USERS_FILE = "./config/users.json"
LOCK_FILE = USERS_FILE + ".lock"
SCHEDULE_LOCK = "./config/schedules.json.lock"

def load_users():
    #lock = FileLock(LOCK_FILE)
    print(f"Skipping lock for loading users from {USERS_FILE}")
    #with lock:  # Only one process at a time
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
    def __init__(self, id, username, password, first_name, last_name, date_registered, email=None, auth_provider=None, role="user", **kwargs):
        self.id = id
        self.username = username
        self.password = password  # NOTE: hash in real life
        self.first_name = first_name
        self.last_name = last_name
        self.date_registered = date_registered
        self.email = email
        self.auth_provider = auth_provider
        self.role = role
    
@login_manager.user_loader
def load_user(user_id):
    if request.path == "/metrics":
        return None # Don't bother hitting the disk/lock for metrics requests since they don't need user info and we want to keep them super fast and avoid lock contention with the regular app routes.
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
    print("load_schedules called")
    # No lock needed: writes use atomic os.rename() so readers never see a
    # partial file. A missing file just returns [].
    if os.path.exists(sched_file):
        try:
            with open(sched_file, "r") as f:
                print(f"loading schedule file = {sched_file}")
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print(f"load_schedules: could not parse {sched_file}, returning []")
            return []
    return []


def _write_schedules_atomic(sched_file, schedules):
    """Write schedules to sched_file via a temp file + rename so reads never
    see a partial write (os.rename is atomic on Linux/macOS)."""
    import tempfile
    dir_ = os.path.dirname(sched_file) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(schedules, f, indent=4)
        os.replace(tmp_path, sched_file)   # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def clear_schedule_file(sched_file, filename, userlogin):
    if not filename:
        return jsonify({"success": False, "message": "Filename missing"}), 400

    schedules = load_schedules(sched_file)
    new_schedules = [s for s in schedules if s["filename"] != filename or s["userlogin"] != userlogin]
    _write_schedules_atomic(sched_file, new_schedules)
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


def prune_orphaned_docs(userlogin, removed_source_url):
    """Remove docs whose last referrer was removed_source_url.

    Called when a source sheet/Excel is removed from the sync list. URLs still
    referenced by at least one other source are kept (referrer entry removed but
    doc entry stays). Only when referrers becomes empty is the doc fully deleted.
    Also handles migration of old flat referrer_url/referrer_file fields.
    """
    json_filename = f"./config/{userlogin}/docs.json"
    docslist = load_shared_files(json_filename)
    if not docslist:
        return

    entries = docslist.get("docs", [])
    updated = []
    orphaned_urls = []

    for entry in entries:
        referrers = entry.get("referrers")

        # Migrate old-style flat fields on the fly
        if referrers is None and "referrer_url" in entry:
            referrers = [{"source_url": entry.pop("referrer_url"),
                          "source_file": entry.pop("referrer_file", "")}]

        if referrers is None:
            referrers = []

        new_referrers = [r for r in referrers if r.get("source_url") != removed_source_url]

        if new_referrers:
            entry["referrers"] = new_referrers
            entry.pop("referrer_url", None)
            entry.pop("referrer_file", None)
            updated.append(entry)
        else:
            orphaned_urls.append(entry["url"])
            print(f"prune_orphaned_docs: {entry['url']} is now orphaned, will be removed")

    if len(updated) == len(entries) and not orphaned_urls:
        return  # nothing changed

    docslist["docs"] = updated
    try:
        with open(json_filename, 'w') as f:
            json.dump(docslist, f, indent=2)
        print(f"prune_orphaned_docs: pruned {len(orphaned_urls)} orphaned URLs for source {removed_source_url}")
    except Exception as e:
        print(f"prune_orphaned_docs: error writing {json_filename}: {e}")
        return

    for url in orphaned_urls:
        safe_url = url.replace("/", "_").replace(":", "_")
        vector_dir = f"./config/{userlogin}/vectors/{safe_url}"
        if os.path.exists(vector_dir):
            shutil.rmtree(vector_dir)
            print(f"prune_orphaned_docs: deleted vector dir {vector_dir}")
        redis_key = f"user:{userlogin}:url:{url}"
        redis_client.delete(redis_key)
        print(f"prune_orphaned_docs: deleted Redis key {redis_key}")


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
            "date_registered": datetime.utcnow().isoformat(),
            "role": "user"
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
        if not current_user.is_authenticated:
            return redirect(url_for("home"))
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
    SCOPES_DRIVE_CONNECT,
)

from googleapiclient.discovery import build

@app.route("/auth/google")
def auth_google():
    """Google Sign-In as the primary app login — no prior login required."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    global callback_host
    redirectpath = callback_host or "https://trinket.cloudcurio.com"

    flow = get_google_flow("__login__", redirectpath)
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    session["google_oauth_state"] = state
    session["google_auth_flow"] = "login"
    return redirect(auth_url)


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

    print(f"/google/login about to call get_google_flow({userlogin},{redirectpath})")
    flow = get_google_flow(userlogin, redirectpath, scopes=SCOPES_DRIVE_CONNECT)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent"
    )
    session["google_oauth_state"] = state
    session["google_user"] = userlogin
    session["google_auth_flow"] = "drive"   # prevent stale "login" flag from /auth/google
    print(f"🌐 Redirecting {userlogin} to Google OAuth...")
    return redirect(auth_url)


@app.route("/google/callback")
def google_callback():
    global callback_host
    redirectpath = callback_host or "https://trinket.cloudcurio.com"

    auth_flow = session.pop("google_auth_flow", "drive")

    if auth_flow == "login":
        # ── App sign-in via Google ──────────────────────────────────────────
        flow = get_google_flow("__login__", redirectpath)
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials

        svc = build("oauth2", "v2", credentials=creds)
        info = svc.userinfo().get().execute()
        email = info.get("email", "")
        name = info.get("name", email)

        if not email:
            return "Could not retrieve email from Google", 400

        users = load_users()
        existing = next(
            (u for u in users if u.get("email") == email or u.get("username") == email),
            None
        )
        if not existing:
            parts = name.split(" ", 1)
            existing = {
                "id": str(len(users) + 1),
                "username": email,
                "password": None,
                "first_name": parts[0],
                "last_name": parts[1] if len(parts) > 1 else "",
                "email": email,
                "date_registered": datetime.utcnow().isoformat(),
                "auth_provider": "google",
                "role": "user",
            }
            users.append(existing)
            save_users(users)
            print(f"✅ Auto-created Google-auth user: {email}")
        elif not existing.get("email"):
            existing["email"] = email
            save_users(users)
            print(f"✅ Backfilled email for existing user: {existing['username']}")

        login_user(User(**existing))
        print(f"✅ Google sign-in: logged in as {email}")
        return redirect(url_for("index"))

    else:
        # ── Drive connection for already-logged-in user ─────────────────────
        userlogin = session.get("google_user")
        if not userlogin:
            return "Missing session user", 400

        print(f"/google/callback (drive-connect) userlogin={userlogin}")
        flow = get_google_flow(userlogin, redirectpath, scopes=SCOPES_DRIVE_CONNECT)
        flow.fetch_token(authorization_response=request.url)
        save_google_token(flow.credentials, userlogin)

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


@app.route("/google/access_token")
@login_required
def google_access_token():
    userlogin = current_user.username
    creds = load_google_token(userlogin)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            save_google_token(creds, userlogin)
        else:
            return jsonify({"error": "Not authenticated with Google"}), 401
    return jsonify({"access_token": creds.token})


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
REDIRECT_URI = f"{callback_host.rstrip('/')}{REDIRECT_PATH}"

print(f"callback_host provided as: {callback_host}")
print(f"REDIRECT_URI = {REDIRECT_URI}")


delegated_auth = False  # set to False to use app-only auth (no user context)


#if args.auth_mode and "user_auth" in args.auth_mode:
if "user_auth" in AUTH:
    print(f"detected argument '{AUTH}' so will use delegated authorization instead of app auth flow")
    delegated_auth = True
    CLIENT_ID = os.environ["CLIENT_ID2"]
    CLIENT_SECRET = os.environ["CLIENT_SECRET2"] # only needed for app-only auth. Not used for delegated user auth.
    TENANT_ID = os.environ["TENANT_ID"]
    # Do NOT include reserved scopes here — MSAL adds them automatically
    SCOPES = ["User.Read", "Files.ReadWrite.All", "Sites.Read.All", "Chat.Read"]
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
'''import os



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
'''


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
@login_required
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
        # Skip MSAL entirely if the user has no Azure token cache (e.g. Google-only users).
        # _build_msal_app() hits the Azure AD discovery endpoint on every call, so avoid
        # it when there is nothing to refresh.
        _token_cache_path = user_config_file(userlogin, "token_cache.json")
        if not os.path.exists(_token_cache_path):
            print(f"No Azure token cache found for {userlogin}, skipping MSAL token refresh")
            session["is_logged_in"] = False
        else:
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
                    session["access_token"] = result["access_token"]
                    # id_token_claims is only present on interactive login, not silent refresh.
                    # Fall back to the MSAL account username so auth_username is never blank.
                    id_claims = result.get("id_token_claims")
                    if id_claims:
                        session["user"] = id_claims
                        auth_user_email = id_claims.get("preferred_username", "")
                        auth_user_name = id_claims.get("name", "")
                    else:
                        auth_user_email = accounts[0].get("username", "")
                        auth_user_name = accounts[0].get("name", auth_user_email)
                        if not session.get("user"):
                            session["user"] = {"preferred_username": auth_user_email, "name": auth_user_name}
                    print(f"auth_user_email={auth_user_email}, auth_user_name={auth_user_name}")
                    print(f"%%%%%%%%% session = {session}")

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

    LLMCONFIG_FILE = user_config_file(current_user.username, "llmconfig.json")
    if not os.path.exists(LLMCONFIG_FILE):
        with open(LLMCONFIG_FILE, "w") as f:
            print(f"creating LLM config settings file = {LLMCONFIG_FILE}")
            json.dump({}, f)
    else:
        print(f"LLM config settings file already exists {LLMCONFIG_FILE}")


    # Load saved value
    #ENV_PATH_USER = os.path.join(os.path.dirname(__file__), "config", f"env.{userlogin}")
    ENV_PATH_USER = user_config_file(current_user.username, "env")

    foo_values = {}
    foo_values["jira_url"] = read_env("JIRA_URL", ENV_PATH_USER)
    foo_values["jira_user"] = read_env("JIRA_EMAIL", ENV_PATH_USER)
    foo_values["jira_token"] = read_env("JIRA_API_TOKEN", ENV_PATH_USER)
    foo_values["confluence_url"] = read_env("CONFLUENCE_URL", ENV_PATH_USER)
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
    shared_files_sharepoint = load_shared_files(user_config_file(userlogin, "shared_files_sharepoint.json"))
    shared_files_google = load_shared_files(user_config_file(userlogin, "shared_files_google.json"))
    shared_files_local = load_shared_files(user_config_file(userlogin, "shared_files_local.json"))
    docs_list = load_shared_files(f"./config/{userlogin}/docs.json")

    print(f"loaded docs_list = {docs_list['docs'] if docs_list else 'None'}")

                                            

    foo_values["mcp_api_key"] = read_mcp_key(current_user.username)  #using foo_values to avoid passing yet another var to form.html
                               

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
                #schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)           
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

    
    print(f"Sharepoint Authorization status: {session.get('is_logged_in', False)}")


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
                           docs_list = docs_list["docs"] if docs_list else [],
                           logged_in=session.get("is_logged_in", False),
                           google_logged_in=google_logged_in,
                           folder_tree=folder_tree,
                           schedule_dict=schedule_dict,
                           username=userlogin,
                           auth_username=auth_user_email,
                           google_username=google_user_email,
                           llm_default=llm_model,
                           is_admin=(current_user.role == "admin")
                           )



@app.route("/logout_sharepoint", methods=["POST"])
@login_required
def logout_sharepoint():
    #global logged_in
    userlogin = current_user.username
    print("recvd /logout_sharepoint endpoint called")
    #if session['logged_in'] == True:
    token_file = user_config_file(userlogin, "token_cache.json")
    print(f"Revoking sharepoint access token for user={userlogin} token_file={token_file}")

    if os.path.exists(token_file):
        os.remove(token_file)
        print(f"Deleted token file: {token_file}")
    else:
        print(f"No token file {token_file} found for user={userlogin}")
    session["is_logged_in"] = False
  
    # Microsoft logout endpoint (kills AAD session cookies)
    ms_logout_url = "https://login.microsoftonline.com/common/oauth2/v2.0/logout"

    # After logout, redirect back to your app
    post_logout_redirect = url_for('index', section="section2", _external=True)

    # Redirect user through Microsoft logout then back to your app
    return redirect(f"{ms_logout_url}?post_logout_redirect_uri={post_logout_redirect}")


from flask import Flask, request, jsonify

@app.route("/save_jira", methods=["POST"])
@login_required
def save_jira():
    data = request.get_json()
    jira_url = data.get("jira_url", "")
    jira_user = data.get("jira_user", "")
    jira_token = data.get("jira_token", "")
    confluence_url = data.get("confluence_url", "")

    userlogin = current_user.username
    ENV_PATH_USER = user_config_file(userlogin, "env")
    print(f"Saving new .env values jira_url={jira_url}, jira_user={jira_user}, confluence_url={confluence_url}")
    write_env("JIRA_URL", jira_url, ENV_PATH_USER)
    write_env("JIRA_EMAIL", jira_user, ENV_PATH_USER)
    write_env("JIRA_API_TOKEN", jira_token, ENV_PATH_USER)
    write_env("CONFLUENCE_URL", confluence_url, ENV_PATH_USER)

    return jsonify({"success": True, "message": "Jira settings updated successfully"})


@app.route("/setmodel", methods=["POST"])
@login_required
def setmodel():
    print("/setmodel endpoint called")
    data = request.get_json()
    #llm_model = data.get("model")

    llm_model = data.get("llm_model")
    openai_token = data.get("openai_token")

    if not llm_model:
        return "LLM model value not received", 400
    
    print(f"/setmodel setting model to {llm_model}")

    LLMCONFIG_FILE = user_config_file(current_user.username, "llmconfig.json")
     # Ensure config folder exists
    os.makedirs(os.path.dirname(LLMCONFIG_FILE), exist_ok=True)

    # Save to JSON file
    with open(LLMCONFIG_FILE, 'w') as f:
        json.dump({"model": llm_model}, f, indent=4)

    write_env("OPENAI_API_KEY", openai_token,ENV_PATH)    
    load_dotenv(dotenv_path=ENV_PATH)

        
    return jsonify({"success": True, "message": "LLM Model updated successfully"})


@app.route("/getmodel", methods=["GET"])
@login_required
def getmodel():
    LLMCONFIG_FILE = user_config_file(current_user.username, "llmconfig.json")
    config = load_llm_config(LLMCONFIG_FILE)
    model = config.get("model", "Local") if config else "Local"
    return jsonify({"default_model": model})


@app.route("/add_sharepoint", methods=["POST"])
@login_required
def add_sharepoint():
    new_val = request.form.get('bar_value', '').strip()
    new_val = unquote(new_val);      # remove %20, etc
    userlogin = current_user.username
    print(f"/add_sharepoint endpoint called with new_val = {new_val} by {userlogin}")
    shared_files_sharepoint= load_shared_files(user_config_file(current_user.username, "shared_files_sharepoint.json"))

    if new_val:
        # Normalize: ensure file extension sits before # (e.g. "file#Sheet.xlsx" → "file.xlsx#Sheet")
        if '#' in new_val:
            _before, _after = new_val.split('#', 1)
            _basename = _before.split('/')[-1].split('\\')[-1]
            if '.' not in _basename and '.' in _after:
                _ext_idx = _after.rfind('.')
                new_val = _before + _after[_ext_idx:] + '#' + _after[:_ext_idx]
                print(f"Normalized SharePoint URL to: {new_val}")
        print(f"add_sharepoint with shared_files_sharepoint={new_val}")
        if not is_location_in_shared_files(new_val, shared_files_sharepoint):
            # Add to shared_files_google list
            from datetime import date
            shared_files_sharepoint.append({
                "location": new_val,
                "user": current_user.username,
                "datetime": datetime.now().isoformat()            })            
            print(f"Added to shared_files_sharepoint: {shared_files_sharepoint[-1]}")

          # Save to JSON file
            json_filename = user_config_file(current_user.username, "shared_files_sharepoint.json")
            save_shared_files(json_filename, shared_files_sharepoint)
            print(f"Saved shared_files_sharepoint to {json_filename}")

        else:
            print(f"{new_val} already present so no action needed")
            return jsonify({"success": True, "message": "File already present, no action needed"})
        return jsonify({"success": True, "message": "Sharepoint file added successfully"})
    return jsonify({"success": False, "message": "No file URL provided"})

@app.route("/remove_sharepoint", methods=["POST"])
@login_required
def remove_sharepoint():
    to_remove = request.form.get('remove_bar')
    userlogin = current_user.username
    print(f"remove_sharepoint called with {to_remove}")

    # Remove from shared_files_google list (independent check)
    json_filename = user_config_file(userlogin, "shared_files_sharepoint.json")
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

            # Remove any docs whose only referrer was this source file
            prune_orphaned_docs(userlogin, to_remove)

            # if file was scheduled for resync then remove from schedule.json
            clear_schedule_file(user_sched_file, to_remove, userlogin)
            #schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)
            return jsonify({"success": True, "message": "Sharepoint file removed successfully"})
        else:
                # this shoudl never happen because only way to trigger remove is from a listed file on gui
            print(f"{to_remove} not found in shared_files_sharepoint, no action taken")
    
    return jsonify({"success": False, "message": "Sharepoint file collection is empty"})


@app.route("/add_local", methods=["POST"])
@login_required
def add_local():
    new_val = request.form.get('local_value', '').strip()
    userlogin = current_user.username
    print(f"/add_local endpoint called with new_val = {new_val} by {userlogin}")
    shared_files_local = load_shared_files(user_config_file(current_user.username, "shared_files_local.json"))

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
            json_filename = user_config_file(current_user.username, "shared_files_local.json")
            save_shared_files(json_filename, shared_files_local)
            print(f"Saved shared_files_local to {json_filename}")

        else:
            print(f"{new_val} already present so no action needed")
            return jsonify({"success": True, "message": "File already present, no action needed"})
        return jsonify({"success": True, "message": "Local file added successfully"})
    return jsonify({"success": False, "message": "No file provided"})



@app.route("/remove_local", methods=["POST"])
@login_required
def remove_local():
    to_remove = request.form.get('remove_local')
    userlogin = current_user.username
    print(f"remove_local called with {to_remove}")

    # Remove from shared_files_google list (independent check)
    json_filename = user_config_file(userlogin, "shared_files_local.json")
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
            #schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)           
            return jsonify({"success": True, "message": "Local file removed successfully"})
        else:
            print(f"{to_remove} not found in file collection, no action taken")
    
    return jsonify({"success": False, "message": "Local file collection is empty"})


@app.route("/schedule", methods=["POST"])
@login_required
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

    print(f"saving to schedule file = {user_sched_file}")
    _write_schedules_atomic(user_sched_file, schedules)

    # update the scheduled jobs
    global delegated_auth
    #schedule_jobs(scheduler, user_sched_file, delegated_auth, filename, userlogin)

    return jsonify({"success": True, "message": "Schedule saved successfully"})



@app.route("/schedule/clear", methods=["POST"])
@login_required
def clear_schedule():
    data = request.get_json()
    filename = data.get("filename")

    if not filename:
        return jsonify({"success": False, "message": "Filename missing"}), 400

    # Load existing schedules
    user_sched_file = SCHEDULE_FILE #f"./logs/{userlogin}/{SCHEDULE_FILE}"
    schedules = []

    schedules = load_schedules(user_sched_file)  # must load for all userlogins
    schedules = [s for s in schedules if s["filename"] != filename]

    print(f"saving schedule file = {user_sched_file}")
    _write_schedules_atomic(user_sched_file, schedules)

    return jsonify({"success": True})



# Add this import at the top of your file
from task_queue import task_queue

# ... rest of your existing imports and code ...


# ============================================================================
# TASK QUEUE ROUTES - Add these new routes
# ============================================================================

'''@app.route("/tasks/status", methods=["GET"])
@login_required
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
'''

from celery.result import AsyncResult
from vector_worker import app as celery_app
from vector_worker import resync_task_worker


@app.route("/tasks/status", methods=["GET"])
def get_task_status():
    global metrics_resync_errors
    print("/tasks/status endpoint called")
    username = current_user.username if current_user.is_authenticated else "anonymous"
    task_ids = redis_client.smembers(f"celery:tasks:{username}")
    print(f"Retrieved task IDs from Redis for user={username}: {task_ids}")

    tasks = []

    status = {
        "total": 0,
        "pending": 0,
        "running": 0,
        "success": 0,
        "failure": 0
    }

    for task_id in task_ids:
        #task_id = task_id.decode()   
        result = AsyncResult(task_id, app=celery_app)
        state = result.state

        task_info = {
            "task_id": task_id,
            "status": state,
            "started_at": None,
            "completed_at": None,
        }

        if state == "SUCCESS":
            task_result = result.result or {}
            task_info["result"] = task_result
            task_info["started_at"] = task_result.get("started_at") if isinstance(task_result, dict) else None
            task_info["completed_at"] = task_result.get("completed_at") if isinstance(task_result, dict) else None
            status["success"] += 1

        elif state == "FAILURE":
            task_info["error"] = str(result.info)
            if result.date_done:
                task_info["completed_at"] = result.date_done.isoformat()
            status["failure"] += 1
            metrics_resync_errors += 1    # ← add this here to increment error counter for metrics

        elif state in ("PENDING", "RECEIVED"):
            status["pending"] += 1

        elif state == "STARTED":
            if isinstance(result.info, dict):
                task_info["started_at"] = result.info.get("started_at")
            status["running"] += 1
            state = "RUNNING"  # normalize state name for frontend
            task_info["status"] = state

        # remove the task from celery redis queue
        if state in ("SUCCESS", "FAILURE"):
            redis_client.srem(f"celery:tasks:{username}", task_id)
            print(f"Removed task_id={task_id} from Redis tracking set for user={username} after completion with state={state}")

        print(f"Task {task_id} is in state {state} with info: {result.info}")
        tasks.append(task_info)
        print(f"Appended task info: {task_info} to tasks collection")
        status["total"] += 1

    print(f"tasks status compiled: {tasks}")
    
    return jsonify({
        "success": True,
        "tasks": tasks,
        "queue_status": status
    })


'''@app.route("/tasks/cancel/<task_id>", methods=["POST"])
@login_required
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
'''
@app.route("/tasks/cancel/<task_id>", methods=["POST"])
def cancel_task_route(task_id):
    app.control.revoke(task_id, terminate=True)
    return jsonify({"success": True, "message": "Task revoked"})


@app.route("/tasks/clear", methods=["POST"])
@login_required
def clear_old_tasks():
    """Clear completed tasks older than 1 hour"""
    cleared = task_queue.clear_completed_tasks(older_than_minutes=60)
    return jsonify({"success": True, "cleared": cleared})



# ADD THIS NEW ROUTE INSTEAD:
'''@app.route("/resync_sharepoint", methods=["POST"])
@login_required
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
'''

import redis
import os

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

print(f"Connecting to Redis at {REDIS_HOST} for task tracking")

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=6379,
    db=2,              # pick a DB just for task tracking (not Celery broker/backend)
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5
)

import time
import platform
#from datetime import datetime

# At module level, add these counters (put near the redis_client definition)
_app_start_time = time.time()
metrics_resync_total = 0       # increment in resync_sharepoint()
metrics_resync_errors = 0      # increment on Celery FAILURE detection


def metrics_foo():
    # Bypass everything else
    print("/metrics endpoint called - returning OK for health check")
    return "OK", 200

@app.route("/metrics")
@csrf.exempt
def metrics():
    """
    Service observability endpoint.
    Returns application metrics in JSON (default) or Prometheus text format (?format=prometheus).

    Covers:
      - Uptime & process info
      - Celery task queue state (via Redis)
      - Registered users & tracked files
      - Redis connectivity
      - Resync operation counters
    """
    output_format = request.args.get("format", "json")

    # ------------------------------------------------------------------
    # 1. Uptime
    # ------------------------------------------------------------------
    uptime_seconds = time.time() - _app_start_time

    # read the contents of ./build_date file_handler
    try:
        with open("/build_date", "r") as f:
            build_date = f.read().strip()
    except FileNotFoundError:
        build_date = "Unknown"

    # ------------------------------------------------------------------
    # 2. Celery task queue state (read from Redis tracking set)
    # ------------------------------------------------------------------
    task_counts = {"pending": 0, "running": 0, "success": 0, "failure": 0, "total": 0}
    redis_ok = False
    redis_latency_ms = None

    try:
        t0 = time.time()
        redis_client.ping()
        redis_latency_ms = round((time.time() - t0) * 1000, 2)
        redis_ok = True

        # Aggregate task IDs across all per-user sets for metrics
        user_task_keys = redis_client.keys("celery:tasks:*")
        task_ids = set()
        for key in user_task_keys:
            task_ids.update(redis_client.smembers(key))
        task_counts["total"] = len(task_ids)

        for task_id in task_ids:
            try:
                result = AsyncResult(task_id, app=celery_app)
                state = result.state
                if state in ("PENDING", "RECEIVED"):
                    task_counts["pending"] += 1
                elif state == "STARTED":
                    task_counts["running"] += 1
                elif state == "SUCCESS":
                    task_counts["success"] += 1
                elif state == "FAILURE":
                    task_counts["failure"] += 1
            except Exception:
                pass  # stale task ID — ignore

    except Exception as e:
        app.logger.warning(f"/metrics: Redis unavailable: {e}")

    # ------------------------------------------------------------------
    # 3. Registered users & tracked files
    # ------------------------------------------------------------------
    users = []
    total_sharepoint_files = 0
    total_google_files = 0
    total_local_files = 0

    
    try:
        users = load_users()
        for u in users:
            uname = u.get("username", "")
            sp = load_shared_files(user_config_file(uname, "shared_files_sharepoint.json"))
            goog = load_shared_files(user_config_file(uname, "shared_files_google.json"))
            loc = load_shared_files(user_config_file(uname, "shared_files_local.json"))
            total_sharepoint_files += len(sp)
            total_google_files += len(goog)
            total_local_files += len(loc)
    except Exception as e:
        app.logger.warning(f"/metrics: error reading user/file data: {e}")
    
    # ------------------------------------------------------------------
    # 4. Active schedules
    # ------------------------------------------------------------------
    total_schedules = 0
    try:
        schedules = load_schedules(SCHEDULE_FILE)
        total_schedules = len(schedules)
    except Exception:
        pass
    

    # ------------------------------------------------------------------
    # 5. Log directory size (bytes)
    # ------------------------------------------------------------------
    log_dir_bytes = 0
    try:
        for dirpath, _, filenames in os.walk("./logs"):
            for fname in filenames:
                fp = os.path.join(dirpath, fname)
                log_dir_bytes += os.path.getsize(fp)
    except Exception:
        pass
    

    # ------------------------------------------------------------------
    # Build response
    # ------------------------------------------------------------------
    data = {
        "build_date": build_date
        }
    
    data = {
        "build_date": build_date,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(uptime_seconds, 1),
        "process": {
            "pid": os.getpid(),
            "python": platform.python_version(),
            "host": platform.node(),
        },
        "redis": {
            "ok": redis_ok,
            "latency_ms": redis_latency_ms,
        },
        "celery_tasks": task_counts,
        "resyncs": {
            "total_triggered": metrics_resync_total,
            "total_errors": metrics_resync_errors,
        },
        "users": {
            "registered": len(users),
        },
        "tracked_files": {
            "sharepoint": total_sharepoint_files,
            "google": total_google_files,
            "local": total_local_files,
            "total": total_sharepoint_files + total_google_files + total_local_files,
        },
        "schedules": {
            "active": total_schedules,
        },
        "logs": {
            "dir_bytes": log_dir_bytes,
        },
    }

    if output_format == "prometheus":
        # Prometheus text exposition format
        #lines = [f"# Application metrics for Prometheus scraping - build date: {build_date}"]

        lines = [
            f"# Application metrics for Prometheus scraping - build date: {build_date}",
            f"# HELP app_uptime_seconds Seconds since application start",
            f"# TYPE app_uptime_seconds gauge",
            f"app_uptime_seconds {data['uptime_seconds']}",

            f"# HELP redis_ok 1 if Redis is reachable, 0 otherwise",
            f"# TYPE redis_ok gauge",
            f"redis_ok {1 if redis_ok else 0}",

            f"# HELP redis_latency_ms Redis ping latency in milliseconds",
            f"# TYPE redis_latency_ms gauge",
            f"redis_latency_ms {redis_latency_ms if redis_latency_ms is not None else -1}",

            f"# HELP celery_tasks_total Tasks in Redis tracking set by state",
            f"# TYPE celery_tasks_total gauge",
            f'celery_tasks_total{{state="pending"}} {task_counts["pending"]}',
            f'celery_tasks_total{{state="running"}} {task_counts["running"]}',
            f'celery_tasks_total{{state="success"}} {task_counts["success"]}',
            f'celery_tasks_total{{state="failure"}} {task_counts["failure"]}',

            f"# HELP resync_triggered_total Total resync tasks dispatched since start",
            f"# TYPE resync_triggered_total counter",
            f"resync_triggered_total {metrics_resync_total}",

            f"# HELP resync_errors_total Total resync tasks that ended in FAILURE",
            f"# TYPE resync_errors_total counter",
            f"resync_errors_total {metrics_resync_errors}",
            
            f"# HELP registered_users_total Number of registered user accounts",
            f"# TYPE registered_users_total gauge",
            f"registered_users_total {len(users)}",

            f"# HELP tracked_files_total Files tracked by source type",
            f"# TYPE tracked_files_total gauge",
            f'tracked_files_total{{source="sharepoint"}} {total_sharepoint_files}',
            f'tracked_files_total{{source="google"}} {total_google_files}',
            f'tracked_files_total{{source="local"}} {total_local_files}',

            f"# HELP active_schedules Number of configured sync schedules",
            f"# TYPE active_schedules gauge",
            f"active_schedules {total_schedules}",
            

            f"# HELP log_dir_bytes Total bytes consumed by the logs directory",
            f"# TYPE log_dir_bytes gauge",
            f"log_dir_bytes {log_dir_bytes}",
        ]

        return "\n".join(lines) + "\n", 200, {"Content-Type": "text/plain; version=0.0.4"}

    return jsonify(data)




@app.route("/resync_sharepoint", methods=["POST"])
def resync_sharepoint():
    """Queue a resync task (async via Celery)"""

    global metrics_resync_total, metrics_resync_errors

    val = request.form.get("resync_bar")
    user = current_user.username if current_user.is_authenticated else None

    print(f"/resync_sharepoint called with val={val}, user={user}")

    if not val:
        return jsonify({"success": False, "message": "No file specified"}), 400

    val = clean_sharepoint_url(val)

    task = resync_task_worker.delay(
        file_url=val,
        userlogin=user,
        delegated_auth=delegated_auth
    )

    metrics_resync_total += 1          # ← add this after .delay()

    task_id = task.id

    print(f"/resync_sharepoint returned taskid {task_id} to process val={val}, user={user}")

    # Store task ID in per-user Redis set for tracking, used by the /status endpoint
    redis_client.sadd(f"celery:tasks:{user}", task_id)
    redis_client.expire(f"celery:tasks:{user}", 3600)
    print(f"Stored task ID {task_id} in Redis for tracking user={user}")



    return jsonify({
        "success": True,
        "message": f"Resync started for {val}",
        "task_id": task.id
    })


@app.route("/resync_sharepoint_userlogin", methods=["POST"])
@csrf.exempt
def resync_sharepoint_userlogin():
    """
    Queue a resync with explicit userlogin.
    Does NOT rely on current_user.
    """

    filename = request.form.get("filename")
    user = request.form.get("userlogin")

    print(f"/resync_sharepoint_userlogin called with filename={filename}, user={user}")

    if not filename:
        return jsonify({"success": False, "message": "No filename provided"}), 400
    if not user:
        return jsonify({"success": False, "message": "No userlogin provided"}), 400

    cleaned = clean_sharepoint_url(filename)

    task = resync_task_worker.delay(
        file_url=cleaned,
        userlogin=user,
        delegated_auth=delegated_auth
    )

    return jsonify({
        "success": True,
        "message": "Resync triggered",
        "task_id": task.id
    })


@app.route("/resync_sharepoint_userlogin_old", methods=["POST"])
def resync_sharepoint_userlogin_old():
    """
    Queue a resync with explicit userlogin (for scheduler use).
    Does NOT rely on current_user.
    """
    filename = request.form.get("filename")
    user = request.form.get("userlogin")

    print(f"/resync_sharepoint_userlogin endpoint called with filename={filename} and user={user}")
    if not filename:
        return jsonify({"success": False, "message": "No filename provided"}), 400
    if not user:
        return jsonify({"success": False, "message": "No userlogin provided"}), 400

    cleaned = clean_sharepoint_url(filename)

    #print(f"/resync_sharepoint_userlogin called for user={user}, file={cleaned}")

    global delegated_auth
    try:
        '''# Call your existing worker function directly
        resync(
            url=cleaned,
            userlogin=userlogin,
            delegated_auth=delegated_auth
        )'''
        # Enqueue the task
        task_id = task_queue.enqueue(
            resync_task_worker,
            file_url=filename,
            userlogin=user,
            delegated_auth=delegated_auth,
            #google_user_email=google_user_email,
            user=user
        )

        print(f"Resync task queued with task_id={task_id} for file={filename} and user={user}  delegated_auth={delegated_auth} ")
        
        return jsonify({"success": True, "message": "Resync triggered"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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

@app.route("/remove_docslist", methods=["POST"])
@login_required
def remove_docslist():
    to_remove = request.form.get('remove_docslist')
    userlogin = current_user.username
    print(f"remove_docslist called with {to_remove}")

    # Remove from shared_files_google list (independent check)
    json_filename = f"./config/{userlogin}/docs.json"
    docslist = load_shared_files(json_filename)
    
    if docslist:
        original_length = len(docslist["docs"])
        
        # Filter out the entry with matching new_val and username
        docslist["docs"] = [
            entry for entry in docslist["docs"] 
            if not (entry.get('url') == to_remove)
        ]
        
        # Check if anything was removed
        if len(docslist["docs"]) < original_length:
            try:
                with open(json_filename, 'w') as f:
                    json.dump(docslist, f, indent=2)
                print(f"Removed from docslist the entry with url={to_remove}")
            except Exception as e:
                print(f"Error writing {json_filename}: {e}")
                return jsonify({"success": False, "message": f"Save error: {e}"})

            # Delete the vector directory for this URL
            safe_url = to_remove.replace("/", "_").replace(":", "_")
            vector_dir = f"./config/{userlogin}/vectors/{safe_url}"
            if os.path.exists(vector_dir):
                shutil.rmtree(vector_dir)
                print(f"Deleted vector directory: {vector_dir}")
            else:
                print(f"No vector directory found at {vector_dir}, skipping")

            # Delete the Redis state record for this URL (DB 2)
            redis_key = f"user:{userlogin}:url:{to_remove}"
            deleted = redis_client.delete(redis_key)
            print(f"Deleted Redis key {redis_key}: {deleted} key(s) removed")

            return jsonify({"success": True, "message": "RAG Document removed successfully"})
        else:
            print(f"{to_remove} not found in docslist (had {original_length} entries), no action taken")

    return jsonify({"success": False, "message": "RAG Document not found"})


@app.route("/resync_docslist", methods=["POST"])
@login_required
def resync_docslist():
    """Queue a re-embed task for a docs.json entry via the url_processing_queue."""
    url = request.form.get("resync_bar")
    userlogin = current_user.username

    print(f"/resync_docslist called with url={url}, user={userlogin}")

    if not url:
        return jsonify({"success": False, "message": "No URL specified"}), 400

    task = process_url.delay(userlogin, url, force=True)

    redis_client.sadd(f"celery:tasks:{userlogin}", task.id)
    redis_client.expire(f"celery:tasks:{userlogin}", 3600)
    print(f"/resync_docslist queued task {task.id} for url={url}, user={userlogin}")

    return jsonify({
        "success": True,
        "message": f"Resync started for {url}",
        "task_id": task.id
    })


@app.route("/sync_teams", methods=["POST"])
@login_required
def sync_teams():
    """Fetch Teams chats for the current user and write transcript files."""
    if not delegated_auth:
        return jsonify({"success": False, "message": "Teams sync requires delegated auth mode (--auth user_auth)"}), 400

    from teams_chat import fetch_and_save_teams_chats, load_teams_config

    userlogin = current_user.username
    try:
        token = get_app_token_delegated()
    except Exception as e:
        return jsonify({"success": False, "message": f"Sync Failed. Please connect to your Microsoft account"}), 401

    try:
        cfg = load_teams_config()
        stats = fetch_and_save_teams_chats(token, userlogin, cfg)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

    # Queue an embedding task for each partition file that received new content
    from vector_worker import embed_local_file
    task_ids = []
    for partition_info in stats.get("updated_partitions", {}).values():
        filepath = partition_info.get("filepath")
        if filepath:
            task = embed_local_file.delay(userlogin, filepath)
            redis_client.sadd(f"celery:tasks:{userlogin}", task.id)
            redis_client.expire(f"celery:tasks:{userlogin}", 3600)
            task_ids.append(task.id)

    return jsonify({
        "success": True,
        "total_chats": stats["total_chats"],
        "new_messages": stats["new_messages"],
        "partitions_updated": stats["partitions_updated"],
        "skipped_chats": stats["skipped_chats"],
        "partition_by": stats["partition_by"],
        "output_dir": stats["output_dir"],
        "embed_task_ids": task_ids,
    })


#--- Google Sheet routes ---
@app.route("/add_google", methods=["POST"])
@login_required
def add_google():
    # URL-paste disabled: use the Google Drive picker so drive.file scope applies
    return jsonify({"success": False, "message": "Please use the Google Drive picker to add sheets"}), 400
    new_val = request.form.get('google_value', '').strip()
    userlogin = current_user.username
    print(f"/add_google endpoint called with new_val = {new_val} by {userlogin}")
    shared_files_google = load_shared_files(user_config_file(current_user.username, "shared_files_google.json"))

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
            json_filename = user_config_file(current_user.username, "shared_files_google.json")
            save_shared_files(json_filename, shared_files_google)
            print(f"Saved shared_files_google to {json_filename}")

        else:
            print(f"{new_val} filename={fname} sheet={sheet} already present so no action needed")
            return jsonify({"success": True, "message": f"File {fname} {sheet} already present, no action needed"})
        return jsonify({"success": True, "message": f"Google Sheet {fname} {sheet} added successfully"})
    return jsonify({"success": False, "message": "No file URL provided"})


@app.route("/remove_google", methods=["POST"])
@login_required
def remove_google():
    to_remove = request.form.get('remove_google')
    userlogin = current_user.username
    print(f"remove_google called with {to_remove}")

    # Remove from shared_files_google list (independent check)
    json_filename = user_config_file(userlogin, "shared_files_google.json")
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

            # Remove any docs whose only referrer was this source file
            prune_orphaned_docs(userlogin, to_remove)

            # if file was scheduled for resync then remove from schedule.json
            clear_schedule_file(user_sched_file, to_remove, userlogin)
            #schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)
            return jsonify({"success": True, "message": "Google Sheet removed successfully"})
        else:
            print(f"{to_remove} not found in google_values, no action taken")
    
    return jsonify({"success": False, "message": "Google sheet file collection is empty"})


# ============================================================================
# BACKGROUND WORKER FUNCTION - Add this new function
# ============================================================================

'''def resync_task_worker(file_url, userlogin, delegated_auth):
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
'''


LOG_BASE_DIR = "./logs"

import re
from datetime import datetime, timezone

from flask import jsonify

@app.route("/logs")
@login_required
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
@login_required
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

# Python Flask Route
@app.route("/runlog/<userlogin>")
@login_required
def get_run_log(userlogin):
    """
    Return the run log file for the logged-in user (URL param is ignored).
    Reads from ./logs/resync.{userlogin}
    """
    userlogin = current_user.username
    print (f"/get_run_log called for userlogin={userlogin}")
    try:
        # Construct log file path with username prefix
        log_file_path = f"./logs/{userlogin}/resync.{userlogin}"

        with open(log_file_path, 'r') as f:
            log_content = f.read()

        print(f"Returning log content for userlogin={userlogin}")
        #print("log_content = " + log_content)
        return log_content, 200, {'Content-Type': 'text/plain'}
    except FileNotFoundError:
        print(f"Log file not found: {log_file_path}")
        return f"Log file not found: {log_file_path}", 404
    except Exception as e:
        print(f"Error reading log file: {str(e)}")
        return f"Error reading log file: {str(e)}", 500


# Load OAuth credentials from JSON file
CONFIG_DIR = "./config"
GOOGLE_CLIENT_SECRETS_FILE = os.path.join(CONFIG_DIR, "google_credentials.json")
with open(GOOGLE_CLIENT_SECRETS_FILE) as f:
    google_creds = json.load(f)["web"]

CLIENT_ID_PICKER = google_creds["client_id"]
CLIENT_SECRET_PICKER = google_creds["client_secret"]

REDIRECT_URI_PICKER = "http://localhost:7000/oauth2callback"
SCOPES_PICKER= ["https://www.googleapis.com/auth/drive.readonly"]


# --- Step 1: Login and consent for server-side token storage ---
@app.route("/authorize")
def authorize():
    print("/authorize called")
    print(f"CLIENT_ID_PICKER={CLIENT_ID_PICKER}\nCLIENT_SECRET_PICKER={CLIENT_SECRET_PICKER} ")
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID_PICKER,
                "client_secret": CLIENT_SECRET_PICKER,
                "redirect_uris": [REDIRECT_URI_PICKER],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES_PICKER,
    )
    flow.redirect_uri = REDIRECT_URI_PICKER
    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return redirect(auth_url)

# --- Step 2: Callback stores refresh token in session ---
@app.route("/oauth2callback")
def oauth2callback():
    print("/oauth2callback called")
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID_PICKER,
                "client_secret": CLIENT_SECRET_PICKER,
                "redirect_uris": [REDIRECT_URI_PICKER],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES_PICKER,
    )
    flow.redirect_uri = REDIRECT_URI_PICKER
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    # Store refresh token securely (database instead of session in real apps)
    session["credentials"] = creds.to_json()
    userlogin = current_user.username
    save_google_token(creds,userlogin)
    return "Authorized! You can now pick files."

# --- Step 3: When user picks file, frontend sends fileId ---
@app.route("/register_drive_file", methods=["POST"])
@login_required
def register_drive_file():
    data = request.get_json()
    file_id = data["fileId"]
    file_url = data["url"]
    file_name = data["name"]
    sheet_tab = data['sheetTab']
    print(f"/register_drive_file called with fileid:{file_id} filename:{file_name} sheet:{sheet_tab} url:{file_url}")
    session["file_id"] = file_id
    # Call your processing function
    # just do something to the file so that google sees that this client_id and scopes are associated with this file
    touch_file(data)

    # now save this in files collections
    shared_files_google = load_shared_files(user_config_file(current_user.username, "shared_files_google.json"))

    if not len(sheet_tab):
        sheet_tab = "Sheet1"

    new_val = file_url + "#" + sheet_tab
    if file_url:

        # Load credentials
        #creds = load_google_token(current_user.username)
        #result = get_google_sheet_filename(creds, new_val)
        #fname = result["filename"]
        #sheet = result['sheet_name']

        print(f"add_google with shared_files_google={new_val} filename={file_name} sheet={sheet_tab}")
       # if new_val not in shared_files_google and new_val not in bar_values and new_val not in local_file_values:
        if not is_location_in_shared_files(new_val, shared_files_google):
            # Add to shared_files_google list
            from datetime import date
            shared_files_google.append({
                "filename": file_name,
                "sheet": sheet_tab,
                "location": new_val,
                "user": current_user.username,
                "datetime": datetime.now().isoformat()            })            
            print(f"Added to shared_files_google: {shared_files_google[-1]}")

          # Save to JSON file
            json_filename = user_config_file(current_user.username, "shared_files_google.json")
            save_shared_files(json_filename, shared_files_google)
            print(f"Saved shared_files_google to {json_filename}")
            return jsonify({"success": True, "message": f"Google Sheet {file_name} {sheet_tab} added successfully"})

        else:
            print(f"{new_val} filename={file_name} sheet={sheet_tab} already present so no action needed")
            return jsonify({"success": True, "message": f"File {file_name} {sheet_tab} already present, no action needed"})
        
   
    return jsonify({"success": False, "message": "No file URL provided"})

    

#@app.route("/api/touch_file", methods=["POST"])
def touch_file(data):
    #data = request.get_json()
    file_id = data.get("fileId")
    userlogin = current_user.username
    #user_id = data.get("userId")  # however you identify users
    print(f"touch_file called data={data}")
    if not file_id: #or not user_id:
        print(f"touch_file error: missing fileid")
        return jsonify({"error": "Missing fileId"}), 400

    creds = load_google_token(userlogin)
    service = build("drive", "v3", credentials=creds)

    try:
        # Perform a harmless request — get file metadata
        metadata = service.files().get(fileId=file_id, fields="id, name, mimeType").execute()

        # Optionally rename or modify permissions, etc.
        # service.files().update(fileId=file_id, body={"name": metadata['name']}).execute()

        return jsonify({
            "message": "File linked successfully!",
            "file": metadata
        })

    except Exception as e:
        print("Drive API error:", e)
        return jsonify({"error": str(e)}), 500
    
@app.before_request
def debug():
    print(">>>", request.method, request.path)

from datetime import datetime

@app.route('/contact', methods=['POST'])
def contact():
    print("/contact endpoint called")
    data = request.get_json()
    full_name = data.get('fullName')
    email = data.get('email')
    message = data.get('message')
    print(f"/contact endpoint params name={full_name} email={email} message={message}")

    # ---- Write payload parameters to file with timestamp ----
    try:
        timestamp = datetime.utcnow().isoformat() + "Z"  # e.g. 2025-12-02T10:24:51.123Z
        with open("./config_local/contactus.messages.txt", "a", encoding="utf-8") as f:
            f.write("----- Contact Us Submission -----\n")
            f.write(f"Received: {timestamp}\n")
            f.write(f"Name: {full_name}\n")
            f.write(f"Email: {email}\n")
            f.write(f"Message: {message}\n")
            f.write("\n")
        print("Payload written to contactus.messages.txt")
    except Exception as e:
        print(f"Error writing payload to file: {e}")

    # Your processing logic here
    print("sending Contact us email...")
    send_text_email(
        "cloudcurio visitor " + email,
        "fz96tw@gmail.com",
        "info@cloudcurio.com",
        full_name + "\n\n" + email + "\n\n" + message
    )
    print("Contact us email sent")

    return jsonify({'success': True}), 200





@app.route("/contactus", methods=["POST"])
def contactus():
    full_name = request.form.get("contactus")
    email = request.form.get("feedback_email")
    message = request.form.get("feedback_message")

    print(f"/contactus endpoint called name={full_name} email={email} message={message}")

     # ---- Write payload parameters to file with timestamp ----
    try:
        timestamp = datetime.utcnow().isoformat() + "Z"  # e.g. 2025-12-02T10:24:51.123Z
        with open("./config_local/contactus.messages.txt", "a", encoding="utf-8") as f:
            f.write("----- Contact Us Submission -----\n")
            f.write(f"Received: {timestamp}\n")
            f.write(f"Name: {full_name}\n")
            f.write(f"Email: {email}\n")
            f.write(f"Message: {message}\n")
            f.write("\n")
        print("Payload written to contactus.messages.txt")
    except Exception as e:
        print(f"Error writing payload to file: {e}")

    # Your processing logic here
    print("sending Contact us email...")
    send_text_email(
        "cloudcurio visitor " + email,
        "fz96tw@gmail.com",
        "info@cloudcurio.com",
        full_name + "\n\n" + email + "\n\n" + message
    )
    print("Contact us email sent")

    return {"status": "ok"}




import json
import os
import fcntl  # POSIX file locking

def read_mcp_key(username):
    """
    Returns the MCP API key for the given username.
    If the username is not found, returns a message.
    """
    mapping_path = "./config/mcp.user.mapping.json"
    print(f"read_mcp_key called for username={username}")
    if not os.path.exists(mapping_path):
        print("MCP cache file does not exist.")
        return "Warning: MCP cache file does not exist."

    with open(mapping_path, "r") as f:
        # Acquire shared lock for reading
        fcntl.flock(f, fcntl.LOCK_SH)

        try:
            data = json.load(f)
            print(f"MCP cache data loaded: {data}")
        except json.JSONDecodeError:
            print("MCP cache file is empty or corrupted.")
            return "user not found in mcp key cache"

        fcntl.flock(f, fcntl.LOCK_UN)  # release lock

    mappings = data.get("mappings", [])
    entry = next((item for item in mappings if item.get("username") == username), None)

    if entry:
        key = entry.get("api_key")
        print(f"Found MCP API key {key} for username={username}")
        return key
    else:
        print(f"Username {username} not found in MCP cache.")
        return f"'{username}' not found in MCP key cache"

import json
import uuid
import os
import fcntl   # For POSIX file locking

def create_mcp_key(username):
    """
    Generates a new UUID API key for the given username, updates or creates
    the mapping entry in ./config/mcp.user.mapping.json, and ensures thread-
    safe and process-safe writes using file locking.
    """

    mapping_path = "./config/mcp.user.mapping.json"
    os.makedirs(os.path.dirname(mapping_path), exist_ok=True)

    # Generate new API key
    new_key = str(uuid.uuid4())

    # Ensure the file exists before locking
    if not os.path.exists(mapping_path):
        with open(mapping_path, "w") as f:
            json.dump({"mappings": []}, f, indent=2)

    # Open file for read/write & locking
    with open(mapping_path, "r+") as f:
        # Acquire exclusive lock so only one process/thread updates the file
        fcntl.flock(f, fcntl.LOCK_EX)

        # Read existing JSON safely
        try:
            data = json.load(f)
            if not isinstance(data, dict) or "mappings" not in data:
                data = {"mappings": []}
        except json.JSONDecodeError:
            # File was empty or corrupted → reset
            data = {"mappings": []}

        # Find existing entry
        entry = next((item for item in data["mappings"]
                      if item.get("username") == username), None)

        if entry:
            entry["api_key"] = new_key
        else:
            data["mappings"].append({
                "api_key": new_key,
                "username": username
            })

        # Rewrite file safely
        f.seek(0)
        f.truncate()
        json.dump(data, f, indent=2)
        f.flush()

        # Lock automatically released when file is closed

    return new_key

@app.route("/get_new_mcp_key", methods=["POST"])
@login_required
def get_new_mcp_key():
    username = request.form.get("username")
    curr_key = request.form.get("mcp_api_key")

    print(f"/get_new_mcp_key endpoint called username={username} curr_key={curr_key}")

    new_key = create_mcp_key(username)
    print(f"Generated new MCP API key for {username}: {new_key}")
    return {"status": "ok"}


# --- Step 4: Later, backend reuses refresh token to fetch file ---
'''@app.route("/download_file")
def download_file():
    if "credentials" not in session or "file_id" not in session:
        return "Not authorized or no file registered", 401

    creds = Credentials.from_authorized_user_info(eval(session["credentials"]))
    if creds.expired and creds.refresh_token:
        creds.refresh(google.auth.transport.requests.Request())

    file_id = session["file_id"]
    resp = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    if resp.status_code != 200:
        return f"Error fetching file: {resp.text}", 500

    with open("downloaded.xlsx", "wb") as f:
        f.write(resp.content)
    return "File downloaded successfully!"
'''

if __name__ == "__main__" and env == "dev":
    print(f"Starting Flask app on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)
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

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Allow HTTP for local dev

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a-very-secret-key")  # Use a real secret in production


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
REDIRECT_URI = f"http://localhost:5000{REDIRECT_PATH}"

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
    
    return cache
    

def save_cache(cache, userlogin=None):
    global TOKEN_CACHE_FILE
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
    def __init__(self, id, username, password, first_name, last_name, date_registered):
        self.id = id
        self.username = username
        self.password = password  # NOTE: hash in real life
        self.first_name = first_name
        self.last_name = last_name
        self.date_registered = date_registered

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

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        users = load_users()

        first_name = request.form["first_name"]
        last_name = request.form["last_name"]
        username = request.form["username"]
        password = request.form["password"]

        # check if username already exists
        if any(u["username"] == username for u in users):
            return "Username already taken!", 400

        new_user = {
            "id": str(len(users) + 1),
            "username": username,
            "password": password,  # hash this in production
            "first_name": first_name,
            "last_name": last_name,
            "date_registered": datetime.utcnow().isoformat()
        }

        users.append(new_user)
        save_users(users)

        print(f"✅ Registered {first_name} {last_name} ({username})")

        return redirect(url_for("index"))

    return render_template("register.html")


from flask_login import logout_user, login_required

@app.route("/logout")
@login_required
def logout():
    logout_user()          # Clears current_user
    session.clear()        # Optional: clear session data
    return redirect(url_for("home"))  # Redirect to login page


# DONT GET CONFUSED.  this route is for sharepoint authorization. Not user login to IAConnector (see /home route)
@app.route("/login")
def login():
    #global logged_in

    if delegated_auth:
        print ("/login endpoint using delegated_auth flow")
        cache = load_cache(userlogin)
        cca = _build_msal_app(cache)
        auth_url = cca.get_authorization_request_url(
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,  # url_for("authorized", _external=True)  <-------------------- 
            prompt="consent" # to make sure the user (or their admin) grants access the first time
        )
        save_cache(cache, userlogin)
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

    userlogin = current_user.username
    flow = get_google_flow(userlogin)
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

    flow = get_google_flow(userlogin)
    flow.fetch_token(authorization_response=request.url)
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
                print("found {username} {password} in users.json")
                user = User(**u)
                login_user(user)
                return redirect(url_for("index"))
    
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
LLMCONFIG_FILE = "./config/llmconfig.json"
#LOCAL_FILES = "./config/files_local.json"

# gloabals ^^^


# Ensure file exists
if not os.path.exists(SCHEDULE_FILE):
    with open(SCHEDULE_FILE, "w") as f:
        print(f"creating schedule file = {SCHEDULE_FILE}")
        json.dump([], f)
else:
    print(f"Schedule file already exists {SCHEDULE_FILE}")



delegated_auth = False  # set to False to use app-only auth (no user context)
if len(sys.argv) == 2:
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

#logged_in = False


# REDIRECT_PATH callback only required when using user-delegated auth flow.  
# not needed/used for private client auth flow
@app.route(REDIRECT_PATH)
def authorized():
    #global logged_in
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
    #global BAR_FILE
    #global GOOGLE_FILE
    #global LOCAL_FILES

    if (delegated_auth):
        print ("/ route is using delegated_auth flow")
        # Try silent token first
        print("Attempting to acquire token silently...")
        cache = load_cache(userlogin)
        print("Loaded cache, checking for accounts...")
        cca = _build_msal_app(cache)
        accounts = cca.get_accounts()
        if accounts:
            print(f"Found {len(accounts)} accounts in token cache")
            result = cca.acquire_token_silent(SCOPES, account=accounts[0])
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
            json.dump([], f)
    else:
        print(f"Schedule file already exists {user_sched_file}")

    if not os.path.exists(LLMCONFIG_FILE):
        with open(LLMCONFIG_FILE, "w") as f:
            print(f"creating LLM config settings file = {LLMCONFIG_FILE}")
            json.dump([], f)
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

    '''# Extract text between the first pair of double quotes in each line
    foo_lines = [re.search(r'"(.*?)"', line).group(1) if re.search(r'"(.*?)"', line) else "" for line in foo_lines]

    if len(foo_lines) >= 3:
        foo_values = {
            "jira_url": foo_lines[0],
            "jira_user": foo_lines[1],
            "jira_token": foo_lines[2],
        }
    '''

 
    if delegated_auth:
        BAR_FILE = f"./config/.bar_{userlogin}"
        LOCAL_FILES = f"./config/local_files_{userlogin}"
        GOOGLE_FILE = f"./config/.google_{userlogin}"
        print(f"using delegated auth so BAR_FILE = {BAR_FILE}, LOCAL_FILES = {LOCAL_FILES}, GOOGLE_FILE = {GOOGLE_FILE}")
   
    #bar_values = read_file_lines(BAR_FILE)
    bar_values = get_bar_values(userlogin)

    print(f"/ route loaded bar_values = {bar_values}")

    #local_file_values = read_file_lines(LOCAL_FILES)
    local_file_values = get_local_values(userlogin)
    print(f"/ route loaded local_file_values = {local_file_values}")    

    #google_values = read_file_lines(GOOGLE_FILE)
    google_values = get_google_values(userlogin)

    print(f"/ route loaded google_values = {google_values}")

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




    auth_user_info = session.get("user")
    if auth_user_info:
        auth_user_email = auth_user_info.get("preferred_username")
        auth_user_name = auth_user_info.get("name")
        print(f"auth_user_info found in session, user = {auth_user_name}, email= {auth_user_email}")
    else:
        print("No auth_user_info found in session!")


    return render_template('form.html',
                           banner_path=BANNER_PATH,
                           foo_values=foo_values,
                           bar_values=bar_values,
                           google_values=google_values,
                           local_values=local_file_values,
                           logged_in=session["is_logged_in"],
                           google_logged_in=google_logged_in,
                           folder_tree=folder_tree,
                           schedule_dict=schedule_dict,
                           username=userlogin,
                           auth_username=f"{auth_user_email}",
                           google_username=google_user_email,
                           llm_default=llm_model)



@app.route("/logout_sharepoint", methods=["POST"])
def logout_sharepoint():
    #global logged_in
    userlogin = current_user.username
    print("recvd /logout_sharepoint endpoint called")
    if session == True:
        print(f"Revoking sharepoint access token for user={userlogin}")
        token_file = f"./config/token_cache_{userlogin}.json"
    
        if os.path.exists(token_file):
            os.remove(token_file)
            print(f"Deleted token file: {token_file}")
            #logged_in = False
            session["is_logged_in"] = False
        else:
            print(f"No token file found for user={userlogin}")

  
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
    BAR_FILE = f"./config/.bar_{current_user.username}"
    bar_values = get_bar_values(current_user.username)
    local_file_values = get_local_values(current_user.username)
    google_values = get_google_values(current_user.username)    
    userlogin = current_user.username
    print(f"add_sharepoint called with {new_val} for user {current_user.username} into BAR_FILE={BAR_FILE}")
    print(f"current bar_values = {bar_values}")
    if new_val:
        print(f"add_bar with bar_value={new_val}")
        if new_val not in bar_values and new_val not in local_file_values and new_val not in google_values:
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


@app.route("/remove_sharepoint", methods=["POST"])
def remove_sharepoint():
    to_remove = request.form.get('remove_bar')
    userlogin = current_user.username
    BAR_FILE = f"./config/.bar_{current_user.username}"
    bar_values = get_bar_values(current_user.username)
    print(f"remove_bar called with {to_remove} for user {userlogin} from {BAR_FILE}")
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
        


@app.route("/add_local", methods=["POST"])
def add_local():
    new_val = request.form.get('local_value', '').strip()
    local_file_values = get_local_values(current_user.username)
    if new_val:
        print(f"add_local with local_value={new_val} for user {current_user.username}")
        if new_val not in local_file_values:
            container_val = map_windows_path_to_container(new_val)
            local_file_values.append(container_val)
            #write_file_lines(LOCAL_FILES, local_file_values)   
            save_local_values(current_user.username, local_file_values)  
            print(f"{new_val} added to local_file_values as {container_val} for user {current_user.username}")             
        else:
            print(f"{new_val} already present so no action needed")
            return jsonify({"success": True, "message": "File already present, no action needed"})
    #return redirect(url_for('index', section="local"))
    return jsonify({"success": True, "message": "File added successfully"})


@app.route("/remove_local", methods=["POST"])
def remove_local():
    to_remove = request.form.get('remove_local')
    userlogin = current_user.username
    #LOCAL_FILES = f"./config/files_local_{current_user.username}.json"
    local_file_values = get_local_values(current_user.username)
    print(f"remove_local called with {to_remove}")
    if to_remove in local_file_values:
        print(f"{to_remove} found and will be removed")
        local_file_values.remove(to_remove)
        #write_file_lines(LOCAL_FILES, local_file_values)
        save_local_values(userlogin, local_file_values)
        # if file was scheduled for resync then remove from schedule.json 
        clear_schedule_file(user_sched_file, to_remove, userlogin) 
        schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)           
        return jsonify({"success": True, "message": "File removed successfully"})
    else:
        print(f"{to_remove} not found in collection , no action taken")
    #return redirect(url_for('index', section="local"))
    return jsonify({"success": False, "message": "File not found"})


@app.route("/schedule", methods=["POST"])
def schedule_file():
    filename = request.form.get("filename")
    time = request.form.get("time")
    interval = request.form.get("interval")
    mode = request.form.get("mode")  # <-- this will be "hourly", "daily", or "weekly", or None if not selected
    days = request.form.getlist("days")  # ["mon", "wed", "fri"]

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
    schedule_jobs(scheduler, user_sched_file, delegated_auth, userlogin, delegated_auth, google_user_email)

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
        google_user_email=google_user_email,
        user=user
    )

    print(f"Resync task queued with task_id={task_id} for file={val} and user={user}")
    
    return jsonify({
        "success": True,
        "message": f"Resync started for {val}",
        "task_id": task_id
    })


#--- Google Sheet routes ---
@app.route("/add_google", methods=["POST"])
def add_google():
    new_val = request.form.get('google_value', '').strip()
    #GOOGLE_FILE = f"./config/.google_{current_user.username}"
    bar_values = get_bar_values(current_user.username)
    google_values = get_google_values(current_user.username)
    local_file_values = get_local_values(current_user.username)
    if new_val:
        print(f"add_google with google_value={new_val}")
        if new_val not in google_values and new_val not in bar_values and new_val not in local_file_values:
            print(f"{new_val} added to google_values")   
            google_values.append(new_val)
            #write_file_lines(GOOGLE_FILE, google_values)    
            save_google_values(current_user.username, google_values)
            print(f"Updated google_values with new value {new_val}")                     
        else:
            print(f"{new_val} already present so no action needed")
            return jsonify({"success": True, "message": "File already present, no action needed"})
        return jsonify({"success": True, "message": "Google Sheet added successfully"})
    return jsonify({"success": False, "message": "No file URL provided"})


@app.route("/remove_google", methods=["POST"])
def remove_google():
    to_remove = request.form.get('remove_google')
    userlogin = current_user.username
    #GOOGLE_FILE = f"./config/.google_{current_user.username}"
    google_values = get_google_values(current_user.username)
    print(f"remove_google called with {to_remove}")
    if to_remove in google_values:
        print(f"{to_remove} found and will be removed")
        google_values.remove(to_remove)
        #write_file_lines(GOOGLE_FILE, google_values)
        save_google_values(userlogin, google_values)
        print(f"Removed from google_values the value {to_remove}")

        # if file was scheduled for resync then remove from schedule.json 
        clear_schedule_file(user_sched_file, to_remove, userlogin) 
        schedule_job_clear(scheduler, user_sched_file, to_remove, userlogin)           
        return jsonify({"success": True, "message": "Google Sheet removed successfully"})
    else:
        print(f"{to_remove} not found in google_values, no action taken")
    return jsonify({"success": False, "message": "File not found"})


# ============================================================================
# BACKGROUND WORKER FUNCTION - Add this new function
# ============================================================================

def resync_task_worker(file_url, userlogin, delegated_auth, google_user_email):
    """
    Background task that performs the actual resync.
    This runs in a separate thread via the task queue.
    """
    print(f"[Task Worker] Starting resync for {file_url}, user: {userlogin}")
    
    try:
        # Call your existing resync function
        result = resync(file_url, userlogin, delegated_auth) # pass google_user_email if needed for google sheets only
        
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)


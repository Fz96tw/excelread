from flask import Flask, render_template, request, redirect, url_for,session
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

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a-very-secret-key")  # Use a real secret in production


FOO_FILE = './config/.env'
BAR_FILE = './config/.bar'
BANNER_PATH = '/static/banner3.jpg'  # put banner.jpg in static folder

# -------------------------------
# TOKEN MANAGEMENT
# -------------------------------
#load_dotenv()
# load .env from config folder
ENV_PATH = os.path.join(os.path.dirname(__file__), "config", ".env")
load_dotenv(dotenv_path=ENV_PATH)
CLIENT_ID = os.environ.get("CLIENT_ID")  # From Azure AD app registration
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")  # From Azure AD app registration
TENANT_ID = os.environ.get("TENANT_ID")  # From Azure AD app registration
#SCOPES = ["Files.ReadWrite.All", "Sites.ReadWrite.All"] #, "offline_access"]
SCOPES = ["https://graph.microsoft.com/.default"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_PATH = "/getAToken"
REDIRECT_URI = f"http://localhost:5000{REDIRECT_PATH}"

TOKEN_CACHE_FILE = "./config/token_cache.json"



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

# gloabals ^^^


# Ensure file exists
if not os.path.exists(SCHEDULE_FILE):
    with open(SCHEDULE_FILE, "w") as f:
        print(f"creating schedule file = {SCHEDULE_FILE}")
        json.dump([], f)
else:
    print(f"Schedule file already exists {SCHEDULE_FILE}")


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
    scheduler.add_job(
        dump_job_status, 
        "interval", 
        minutes=5, 
        args=[scheduler], 
        id="__status_dumper__", 
        replace_existing = True,
        misfire_grace_time=300,  # 5 minutes to prevent skipping of jobs when delays occur)
        max_instances=1 )  # don't start new one if previous still running
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    # Setup all the schedules since app is starting up
    schedule_jobs(scheduler,SCHEDULE_FILE)




@app.route('/', methods=['GET', 'POST'])
def index():

    # Make sure user is logged into AI Connector before showing main page
    #userlogin = None
    if current_user.is_authenticated:
        global userlogin
        userlogin = current_user.username
        print(f"User logged in: {userlogin}")
    else:
        print("Not logged so redirecting to home for login")
        userlogin = None
        return redirect(url_for("home"))


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
    foo_values = {}
    foo_values["jira_url"] = read_env("JIRA_URL", ENV_PATH)
    foo_values["jira_user"] = read_env("JIRA_EMAIL", ENV_PATH)
    foo_values["jira_token"] = read_env("JIRA_API_TOKEN", ENV_PATH)
    foo_values["openai_token"] = read_env("OPENAI_API_KEY", ENV_PATH)

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
    
    bar_values = read_file_lines(BAR_FILE)
    
    bar_values_original = {}

    # Synchronize session login status with real token state every request
    print("Checking login status...")
    logged_in_state = is_logged_in()  # returns True or False
    print(f"Login status: {logged_in_state}")
    session["is_logged_in"] = logged_in_state
    logged_in = logged_in_state


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
            write_env("JIRA_URL",jira_url,ENV_PATH)
            write_env("JIRA_EMAIL",jira_user,ENV_PATH)
            write_env("JIRA_API_TOKEN",jira_token,ENV_PATH)
            # load .env from config folder
            load_dotenv(dotenv_path=ENV_PATH)
            
            #return redirect(url_for('index'))
            return jsonify({"success": True, "message": "Jira settings updated successfully"})
        
        elif 'add_bar' in request.form:
            new_val = request.form.get('bar_value', '').strip()
            if new_val:
                if new_val not in bar_values:   
                    bar_values.append(new_val)
                    write_file_lines(BAR_FILE, bar_values)
            return redirect(url_for('index'))

        elif 'remove_bar' in request.form:
            to_remove = request.form.get('remove_bar')
            if to_remove in bar_values:
                bar_values.remove(to_remove)
                write_file_lines(BAR_FILE, bar_values)
                # if file was scheduled for resync then remove from schedule.json 
                clear_schedule_file(user_sched_file, to_remove, userlogin) 
                schedule_job_clear(user_sched_file, to_remove, userlogin)           
            return redirect(url_for('index'))
        
        elif 'resync_bar' in request.form:
            print("Resyncing file values...")
            val = request.form["resync_bar"]
            val = clean_sharepoint_url(val)
            resync(val,userlogin)  # call your function with the string value file URL and userlogin (used for working folder for script)
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

    
    print(f"Sharepoint Authorization status: {logged_in}")

    return render_template('form.html',
                           banner_path=BANNER_PATH,
                           foo_values=foo_values,
                           bar_values=bar_values,
                           logged_in=logged_in,
                           folder_tree=folder_tree,
                           schedule_dict=schedule_dict,
                           username=userlogin,
                           llm_default=llm_model)


from flask import Flask, request, jsonify

@app.route("/save_jira", methods=["POST"])
def save_jira():
    data = request.get_json()
    jira_url = data.get("jira_url", "")
    jira_user = data.get("jira_user", "")
    jira_token = data.get("jira_token", "")

    print(f"Saving new .env values {jira_url}, {jira_user}, {jira_token}")
    write_env("JIRA_URL", jira_url, ENV_PATH)
    write_env("JIRA_EMAIL", jira_user, ENV_PATH)
    write_env("JIRA_API_TOKEN", jira_token, ENV_PATH)

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
    schedule_jobs(scheduler, user_sched_file, filename, userlogin)

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000, debug=True, use_reloader=False)


from flask import Flask, render_template, request, redirect, url_for,session
import os
import re
import json
import requests
import msal
import uuid
from pathlib import Path
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
#AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Files.ReadWrite.All", "Sites.ReadWrite.All"] #, "offline_access"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_PATH = "/getAToken"
REDIRECT_URI = f"http://localhost:5000{REDIRECT_PATH}"

TOKEN_CACHE_FILE = "token_cache.json"


def load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
    return cache


def save_cache(cache):
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())



def build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache
    )


def read_file_lines(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return [line.strip() for line in f.readlines()]
    return []

def write_file_lines(path, lines):
    with open(path, 'w') as f:
        f.write("\n".join(lines))


@app.route("/check_token")
def check_token():
    cache = load_cache()
    cca = build_msal_app(cache)
    accounts = cca.get_accounts()

    if accounts:
        result = cca.acquire_token_silent(SCOPES, account=accounts[0])
        save_cache(cache)
        if result:
            return """
                <h3>Access token ready!</h3>
                <pre>{}</pre>
                <button onclick="logout()">Logout</button>
                <script>
                    function logout() {{
                        fetch('/logout').then(() => {{
                            document.getElementById("loginBtn").textContent = "Login with Microsoft";
                        }});
                    }}
                </script>
            """.format(result['access_token'][:40] + "...")

    # Not logged in → show login button
    return """
        <h3>Not logged in</h3>
        <button id="loginBtn">Login with Microsoft</button>
        <script>
        document.getElementById("loginBtn").addEventListener("click", function() {
            window.open("/login", "LoginWindow", "width=600,height=700");
        });

        window.addEventListener("message", function(e) {
            if (e.data === "login-success") {
                document.getElementById("loginBtn").textContent = "✅ Logged in";
            } else if (e.data === "login-failed") {
                document.getElementById("loginBtn").textContent = "❌ Login failed";
            }
        });
        </script>
    """




@app.route("/login")
def login():
    cache = load_cache()
    cca = build_msal_app(cache)
    auth_url = cca.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    save_cache(cache)
    return redirect(auth_url)


@app.route(REDIRECT_PATH)
def authorized():
    cache = load_cache()
    cca = build_msal_app(cache)

    if "code" in request.args:
        result = cca.acquire_token_by_authorization_code(
            request.args["code"], scopes=SCOPES, redirect_uri=REDIRECT_URI
        )
        save_cache(cache)

        if "access_token" in result:
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




@app.route("/logout")
def logout():
    if os.path.exists(TOKEN_CACHE_FILE):
        os.remove(TOKEN_CACHE_FILE)
    return "Logged out"


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
        
        #elif 'login_bar' in request.form:
        #    #get_access_token()  # Trigger login flow
        #    return redirect(url_for('check_token'))

    return render_template('form.html',
                           banner_path=BANNER_PATH,
                           foo_values=foo_values,
                           bar_values=bar_values)

if __name__ == '__main__':
    app.run(debug=True)

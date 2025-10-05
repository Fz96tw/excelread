import os
import json
import msal
from flask import Flask, session, redirect, url_for, request, render_template_string
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = "a_very_secret_key"

# load .env from config folder
ENV_PATH = os.path.join(os.path.dirname(__file__), "config", ".env")
load_dotenv(dotenv_path=ENV_PATH)
CLIENT_ID = os.environ.get("CLIENT_ID2")  # From Azure AD app registration
CLIENT_SECRET = os.environ.get("CLIENT_SECRET2")  # From Azure AD app registration
TENANT_ID = os.environ.get("TENANT_ID2")  # From Azure AD app registration
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_PATH = "/getAToken"
REDIRECT_URI = f"http://localhost:5000{REDIRECT_PATH}"

# Do NOT include reserved scopes here — MSAL adds them automatically
SCOPES = ["User.Read","Files.ReadWrite.All", "Sites.ReadWrite.All"]
#TOKEN_CACHE_FILE = "./token_cache.json"
TOKEN_CACHE_FILE = "./config/token_cache.json"


def load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
    return cache


def save_cache(cache):
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w") as f:
            print(f"save_cache token in {TOKEN_CACHE_FILE} ")
            f.write(cache.serialize())



def build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache
    )


def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache
    )

'''def get_user_token():
    print("🔑 Acquiring delegated user token...")
    cache = load_cache()
    pca = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    print("Created PublicClientApplication(...)")

    # Try to get a cached token first
    accounts = pca.get_accounts()
    if accounts:
        print("get_accounts returned accounts")
        result = pca.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            print("✅ Using cached token.")
            return result["access_token"]

    # No cached token, perform interactive login
    result = pca.acquire_token_interactive(SCOPES)
    if "access_token" not in result:
        raise Exception(f"❌ Failed to get delegated token: {result}")

    save_cache(cache)
    print("✅ Delegated token acquired and cached.")
    return result["access_token"]
'''

#def build_msal_delegated_app(cache=None):
#    return msal.PublicClientApplication(
#        CLIENT_ID, authority=AUTHORITY, token_cache=cache
#    )


@app.route("/")
def index():
    # Try silent token first
    print("Attempting to acquire token silently...")
    cache = load_cache()
    print("Loaded cache, checking for accounts...")
    cca = _build_msal_app(cache)
    accounts = cca.get_accounts()
    if accounts:
        print(f"Found {len(accounts)} accounts in token cache")
        result = cca.acquire_token_silent(SCOPES, account=accounts[0])
        print("called 'acquire_token_silent'")
        save_cache(cache)
        if result:
            return f"Access token ready!<br>{result['access_token'][:40]}..."
        else:
            return "Failed acquire_token_silent <br>"
    else:
        print("No existing accounts found in token cache")
    return '<a href="/login">Login with Microsoft</a>'


'''@app.route("/login")
def login():
    # Create MSAL instance and redirect user to Azure AD sign-in
    msal_app = _build_msal_app()
    auth_url = msal_app.get_authorization_request_url(
        SCOPES,
        redirect_uri=url_for("authorized", _external=True)  <-------------------- 
    )
    return redirect(auth_url)
'''

@app.route("/login")
def login():
    cache = load_cache()
    cca = _build_msal_app(cache)
    auth_url = cca.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI  # url_for("authorized", _external=True)  <-------------------- 
    )
    save_cache(cache)
    return redirect(auth_url)


'''@app.route(REDIRECT_PATH)
def authorized():
    # Handle redirect from Azure AD
    code = request.args.get("code")
    if not code:
        return "No code found in redirect."

    msal_app = _build_msal_app()
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=url_for("authorized", _external=True)
    )

    if "error" in result:
        return f"Login failure: {result['error_description']}"

    session["user"] = result.get("id_token_claims")
    session["access_token"] = result["access_token"]
    return redirect(url_for("index"))
'''

@app.route(REDIRECT_PATH)
def authorized():

     # Handle redirect from Azure AD
    code = request.args.get("code")
    if not code:
        return "No code found in redirect."

    cache = load_cache()
    cca = _build_msal_app(cache)
    if "code" in request.args:
        print ("received 'code' in OAuth callback")
        result = cca.acquire_token_by_authorization_code(
            code, # request.args["code"],
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI   # url_for("authorized", _external=True)
        )
        save_cache(cache)
        if "access_token" in result:
            #session["user"] = result.get("id_token_claims")
            #session["access_token"] = result["access_token"]
            return redirect(url_for("index"))
        else:
            return f"Error: {result.get('error_description')}"
    return "No code provided."


if __name__ == "__main__":
    print (f"Tenant id: {TENANT_ID}")
    print (f"Client id: {CLIENT_ID}")
    print (f"Client secret: {CLIENT_SECRET}")
    print (f"Authority: {AUTHORITY}")
    print (f"Redirect URI: {REDIRECT_URI}")

    app.run(debug=True)

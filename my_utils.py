import re



import smtplib


def send_text_email(subject: str, from_address: str, to_address: str, data: str):
    print(
        f"send_text_email called params= {subject}, {from_address}, {to_address}, "
        f"{data[:20]}{'...' if len(data) > 20 else ''}"
    )

    # Build a raw RFC822 email manually
    message = (
        f"Subject: {subject}\n"
        f"From: {from_address}\n"
        f"To: {to_address}\n"
        f"Content-Type: text/plain; charset=utf-8\n"
        f"\n"
        f"{data}"
    )

    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    smtp_user = "fz96tw@gmail.com"
    smtp_password = "tgpmcbauhlligxvi"  # Your 16-char Gmail app password

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(from_address, [to_address], message.encode("utf-8"))

    print(f"Plain-text email sent to {to_address}")



def is_googlesheet(filename: str) -> bool:
     # Detect if source is Google Sheet (simple heuristic: URL or just ID)
    is_google_sheet = isinstance(filename, str) and ("docs.google.com/spreadsheets" in filename or re.match(r"^[a-zA-Z0-9-_]{20,}$", filename))
    return is_google_sheet


def extract_google_doc_id(url_or_id: str) -> str | None:
    """
    Extracts the Google document ID from a full URL or returns the string as-is
    if it already looks like an ID. Returns None if not found.
    """
    if not isinstance(url_or_id, str):
        return None

    # Match patterns like:
    # https://docs.google.com/spreadsheets/d/<ID>/edit
    # https://docs.google.com/document/d/<ID>/
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url_or_id)
    if match:
        return match.group(1)

    # If it looks like a raw ID (usually >20 chars alphanumeric + _ or -)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", url_or_id.strip()):
        return url_or_id.strip()

    return None


# convert any rich-text formatting in any jira field who value is retrieved with getattr()
# jira client getattr() adds markdown for jira rich fields that contain certain text, 
# eg. hyperlinks have a'|' char which will break out jira.csv file format! 
def clean_jira_wiki(text):

    print(f"Original text before cleaning jira rich text formatting: {text}")
    if not text:
        print("Empty text, returning empty string") 
        return ""

    text = str(text)  # convert from jira object to string so we can call replace

    # Replace wiki-style link markers [text|url] → url
    # This simplistic approach assumes the link and text are similar or you don’t need to keep both.
    text = text.replace("[", "(").replace("]", ")").replace("|", " ")

    # Remove basic bold/italic markers (*bold*, _italic_)
    text = text.replace("*", "").replace("_", "")

    # Remove table/heading markers (|, ||, #)
    text = text.replace("||", " ").replace("|", " ").replace("#", " ")

    # Clean up (compact) any multiple spaces introduced by above replaces
    text = " ".join(text.split())

    print(f"Cleaned text after removing jira rich text formatting: {text}")    
    return text.strip()


def clean_sharepoint_url(url: str) -> str:
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

# Without escaping, Excel would see the unescaped quote as the end of the string, breaking the formula:
# So _excel_escape_quotes() prevents that by doubling the quotes inside the formula string
# the correct way to represent quotes inside Excel string literals.
def excel_escape_quotes(s: str) -> str:
    # Excel doubles double-quotes inside string literals
    return s.replace('"', '""')

# use TinyURL when hyperlink length exceeds 255 which break excel hyperlinks
import requests
def shorten_url(url: str) -> str:
    """Shorten a URL using TinyURL."""
    try:
        api_url = f"http://tinyurl.com/api-create.php?url={url}"
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            return response.text.strip()
    except Exception as e:
        print(f"⚠️ URL shortening failed for {url}: {e}")
    return url  # fallback to original if shortening fails


def make_hyperlink_formula(url: str, text: str) -> str:
    """Create an Excel HYPERLINK formula; shorten URL only if it's too long."""
    text = text.replace("\n", " ")

    # Excel's HYPERLINK() formula limit for URLs is ~255 characters
    short_url = url
    if len(url) > 255:
        print(f"URL too long ({len(url)} chars), shortening with TinyURL...")
        short_url = shorten_url(url)

    return f'=HYPERLINK("{excel_escape_quotes(short_url)}","{excel_escape_quotes(text)}")'


import os
from dotenv import load_dotenv, set_key, unset_key
from pathlib import Path

def load_env(env_path: str | Path):
    """Load variables from the given .env file into os.environ."""
    env_path = Path(env_path)
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        raise FileNotFoundError(f".env file not found: {env_path}")

def read_env(key: str, env_path: str | Path) -> str | None:
    """Read a variable from the given .env file via os.getenv."""
    env_path = Path(env_path)
    if not env_path.exists():
        return None
    load_dotenv(dotenv_path=env_path, override=True)  # refresh environment
    return os.getenv(key)

def write_env(key: str, value: str, env_path: str | Path):
    """Add or update a variable in the given .env file."""
    env_path = Path(env_path)
    env_path.parent.mkdir(parents=True, exist_ok=True)  # ensure folder exists
    set_key(str(env_path), key, value)

def update_env(key: str, value: str, env_path: str | Path):
    """Update a variable (alias for write)."""
    write_env(key, value, env_path)

def delete_env(key: str, env_path: str | Path):
    """Remove a variable from the given .env file."""
    env_path = Path(env_path)
    if env_path.exists():
        unset_key(str(env_path), key)



import os

def map_windows_path_to_container(path: str) -> str:
    
    #Convert Windows-style path (C:\...) to container path (/cdrive/...).
    #If already looks like a Linux path, return as-is.
    
    # Handle "C:\..." or "C:/..."
    if path[1:3] in [":\\", ":/"]:
        drive_letter = path[0].lower()
        relative_path = path[2:].replace("\\", "/")
        return f"/{drive_letter}drive/{relative_path}"
    
    return path  # already container-friendly

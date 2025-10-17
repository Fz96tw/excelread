import re


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
    """
    Convert Windows-style path (C:\...) to container path (/cdrive/...).
    If already looks like a Linux path, return as-is.
    """
    # Handle "C:\..." or "C:/..."
    if path[1:3] in [":\\", ":/"]:
        drive_letter = path[0].lower()
        relative_path = path[2:].replace("\\", "/")
        return f"/{drive_letter}drive/{relative_path}"
    
    return path  # already container-friendly

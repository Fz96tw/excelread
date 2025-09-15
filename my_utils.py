import re


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

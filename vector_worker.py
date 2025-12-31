import os
import requests
import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, Tuple
from celery import Celery
import faiss
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from redis_state import get_url_state, update_url_state
from vector_embedder import get_embedder

# Configure logging
logger = logging.getLogger(__name__)

# Redis host configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

# Celery app
app = Celery(
    "vector_worker",
    broker=f"redis://{REDIS_HOST}:6379/0",
    backend=f"redis://{REDIS_HOST}:6379/1"
)

# Get configured embedder (supports multiple backends)
embedder = get_embedder()
logger.info(f"Using embedder: {embedder.get_name()}")

# Base directory for all user data
CONFIG_DIR = "./config"
os.makedirs(CONFIG_DIR, exist_ok=True)


def get_user_dir(user_id):
    """Get the base directory for a user's data."""
    user_dir = os.path.join(CONFIG_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def get_vectors_dir(user_id):
    """Get the vectors directory for a user."""
    vectors_dir = os.path.join(get_user_dir(user_id), "vectors")
    os.makedirs(vectors_dir, exist_ok=True)
    return vectors_dir


def get_metadata_path(user_id, url):
    """Get metadata file path for a user's URL (stored alongside vectors)."""
    safe = url.replace("/", "_").replace(":", "_")
    vectors_dir = get_vectors_dir(user_id)
    vector_dir = os.path.join(vectors_dir, safe)
    os.makedirs(vector_dir, exist_ok=True)
    return os.path.join(vector_dir, "metadata.json")


def load_metadata(user_id, url):
    """Load metadata for a user's URL."""
    path = get_metadata_path(user_id, url)
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_metadata(user_id, url, data):
    """Save metadata for a user's URL."""
    path = get_metadata_path(user_id, url)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_user_env(user_id: str) -> Dict[str, str]:
    """Load environment variables from user's config file."""
    env_path = os.path.join(CONFIG_DIR, f"env.{user_id}")
    env_vars = {}
    
    if not os.path.exists(env_path):
        return env_vars
    
    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Parse KEY=VALUE format
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Error loading env file for {user_id}: {e}")
    
    return env_vars


def is_confluence_url(url: str) -> bool:
    """Check if URL is an Atlassian Confluence wiki."""
    return 'atlassian.net/wiki' in url or '/confluence/' in url


def fetch_confluence_page(url: str, user_env: Dict[str, str]) -> Tuple[str, str, str]:
    """
    Fetch Confluence page using v1 to resolve correct content ID,
    then call v2 to retrieve storage format content.
    Includes debug logging of page ID resolution.
    """
    confluence_url = user_env.get('CONFLUENCE_URL')
    api_token = user_env.get('CONFLUENCE_API_TOKEN')
    email = user_env.get('CONFLUENCE_EMAIL')

    if not confluence_url or not api_token or not email:
        logger.warning("Missing Confluence credentials, falling back to web scraping")
        return fetch_regular_page(url)

    import re
    # Extract SPACE KEY, LEGACY PAGE ID, TITLE from URL
    m = re.search(r'/spaces/([^/]+)/pages/(\d+)/(.*)$', url)
    if not m:
        logger.warning(f"Could not parse Confluence URL format: {url}")
        return fetch_regular_page(url)

    space_key = m.group(1)
    legacy_page_id = m.group(2)
    title = m.group(3).replace("+", " ")

    logger.info(f"[DEBUG] Extracted from URL:")
    logger.info(f"        Space Key: {space_key}")
    logger.info(f"        Legacy Page ID: {legacy_page_id}")
    logger.info(f"        Title: {title}")

    auth = HTTPBasicAuth(email, api_token)

    # --------------------------------------------------------------
    # FIX: Correct Confluence Cloud v1 endpoint uses /wiki/rest/api/
    # --------------------------------------------------------------
    search_url = (
        f"{confluence_url}/wiki/rest/api/content"
        f"?title={requests.utils.quote(title)}"
        f"&spaceKey={requests.utils.quote(space_key)}"
    )

    logger.info(f"[DEBUG] v1 Search URL: {search_url}")

    resp = requests.get(search_url, auth=auth, timeout=30)

    resolved_id = None
    v1_ids = []

    if resp.ok:
        items = resp.json().get("results", [])
        for entry in items:
            v1_ids.append(entry.get("id"))

        logger.info(f"[DEBUG] v1 Search returned IDs: {v1_ids}")

        if len(v1_ids) > 0:
            resolved_id = v1_ids[0]

    if not resolved_id:
        logger.warning(
            f"[DEBUG] No v1 search match found for title '{title}' "
            f"in space '{space_key}', falling back to legacy ID {legacy_page_id}"
        )
        resolved_id = legacy_page_id

    logger.info(f"[DEBUG] Final resolved content ID: {resolved_id}")

    # --------------------------------------------------------------
    # Call Confluence Cloud API v2 with resolved ID
    # --------------------------------------------------------------
    v2_url = f"{confluence_url}/wiki/api/v2/pages/{resolved_id}?body-format=storage"
    logger.info(f"[DEBUG] Calling v2 URL: {v2_url}")

    headers = {"Accept": "application/json"}
    response = requests.get(v2_url, headers=headers, auth=auth, timeout=30)

    if not response.ok:
        logger.warning(
            f"[DEBUG] API v2 failed for content ID {resolved_id}. "
            "Falling back to authenticated web scraping."
        )
        return fetch_confluence_web_authenticated(url, email, api_token)

    data = response.json()

    # Extract storage-format HTML and metadata
    content_html = data.get("body", {}).get("storage", {}).get("value", "")
    version_number = str(data.get("version", {}).get("number", ""))
    last_modified = data.get("version", {}).get("createdAt", "")

    etag = f"confluence-v{version_number}"

    logger.info(f"[DEBUG] v2 returned version: {version_number}")
    logger.info(f"[DEBUG] v2 last_modified: {last_modified}")

    return content_html, etag, last_modified



def fetch_confluence_page_claude(url: str, user_env: Dict[str, str]) -> Tuple[str, str, str]:
    """
    Fetch Confluence page using API, with fallback to authenticated web scraping.
    
    Args:
        url: Confluence page URL
        user_env: User environment variables containing CONFLUENCE_URL, CONFLUENCE_EMAIL, and CONFLUENCE_API_TOKEN
        
    Returns:
        Tuple of (content, etag, last_modified)
    """
    confluence_url = user_env.get('CONFLUENCE_URL')
    api_token = user_env.get('CONFLUENCE_API_TOKEN')
    email = user_env.get('CONFLUENCE_EMAIL')
    
    if not confluence_url or not api_token or not email:
        logger.warning("Missing Confluence credentials, falling back to web scraping")
        return fetch_regular_page(url)
    
    # Extract page ID from URL
    # Example: https://fz96tw.atlassian.net/wiki/spaces/Trinket/pages/655361/...
    import re
    page_id_match = re.search(r'/pages/(\d+)', url)
    if not page_id_match:
        logger.warning(f"Could not extract page ID from URL: {url}, falling back to web scraping")
        return fetch_regular_page(url)
    
    page_id = page_id_match.group(1)
    
    # Try Confluence Cloud REST API v2 first, then fall back to v1
    api_urls = [
        f"{confluence_url}/wiki/api/v2/pages/{page_id}?body-format=storage",
        f"{confluence_url}/rest/api/content/{page_id}?expand=body.storage,version"
    ]
    
    logger.info(f"Fetching Confluence page via API: {page_id}")
    
    # Confluence Cloud uses Basic Auth with email:api_token
    auth = HTTPBasicAuth(email, api_token)
    
    headers = {
        'Accept': 'application/json'
    }
    
    response = None
    last_error = None
    
    # Try each API endpoint
    for api_url in api_urls:
        try:
            logger.info(f"Trying API endpoint: {api_url}")
            response = requests.get(api_url, headers=headers, auth=auth, timeout=30)
            response.raise_for_status()
            break  # Success!
        except requests.exceptions.HTTPError as e:
            last_error = e
            logger.warning(f"API endpoint failed: {e}")
            continue
    
    if response is None or not response.ok:
        logger.warning(f"All API endpoints failed for page {page_id}. Error: {last_error}")
        logger.info("Falling back to authenticated web scraping")
        return fetch_confluence_web_authenticated(url, email, api_token)
    
    data = response.json()
    
    # Parse response based on API version
    if 'body' in data:
        # API v1 format
        content_html = data.get('body', {}).get('storage', {}).get('value', '')
        version = data.get('version', {})
        version_number = str(version.get('number', ''))
        last_modified = version.get('when', '')
    else:
        # API v2 format
        content_html = data.get('body', {}).get('storage', {}).get('value', '')
        version = data.get('version', {})
        version_number = str(version.get('number', ''))
        last_modified = version.get('createdAt', '')
    
    # Use version number as etag
    etag = f'confluence-v{version_number}'
    
    return content_html, etag, last_modified


def fetch_confluence_web_authenticated(url: str, email: str, api_token: str) -> Tuple[str, str, str]:
    """
    Fetch Confluence page by scraping the web interface with authentication.
    
    Args:
        url: Confluence page URL
        email: Atlassian account email
        api_token: API token
        
    Returns:
        Tuple of (content, etag, last_modified)
    """
    logger.info(f"Attempting authenticated web scraping for: {url}")
    
    # Use a session to maintain cookies
    session = requests.Session()
    
    # Set up Basic Auth
    session.auth = HTTPBasicAuth(email, api_token)
    
    # Add browser headers
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    })
    
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        
        # Generate a simple etag from content hash
        content_hash = hashlib.md5(response.text.encode()).hexdigest()
        etag = f'web-{content_hash[:16]}'
        
        # Try to get last-modified from headers
        last_modified = response.headers.get('Last-Modified', '')
        
        return response.text, etag, last_modified
        
    except Exception as e:
        logger.error(f"Authenticated web scraping failed: {e}")
        raise ValueError(f"Could not fetch Confluence page via API or web scraping: {url}")


def fetch_regular_page(url: str) -> Tuple[str, str, str]:
    """
    Fetch regular web page with browser headers.
    
    Returns:
        Tuple of (content, etag, last_modified)
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    response = requests.get(url, timeout=10, headers=headers)
    response.raise_for_status()
    
    content = response.text
    etag = response.headers.get("ETag")
    last_modified = response.headers.get("Last-Modified")
    
    return content, etag, last_modified


def content_hash(text: str) -> str:
    """Generate SHA256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text, chunk_size=500):
    """Split text into chunks of approximately chunk_size words."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i:i + chunk_size]))
    return chunks


def extract_text_from_html(html_content):
    """Extract clean text from HTML, removing scripts, styles, and tags."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    
    # Get text
    text = soup.get_text(separator=' ', strip=True)
    
    # Clean up whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    
    return text


def build_vector_store(user_id, url, text):
    """Build FAISS vector store for a user's URL content."""
    safe = url.replace("/", "_").replace(":", "_")
    vectors_dir = get_vectors_dir(user_id)
    out_dir = os.path.join(vectors_dir, safe)
    os.makedirs(out_dir, exist_ok=True)

    chunks = chunk_text(text)
    embeddings = embedder.encode(chunks)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)

    tmp_path = os.path.join(out_dir, "index.faiss.tmp")
    final_path = os.path.join(out_dir, "index.faiss")

    faiss.write_index(index, tmp_path)
    os.replace(tmp_path, final_path)

    # Save chunks for retrieval
    chunks_path = os.path.join(out_dir, "chunks.json")
    with open(chunks_path, "w") as f:
        json.dump(chunks, f, indent=2)

    return len(chunks)


@app.task
def process_url(user_id, url):
    """Process a URL for a specific user: fetch, check changes, and vectorize."""
    logger.info(f"[{user_id}] Processing URL: {url}")
    update_url_state(user_id, url, status="DOWNLOADING")

    try:
        # Load user environment variables
        user_env = load_user_env(user_id)
        
        # Fetch the URL (Confluence API or regular web page)
        logger.info(f"[{user_id}] Downloading: {url}")
        
        if is_confluence_url(url):
            logger.info(f"[{user_id}] Detected Confluence URL, using API")
            content, etag, last_modified = fetch_confluence_page(url, user_env)
        else:
            logger.info(f"[{user_id}] Regular web page")
            content, etag, last_modified = fetch_regular_page(url)
        
        # Extract clean text from HTML
        clean_text = extract_text_from_html(content)
        logger.info(f"[{user_id}] Extracted {len(clean_text)} characters of text")

        checksum = hashlib.sha256(content.encode()).hexdigest()

        prev = get_url_state(user_id, url)

        # Check if unchanged
        if prev:
            if (
                prev.get("last_etag") == etag
                and prev.get("last_modified") == last_modified
                and prev.get("last_checksum") == checksum
            ):
                logger.info(f"[{user_id}] Content unchanged, skipping vectorization: {url}")
                update_url_state(user_id, url, status="UNCHANGED")
                return

        # Vectorize because content changed
        logger.info(f"[{user_id}] Vectorizing content: {url}")
        update_url_state(user_id, url, status="VECTORIZING")
        num_chunks = build_vector_store(user_id, url, clean_text)

        # Save metadata to file
        metadata = {
            "url": url,
            "etag": etag,
            "last_modified": last_modified,
            "checksum": checksum,
            "num_chunks": num_chunks,
            "last_processed": datetime.now().isoformat(),
            "embedder": embedder.get_name(),
            "embedding_dimension": embedder.get_dimension(),
            "source_type": "confluence" if is_confluence_url(url) else "web"
        }
        save_metadata(user_id, url, metadata)

        logger.info(f"[{user_id}] Successfully processed {num_chunks} chunks: {url}")
        update_url_state(
            user_id,
            url,
            status="DONE",
            last_etag=etag,
            last_modified=last_modified,
            last_checksum=checksum,
            num_chunks=num_chunks,
        )

    except Exception as e:
        logger.error(f"[{user_id}] Error processing {url}: {str(e)}")
        update_url_state(user_id, url, status="ERROR", error=str(e))
        raise
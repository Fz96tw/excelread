import os
import yaml
import redis
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from vector_worker import process_url  # Celery task
from redis_state import get_url_state, update_url_state  # Use consistent state management

# Detect if running in Docker or on host
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")  # Default to localhost for WSL host

CONFIG_ROOT = "./config"  # directory containing user folders


class DocsFileHandler(FileSystemEventHandler):
    """
    Handles changes to ANY docs.yaml inside ANY user's folder.
    Also detects new user folders being created.
    Directory structure:
        config/<username>/docs.yaml
    """
    def __init__(self, observer):
        self.observer = observer
        self.watched_folders = set()
        self.last_modified = {}  # Track last modification time to debounce
        self.debounce_seconds = 1.0  # Wait 1 second between processing same file
        
    def on_created(self, event):
        """Handle new files or directories being created."""
        # Check if a new directory was created in config root
        if event.is_directory:
            parent_dir = os.path.dirname(event.src_path)
            if os.path.abspath(parent_dir) == os.path.abspath(CONFIG_ROOT):
                # New user folder created
                username = os.path.basename(event.src_path)
                print(f"[Watcher] New user folder detected: {username}")
                self.add_user_folder(event.src_path)
        
        # Check if a new docs.yaml was created
        elif event.src_path.endswith("docs.yaml"):
            print(f"[Watcher] New docs.yaml detected: {event.src_path}")
            parts = event.src_path.split(os.sep)
            try:
                config_index = parts.index("config") + 1
                username = parts[config_index]
                self.process_user_docs(username, event.src_path)
            except Exception as e:
                print(f"[Watcher] ERROR parsing username from path: {e}")
    
    def on_modified(self, event):
        if event.is_directory:
            return

        if not event.src_path.endswith("docs.yaml"):
            return

        # Debounce: check if we processed this file recently
        current_time = time.time()
        last_time = self.last_modified.get(event.src_path, 0)
        
        if current_time - last_time < self.debounce_seconds:
            # Too soon, skip this event
            return
        
        self.last_modified[event.src_path] = current_time

        print(f"[Watcher] Detected change in: {event.src_path}")

        # Extract username (e.g. config/username/docs.yaml)
        parts = event.src_path.split(os.sep)
        try:
            config_index = parts.index("config") + 1
            username = parts[config_index]
        except Exception:
            print("[Watcher] ERROR parsing username from path")
            return

        self.process_user_docs(username, event.src_path)

    def add_user_folder(self, folder_path):
        """Add a watch for a newly created user folder."""
        if folder_path not in self.watched_folders:
            print(f"[Watcher] Adding watch for: {folder_path}")
            self.observer.schedule(self, folder_path, recursive=False)
            self.watched_folders.add(folder_path)

    def process_user_docs(self, username, filepath):
        print(f"[Watcher] Loading docs.yaml for user {username}")
        try:
            with open(filepath, "r") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[Watcher] Failed to read YAML for {username}: {e}")
            return

        urls = data.get("documents", [])
        if not isinstance(urls, list):
            print(f"[Watcher] Invalid YAML structure for {username}")
            return

        print(f"[Watcher] User {username} has {len(urls)} URLs")

        for url in urls:
            # Skip invalid URLs
            if not url or not isinstance(url, str) or not url.strip():
                print(f"[Watcher] Skipping invalid URL entry for user {username}")
                continue
            
            url = url.strip()  # Remove whitespace
            
            existing = get_url_state(username, url)
            if not existing:
                print(f"[Watcher] New URL for user {username}: {url}")
                update_url_state(username, url, status="queued")
                process_url.delay(username, url)
            else:
                print(f"[Watcher] URL already tracked (user={username}): {url}")
                # You *could* add logic: If YAML changed, reprocess, etc.


def start_watcher():
    """Start watching all user folders in the config directory."""
    observer = Observer()
    
    # Create handler with reference to observer
    handler = DocsFileHandler(observer)

    print(f"[Watcher] Watching root directory: {CONFIG_ROOT}")

    # Ensure config directory exists
    os.makedirs(CONFIG_ROOT, exist_ok=True)

    # Watch the config root directory itself for new user folders
    observer.schedule(handler, CONFIG_ROOT, recursive=False)
    print(f"[Watcher] Watching config root for new user folders")

    # Watch each existing user folder
    for user_folder in os.listdir(CONFIG_ROOT):
        full_path = os.path.join(CONFIG_ROOT, user_folder)
        if os.path.isdir(full_path):
            print(f"[Watcher] Watching user folder: {full_path}")
            observer.schedule(handler, full_path, recursive=False)
            handler.watched_folders.add(full_path)

    observer.start()

    print("[Watcher] File watcher started (multi-user mode).")
    try:
        while True:
            pass  # watchdog keeps running
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    start_watcher()
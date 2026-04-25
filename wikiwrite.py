#!/usr/bin/env python3
import sys
import os
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv

def parse_confluence_url(wiki_link):
    print(f"[INFO] Parsing wiki link: {wiki_link}")

    parsed = urlparse(wiki_link)
    parts = parsed.path.strip("/").split("/")

    # Expected pattern: /wiki/spaces/<SPACEKEY>/pages/<PAGEID>/...
    try:
        space_key = parts[parts.index("spaces") + 1]
        page_id = parts[parts.index("pages") + 1]
    except (ValueError, IndexError):
        print("[ERROR] Invalid Confluence URL format. Could not extract spaceKey or pageId.")
        sys.exit(1)

    print(f"[INFO] Extracted spaceKey={space_key}, pageId={page_id}")
    return space_key, page_id


def get_page(JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, page_id):
    url = f"{JIRA_URL}/wiki/api/v2/pages/{page_id}"
    print(f"[INFO] Fetching existing page metadata from: {url}")

    response = requests.get(url, auth=(JIRA_EMAIL, JIRA_API_TOKEN))

    if response.status_code != 200:
        print(f"[ERROR] Unable to fetch Confluence page metadata. Status={response.status_code}")
        print(response.text)
        sys.exit(1)

    print("[INFO] Page metadata retrieved.")
    return response.json()


def update_page(JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, page_id, existing_title, report, current_version):
    new_version = current_version + 1

    print(f"[INFO] Preparing to update page:")
    print(f"       - Page ID: {page_id}")
    print(f"       - Title (unchanged): {existing_title}")
    print(f"       - Version: {current_version} → {new_version}")

    url = f"{JIRA_URL}/wiki/api/v2/pages/{page_id}"

    payload = {
        "id": page_id,
        "title": existing_title,
        "body": {
            "representation": "storage",
            "value": report
        },
        "version": {
            "number": new_version
        },
        "status": "current"   # REQUIRED!
    }

    response = requests.put(url, json=payload, auth=(JIRA_EMAIL, JIRA_API_TOKEN))

    if response.status_code == 200:
        print("[SUCCESS] Page updated successfully with unchanged title.")
    else:
        print(f"[ERROR] Failed to update page. Status={response.status_code}")
        print(response.text)
        sys.exit(1)



def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("   post_to_confluence_wiki.py <report_file.txt> <wiki_page_url>")
        sys.exit(1)

    report_file = sys.argv[1]
    wiki_link = sys.argv[2]

    if not os.path.exists(report_file):
        print(f"[ERROR] Report file not found: {report_file}")
        sys.exit(1)

    load_dotenv()
    JIRA_URL = os.environ.get("CONFLUENCE_URL") or os.environ.get("JIRA_URL", "")
    JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
    JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")

    if not all([JIRA_API_TOKEN, JIRA_URL, JIRA_EMAIL]):
        print("[ERROR] Missing one or more required environment variables.")
        sys.exit(1)

    # Load the report content
    with open(report_file, "r", encoding="utf-8") as f:
        report = f.read()

    print("[INFO] Report file loaded.")

    # Extract spaceKey + pageId from the URL
    space_key, page_id = parse_confluence_url(wiki_link)

    # Fetch the current page information
    page_data = get_page(JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, page_id)

    # Read existing title and version
    existing_title = page_data["title"]
    existing_version = page_data["version"]["number"]

    print(f"[INFO] Live Confluence page title: {existing_title}")
    print(f"[INFO] Current version: {existing_version}")

    # Update the page without changing its title
    update_page(JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, page_id, existing_title, report, existing_version)


if __name__ == "__main__":
    main()

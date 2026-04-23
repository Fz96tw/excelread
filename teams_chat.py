"""
Teams chat fetcher — reads all Teams chats the authenticated user is part of
via Microsoft Graph API and writes time-partitioned merged transcript files.

Intended to be called from appnew.py with a delegated user token obtained via
get_app_token_delegated(). Requires Chat.Read delegated scope.

Output layout (per user):
  config/<username>/teams/
    manifest.json              — index: partition files + per-chat fetch state
    teams_<partition_key>.txt  — merged transcript for that time window

Partition granularity is controlled by config["partition_by"]:
  "day"     → one file per day       e.g. teams_2026_04_22.txt
  "week"    → one file per ISO week  e.g. teams_2026_W17.txt
  "month"   → one file per month     e.g. teams_2026_04.txt
  "quarter" → one file per quarter   e.g. teams_2026_Q2.txt   (default)
  "year"    → one file per year      e.g. teams_2026.txt

Changing partition_by invalidates existing files. A warning is logged and the
manifest is reset so next run rebuilds from the lookback window.
"""

import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

from my_utils import _CONFIG_DIR

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

VALID_PARTITIONS = ("day", "week", "month", "quarter", "year")

DEFAULT_CONFIG = {
    "lookback_days": 90,
    "partition_by": "day",   # day | week | month | quarter | year
    "include_group_chats": True,
    "include_one_on_one": True,
    "min_messages": 1,
    "output_subdir": "teams",
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_teams_config() -> dict:
    path = os.path.join(_CONFIG_DIR, "teams_config.json")
    if os.path.exists(path):
        with open(path) as f:
            overrides = json.load(f)
        cfg = {**DEFAULT_CONFIG, **overrides}
    else:
        cfg = dict(DEFAULT_CONFIG)

    if cfg["partition_by"] not in VALID_PARTITIONS:
        logger.warning("Invalid partition_by '%s', falling back to 'quarter'", cfg["partition_by"])
        cfg["partition_by"] = "quarter"

    return cfg


# ---------------------------------------------------------------------------
# Partition key helpers
# ---------------------------------------------------------------------------

def _partition_key(dt: datetime, partition_by: str) -> str:
    """Return the partition bucket string for a given UTC datetime."""
    if partition_by == "day":
        return dt.strftime("%Y_%m_%d")
    if partition_by == "week":
        return dt.strftime("%Y_W%W")
    if partition_by == "month":
        return dt.strftime("%Y_%m")
    if partition_by == "quarter":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}_Q{q}"
    if partition_by == "year":
        return str(dt.year)
    return dt.strftime("%Y_%m")  # fallback


def _parse_iso(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _partition_key_from_iso(iso: str, partition_by: str) -> str:
    return _partition_key(_parse_iso(iso), partition_by)


def _partition_filename(key: str) -> str:
    return f"teams_{key}.txt"


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _teams_dir(userlogin: str, cfg: dict) -> str:
    base = os.path.join(_CONFIG_DIR, userlogin, cfg["output_subdir"])
    os.makedirs(base, exist_ok=True)
    return base


def _load_manifest(teams_dir: str) -> dict:
    path = os.path.join(teams_dir, "manifest.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_manifest(teams_dir: str, manifest: dict):
    with open(os.path.join(teams_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)


def _check_partition_change(manifest: dict, cfg: dict) -> bool:
    """Return True if partition_by changed since last run (requires reset)."""
    prev = manifest.get("_meta", {}).get("partition_by")
    return prev is not None and prev != cfg["partition_by"]


# ---------------------------------------------------------------------------
# Graph API helpers
# ---------------------------------------------------------------------------

def _get(url: str, token: str, params: dict = None, retries: int = 3) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    for attempt in range(retries):
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 10))
            logger.warning("Graph API rate-limited, waiting %ds", wait)
            time.sleep(wait)
            continue
        if not resp.ok:
            logger.error("Graph API %s %s — %s", resp.status_code, url, resp.text)
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Graph API request failed after {retries} retries: {url}")


def _paginate(url: str, token: str, params: dict = None) -> list:
    results = []
    next_url = url
    while next_url:
        data = _get(next_url, token, params=params if next_url == url else None)
        results.extend(data.get("value", []))
        next_url = data.get("@odata.nextLink")
    return results


# ---------------------------------------------------------------------------
# Graph fetch
# ---------------------------------------------------------------------------

def _fetch_chats(token: str, cfg: dict) -> list:
    url = f"{GRAPH_BASE}/me/chats"
    params = {"$expand": "members", "$top": "50"}
    chats = _paginate(url, token, params)

    filtered = []
    for chat in chats:
        chat_type = chat.get("chatType", "")
        if chat_type == "oneOnOne" and not cfg["include_one_on_one"]:
            continue
        if chat_type in ("group", "meeting") and not cfg["include_group_chats"]:
            continue
        filtered.append(chat)

    logger.info("Found %d chats (after type filter)", len(filtered))
    return filtered


def _fetch_messages(token: str, chat_id: str, since_iso: str = None) -> list:
    """
    Fetch messages newest-first and stop early when we reach messages older
    than since_iso. Graph API does not support $filter on createdDateTime.
    """
    url = f"{GRAPH_BASE}/me/chats/{chat_id}/messages"
    params = {"$top": "50"}

    results = []
    next_url = url
    while next_url:
        data = _get(next_url, token, params=params if next_url == url else None)
        page = data.get("value", [])
        if since_iso:
            for msg in page:
                if msg.get("createdDateTime", "") <= since_iso:
                    next_url = None  # stop pagination
                    break
                results.append(msg)
        else:
            results.extend(page)
        if next_url:
            next_url = data.get("@odata.nextLink")

    return [
        m for m in results
        if m.get("messageType") == "message"
        and not m.get("deletedDateTime")
        and _extract_body(m).strip()
    ]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _extract_body(message: dict) -> str:
    body = message.get("body", {})
    content = body.get("content", "")
    if body.get("contentType") == "html":
        content = re.sub(r"<[^>]+>", "", content)
        content = (content
                   .replace("&nbsp;", " ")
                   .replace("&amp;", "&")
                   .replace("&lt;", "<")
                   .replace("&gt;", ">")
                   .strip())
    return content


def _format_ts(iso: str) -> str:
    try:
        return _parse_iso(iso).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso


def _participants_from_chat(chat: dict) -> list:
    return [
        m.get("displayName") or m.get("email") or m.get("userId", "?")
        for m in chat.get("members", [])
    ]


def _sender_name(msg: dict) -> str:
    sender = msg.get("from") or {}
    user = sender.get("user") or {}
    app = sender.get("application") or {}
    return user.get("displayName") or app.get("displayName") or "Unknown"


def _chat_label(chat: dict) -> str:
    topic = chat.get("topic") or ""
    chat_type = chat.get("chatType", "")
    participants = _participants_from_chat(chat)
    parts_str = ", ".join(participants)
    label = topic if topic else f"{chat_type}"
    return f"{label} | {chat_type} | {parts_str}"


def _format_chat_block(chat: dict, messages: list) -> str:
    """Format one chat's messages as a labelled block for a partition file."""
    sorted_msgs = sorted(messages, key=lambda m: m.get("createdDateTime", ""))
    lines = [
        "",
        "=" * 72,
        f"CHAT: {_chat_label(chat)}",
        f"Created: {_format_ts(chat.get('createdDateTime', ''))}",
        "=" * 72,
    ]
    for msg in sorted_msgs:
        ts = _format_ts(msg.get("createdDateTime", ""))
        sender = _sender_name(msg)
        body = _extract_body(msg)
        lines.append(f"[{ts}] {sender}:")
        lines.append(f"  {body}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_and_save_teams_chats(token: str, userlogin: str, cfg: dict = None) -> dict:
    """
    Fetch new Teams messages, bucket them by partition window, and append to
    the appropriate partition files. Returns a summary dict.
    """
    if cfg is None:
        cfg = load_teams_config()

    partition_by = cfg["partition_by"]
    teams_dir = _teams_dir(userlogin, cfg)
    manifest = _load_manifest(teams_dir)

    # Reset if partition scheme changed
    if _check_partition_change(manifest, cfg):
        logger.warning(
            "partition_by changed from '%s' to '%s' — resetting manifest. "
            "Old partition files are kept but will not be updated.",
            manifest["_meta"]["partition_by"], partition_by
        )
        manifest = {}

    manifest.setdefault("_meta", {})["partition_by"] = partition_by
    manifest.setdefault("_meta", {})["last_sync"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest.setdefault("chats", {})
    manifest.setdefault("partitions", {})

    # Build lookback cutoff
    lookback_cutoff = None
    if cfg.get("lookback_days"):
        cutoff_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_dt -= timedelta(days=cfg["lookback_days"])
        lookback_cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    chats = _fetch_chats(token, cfg)
    stats = {
        "total_chats": len(chats),
        "new_messages": 0,
        "partitions_updated": 0,
        "skipped_chats": 0,
        "output_dir": teams_dir,
        "partition_by": partition_by,
        "updated_partitions": {},   # key → {filename, filepath} for caller to embed
    }

    # Collect new messages per chat, then bucket by partition key
    # Structure: {partition_key: [(chat, [messages])]}
    buckets: dict[str, list] = defaultdict(list)

    for chat in chats:
        chat_id = chat["id"]
        prev = manifest["chats"].get(chat_id, {})
        since = prev.get("last_fetched_at") or lookback_cutoff

        messages = _fetch_messages(token, chat_id, since_iso=since)

        existing_count = prev.get("message_count", 0)
        if not messages:
            if existing_count < cfg["min_messages"]:
                stats["skipped_chats"] += 1
            continue

        if existing_count + len(messages) < cfg["min_messages"]:
            stats["skipped_chats"] += 1
            continue

        # Bucket messages by their partition key
        per_partition: dict[str, list] = defaultdict(list)
        for msg in messages:
            ts = msg.get("createdDateTime", "")
            if ts:
                key = _partition_key_from_iso(ts, partition_by)
                per_partition[key].append(msg)

        for key, msgs in per_partition.items():
            buckets[key].append((chat, msgs))

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest["chats"][chat_id] = {
            "topic": chat.get("topic") or "",
            "chat_type": chat.get("chatType", ""),
            "participants": _participants_from_chat(chat),
            "created": chat.get("createdDateTime", ""),
            "message_count": existing_count + len(messages),
            "last_fetched_at": now_iso,
        }
        stats["new_messages"] += len(messages)

    # Write partition files
    now_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for key, chat_message_pairs in buckets.items():
        filename = _partition_filename(key)
        filepath = os.path.join(teams_dir, filename)

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"\n\n{'#' * 72}\n")
            f.write(f"# Sync run: {now_label}  |  Partition: {key}  |  Window: {partition_by}\n")
            f.write(f"{'#' * 72}\n")
            for chat, messages in chat_message_pairs:
                f.write(_format_chat_block(chat, messages))

        partition_entry = {
            "filename": filename,
            "filepath": filepath,
            "last_updated": now_label,
        }
        manifest["partitions"][key] = partition_entry
        stats["updated_partitions"][key] = partition_entry
        stats["partitions_updated"] += 1
        logger.info("Wrote %d chat(s) to %s", len(chat_message_pairs), filename)

    _save_manifest(teams_dir, manifest)
    logger.info(
        "Teams sync complete: %d chats, %d new messages across %d partition file(s), %d skipped",
        stats["total_chats"], stats["new_messages"],
        stats["partitions_updated"], stats["skipped_chats"],
    )
    return stats

"""
Migrate per-user config files from flat config/ layout to per-user subfolders.

Before:  config/token_cache_fz96tw.json
         config/llmconfig_fz96tw.json
         config/env.fz96tw
         config/shared_files_sharepoint_fz96tw.json
         config/shared_files_google_fz96tw.json
         config/shared_files_local_fz96tw.json

After:   config/fz96tw/token_cache.json
         config/fz96tw/llmconfig.json
         config/fz96tw/env
         config/fz96tw/shared_files_sharepoint.json
         config/fz96tw/shared_files_google.json
         config/fz96tw/shared_files_local.json
"""

import os
import shutil
import re
import glob

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")

# Patterns: (glob pattern, extract username fn, new filename fn)
MIGRATIONS = [
    # token_cache_USERNAME.json -> USERNAME/token_cache.json
    ("token_cache_*.json",
     lambda n: re.match(r"token_cache_(.+)\.json$", n).group(1),
     lambda _: "token_cache.json"),

    # llmconfig_USERNAME.json -> USERNAME/llmconfig.json
    ("llmconfig_*.json",
     lambda n: re.match(r"llmconfig_(.+)\.json$", n).group(1),
     lambda _: "llmconfig.json"),

    # env.USERNAME -> USERNAME/env
    ("env.*",
     lambda n: re.match(r"env\.(.+)$", n).group(1),
     lambda _: "env"),

    # shared_files_sharepoint_USERNAME.json -> USERNAME/shared_files_sharepoint.json
    ("shared_files_sharepoint_*.json",
     lambda n: re.match(r"shared_files_sharepoint_(.+)\.json$", n).group(1),
     lambda _: "shared_files_sharepoint.json"),

    # shared_files_google_USERNAME.json -> USERNAME/shared_files_google.json
    ("shared_files_google_*.json",
     lambda n: re.match(r"shared_files_google_(.+)\.json$", n).group(1),
     lambda _: "shared_files_google.json"),

    # shared_files_local_USERNAME.json -> USERNAME/shared_files_local.json
    ("shared_files_local_*.json",
     lambda n: re.match(r"shared_files_local_(.+)\.json$", n).group(1),
     lambda _: "shared_files_local.json"),

    # google_token_USERNAME.json -> USERNAME/google_token.json  (legacy name)
    ("google_token_*.json",
     lambda n: re.match(r"google_token_(.+)\.json$", n).group(1),
     lambda _: "google_token.json"),
]

# Filenames to skip (system-level, not per-user)
SKIP_FILES = {"env.system", "google_credentials.json", "mcp.user.mapping.json",
              "token_cache.json", "schedules.json"}


def migrate(dry_run=True):
    moved = []
    skipped = []

    for pattern, get_user, get_newname in MIGRATIONS:
        matches = glob.glob(os.path.join(CONFIG_DIR, pattern))
        for src in matches:
            name = os.path.basename(src)
            if name in SKIP_FILES:
                skipped.append(src)
                continue

            try:
                username = get_user(name)
            except AttributeError:
                skipped.append(src)
                continue

            # Skip if username is "system" or looks like a reserved name
            if username in ("system",):
                skipped.append(src)
                continue

            new_name = get_newname(name)
            dest_dir = os.path.join(CONFIG_DIR, username)
            dest = os.path.join(dest_dir, new_name)

            if os.path.exists(dest):
                print(f"  SKIP (already exists): {src} -> {dest}")
                skipped.append(src)
                continue

            print(f"  {'WOULD MOVE' if dry_run else 'MOVING'}: {src}")
            print(f"           -> {dest}")
            if not dry_run:
                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(src, dest)
            moved.append((src, dest))

    print(f"\nTotal: {len(moved)} file(s) {'to move' if dry_run else 'moved'}, "
          f"{len(skipped)} skipped.")
    return moved


if __name__ == "__main__":
    import sys
    dry_run = "--apply" not in sys.argv

    if dry_run:
        print("=== DRY RUN (pass --apply to actually move files) ===\n")
    else:
        print("=== APPLYING MIGRATION ===\n")

    migrate(dry_run=dry_run)

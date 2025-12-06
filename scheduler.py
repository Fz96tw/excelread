#!/usr/bin/env python3
"""
Independent Scheduler Service
Runs as a standalone container that monitors schedules.json and executes scheduled tasks
"""

import os
import json
import time
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from dotenv import load_dotenv
import re
from filelock import FileLock, Timeout

# Import your refresh function
from refresh import resync

# Default to localhost unless overridden in env variable (set when in Docker)
APPNEW_HOST = os.getenv("APPNEW_HOST", "http://localhost:7000")

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
SCHEDULE_FILE = "./config/schedules.json"
SCHEDULE_LOCK = "./config/schedules.json.lock"
SCHEDULE_CHECK_INTERVAL = 60  # Check for schedule changes every 60 seconds
LOG_DIR = "./logs"

# Load environment variables
ENV_PATH = os.path.join(os.path.dirname(__file__), "config", "env.system")
load_dotenv(dotenv_path=ENV_PATH)

'''CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
TENANT_ID = os.environ.get("TENANT_ID")
SCOPES = ["https://graph.microsoft.com/.default"]

# Check if using delegated auth
AUTH_MODE = os.environ.get("AUTH", "")
delegated_auth = "user_auth" in AUTH_MODE

if delegated_auth:
    CLIENT_ID = os.environ.get("CLIENT_ID2")
    CLIENT_SECRET = os.environ.get("CLIENT_SECRET2")
    SCOPES = ["User.Read", "Files.ReadWrite.All", "Sites.ReadWrite.All"]
'''

# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "scheduler_service.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------

def clean_sharepoint_url(url: str) -> str:
    """Clean SharePoint URL by removing 'Shared Documents' or 'Shared Folders'"""
    url = url.replace("%20", " ")
    url = re.sub(r"/Shared (Documents|Folders)", "", url, flags=re.IGNORECASE)
    return url.replace(" ", "%20")


def make_job_id(userlogin: str, filename: str) -> str:
    """Generate a unique job ID from userlogin and filename"""
    file_hash = hashlib.sha1(filename.encode("utf-8")).hexdigest()[:12]
    return file_hash


def load_schedules(schedule_file: str) -> list:

    lock = FileLock(SCHEDULE_LOCK)
    with lock:
        """Load schedules from JSON file"""
        if not os.path.exists(schedule_file):
            logger.warning(f"Schedule file {schedule_file} does not exist")
            return []
        
        try:
            with open(schedule_file, "r") as f:
                schedules = json.load(f)
                logger.info(f"Loaded {len(schedules)} schedules from {schedule_file}")
                print (f"{schedules}")
                return schedules
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing schedule file: {e}")
            return []
        except Exception as e:
            logger.error(f"Error loading schedule file: {e}")
            return []


def get_schedule_hash(schedules: list) -> str:
    """Generate hash of current schedules for change detection"""
    schedule_str = json.dumps(schedules, sort_keys=True)
    return hashlib.sha256(schedule_str.encode()).hexdigest()

# -----------------------------------------------------------------------------
# Scheduler Event Listeners
# -----------------------------------------------------------------------------

def job_listener(event):
    """Log job execution results"""
    if event.exception:
        logger.error(f"Job {event.job_id} failed: {event.exception}")
    else:
        logger.info(
            f"Job {event.job_id} executed successfully at {event.scheduled_run_time}"
        )


# -----------------------------------------------------------------------------
# Schedule Management
# -----------------------------------------------------------------------------

def sync_schedules(scheduler, schedule_file: str):
    """
    Load schedules from file and sync with scheduler.
    Adds new jobs, removes deleted ones, updates modified ones.
    """
    logger.info(f"Syncing schedules from {schedule_file}")
    
    schedules = load_schedules(schedule_file)
    
    # Get currently scheduled job IDs
    current_job_ids = {job.id for job in scheduler.get_jobs()}
    
    # Get job IDs that should exist based on schedule file
    expected_job_ids = set()
    
    for s in schedules:
        userlogin = s.get("userlogin")
        filename = s.get("filename")
        
        if not userlogin or not filename:
            logger.warning(f"Skipping invalid schedule entry: {s}")
            continue
        
        job_id = make_job_id(userlogin, filename)
        expected_job_ids.add(job_id)
        
        cleaned_filename = clean_sharepoint_url(filename)
        
        # Check if job already exists
        existing_job = scheduler.get_job(job_id)
        
        # Determine if we need to add/update the job
        should_update = False
        
        if not existing_job:
            should_update = True
            logger.info(f"Adding new job: {job_id}")
        else:
            # Check if schedule parameters have changed
            # This is a simple check - you might want more sophisticated comparison
            should_update = True
            logger.info(f"Updating existing job: {job_id}")
        
        if should_update:
            # Remove old job if it exists
            if existing_job:
                scheduler.remove_job(job_id)
            
            # Add job based on interval or time+mode
            if s.get("interval"):
                interval = int(s["interval"])
                logger.info(f"Scheduling {job_id}: every {interval} minutes")
                
                scheduler.add_job(
                    call_resync,
                    "interval",
                    minutes=interval,
                    args=[cleaned_filename, userlogin],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=300,
                    max_instances=1
                )            
            elif s.get("time") and s.get("mode"):
                hour, minute = map(int, s["time"].split(":"))
                mode = s["mode"].lower()
                
                if mode == "daily":
                    logger.info(f"Scheduling {job_id}: daily at {hour:02d}:{minute:02d}")
                    
                    scheduler.add_job(
                        call_resync,
                        "cron",
                        hour=hour,
                        minute=minute,
                        args=[cleaned_filename, userlogin],
                        id=job_id,
                        replace_existing=True,
                        misfire_grace_time=300,
                        max_instances=1
                    )
                
                elif mode == "weekly":
                    days = s.get("days", ["mon"])
                    logger.info(
                        f"Scheduling {job_id}: weekly on {','.join(days)} at {hour:02d}:{minute:02d}"
                    )
                    
                    scheduler.add_job(
                        call_resync,
                        "cron",
                        day_of_week=",".join(days),
                        hour=hour,
                        minute=minute,
                        args=[cleaned_filename, userlogin],
                        id=job_id,
                        replace_existing=True,
                        misfire_grace_time=300,
                        max_instances=1
                    )
    
    # Remove jobs that are no longer in the schedule file
    jobs_to_remove = current_job_ids - expected_job_ids
    for job_id in jobs_to_remove:
        logger.info(f"Removing job no longer in schedule: {job_id}")
        scheduler.remove_job(job_id)
    
    logger.info(f"Schedule sync complete. Active jobs: {len(scheduler.get_jobs())}")


def dump_job_status(scheduler):
    """Log current status of all scheduled jobs"""
    jobs = scheduler.get_jobs()
    if not jobs:
        logger.info("No scheduled jobs currently")
        return
    
    logger.info("==== Scheduled Jobs Status ====")
    for job in jobs:
        filename = job.kwargs.get("url", "<unknown>")
        userlogin = job.kwargs.get("userlogin", "<unknown>")
        logger.info(
            f"  job_id={job.id}, user={userlogin}, file={filename}, "
            f"next_run={job.next_run_time}, trigger={job.trigger}"
        )
    logger.info("================================")



# api_client.py
import requests
import logging

logger = logging.getLogger(__name__)

def call_resync(filename: str, userlogin: str):
    """Invoke scheduler-specific resync endpoint."""
    endpoint = f"{APPNEW_HOST}/resync_sharepoint_userlogin"
    print(f"call_resync calling endpoint {endpoint} for user={userlogin} file={filename}")

    response = requests.post(
        endpoint,
        data={
            "filename": filename,
            "userlogin": userlogin
        }
    )

    if response.status_code != 200:
        logger.error(f"Resync API error {response.status_code}: {response.text}")
    else:
        logger.info(f"Resync API call succeeded: {response.json()}")

    return response


# -----------------------------------------------------------------------------
# Main Service Loop
# -----------------------------------------------------------------------------

def main():
    """Main service loop"""
    logger.info("=" * 80)
    logger.info("Starting Independent Scheduler Service")
    logger.info(f"Schedule file: {SCHEDULE_FILE}")
    logger.info(f"Check interval: {SCHEDULE_CHECK_INTERVAL} seconds")
    #logger.info(f"Delegated auth: {delegated_auth}")
    logger.info("=" * 80)
    
    # Create scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    
    # Add periodic status dump job
    scheduler.add_job(
        dump_job_status,
        "interval",
        minutes=5,
        args=[scheduler],
        id="__status_dumper__",
        replace_existing=True,
        misfire_grace_time=300,
        max_instances=1
    )
    
    scheduler.start()
    logger.info("Scheduler started")
    
    # Initial schedule sync
    sync_schedules(scheduler, SCHEDULE_FILE)
    
    # Track last known schedule state
    last_schedule_hash = get_schedule_hash(load_schedules(SCHEDULE_FILE))
    
    try:
        # Main loop: periodically check for schedule changes
        while True:
            time.sleep(SCHEDULE_CHECK_INTERVAL)
            
            # Load current schedules and check if they've changed
            current_schedules = load_schedules(SCHEDULE_FILE)
            current_hash = get_schedule_hash(current_schedules)
            
            if current_hash != last_schedule_hash:
                logger.info("Schedule file has changed, resyncing...")
                sync_schedules(scheduler, SCHEDULE_FILE)
                last_schedule_hash = current_hash
            
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received, stopping scheduler...")
        scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped cleanly")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        scheduler.shutdown(wait=False)
        raise


if __name__ == "__main__":
    main()
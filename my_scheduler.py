import os
import json
import logging

from refresh import *
#from my_utils import clean_sharepoint_url

# -----------------------------------------------------------------------------
# Configure logging once at startup
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s"
)
logger = logging.getLogger(__name__)




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

# -----------------------------------------------------------------------------
# Periodic status dumper for scheduled jobs
# -----------------------------------------------------------------------------
def dump_job_status(scheduler):
    jobs = scheduler.get_jobs()
    if not jobs:
        logger.info("No scheduled jobs currently.")
        return

    logger.info("==== Scheduled Jobs Status Dump ====")
    for job in jobs:
        orig_filename = job.kwargs.get("url", "<unknown>")
        logger.info(
            f"job_id={job.id}, filename={orig_filename}, next_run={job.next_run_time}, trigger={job.trigger}"
        )
    logger.info("====================================")


#print("calling clean_sharepoint_url")

#clean_sharepoint_url("http://www.cnn.com")


import hashlib

def make_job_id(userlogin: str, filename: str) -> str:
    """
    Generate a short, unique job ID safe for APScheduler job stores.
    Combines user login and a hash of the filename.
    """
    # Create a SHA1 hash of the filename (short & unique enough for IDs)
    file_hash = hashlib.sha1(filename.encode("utf-8")).hexdigest()[:12]  # 12 chars is plenty

    # Build a short job_id like: "userlogin::abc123..."
    #job_id = f"{userlogin}::{file_hash}"
    job_id = file_hash
    return job_id


def schedule_jobs(scheduler, sched_file, delegated_auth, google_user_email=None, filename=None, userlogin=None):
    """
    Schedule all jobs from schedules.json or reschedule a specific entry.
    """

    logger.info(f"schedule_jobs called with filename={filename}, userlogin={userlogin}, google_user_email={google_user_email}")

    if not os.path.exists(sched_file):
        logger.warning(f"Schedule file {sched_file} does not exist. Exiting function.")
        return  # Return early if file doesn't exist

    # Load the schedule JSON
    with open(sched_file, "r") as f:
        schedules = json.load(f)

    if not schedules:
        logger.info("Schedule file is empty so nothing to schedule at the moment")

    for s in schedules:
        # If filename/userlogin not passed explicitly, use entry
        if filename is None and userlogin is None:
            filename = s["filename"]
            userlogin = s["userlogin"]

        #job_id = f"{userlogin}::{filename}"
        job_id = make_job_id(userlogin,filename)
        logger.info(f"Scheduling job_id={job_id} for user={userlogin} file={filename}")

        cleaned_filename = clean_sharepoint_url(filename)

        # Remove old job if it exists to prevent duplicates
        if scheduler.get_job(job_id):
            logger.info(f"Found and removing existing job_id={job_id}")
            scheduler.remove_job(job_id)

        # Schedule based on interval
        if s.get("interval"):
            logger.info(f"Adding interval schedule: every {s['interval']} min")
            scheduler.add_job(
                resync,
                "interval",
                minutes=int(s["interval"]),
#                args=[cleaned_filename, userlogin],
                kwargs={"url": cleaned_filename, "userlogin":userlogin, "delegated_auth":delegated_auth,"google_user_email":google_user_email},
                id=job_id,
                replace_existing=True,
                misfire_grace_time=300,  # 5 minutes to prevent skipping of jobs when delays occur)
                max_instances=1 )  # don't start new one if previous still running


        # Schedule based on specific time + mode (Daily, Weekly, etc.)
        elif s.get("time") and s.get("mode"):
            hour, minute = map(int, s["time"].split(":"))

            if s["mode"].lower() == "daily":
                logger.info(f"Adding daily schedule at {hour:02d}:{minute:02d}")
                scheduler.add_job(
                    resync,
                    "cron",
                    hour=hour,
                    minute=minute,
#                    args=[cleaned_filename, userlogin],
                    kwargs={"url": cleaned_filename, "userlogin":userlogin},
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=300,  # 5 minutes to prevent skipping of jobs when delays occur)
                    max_instances=1
                )

            elif s["mode"].lower() == "weekly":
                days = s.get("days", ["mon"])  # default Monday if not provided
                logger.info(
                    f"Adding weekly schedule on {','.join(days)} at {hour:02d}:{minute:02d}"
                )
                scheduler.add_job(
                    resync,
                    "cron",
                    day_of_week=",".join(days),
                    hour=hour,
                    minute=minute,
                    #args=[cleaned_filename, userlogin],
                    kwargs={"url": cleaned_filename, "userlogin":userlogin},
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=300,  # 5 minutes to prevent skipping of jobs when delays occur)
                    max_instances=1
                )
            # Add more modes if needed


def schedule_job_clear(scheduler, sched_file, filename, userlogin):
    """
    Remove a specific scheduled job if it exists.
    """
    logger.info(f"schedule_job_clear called with filename={filename}, userlogin={userlogin}")
    ret = False

    if not os.path.exists(sched_file):
        logger.warning(f"Schedule file {sched_file} does not exist. Exiting function.")
        return ret

    # Load the schedule JSON
    with open(sched_file, "r") as f:
        schedules = json.load(f)

    target_job_id = make_job_id(userlogin, filename)
    #for s in schedules:
    #    scheduled_filename = s["filename"]
    #    scheduled_userlogin = s["userlogin"]

        #job_id = f"{userlogin}::{filename}"
        #job_id = make_job_id(userlogin,filename)
    logger.info(f"Checking if target_job_id={target_job_id} exists in scheduler")

    if scheduler.get_job(target_job_id):
        logger.info(f"Found and removing job_id={target_job_id}")
        scheduler.remove_job(target_job_id)
        ret = True
        #break

    return ret

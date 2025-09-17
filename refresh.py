import subprocess
import os
from urllib.parse import urlparse
from datetime import datetime
import sys
import glob
import re
import time
import shutil
import logging
from logging.handlers import RotatingFileHandler

# -----------------------------------------------------------------------------
# Configure logging
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)

logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

resync_log = os.path.join(logs_dir, "resync.log")

#file_handler = logging.FileHandler(resync_log, encoding="utf-8")
# Use RotatingFileHandler instead of FileHandler
file_handler = RotatingFileHandler(
    resync_log,
    maxBytes=5 * 1024 * 1024,  # 5 MB per file
    backupCount=0,             # keep last 3 rotated logs
    encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(file_handler)
logger.setLevel(logging.INFO)


'''def move_temp_files():
    """Move temp files into logs/temp directory."""
    target_dir = os.path.join("logs", "temp")
    os.makedirs(target_dir, exist_ok=True)

    patterns = ["*.scope.yaml", "*.changes.txt", "*.meta.json", "*.jira.csv"]

    for pattern in patterns:
        for file_path in glob.glob(pattern):
            dest = os.path.join(target_dir, os.path.basename(file_path))
            logger.info(f"Moving {file_path} → {dest}")
            shutil.move(file_path, dest)
'''

from urllib.parse import unquote
import os
import shutil


def resync(url: str, userlogin):
    """
    Full resync process with recursive handling of YAML files.
    """
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)  # e.g., Milestones.xlsx
    filename = unquote(filename)  # decode %20 → space if there are space chars in filename

    basename, _ = os.path.splitext(filename)      # e.g., Milestones

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info(f"resync: timestamp = {timestamp}")
    base_dir = os.path.dirname(__file__)

    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True) 

    log_file= os.path.join(logs_dir, f"{basename}_{timestamp}.log")

    # Persistent rolling resync.log
    #resync_log = os.path.join(logs_dir, "resync.log")
    #with open(resync_log, "a", encoding="utf-8") as f:
    #    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
    #            f"Resync called on URL={url}, file={filename} timestamp={timestamp}\n")
    logger.info(f"Resync called on URL={url}, file={filename} timestamp={timestamp}\n")

    import uuid
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    work_dir = os.path.join(base_dir, "logs", userlogin, run_id)
    os.makedirs(work_dir, exist_ok=True)

    download_script = os.path.join(base_dir, "download.py")
    scope_script = os.path.join(base_dir, "scope.py")
    read_jira_script = os.path.join(base_dir, "read_jira.py")
    create_jira_script = os.path.join(base_dir, "create_jira.py")
    update_excel_script = os.path.join(base_dir, "update_excel.py")
    update_sharepoint_script = os.path.join(base_dir, "update_sharepoint.py")
    aibrief_script = os.path.join(base_dir, "aibrief.py")

    def run_and_log(cmd, log, desc):
        """Run a command and log output."""
        header = f"\n--- Running {desc} at {datetime.now()} ---\n"
        logger.info(header.strip())
        log.write(header)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=work_dir
        )

        output_lines = []
        for line in process.stdout:
            #logger.info(line.strip())   # do not echo the subprocess output to rsync log file!
            log.write(line) # this write stdout to the table specific log file as intended.
            output_lines.append(line.strip())

        process.wait()

        footer = f"--- Finished {desc} at {datetime.now()} ---\n"
        logger.info(footer.strip())
        log.write(footer)

        return output_lines

    '''
    def run_post_import_resync_chain(csv_files, file_url, input_file):
        def extract_substring_from_csv(path):
            m = re.match(rf"{re.escape(input_file)}\.(.+)\.jira\.csv", os.path.basename(path))
            return m.group(1) if m else ""

        csv_files.sort(key=extract_substring_from_csv)

        for jira_csv in csv_files:
            match = re.match(rf"{re.escape(input_file)}\.(.+)\.jira\.csv", os.path.basename(jira_csv))
            if not match:
                continue
            substring = match.group(1)

            while True:
                run_and_log(
                    ["python", "-u", update_excel_script, jira_csv, input_file, timestamp],
                    log,
                    f"update_excel.py {jira_csv} {input_file} {timestamp}"
                )

                output_lines = run_and_log(
                    ["python", "-u", update_sharepoint_script, url, f"{input_file}.{substring}.changes.txt", timestamp],
                    log,
                    f"update_sharepoint.py {url} {input_file}.{substring}.changes.txt {timestamp}"
                )

                if any("Aborting update" in line for line in output_lines):
                    wait_msg = f"Aborting update detected for {jira_csv}, waiting 30 seconds before retry..."
                    logger.warning(wait_msg)
                    log.write(wait_msg + "\n")
                    time.sleep(30)
                    continue
                else:
                    break
    '''


    def process_yaml(file_url, input_file, timestamp):
        logger.info(f"Running scope.py on {input_file} timestamp={timestamp}...")
        run_and_log(["python", "-u", scope_script, input_file, timestamp], log, f"scope.py {input_file} {timestamp}")

        yaml_pattern = os.path.join(work_dir, f"{input_file}.*.{timestamp}.*scope.yaml")
        yaml_files = glob.glob(yaml_pattern)
        if not yaml_files:
            msg = f"No YAML files found matching pattern {yaml_pattern}"
            logger.warning(msg)
            log.write(msg + "\n")
            return

        def extract_substring(path):
            m = re.match(rf"{re.escape(input_file)}\.(.+)\.scope\.yaml", os.path.basename(path))
            return m.group(1) if m else ""

        yaml_files.sort(key=extract_substring)

        exec_summary_yaml_file = ""
        for yaml_file in yaml_files:
            logger.info(f"Processing YAML file: {yaml_file}")
            match = re.match(rf"{re.escape(input_file)}\.(.+)\.scope\.yaml", os.path.basename(yaml_file))
            if not match:
                continue
            substring = match.group(1)

            while True:
                logger.info(f"Re-downloading {file_url}...")
                run_and_log(["python", "-u", download_script, file_url, timestamp], log, f"download.py {file_url} {timestamp}")

                logger.info(f"Re-running scope.py on {input_file}...")
                run_and_log(["python", "-u", scope_script, input_file, timestamp], log, f"scope.py {input_file} {timestamp}")

                if "create" in yaml_file:
                    logger.info(f"Found CREATE jira file {yaml_file}")
                    run_and_log(["python", "-u", create_jira_script, yaml_file, filename, timestamp], log, f"create_jira.py {yaml_file} {filename} {timestamp}")
                
                #elif "ExecSummary" in yaml_file:
                #    logger.info("skipping ExecSummary yaml - will process at the end of yaml chain")
                #    exec_summary_yaml_file = yaml_file
                else:
                    jira_csv = f"{input_file}.{substring}.jira.csv"
                    logger.info(f"Generating Jira CSV: {jira_csv}")
                    run_and_log(["python", "-u", read_jira_script, yaml_file, timestamp], log, f"read_jira.py {yaml_file} {timestamp}")

                    logger.info(f"Updating Excel with {jira_csv}...")
                    run_and_log(["python", "-u", update_excel_script, jira_csv, input_file, timestamp], log, f"update_excel.py {jira_csv} {input_file} {timestamp}")

                logger.info(f"Updating SharePoint for {url} with changes from {input_file}.{substring}.changes.txt...")
                output_lines = run_and_log(
                    ["python", "-u", update_sharepoint_script, url, f"{input_file}.{substring}.changes.txt", timestamp],
                    log,
                    f"update_sharepoint.py {url} {input_file}.{substring}.changes.txt {timestamp}"
                )

                if any("Aborting update" in line for line in output_lines):
                    wait_msg = f"Aborting update detected for {yaml_file}, waiting 30 seconds before retry..."
                    logger.warning(wait_msg)
                    log.write(wait_msg + "\n")
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    time.sleep(30)
                    continue
                else:
                    
                    # now process exec_summary yaml file if one was present
                    #if (exec_summary_yaml_file):
                       #print(f"About to process exec summary file = {exec_summary_yaml_file}")    
                    
                    # all files are process now so end the loop
                    break

    def process_aibrief_yaml(file_url, input_file, timestamp):
        yaml_pattern = os.path.join(work_dir, f"{input_file}.*.{timestamp}.aisummary.yaml")
        yaml_files = glob.glob(yaml_pattern)
        if not yaml_files:
            msg = f"No aisummary.yaml files found matching pattern {yaml_pattern}"
            logger.warning(msg)
            log.write(msg + "\n")
            return

        def extract_substring(path):
            m = re.match(rf"{re.escape(input_file)}\.(.+)\.aisummary\.yaml", os.path.basename(path))
            return m.group(1) if m else ""

        yaml_files.sort(key=extract_substring)

        if yaml_files:
            logger.info(f"aisummary.yaml files found =  {yaml_files}")
        else:
            logger.info("No aisummary.yaml files found")

        for yaml_file in yaml_files:
            logger.info(f"Start processing {yaml_file}")
            run_and_log(["python", "-u", aibrief_script, yaml_file, timestamp], log, f"aibrief.py params = {yaml_file}, {timestamp}")
        


    def process_aibrief_changes_txt(file_url, input_file, timestamp):
        file_pattern = os.path.join(work_dir, f"{input_file}.*.aisummary.changes.txt")
        changes_files = glob.glob(file_pattern)
        if not changes_files:
            msg = f"No aisummary.changes.txt files found matching pattern {file_pattern}"
            logger.warning(msg)
            log.write(msg + "\n")
            return

        def extract_substring(path):
            m = re.match(rf"{re.escape(input_file)}\.(.+)\.aisummary\.yaml", os.path.basename(path))
            return m.group(1) if m else ""

        changes_files.sort(key=extract_substring)

        if changes_files:
            logger.info(f"aisummary.changes.txt files found =  {changes_files}")
        else:
            logger.info("No aisummary.changes.txt files found")

        for changes_file in changes_files:    
            logger.info(f"Updating SharePoint for {url} with changes from {changes_file}...")
            output_lines = run_and_log(
                ["python", "-u", update_sharepoint_script, url, changes_file, timestamp],
                log,
                f"update_sharepoint.py {url} {changes_file} {timestamp}"
            )
                


    with open(log_file, "w", encoding="utf-8") as log:
        try:
            run_and_log(["python", "-u", download_script, url, timestamp], log, f"download.py {url} {timestamp}")
            logger.info("about to call process_yaml")
            process_yaml(url, filename, timestamp)
            logger.info("about to call process_aibrief_yaml")
            process_aibrief_yaml(url, filename, timestamp)

            # need to download xlsx file again since process_yaml earlier updated
            # sharepoint and this means the meta data will not match any longer 
            logger.info(f"Re-downloading {url}...")
            run_and_log(["python", "-u", download_script, url, timestamp], log, f"download.py {url} {timestamp}")

            logger.info("about to call process_aibrief_changes_txt")
            process_aibrief_changes_txt(url, filename, timestamp)

        except Exception as e:
            err_msg = f"Error running resync: {e}"
            logger.exception(err_msg)
            log.write(err_msg + "\n")

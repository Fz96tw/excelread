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

from my_utils import *

from google_oauth_appnew import *

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
    backupCount=1,             # keep last 3 rotated logs
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

import time

def delete_old_folders_by_hours(path: str, hours: int):
    """
    Deletes folders inside `path` that are older than `hours` (based on creation time).
    
    :param path: Parent directory path to scan
    :param hours: Number of hours threshold for folder age
    """
    now = time.time()
    #cutoff = now - (hours * 60)  # seconds in an hour
    cutoff = now - (hours * 3600)  # seconds in an hour
    #cutoff = now - (days * 86400)  # seconds in a day

    logger.info(f"delete_old_folders_by_hours called for file path: {path}, hours:{hours}")
    
    if not os.path.exists(path):
        logger.warning(f"Path not found: {path}")
        return

    for item in os.listdir(path):
        item_path = os.path.join(path, item)

        if os.path.isdir(item_path):
            # Get folder creation time
            ctime = os.path.getctime(item_path)
            logger.info(f"Checking folder: {item_path}, created at {time.ctime(ctime)}")
            if ctime < cutoff:
                try:
                    shutil.rmtree(item_path)
                    logger.info(f"Deleted: {item_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete {item_path}: {e}")





def resync(url: str, userlogin, delegated_auth, workdir = None, ts = None):
    """
    Full resync process with recursive handling of YAML files.
    """

    import uuid
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    logger.info(f"run_id set to {run_id}")        


    # do this right here instead of later to limit the number of changes
    # needed to make to add support for sheet name
    sheet = "Sheet1"
    if "#" in url:
        sheet = url.split("#")[1]
        url = url.split("#")[0]


    sheet = unquote(sheet) #replace any %20 with space character 
    
   

    if is_googlesheet(url):
        try:
            if workdir:
                # needed because resync expects directoy to be same as appnew.py
                os.chdir("../../../")
                print(f"changed directory to ../../../ and now cwd={os.getcwd()}")
        
            logger.info("Detected Google Sheets URL")
    #        filename = url
            doc_id = extract_google_doc_id(url)
            basename = get_google_drive_filename(userlogin, doc_id) or doc_id
            filename = basename
        finally:
            if workdir:
                # needed because resync expects directoy to be same as appnew.py
                os.chdir(workdir)
                print(f"changed directory back to {workdir}")


    else:
        logger.info("Not a Google sheets URL, will treat as local or Sharepoint")
        # Parse a URL into 6 components:
        # <scheme>://<netloc>/<path>;<params>?<query>#<fragment>
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)  # e.g., Milestones.xlsx
        basename, _ = os.path.splitext(filename)      # e.g., Milestones

    filename = unquote(filename)  # decode %20 → space if there are space chars in filename
    url = unquote(url)            # decode %20 → space if there are space chars in url

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info(f"timestamp not provided, so generated new timestamp {timestamp}")        

    if ts is not None:
        timestamp = ts
        logger.info(f"timestamp provided, re-using {timestamp} instead")        

    logger.info(f"resync: timestamp = {timestamp}")
    base_dir = os.path.dirname(__file__)

    if workdir is None:
        work_dir = os.path.join(base_dir, "logs", userlogin, run_id)
        os.makedirs(work_dir, exist_ok=True)
        logger.info(f"workdir not provided, creating a new workdir {work_dir}")        
    else:
        logger.info(f"workdir provided: {workdir}")
        work_dir = workdir


#    logs_dir = os.path.join(base_dir, "logs")
    logs_dir = work_dir  # os.path.join(base_dir, f"logs/{userlogin}")  # keep log in the user folder same place as yaml and other temp fiels
    os.makedirs(logs_dir, exist_ok=True) 

    # keep sheet specific log files, makes it easuer to find log with resync is called for specific sheet
    log_file= os.path.join(logs_dir, f"{basename}.{sheet}.{timestamp}.log")

    fileinfo = {}
    fileinfo["filename"] = filename
    fileinfo["sheet"] = sheet
    fileinfo["url"] = url
    fileinfo["base_dir"] = base_dir
    fileinfo["basename"] = basename
    fileinfo["work_dir"] = work_dir
    fileinfo["logs_dir"] = logs_dir
    import json
    with open(f"{work_dir}/fileinfo.json", "w") as f:
        json.dump(fileinfo, f, indent=4)

    # Persistent rolling resync.log
    #resync_log = os.path.join(logs_dir, "resync.log")
    #with open(resync_log, "a", encoding="utf-8") as f:
    #    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
    #            f"Resync called on URL={url}, file={filename} timestamp={timestamp}\n")
    logger.info(f"Resync called on URL={url}, file={filename} timestamp={timestamp}\n")


    download_script = os.path.join(base_dir, "download.py")
    scope_script = os.path.join(base_dir, "scope.py")
    read_jira_script = os.path.join(base_dir, "read_jira.py")
    create_jira_script = os.path.join(base_dir, "create_jira.py")
    runrate_resolved_jira_script = os.path.join(base_dir, "runrate_resolved.py")
    runrate_assignee_jira_script = os.path.join(base_dir, "runrate_assignee.py")
    update_excel_script = os.path.join(base_dir, "update_excel.py")
    update_sharepoint_script = os.path.join(base_dir, "update_sharepoint.py")
    update_googlesheet_script = os.path.join(base_dir, "update_googlesheet.py")
    aibrief_script = os.path.join(base_dir, "aibrief.py")
    quickstart_script = os.path.join(base_dir, "quickstart.py")
    cycletime_script = os.path.join(base_dir, "cycletime.py")
    statustime_script = os.path.join(base_dir, "statustime.py")
    

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

    '''def run_post_import_resync_chain(csv_files, file_url, input_file):
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




    def process_yaml(file_url, input_file, sheet, timestamp, delegated_auth, userlogin):
        
        '''if is_googlesheet(file_url):
            logger.info("process_yaml: Detected Google Sheets URL")
            logger.info(f"Running scope.py on {file_url} {sheet} timestamp={timestamp}...")
            run_and_log(["python", "-u", scope_script, file_url, sheet, timestamp, userlogin], log, f"scope.py {file_url} {timestamp} {userlogin}")
        else:
            logger.info("process_yaml: Not a Google Sheets URL")
            logger.info(f"Running scope.py on {input_file} {sheet} timestamp={timestamp}...")
            run_and_log(["python", "-u", scope_script, input_file, sheet, timestamp, userlogin], log, f"scope.py {input_file} {timestamp} {userlogin}")
        '''
        input_file_orig = input_file

        if is_googlesheet(file_url):
            logger.info(f"process_yaml: Detected Google Sheets URL {file_url}")
            input_file = file_url       # for google sheets we pass the url to scope.py and not the filename. 
                                        # by doing this we can keep the rest of the code same below.
            
            # used further below to pick which update py script to run
            script_to_run = update_googlesheet_script 
            script_to_run_str = "update_googlesheet.py"
            logger.info(f"script_to_run set to update_googlesheet_script  for {file_url} when processing changes.txt")
            
        else:
            script_to_run = update_sharepoint_script
            script_to_run_str = "update_sharepoint.py"
            logger.info(f"script_to_run set to update_sharepoint.py for {file_url} when processing changes.txt...")

        logger.info(f"Running scope.py on {input_file} {sheet} timestamp={timestamp}...")
        run_and_log(["python", "-u", scope_script, input_file, sheet, timestamp, userlogin], log, f"scope.py {input_file} {timestamp} {userlogin}")

        yaml_pattern = os.path.join(work_dir, f"{input_file_orig}.*.{timestamp}.*scope.yaml")
        yaml_files = glob.glob(yaml_pattern)
        if not yaml_files:
            msg = f"No YAML files found matching pattern {yaml_pattern}"
            logger.warning(msg)
            log.write(msg + "\n")
            return

        def extract_substring(path):
            m = re.match(rf"{re.escape(input_file_orig)}\.(.+)\.scope\.yaml", os.path.basename(path))
            return m.group(1) if m else ""

        yaml_files.sort(key=extract_substring)

        exec_summary_yaml_file = ""
        for yaml_file in yaml_files:
            if sheet.lower() not in yaml_file.lower():
                logger.info(f"Skipping YAML file {yaml_file} as it does not match sheet {sheet}")
                continue
            logger.info(f"Processing YAML file: {yaml_file}")

            match = re.match(rf"{re.escape(input_file_orig)}\.(.+)\.scope\.yaml", os.path.basename(yaml_file))
            if not match:
                continue
            substring = match.group(1)

            while True:

                if not is_googlesheet(file_url):
                    # for google sheets we already ran scope.py once above so no need to do it again here.
                    logger.info(f"Re-downloading {file_url}...")
    #                run_and_log(["python", "-u", download_script, file_url, timestamp], log, f"download.py {file_url} {timestamp}")
                    if delegated_auth:
                        logger.info("delegated_auth detected")
                        run_and_log(["python", "-u", download_script, file_url, timestamp, "user_auth", userlogin], log, f"download.py {url} {timestamp} user_auth {userlogin}")
                    else:
                        run_and_log(["python", "-u", download_script, file_url, timestamp], log, f"download.py {url} {timestamp}")

                logger.info(f"Re-running scope.py on {input_file}...")
                run_and_log(["python", "-u", scope_script, input_file, sheet, timestamp, userlogin], log, f"scope.py {input_file} {sheet} {timestamp} {userlogin}")

                if "create" in yaml_file:
                    logger.info(f"Found CREATE jira file {yaml_file}")
                    run_and_log(["python", "-u", create_jira_script, yaml_file, filename, timestamp, userlogin], log, f"create_jira.py {yaml_file} {filename} {timestamp} {userlogin}")
                
                elif "resolved.rate" in yaml_file:
                    logger.info(f"Found RUNRATE  jira file {yaml_file}")
                    run_and_log(["python", "-u", runrate_resolved_jira_script, yaml_file, timestamp, userlogin], log, f"runrate_resolved_jira.py {yaml_file} {timestamp} {userlogin}")
                elif "assignee.rate" in yaml_file:
                    logger.info(f"Found RUNRATE  jira file {yaml_file}")
                    run_and_log(["python", "-u", runrate_assignee_jira_script, yaml_file, timestamp, userlogin], log, f"runrate_assignee_jira.py {yaml_file} {timestamp} {userlogin}")
                elif "cycletime.scope.yaml" in yaml_file:
                    logger.info(f"Found CYCLETIME scope yaml file {yaml_file}")
                    run_and_log(["python", "-u", cycletime_script, yaml_file, timestamp, userlogin], log, f"cycletime.py {yaml_file} {timestamp} {userlogin}")

                    # cycletime.py has output *.cyc.scope.yaml files that have to be processed                                
                    chain_yaml_pattern = os.path.join(work_dir, f"{input_file_orig}.*.{timestamp}.chain.scope.yaml")
                    chain_yaml_files = glob.glob(chain_yaml_pattern)
                    if not chain_yaml_files:
                        msg = f"No Chain YAML files found matching pattern {chain_yaml_pattern} after running cycletime.py"
                        logger.warning(msg)
                        log.write(msg + "\n")
                        return
                    
                    chain_yaml_files.sort(key=extract_substring)

                    for chain_yaml_file in chain_yaml_files:
                        if sheet.lower() not in chain_yaml_file.lower():
                            logger.info(f"Skipping Chain YAML file {chain_yaml_file} as it does not match sheet {sheet}")
                            continue
                        
                        logger.info(f"Processing Chain YAML file: {chain_yaml_file}")
                        match = re.match(f"{re.escape(input_file_orig)}\.(.+?)\.chain\.scope\.yaml", os.path.basename(chain_yaml_file))
                        if match:
                            substring_chain = match.group(1)
                            jira_csv = f"{input_file_orig}.{substring_chain}.jira.csv"
                            logger.info(f"Generating Jira CSV: {jira_csv}")
                            run_and_log(["python", "-u", read_jira_script, chain_yaml_file, timestamp, userlogin], log, f"read_jira.py {chain_yaml_file} {timestamp} {userlogin}")

                            # no need to call update_excel since jira csv data is not intended to be shown on spreadsheet.  
                            # The second follow up call to cycletime needs to procees the jira.csv that it generated
                            #logger.info(f"Updating Excel with {jira_csv}...")
                            #run_and_log(["python", "-u", update_excel_script, jira_csv, input_file, sheet, userlogin], log, f"update_excel.py {jira_csv} {input_file} {sheet} {userlogin}")
                        else:
                            print(f"re.match failed for ({input_file_orig})\.(.+)\.chain\.scope\.yaml, os.path.basename({chain_yaml_file})")

                    # at this point all the chain.jira.csv files should be created (or not if read_jira failed for valid reasons)
                    # so let's call cycletime again so it will discover and process these  jira.csv files now
                    logger.info("calling second pass of CYCLETIME to process all the chain.jira.csv files")
                    run_and_log(["python", "-u", cycletime_script, yaml_file, timestamp, userlogin], log, f"cycletime.py {yaml_file} {timestamp} {userlogin}")


                elif "statustime.scope.yaml" in yaml_file:
                    logger.info(f"Found STATUSTIME scope yaml file {yaml_file}")
                    run_and_log(["python", "-u", statustime_script, yaml_file, timestamp, userlogin], log, f"statustime.py {yaml_file} {timestamp} {userlogin}")
                elif "quickstart.scope.yaml" in yaml_file:
                    logger.info(f"Found QUIKSTART scope yaml file {yaml_file}")
                    run_and_log(["python", "-u", quickstart_script, yaml_file, timestamp], log, f"quickstart.py {yaml_file} {timestamp}")
                elif "aibrief.scope.yaml" in yaml_file:
                    # skip aibrief here since we will process them separately later
                    logger.info(f"Skipping aibrief scope yaml file {yaml_file} here, will process later separately")
                    break
                else:
                    jira_csv = f"{input_file_orig}.{substring}.jira.csv"
                    logger.info(f"Generating Jira CSV: {jira_csv}")
                    run_and_log(["python", "-u", read_jira_script, yaml_file, timestamp, userlogin], log, f"read_jira.py {yaml_file} {timestamp} {userlogin}")

                    logger.info(f"Updating Excel with {jira_csv}...")
                    run_and_log(["python", "-u", update_excel_script, jira_csv, input_file, sheet, userlogin], log, f"update_excel.py {jira_csv} {input_file} {sheet} {userlogin}")

                changes_file = f"{substring}.changes.txt"
                k = ["cycletime", "statustime","resolved", "assignee"]

                if any(s in changes_file for s in k):
                    changes_file = changes_file.replace(".changes.txt", ".import.changes.txt")
                    print(f"modified changes_file to include 'import' keyword =  {changes_file}")                    

                logger.info(f"Updating spreadsheet for {file_url} with changes from {input_file_orig}.{changes_file}...")
                #logger.info(f"Updating SharePoint for {url} with changes from {input_file}.{substring}.changes.txt...")
                if delegated_auth:
                    output_lines = run_and_log(
                    ["python", "-u", script_to_run, file_url, f"{input_file_orig}.{changes_file}", timestamp, userlogin, sheet, "--user_auth"],
                    log,
                    f"{script_to_run_str} {file_url} {input_file_orig}.{changes_file} {timestamp} {userlogin} '{sheet}' --user_auth"
                    )
                else:
                    output_lines = run_and_log(
                    ["python", "-u", script_to_run, file_url, f"{input_file_orig}.{changes_file}", timestamp, userlogin, sheet],
                    log,
                    f"{script_to_run_str} {file_url} {input_file_orig}.{changes_file} {timestamp} {userlogin} '{sheet}'"
                    )

                if any("Aborting update" in line for line in output_lines):
                    wait_msg = f"Aborting update detected for {yaml_file}, waiting 30 seconds before retry..."
                    logger.warning(wait_msg)
                    log.write(wait_msg + "\n")

                    #commented out possible bug. read_jira and update_excel were cusing diff timestamps after an Abort. ?!
                    # prob ok to re-use the same timestamp because files will be overwritten anyway.
                    #timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")   #commented out possible bug. read_jira and update_excel were cusing diff timestamps after an Abort. ?!
                    
                    time.sleep(30)
                    continue
                else:
                    
                    # now process exec_summary yaml file if one was present
                    #if (exec_summary_yaml_file):
                       #print(f"About to process exec summary file = {exec_summary_yaml_file}")    
                    
                    # all files are process now so end the loop
                    break
 


    def process_aibrief_yaml(file_url, input_file, timestamp, userlogin, delegated_auth):
        yaml_pattern = os.path.join(work_dir, f"{input_file}.*.{timestamp}.aibrief.scope.yaml")
        yaml_files = glob.glob(yaml_pattern)
        
        if not yaml_files:
            msg = f"No aibrief.scope.yaml files found matching pattern {yaml_pattern}"
            logger.warning(msg)
            log.write(msg + "\n")
            return

        def extract_substring(path):
            m = re.match(rf"{re.escape(input_file)}\.(.+)\.aisummary\.yaml", os.path.basename(path))
            return m.group(1) if m else ""

        yaml_files.sort(key=extract_substring)

        if yaml_files:
            logger.info(f"aibrief.scope.yaml files found =  {yaml_files}")
        else:
            logger.info("No aibrief.scope.yaml files found")

        for yaml_file in yaml_files:
            if sheet.lower() not in yaml_file.lower():
                logger.info(f"Skipping YAML file {yaml_file} as it does not match sheet {sheet}")
                continue

            logger.info(f"Start processing {yaml_file}")
            cmd = ["python", "-u", aibrief_script, file_url, yaml_file, timestamp, userlogin]
            if delegated_auth:
                logger.info("delegated_auth detected, adding --user_auth to aibrief.py call")
                cmd.append("--user_auth")
            #run_and_log(["python", "-u", aibrief_script, file_url, yaml_file, timestamp, userlogin], log, f"aibrief.py {yaml_file} {timestamp} {userlogin}")
            run_and_log(cmd, log, f"aibrief.py {yaml_file} {timestamp} {userlogin}")
  


    def process_aibrief_changes_txt(file_url, sheet, input_file, timestamp):
        file_pattern = os.path.join(work_dir, f"{input_file}.*.aibrief.changes.txt")
        changes_files = glob.glob(file_pattern)
        if not changes_files:
            msg = f"No aibrief.changes.txt files found matching pattern {file_pattern}"
            logger.warning(msg)
            log.write(msg + "\n")
            return

        def extract_substring(path):
            m = re.match(rf"{re.escape(input_file)}\.(.+)\.aibrief\.scope\.yaml", os.path.basename(path))
            return m.group(1) if m else ""

        changes_files.sort(key=extract_substring)

        if changes_files:
            logger.info(f"aibrief.changes.txt files found =  {changes_files}")
        else:
            logger.info("No aibrief.changes.txt files found")


        if is_googlesheet(file_url):
            logger.info(f"process_aibrief_changes_txt: Detected Google Sheets URL {file_url}")
            input_file = file_url       # for google sheets we pass the url to scope.py and not the filename. 
                                        # by doing this we can keep the rest of the code same below.
            
            # used further below to pick which update py script to run
            script_to_run = update_googlesheet_script 
            script_to_run_str = "update_googlesheet.py"
            logger.info(f"script_to_run set to update_googlesheet_script  for {file_url} when processing changes.txt")
            
        else:
            script_to_run = update_sharepoint_script
            script_to_run_str = "update_sharepoint.py"
            logger.info(f"script_to_run set to update_sharepoint.py for {file_url} when processing changes.txt...")

        for changes_file in changes_files:   
            while True:    
                if sheet.lower() not in changes_file.lower():
                    logger.info(f"Skipping changes file {changes_file} as it does not match sheet {sheet}")
                    break

                logger.info(f"Updating spreadsheet for {file_url} with changes from {changes_file}...")
                if delegated_auth:
                    output_lines = run_and_log(
                    #["python", "-u", update_sharepoint_script, url, f"{input_file}.{substring}.changes.txt", timestamp, userlogin, "--user_auth"],
                    ["python", "-u", script_to_run, file_url, changes_file, timestamp, userlogin, sheet, "--user_auth"],
                    log,
                    f"{script_to_run_str} {file_url} {changes_file} {timestamp} {userlogin} {sheet} --user_auth"
                    )
                else:
                    output_lines = run_and_log(
                    ["python", "-u", script_to_run, file_url, changes_file, timestamp, userlogin, sheet],
                    log,
                    f"{script_to_run_str} {file_url} {changes_file} {timestamp} {userlogin} {sheet}"
                    )
            
                if any("Aborting update" in line for line in output_lines):
                    wait_msg = f"Aborting update detected for {changes_file}, waiting 30 seconds before retry..."
                    logger.warning(wait_msg)
                    log.write(wait_msg + "\n")

                    #commented out possible bug. read_jira and update_excel were cusing diff timestamps after an Abort. ?!
                    # prob ok to re-use the same timestamp because files will be overwritten anyway.
                    #timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")   #commented out possible bug. read_jira and update_excel were cusing diff timestamps after an Abort. ?!
                    
                    time.sleep(30)
                    
                    # we had tag mismatch so let's download again to update file and tag
                    logger.info(f"Re-downloading {file_url}...")
        #                run_and_log(["python", "-u", download_script, file_url, timestamp], log, f"download.py {file_url} {timestamp}")
                    if delegated_auth:
                        logger.info("delegated_auth detected")
                        run_and_log(["python", "-u", download_script, file_url, timestamp, "user_auth", userlogin], log, f"download.py {url} {timestamp} user_auth {userlogin}")
                    else:
                        run_and_log(["python", "-u", download_script, file_url, timestamp], log, f"download.py {url} {timestamp}")

                    continue

                else:
                    
                    # now process exec_summary yaml file if one was present
                    #if (exec_summary_yaml_file):
                        #print(f"About to process exec summary file = {exec_summary_yaml_file}")    
                    
                    # all files are process now so end the loop
                    break
           


    with open(log_file, "w", encoding="utf-8") as log:
        try:
            if not is_googlesheet(url):
                logger.info(f"Downloading {url}...")
                if delegated_auth:
                    logger.info("delegated_auth detected")
                    run_and_log(["python", "-u", download_script, url, timestamp, "user_auth", userlogin], log, f"download.py {url} {timestamp} user_auth {userlogin}")
                else:
                    run_and_log(["python", "-u", download_script, url, timestamp], log, f"download.py {url} {timestamp}")
            

            logger.info("about to call process_yaml")
            process_yaml(url, filename, sheet, timestamp, delegated_auth, userlogin)
            
            logger.info("about to call process_aibrief_yaml")
            process_aibrief_yaml(url, filename, timestamp, userlogin, delegated_auth)

            # need to download xlsx file again since process_yaml earlier updated
            # sharepoint and this means the meta data will not match any longer 
            if not is_googlesheet(url):
                logger.info(f"Re-downloading {url}...")
    #            run_and_log(["python", "-u", download_script, url, timestamp], log, f"download.py {url} {timestamp}")
                if delegated_auth:
                    logger.info("delegated_auth detected")
                    run_and_log(["python", "-u", download_script, url, timestamp, "user_auth", userlogin], log, f"download.py {url} {timestamp} user_auth {userlogin}")
                else:
                    run_and_log(["python", "-u", download_script, url, timestamp], log, f"download.py {url} {timestamp}")

            logger.info("about to call process_aibrief_changes_txt")
            process_aibrief_changes_txt(url, sheet, filename, timestamp)

        except Exception as e:
            err_msg = f"Error while running resync: {e}"
            logger.exception(err_msg)
            log.write(err_msg + "\n")


    userfolder = f"{work_dir}/../"
    delete_old_folders_by_hours(userfolder,24)   # remove user-level temporary file that are older than 24 hour


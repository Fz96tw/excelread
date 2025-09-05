import subprocess
import os
from urllib.parse import urlparse
from datetime import datetime
import sys
import glob
import re
import time

import shutil

def move_temp_files():
    # Ensure target folder exists
    target_dir = os.path.join("logs", "temp")
    os.makedirs(target_dir, exist_ok=True)

    # File patterns to move
    patterns = ["*.scope.yaml", "*.changes.txt", "*.meta.json", "*.jira.csv"]

    for pattern in patterns:
        for file_path in glob.glob(pattern):
            dest = os.path.join(target_dir, os.path.basename(file_path))
            print(f"Moving {file_path} → {dest}")
            shutil.move(file_path, dest)


def resync(url: str):
    """
    Full resync process with recursive handling of YAML files.
    """
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)  # e.g., Milestones.xlsx
    basename, _ = os.path.splitext(filename)      # e.g., Milestones

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"resync: timestamp = {timestamp}")
    base_dir = os.path.dirname(__file__)

    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_file = os.path.join(logs_dir, f"{basename}_{timestamp}.log")

    # Persistent rolling resync.log
    resync_log = os.path.join(logs_dir, "resync.log")

    # Append entry to resync.log
    with open(resync_log, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Resync called on URL={url}, file={filename} timestamp={timestamp}\n")


    download_script = os.path.join(base_dir, "download.py")
    scope_script = os.path.join(base_dir, "scope.py")
    read_jira_script = os.path.join(base_dir, "read_jira.py")
    create_jira_script = os.path.join(base_dir, "create_jira.py")
    update_excel_script = os.path.join(base_dir, "update_excel.py")
    update_sharepoint_script = os.path.join(base_dir, "update_sharepoint.py")

    def run_and_log(cmd, log, desc):
        """Run a command and log output."""
        header = f"\n--- Running {desc} at {datetime.now()} ---\n"
        print(header, end="")
        log.write(header)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=base_dir
        )

        output_lines = []
        for line in process.stdout:
            sys.stdout.write(line)
            log.write(line)
            output_lines.append(line.strip())

        process.wait()

        footer = f"--- Finished {desc} at {datetime.now()} ---\n"
        print(footer, end="")
        log.write(footer)

        return output_lines

    def process_import_yaml(file_url, input_file):

        csv_files = []
        from pathlib import Path
        import shutil

        directory = Path("./")  # replace with your directory
        destination_dir = Path("./")  # where new files will go
        #destination_dir.mkdir(parents=True, exist_ok=True)  # create if not exists

        # Find all *.import.jira.csv files
        for file_path in directory.glob("*.import.jira.csv"):
            # Remove "import." from filename
            new_name = file_path.name.replace("import.", "")
            new_path = destination_dir / new_name

            # Copy file to new path
            shutil.copy(file_path, new_path)
            print(f"Copied '{file_path.name}' → '{new_name}'")

            csv_files.append(new_path)

            run_post_import_resync_chain(csv_files,file_url, input_file)


    def run_post_import_resync_chain(csv_files,file_url, input_file):


        # Sort YAML files by substring between filename and .scope.yaml
        def extract_substring_from_csv(path):
            m = re.match(rf"{re.escape(input_file)}\.(.+)\.jira\.csv", os.path.basename(path))
            return m.group(1) if m else ""

        csv_files.sort(key=extract_substring_from_csv)

        for jira_csv in csv_files:

            # Extract the substring matched by '*' in filename.*.scope.yaml
            match = re.match(rf"{re.escape(input_file)}\.(.+)\.jira\.csv", os.path.basename(yaml_file))
            if not match:
                continue
            substring = match.group(1)            
            
            # Define retry loop for this csv file
            while True:

                # Update Excel
                run_and_log(
                    ["python", "-u", update_excel_script, jira_csv, input_file, timestamp],
                    log,
                    f"update_excel.py {jira_csv} {input_file} timestamp"
                )
                    
                # Update SharePoint and capture output
                output_lines = run_and_log(
                    ["python", "-u", update_sharepoint_script, url, f"{input_file}.{substring}.changes.txt",timestamp],
                    log,
                    f"update_sharepoint.py {url} {input_file}.{substring}.{timestamp}.changes.txt {timestamp}"
                )

                # Check if "Aborting update" is in output
                if any("Aborting update" in line for line in output_lines):
                    wait_msg = f"Aborting update detected for {yaml_file}, waiting 30 seconds before retry...\n"
                    print(wait_msg, end="")
                    log.write(wait_msg)
                    time.sleep(30)
                    continue  # retry the loop
                else:
                    break  # success, move to next yaml_file




    def process_yaml(file_url, input_file, timestamp):
        """
        Given a URL and an input file, run scope.py and then recursively process all generated YAML files.
        """
        # Run scope.py on the input file
        print(f"refresh.py Running scope.py on {input_file} timestamp={timestamp}...")
        run_and_log(
            ["python", "-u", scope_script, input_file, timestamp],
            log,
            f"scope.py {input_file} {timestamp}"
        )

        # Find all YAML files generated by scope.py
        yaml_pattern = os.path.join(base_dir, f"{input_file}.*.{timestamp}.*scope.yaml")
        yaml_files = glob.glob(yaml_pattern)
        if not yaml_files:
            msg = f"No YAML files found matching pattern {yaml_pattern}\n"
            print(msg, end="")
            log.write(msg)
            return


        # Sort YAML files by substring between filename and .scope.yaml
        def extract_substring(path):
            m = re.match(rf"{re.escape(input_file)}\.(.+)\.scope\.yaml", os.path.basename(path))
            return m.group(1) if m else ""

        yaml_files.sort(key=extract_substring)
            
        

        for yaml_file in yaml_files:
            print(f"refresh.py Processing YAML file: {yaml_file}")
            # Extract the substring matched by '*' in filename.*.scope.yaml
            match = re.match(rf"{re.escape(input_file)}\.(.+)\.scope\.yaml", os.path.basename(yaml_file))
            if not match:
                continue
            substring = match.group(1)

            # Define retry loop for this YAML file
            while True:
                # Re-run download.py on the original URL
                print(f"refresh.py Re-downloading {file_url}...")
                run_and_log(["python", "-u", download_script, file_url,timestamp], log, f"download.py {file_url} {timestamp}")

                # Run scope.py on the input file again
                print(f"refresh.py Re-running scope.py on {input_file}...")
                run_and_log(["python", "-u", scope_script, input_file,timestamp], log, f"scope.py {input_file} {timestamp}")

                if "create" in yaml_file:
                    print(f"refresh.py Found CREATE jira file {yaml_file}")
                    run_and_log(
                        ["python", "-u", create_jira_script, yaml_file, filename, timestamp],
                        log,
                        f"create_jira.py {yaml_file} {filename}, {timestamp}"
                    )
                else:
                    # Generate CSV file for Jira
                    jira_csv = f"{input_file}.{substring}.jira.csv"
                    print(f"refresh.py Generating Jira CSV: {jira_csv}")
                    run_and_log(
                        ["python", "-u", read_jira_script, yaml_file, timestamp],
                        log,
                        f"read_jira.py {yaml_file}, {timestamp}"
                    )

                    # Update Excel
                    print(f"refresh.py Updating Excel with {jira_csv}...")
                    run_and_log(
                        ["python", "-u", update_excel_script, jira_csv, input_file, timestamp],
                        log,
                        f"update_excel.py {jira_csv} {input_file}, {timestamp}"
                    )

                # Update SharePoint and capture output
                print(f"refresh.py Updating SharePoint for {url} with changes from {input_file}.{substring}.changes.txt...")    
                output_lines = run_and_log(
                    ["python", "-u", update_sharepoint_script, url, f"{input_file}.{substring}.changes.txt", timestamp],
                    log,
                    f"update_sharepoint.py {url} {input_file}.{substring}.changes.txt {timestamp}"
                )

                # Check if "Aborting update" is in output
                if any("Aborting update" in line for line in output_lines):
                    wait_msg = f"Aborting update detected for {yaml_file}, waiting 30 seconds before retry...\n"
                    print(wait_msg, end="")
                    log.write(wait_msg)
                    time.sleep(30)
                    # get a new timestamp tag for the data files since we will be featching  xls and process again
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    continue  # retry the loop
                else:
                    break  # success, move to next yaml_file


    with open(log_file, "a", encoding="utf-8") as log:
        try:

            move_temp_files()

            # Step 1: initial download
            run_and_log(["python", "-u", download_script, url, timestamp], log, f"download.py {url}, {timestamp}")

            # Step 2: initial scope processing
            process_yaml(url, filename, timestamp)

            # now post-process any import.yaml files that might have been generated
            # Find all import YAML files generated by scope.py
            #process_import_yaml(url, filename)

        except Exception as e:
            err_msg = f"Error running resync: {e}\n"
            print(err_msg, end="")
            log.write(err_msg)

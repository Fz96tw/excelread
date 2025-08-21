import subprocess
import os
from urllib.parse import urlparse
from datetime import datetime
import sys
import glob

def resync(url: str):
    """
    Full resync process:
    1. download.py <url>
    2. scope.py <filename> <url>
    3. read_jira.py for each *.scope.yaml
    4. update_excel.py for each *.jira.csv with original filename
    5. update_sharepoint.py for each corresponding *.changes.txt derived from CSV
    Logs all outputs to stdout and timestamped logfile in logs/ folder.
    """
    # Extract filename from URL
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)  # e.g., Milestones.xlsx
    basename, _ = os.path.splitext(filename)      # e.g., Milestones

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    base_dir = os.path.dirname(__file__)

    # Create logs folder if it doesn't exist
    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_file = os.path.join(logs_dir, f"{basename}_{timestamp}.log")
    
    # Script paths
    download_script = os.path.join(base_dir, "download.py")
    scope_script = os.path.join(base_dir, "scope.py")
    read_jira_script = os.path.join(base_dir, "read_jira.py")
    update_excel_script = os.path.join(base_dir, "update_excel.py")
    update_sharepoint_script = os.path.join(base_dir, "update_sharepoint.py")

    def run_and_log(cmd, log, desc):
        """Run a command, log stdout/stderr to log and console, return output lines as list."""
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

    with open(log_file, "a", encoding="utf-8") as log:
        try:
            # Step 1: download.py <url>
            run_and_log(["python", "-u", download_script, url], log, f"download.py {url}")

            # Step 2: scope.py <filename> <url>
            run_and_log(
                ["python", "-u", scope_script, filename, url],
                log,
                f"scope.py {filename} {url}"
            )

            # Step 3: read_jira.py for each *.scope.yaml
            yaml_pattern = os.path.join(base_dir, f"{filename}.*.scope.yaml")
            yaml_files = glob.glob(yaml_pattern)
            if not yaml_files:
                msg = f"No YAML files found matching pattern {yaml_pattern}\n"
                print(msg, end="")
                log.write(msg)

            jira_csv_files = []
            for yaml_file in yaml_files:
                output_lines = run_and_log(
                    ["python", "-u", read_jira_script, yaml_file],
                    log,
                    f"read_jira.py {yaml_file}"
                )
                # Collect generated CSVs
                for line in output_lines:
                    if line.startswith("CSV_CREATED:"):
                        csv_path = line.replace("CSV_CREATED:", "").strip()
                        jira_csv_files.append(csv_path)

            # Step 4: update_excel.py for each *.jira.csv
            for csv_file in jira_csv_files:
                run_and_log(
                    ["python", "-u", update_excel_script, csv_file, filename],
                    log,
                    f"update_excel.py {csv_file} {filename}"
                )

            # Step 5: update_sharepoint.py for each changes file derived from CSVs
            for csv_file in jira_csv_files:
                changes_file = csv_file.replace(".jira.csv", ".changes.txt")
                run_and_log(
                    ["python", "-u", update_sharepoint_script, url, changes_file],
                    log,
                    f"update_sharepoint.py {url} {changes_file}"
                )

        except Exception as e:
            err_msg = f"Error running resync: {e}\n"
            print(err_msg, end="")
            log.write(err_msg)

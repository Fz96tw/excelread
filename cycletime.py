from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Any, Tuple
import statistics


def calculate_average_status_transition_time(jira_issues: List[Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Calculate the average time it takes to transition between each status for a list of JIRA issues.
    
    Args:
        jira_issues: List of JIRA issues (can be dictionaries or JIRA Issue objects)
                    Can handle both:
                    - Dictionary format with 'key', 'changelog' structure
                    - JIRA library Issue objects with .key, .changelog attributes
    
    Returns:
        Dict with transition pairs as keys (from_status, to_status) and values containing:
        - 'average_hours': Average time in hours
        - 'average_days': Average time in days
        - 'count': Number of transitions observed
        - 'durations': List of all durations for this transition (in hours)
    """
    
    # Dictionary to store all transition durations
    # Key: (from_status, to_status), Value: list of durations in hours
    transition_durations = defaultdict(list)
    
    print(f"Calculating status transition times for {len(jira_issues)} issues...")

    for issue in jira_issues:
        # Handle both dictionary and JIRA Issue object formats
        if hasattr(issue, 'key'):
            # JIRA Issue object
            issue_key = issue.key
            # Get changelog - need to expand it first if not already done
            if hasattr(issue, 'changelog') and issue.changelog:
                changelog = issue.changelog
            else:
                print(f"Warning: Issue {issue_key} does not have changelog data. Make sure to include 'expand=\"changelog\"' in your JIRA query.")
                continue
                
            # Get issue creation time for first transitions
            creation_time = None
            if hasattr(issue, 'fields') and hasattr(issue.fields, 'created'):
                try:
                    creation_time = parse_jira_timestamp(issue.fields.created)
                    print(f"  Issue {issue_key} created at: {creation_time}")
                except ValueError as e:
                    print(f"Warning: Could not parse creation time for {issue_key}: {e}")
        else:
            # Dictionary format
            issue_key = issue.get('key', 'Unknown')
            changelog = issue.changelog
            # Try to get creation time from dictionary format
            creation_time = None
            fields = issue.get('fields', {})
            if 'created' in fields:
                try:
                    creation_time = parse_jira_timestamp(fields['created'])
                except ValueError:
                    pass
        
        # Handle both dictionary and JIRA Issue object changelog formats
        if hasattr(changelog, 'histories'):
            # JIRA Issue object - changelog is an object with histories attribute
            histories = changelog.histories
        else:
            # Dictionary format
            histories = changelog.get('histories', []) if isinstance(changelog, dict) else []
        
        if not histories:
            print(f"Warning: No changelog found for issue {issue_key}")
            continue
        
        # Extract status changes with timestamps
        status_changes = []
        
        for history in sorted(histories, key=lambda h: getattr(h, 'created', '') if hasattr(h, 'created') else h.get('created', '')):
            # Handle both object and dictionary formats for history
            if hasattr(history, 'created'):
                created_str = history.created
            else:
                created_str = history.get('created', '')
                
            if not created_str:
                continue
                
            try:
                # Parse JIRA timestamp format
                timestamp = parse_jira_timestamp(created_str)
            except ValueError as e:
                print(f"Warning: Could not parse timestamp '{created_str}' for issue {issue_key}: {e}")
                continue
            
            # Look for status changes in this history entry
            if hasattr(history, 'items'):
                items = history.items
            else:
                items = history.get('items', [])
                
            for item in items:
                # Handle both object and dictionary formats for items
                if hasattr(item, 'field'):
                    field = item.field
                    from_status = getattr(item, 'fromString', None)
                    to_status = getattr(item, 'toString', None)
                else:
                    field = item.get('field')
                    from_status = item.get('fromString')
                    to_status = item.get('toString')
                
                if field == 'status' and from_status and to_status:
                    print(f"  Issue {issue_key} status change: {from_status} -> {to_status} at {timestamp}")
                    status_changes.append({
                        'timestamp': timestamp,
                        'from_status': from_status,
                        'to_status': to_status
                    })
        
        # Calculate durations between consecutive status changes
        # For each transition, measure time since the previous status change or creation
        for i in range(len(status_changes)):
            change = status_changes[i]
            from_status = change['from_status']
            to_status = change['to_status']
            
            previous_timestamp = None
            
            if i == 0:
                # For the first transition, use issue creation time if available
                if creation_time:
                    previous_timestamp = creation_time
                    print(f"    Using creation time for first transition: {issue_key}")
                else:
                    print(f"    Skipping first transition for {issue_key}: {from_status} -> {to_status} (no creation time available)")
                    continue
            else:
                # For subsequent transitions, use the timestamp of the previous change
                previous_timestamp = status_changes[i-1]['timestamp']
            
            # Calculate duration between consecutive status changes
            if previous_timestamp:
                duration_hours = (change['timestamp'] - previous_timestamp).total_seconds() / 3600
                if duration_hours >= 0:  # Ensure positive duration
                    transition_key = (from_status, to_status)
                    transition_durations[transition_key].append(duration_hours)
                    duration_minutes = duration_hours * 60
                    print(f"    Calculated duration: {from_status} -> {to_status} = {duration_hours:.6f} hours ({duration_minutes:.2f} minutes)")
    
    # Calculate averages and compile results
    results = {}
    
    for (from_status, to_status), durations in transition_durations.items():
        if durations:  # Only include transitions with data
            avg_hours = statistics.mean(durations)
            avg_days = avg_hours / 24
            
            results[(from_status, to_status)] = {
                'average_hours': round(avg_hours, 6),  # More precision for small durations
                'average_minutes': round(avg_hours * 60, 2),  # Also show in minutes
                'average_days': round(avg_days, 2),
                'count': len(durations),
                'durations': durations,
                'median_hours': round(statistics.median(durations), 6),
                'min_hours': round(min(durations), 6),
                'max_hours': round(max(durations), 6)
            }
    
    print(f"Calculated {len(results)} unique status transitions.")

    return results



def calculate_average_status_transition_time_old(jira_issues: List[Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Calculate the average time it takes to transition between each status for a list of JIRA issues.
    
    Args:
        jira_issues: List of JIRA issues (can be dictionaries or JIRA Issue objects)
                    Can handle both:
                    - Dictionary format with 'key', 'changelog' structure
                    - JIRA library Issue objects with .key, .changelog attributes
    
    Returns:
        Dict with transition pairs as keys (from_status, to_status) and values containing:
        - 'average_hours': Average time in hours
        - 'average_days': Average time in days
        - 'count': Number of transitions observed
        - 'durations': List of all durations for this transition (in hours)
    """
    
    # Dictionary to store all transition durations
    # Key: (from_status, to_status), Value: list of durations in hours
    transition_durations = defaultdict(list)
    
    print(f"Calculating status transition times for {len(jira_issues)} issues...")

    for issue in jira_issues:
        # Handle both dictionary and JIRA Issue object formats
        if hasattr(issue, 'key'):
            # JIRA Issue object
            issue_key = issue.key
            # Get changelog - need to expand it first if not already done
            if hasattr(issue, 'changelog') and issue.changelog:
                changelog = issue.changelog
            else:
                print(f"Warning: Issue {issue_key} does not have changelog data. Make sure to include 'expand=\"changelog\"' in your JIRA query.")
                continue
        else:
            # Dictionary format
            issue_key = issue.get('key', 'Unknown')
            changelog = issue.changelog
        
        # Handle both dictionary and JIRA Issue object changelog formats
        if hasattr(changelog, 'histories'):
            # JIRA Issue object - changelog is an object with histories attribute
            histories = changelog.histories
        else:
            # Dictionary format
            histories = changelog.get('histories', []) if isinstance(changelog, dict) else []
        
        if not histories:
            print(f"Warning: No changelog found for issue {issue_key}")
            continue
        
        # Extract status changes with timestamps
        status_changes = []
        
        # Add initial status if available (assuming it was created with first status)
        current_status = None
        
        for history in sorted(histories, key=lambda h: getattr(h, 'created', '') if hasattr(h, 'created') else h.get('created', '')):
            # Handle both object and dictionary formats for history
            if hasattr(history, 'created'):
                created_str = history.created
            else:
                created_str = history.get('created', '')
                
            if not created_str:
                continue
                
            try:
                # Parse JIRA timestamp format
                timestamp = parse_jira_timestamp(created_str)
            except ValueError as e:
                print(f"Warning: Could not parse timestamp '{created_str}' for issue {issue_key}: {e}")
                continue
            
            # Look for status changes in this history entry
            if hasattr(history, 'items'):
                items = history.items
            else:
                items = history.get('items', [])
                
            for item in items:
                # Handle both object and dictionary formats for items
                if hasattr(item, 'field'):
                    field = item.field
                    from_status = getattr(item, 'fromString', None)
                    to_status = getattr(item, 'toString', None)
                else:
                    field = item.get('field')
                    from_status = item.get('fromString')
                    to_status = item.get('toString')
                
                if field == 'status' and from_status and to_status:
                        print(f"  Issue {issue_key} status change: {from_status} -> {to_status} at {timestamp}")
                        status_changes.append({
                            'timestamp': timestamp,
                            'from_status': from_status,
                            'to_status': to_status
                        })
        
        # Calculate durations between consecutive status changes
        for i in range(len(status_changes)):
            change = status_changes[i]
            from_status = change['from_status']
            to_status = change['to_status']
            
            # Find the previous timestamp for this "from_status"
            # This could be either from a previous status change or issue creation
            previous_timestamp = None
            
            if i > 0:
                # Look for when we last entered the "from_status"
                for j in range(i - 1, -1, -1):
                    if status_changes[j]['to_status'] == from_status:
                        previous_timestamp = status_changes[j]['timestamp']
                        break
            
            # If we found a previous timestamp, calculate duration
            if previous_timestamp:
                duration_hours = (change['timestamp'] - previous_timestamp).total_seconds() / 3600
                if duration_hours >= 0:  # Ensure positive duration
                    transition_key = (from_status, to_status)
                    transition_durations[transition_key].append(duration_hours)
    
    # Calculate averages and compile results
    results = {}
    
    for (from_status, to_status), durations in transition_durations.items():
        if durations:  # Only include transitions with data
            avg_hours = statistics.mean(durations)
            avg_days = avg_hours / 24
            
            results[(from_status, to_status)] = {
                'average_hours': round(avg_hours, 2),
                'average_days': round(avg_days, 2),
                'count': len(durations),
                'durations': durations,
                'median_hours': round(statistics.median(durations), 2),
                'min_hours': round(min(durations), 2),
                'max_hours': round(max(durations), 2)
            }
    
    return results


def parse_jira_timestamp(timestamp_str: str) -> datetime:
    import re
    from datetime import timezone
    
    ts = timestamp_str.strip()
    
    # Convert -0400 to -04:00 format
    tz_pattern = r'([+-])(\d{2})(\d{2})$'
    match = re.search(tz_pattern, ts)
    if match:
        sign, hours, minutes = match.groups()
        ts = re.sub(tz_pattern, f'{sign}{hours}:{minutes}', ts)
    
    formats = [
        '%Y-%m-%dT%H:%M:%S.%f%z',  # 2025-09-02T23:31:32.138-04:00
        '%Y-%m-%dT%H:%M:%S%z',     # 2025-09-02T23:31:32-04:00
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    
    raise ValueError(f"Unable to parse timestamp: {timestamp_str}")


def print_transition_report(transition_data: Dict[Tuple[str, str], Dict[str, Any]]) -> None:
    """
    Print a formatted report of status transition times.
    """
    if not transition_data:
        print("No status transitions found in the provided issues.")
        return
    
    print("JIRA Status Transition Time Analysis")
    print("=" * 50)
    
    # Sort transitions by average time (descending)
    sorted_transitions = sorted(
        transition_data.items(),
        key=lambda x: x[1]['average_hours'],
        reverse=True
    )
    
    for (from_status, to_status), data in sorted_transitions:
        print(f"\n{from_status} → {to_status}")
        print(f"  Average Time: {data['average_hours']:.1f} hours ({data['average_days']:.1f} days)")
        print(f"  Median Time:  {data['median_hours']:.1f} hours")
        print(f"  Range:        {data['min_hours']:.1f} - {data['max_hours']:.1f} hours")
        print(f"  Sample Size:  {data['count']} transitions")




import os
import sys
import yaml
from datetime import datetime
from urllib.parse import unquote
from openpyxl.utils import get_column_letter

if len(sys.argv) < 4:
    print("Usage: python cycletime.py <yaml_file> <timestamp> <userlogin>")
    sys.exit(1)

yaml_file = sys.argv[1]
timestamp = sys.argv[2]
userlogin = sys.argv[3]

print(f"cycletime parameters  yaml_file={yaml_file} timestamp={timestamp} userlogin={userlogin}")

with open(yaml_file, 'r') as f:
    data = yaml.safe_load(f)

fileinfo = data.get('fileinfo', {})
if not fileinfo:
    print("No fileinfo found in the YAML file.")
    sys.exit(1)
basename = fileinfo.get('basename')
tablename = fileinfo.get('table').replace(" ", "_") if fileinfo.get('table') else ""
source = fileinfo.get('source')
scope_file = fileinfo.get('scope file')

if not basename:
    print("No 'basename'found in fileinfo. Expecting 'basename' key.")
    sys.exit(1)

if not tablename:
    print("No 'table' found in fileinfo. Expecting 'table' key.")
    sys.exit(1)


# I don't think this code is doing anything useful. It always sets create_mode to True?! since 
# Determine if we will be INSERTING rows eventually vs just UPDATING existing rows in Excel/SharePoint
if "cycletime.scope" in yaml_file.lower():
    print(f"cycletime detected based on filename: {yaml_file}.")
    # You can set a flag or handle import-specific logic here if needed
    output_file = basename + "." + tablename + timestamp + ".cycletime.jira.csv"
    #mode = "assignee" #"resolved"
else:
    print("Error: YAML filename is not 'cycletime.scope.yaml")
    sys.exit(1)

fields = data.get('fields', [])
# Convert list of dicts into a dictionary
fields_dict = {field["value"]: field.get("index", "<blank>") for field in fields}

field_values = [field.get('value') for field in fields if 'value' in field]
field_indexes = [field.get('index') for field in fields if 'index' in field]
field_values_str = ','.join(field_values)
field_indexes_str = ','.join(map(str, field_indexes))

print("Source file,", source)
print("basename,", basename)
print("Table,", tablename)
print("Field indexes,", field_indexes_str)
print("Field values,", field_values_str)

'''with open(output_file, "w") as outfile:
    outfile.write("Source file," + source + "\n")
    outfile.write("Basename," + basename + "\n")
    outfile.write("Scope file," + scope_file + "\n")    
    outfile.write("Table," + tablename + "\n")
    outfile.write("Field indexes," + field_indexes_str + "\n")
    outfile.write("Field values," + field_values_str + "\n")
'''

# yaml will expected to contain params, eg:
'''
    fileinfo:
    basename: Quickstart.xlsx
    scope file: Quickstart.xlsx.Cycle_Time.20250928_164350.cycletime.scope.yaml
    source: Quickstart.xlsx
    table: Cycle_Time
    jql: project in (tes,fr) and updated > -90d
    row: 27
    col: 1
    lastrow: 49
'''

# the following were addded by scope.py in runrate yaml file
cycletime_table_row = data.get('row', None)
print(f"quickstart_table_row from yaml: {cycletime_table_row}")
cycletime_table_col = data.get('col', None)
print(f"quickstart_table_col from yaml: {cycletime_table_col}")
last_excel_row = data.get('lastrow', None)
print(f"last_excel_row from yaml: {last_excel_row}")
jql_str = data.get('jql', None)
print(f"jql from yaml: {jql_str}")

# validate
if not jql_str or cycletime_table_row is None or cycletime_table_col is None or last_excel_row is None:
    print("❌ Error: Missing required fields in YAML file")
    sys.exit(1)



'''coord = get_column_letter(1)
r = last_excel_row

excel_col = quickstart_table_col + 1

changes_list.append(f"{get_column_letter(excel_col)}{r} = {changes_overall_status[0]} || ")
r += 5
changes_list.append(f"{get_column_letter(excel_col + 1)}{r} = {changes_resolved_velocity[0]} || ")
r += 10
changes_list.append(f"{get_column_letter(excel_col + 1)}{r} = {changes_assignee_velocity[0]} || ")
r += 10

changes_list.append(f"{get_column_letter(excel_col + 1)}{r} = {changes_cycletime[0]} || ")
r += 10

# column write always start at column A
for idx, entry in enumerate(changes_epics):
    if idx == 0:
        changes_list.append(f"{get_column_letter(excel_col + 1)}{r} = {entry} || ")
    else:
        coord = f"{get_column_letter(excel_col + 1 + idx)}{r + 1}"
        changes_list.append(f"{coord} = {entry} || ")
'''
    
from jira import JIRA
from dotenv import load_dotenv

JIRA_MAX_RESULTS = 50

# Load environment variables from a .env file if present
# -------------------------------
#load_dotenv()
# load .env from config folder
ENV_PATH = f"../../../config/env.{userlogin}"
load_dotenv(dotenv_path=ENV_PATH)

JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")
JIRA_URL = os.environ.get("JIRA_URL")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")

if not JIRA_API_TOKEN:
    print("Error: JIRA_API_TOKEN environment variable not set.")
    sys.exit(1)


# Connect to Jira with basic auth
try:
    jira = JIRA(server=JIRA_URL, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
    #print("✅ Successfully connected to Jira.")
except Exception as e:
    print(f"❌ Failed to connect to Jira: {e}")
    sys.exit(1)

print(f"JIRA client connected to {JIRA_URL} login:{JIRA_EMAIL} apitoken:{JIRA_API_TOKEN} ")

issues = []  # global issues list to hold results from both ID and JQL searches



try:
    jql_query = jql_str
    jql_query = jql_query.lower().replace("jql ", "").strip()
    issues = jira.search_issues(jql_query, maxResults = JIRA_MAX_RESULTS, expand='changelog')
    print(f"Found {len(issues)} issues for JQL query '{jql_query}':")
    if len(issues) == 0:
        print(f"No issues found for JQL query '{jql_query}'.")
        sys.exit(1)
    filtered_ids = [issue.key for issue in issues]
    print(f"Filtered IDs from JQL: {filtered_ids}")
    #jql_ids = []  # Clear jql_ids to avoid re-processing later below
except Exception as e:
    print(f"❌ Failed to search issues for JQL query '{jql_query}': {e}")
    sys.exit(1)

# Calculate transition times
results = calculate_average_status_transition_time(issues)
print(f"\nCalculated transition times for {len(results)} status transitions.")

# Print results
#print_transition_report(results)

transition_data = results
  
# Sort transitions by average time (descending)
sorted_transitions = sorted(
    transition_data.items(),
    key=lambda x: x[1]['average_hours'],
    reverse=True
)


changes_list = []
r = cycletime_table_row + 1
excel_col = cycletime_table_col + 1

# write out the timestamp in cell adjacent to <> so we can tell when the update occured
coord = f"{get_column_letter(cycletime_table_col + 2)}{cycletime_table_row}"
now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
entry = f"{coord} = {now_str} ||"
print (entry)
changes_list.append(entry)

changes_list.append(f"{get_column_letter(excel_col)}{r} = INSERT Status Transition || ")  # add INSERT to only first since the rest are on same row
changes_list.append(f"{get_column_letter(excel_col + 1)}{r} =  INSERT Median Time || ")
changes_list.append(f"{get_column_letter(excel_col + 2 )}{r} =  INSERT Average Time || ")
changes_list.append(f"{get_column_letter(excel_col + 3)}{r} =  INSERT Range || ")
changes_list.append(f"{get_column_letter(excel_col + 4)}{r} =  INSERT Sample Size || ")

r +=1

for (from_status, to_status), data in sorted_transitions:
    print(f"\n{from_status} → {to_status}")
    changes_list.append(f"{get_column_letter(excel_col)}{r} = INSERT {from_status} -> {to_status} || ")  # add INSERT only to first row since rest are in sme row
    changes_list.append(f"{get_column_letter(excel_col + 1)}{r} = INSERT {data['average_hours']:.1f} hours ({data['average_days']:.1f} days) || ")
    changes_list.append(f"{get_column_letter(excel_col + 2)}{r} = INSERT {data['median_hours']:.1f} hours || ")
    changes_list.append(f"{get_column_letter(excel_col + 3)}{r} = INSERT {data['min_hours']:.1f} - {data['max_hours']:.1f} hours || ")
    changes_list.append(f"{get_column_letter(excel_col + 4)}{r} = INSERT {data['count']} issues || ")
    
    r += 1

    print(f"  Average Time: {data['average_hours']:.1f} hours ({data['average_days']:.1f} days)")
    print(f"  Median Time:  {data['median_hours']:.1f} hours")
    print(f"  Range:        {data['min_hours']:.1f} - {data['max_hours']:.1f} hours")
    print(f"  Sample Size:  {data['count']} issues")


changes_file = yaml_file.replace("scope.yaml","import.changes.txt")
print(f"Writing changes to {changes_file}")

if changes_list:
    with open(changes_file, "w") as f:
        for entry in changes_list:
            if "||None" in entry:
                entry = entry.replace("||None", "||")
            f.write(entry + "\n")
            print(entry)
    print(f"Changes written to {changes_file} with ({len(changes_list)} entries).")
else:
    print(f"No changes to write. Not need to create {changes_file}")

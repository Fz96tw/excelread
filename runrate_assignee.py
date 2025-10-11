import sys
import yaml
from jira import JIRA
import os
from dotenv import load_dotenv
import re
import ollama
from datetime import datetime
from openpyxl.styles import Alignment
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

# Cache dictionary to avoid repeated calls
user_cache = {}

import requests
from requests.auth import HTTPBasicAuth

from datetime import datetime, timedelta
from collections import defaultdict
import calendar



from datetime import datetime, timedelta
from collections import defaultdict
import calendar

def get_week_number(date):
    """Get the ISO week number for a given date"""
    return date.isocalendar()[1]

def get_year_week(date):
    """Get year and week as a tuple for proper sorting across years"""
    iso_cal = date.isocalendar()
    return (iso_cal[0], iso_cal[1])  # (year, week)

def get_year_month(date):
    """Get year and month as a tuple"""
    return (date.year, date.month)

def get_year_day(date):
    """Get year and day of year as a tuple"""
    return (date.year, date.timetuple().tm_yday)

def get_period_key(date, interval):
    """Get the appropriate period key based on interval type"""
    if interval == "days":
        return (date.year, date.month, date.day)
    elif interval == "weeks":
        return get_year_week(date)
    elif interval == "months":
        return get_year_month(date)
    elif interval == "years":
        return (date.year,)
    else:
        raise ValueError(f"Invalid interval: {interval}")

def get_period_bounds(date, interval):
    """Get start and end dates for a period based on interval type"""
    if interval == "days":
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        return start, end
    
    elif interval == "weeks":
        # Start on Monday
        start = date - timedelta(days=date.weekday())
        end = start + timedelta(days=6)
        return start, end
    
    elif interval == "months":
        # First day of month
        start = date.replace(day=1)
        # Last day of month
        if date.month == 12:
            end = date.replace(day=31)
        else:
            next_month = date.replace(month=date.month + 1, day=1)
            end = next_month - timedelta(days=1)
        return start, end
    
    elif interval == "years":
        # First day of year
        start = date.replace(month=1, day=1)
        # Last day of year
        end = date.replace(month=12, day=31)
        return start, end
    
    else:
        raise ValueError(f"Invalid interval: {interval}")

def advance_period(date, interval):
    """Advance date to the next period based on interval type"""
    if interval == "days":
        return date + timedelta(days=1)
    elif interval == "weeks":
        return date + timedelta(weeks=1)
    elif interval == "months":
        # Handle month rollover
        if date.month == 12:
            return date.replace(year=date.year + 1, month=1)
        else:
            return date.replace(month=date.month + 1)
    elif interval == "years":
        return date.replace(year=date.year + 1)
    else:
        raise ValueError(f"Invalid interval: {interval}")

def get_period_label(period_key, interval):
    """Generate a human-readable label for the period"""
    if interval == "days":
        year, month, day = period_key
        return f"{year}-{month:02d}-{day:02d}"
    elif interval == "weeks":
        year, week_num = period_key
        return f"{year}-W{week_num:02d}"
    elif interval == "months":
        year, month = period_key
        month_name = calendar.month_abbr[month]
        return f"{year}-{month_name}"
    elif interval == "years":
        year = period_key[0]
        return f"{year}"
    else:
        return str(period_key)

def bucketize_issues_by_interval(issues, mode, interval="weeks", assignee_filter=None):
    """
    Bucketize Jira issues by time interval based on resolution/creation date.
    
    Args:
        issues: List of Jira issues from jira.search_issues()
        mode: String indicating which date field to use ("resolved", "open", "closed")
        interval: String indicating time interval ("days", "weeks", "months", "years")
        
    Returns:
        tuple: (period_buckets, period_info)
        - period_buckets: List of lists, each containing issues for that period
        - period_info: List of tuples with period metadata (varies by interval)
    """
    
    # Validate interval
    valid_intervals = ["days", "weeks", "months", "years"]
    if interval not in valid_intervals:
        print(f"❌ Invalid interval '{interval}'. Must be one of: {', '.join(valid_intervals)}")
        return [], []
    
    # Dictionary to group issues by period
    issues_by_period = defaultdict(list)
    resolution_dates = []
    
    print(f"\n🔍 Processing issues for {interval} bucketization for assignee={assignee_filter}...")
    print(f"Mode: {mode}")
    print(f"Interval: {interval}")
    
    # Group issues by period and collect resolution dates
    for issue in issues:
        a = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"   

        if assignee_filter is not None and assignee_filter not in a:
            continue  # skip issues not matching assignee filter


        print(f"Processing issue {issue.key} assigned to {a}")

        try:
            # Get resolution date - try different field names based on mode
            resolved_date = None
            
            if "resolved" in mode:
                if hasattr(issue.fields, 'resolutiondate') and issue.fields.resolutiondate:
                    resolved_date = datetime.strptime(issue.fields.resolutiondate[:19], '%Y-%m-%dT%H:%M:%S')
                elif hasattr(issue.fields, 'resolved') and issue.fields.resolved:
                    resolved_date = datetime.strptime(issue.fields.resolved[:19], '%Y-%m-%dT%H:%M:%S')
            elif "open" in mode: 
                if hasattr(issue.fields, 'created') and issue.fields.created:
                    resolved_date = datetime.strptime(issue.fields.created[:19], '%Y-%m-%dT%H:%M:%S')
                elif hasattr(issue.fields, 'createddate') and issue.fields.createddate:
                    resolved_date = datetime.strptime(issue.fields.createddate[:19], '%Y-%m-%dT%H:%M:%S')
            elif "closed" in mode: 
                if hasattr(issue.fields, 'closed') and issue.fields.closed:
                    resolved_date = datetime.strptime(issue.fields.closed[:19], '%Y-%m-%dT%H:%M:%S')
            else:
                print(f"❌ Unknown mode '{mode}' specified for bucketization.")
                return [], []
                                
            if resolved_date:
                period_key = get_period_key(resolved_date, interval)
                issues_by_period[period_key].append(issue)
                resolution_dates.append(resolved_date)
                
                period_label = get_period_label(period_key, interval)
                print(f"  📅 {issue.key}: {mode} {resolved_date.strftime('%Y-%m-%d')} ({period_label})")
            else:
                print(f"  ⚠️  {issue.key}: No {mode} date found - skipping")
                
        except Exception as e:
            print(f"  ❌ Error processing {issue.key}: {e}")
            continue
    
    if not resolution_dates:
        print(f"❌ No issues with valid {mode} dates found!")
        return [], []
    
    # Find the earliest and latest resolution dates
    earliest_date = min(resolution_dates)
    latest_date = max(resolution_dates)
    
    print(f"\n📊 Date range: {earliest_date.strftime('%Y-%m-%d')} to {latest_date.strftime('%Y-%m-%d')}")
    
    # Generate all periods in the range
    current_date = earliest_date
    
    # Align to the start of the first period
    period_start, _ = get_period_bounds(current_date, interval)
    current_date = period_start
    
    period_buckets = []
    period_info = []
    
    while current_date <= latest_date:
        period_key = get_period_key(current_date, interval)
        period_start, period_end = get_period_bounds(current_date, interval)
        
        # Get issues for this period (if any)
        period_issues = issues_by_period.get(period_key, [])
        period_buckets.append(period_issues)
        
        # Store period information with appropriate metadata
        if interval == "weeks":
            year_week = get_year_week(current_date)
            period_info.append((year_week[0], year_week[1], period_start, period_end))
        elif interval == "months":
            year_month = get_year_month(current_date)
            period_info.append((year_month[0], year_month[1], period_start, period_end))
        elif interval == "years":
            period_info.append((current_date.year, period_start, period_end))
        elif interval == "days":
            period_info.append((current_date.year, current_date.month, current_date.day, period_start, period_end))
        
        # Move to next period
        current_date = advance_period(current_date, interval)
        
        # Safety check to prevent infinite loops
        if len(period_buckets) > 10000:
            print("⚠️  Warning: Generated more than 10,000 periods. Stopping.")
            break
    
    print(f"\n✅ Created {len(period_buckets)} {interval} buckets")
    
    return period_buckets, period_info


# Backwards compatibility - keep the old function name
def bucketize_issues_by_weeks(issues, mode):
    """Legacy function - calls bucketize_issues_by_interval with weeks"""
    return bucketize_issues_by_interval(issues, mode, interval="weeks")


def get_week_number(date):
    """Get the ISO week number for a given date"""
    return date.isocalendar()[1]

def get_year_week(date):
    """Get year and week as a tuple for proper sorting across years"""
    iso_cal = date.isocalendar()
    return (iso_cal[0], iso_cal[1])  # (year, week)


def print_weekly_summary(weekly_buckets, week_info):
    """Print a summary of issues bucketized by weeks"""
    
    print(f"\n📈 WEEKLY BUCKETIZATION SUMMARY")
    print(f"{'='*60}")
    
    total_issues = sum(len(bucket) for bucket in weekly_buckets)
    print(f"Total issues processed: {total_issues}")
    print(f"Total weeks in range: {len(weekly_buckets)}")
    print(f"{'='*60}")
    
    for i, (bucket, (year, week_num, start_date, end_date)) in enumerate(zip(weekly_buckets, week_info)):
        week_str = f"Week {i+1} ({year}-W{week_num:02d})"
        date_range = f"{start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d/%Y')}"
        issue_count = len(bucket)
        
        print(f"{week_str:<20} {date_range:<20} Issues: {issue_count}")
        
        # Print issue keys for this week
        if bucket:
            issue_keys = [issue.key for issue in bucket]
            print(f"{'':>20} └─ {', '.join(issue_keys)}")
        
        print()


def bucketize_issues_by_weeks_foo(issues, mode):
    """
    Bucketize Jira issues by calendar weeks based on resolution date.
    
    Args:
        issues: List of Jira issues from jira.search_issues()
        
    Returns:
        tuple: (weekly_buckets, week_info)
        - weekly_buckets: List of lists, each containing issues for that week
        - week_info: List of tuples with (year, week_num, start_date, end_date) for each bucket
    """
    
    # Dictionary to group issues by year-week
    issues_by_week = defaultdict(list)
    resolution_dates = []
    
    print("\n🔍 Processing issues for weekly bucketization...")
    print(f"Mode: {mode}")
    
    # Group issues by week and collect resolution dates
    for issue in issues:
        try:
            # Get resolution date - try different field names
            resolved_date = None
            
            if "resolved" in mode:
                if hasattr(issue.fields, 'resolutiondate') and issue.fields.resolutiondate:
                    resolved_date = datetime.strptime(issue.fields.resolutiondate[:19], '%Y-%m-%dT%H:%M:%S')
                elif hasattr(issue.fields, 'resolved') and issue.fields.resolved:
                    resolved_date = datetime.strptime(issue.fields.resolved[:19], '%Y-%m-%dT%H:%M:%S')
            elif "open" in mode: 
                if hasattr(issue.fields, 'created') and issue.fields.created:
                    resolved_date = datetime.strptime(issue.fields.created[:19], '%Y-%m-%dT%H:%M:%S')
                elif hasattr(issue.fields, 'createddate') and issue.fields.createddate:
                    resolved_date = datetime.strptime(issue.fields.createddate[:19], '%Y-%m-%dT%H:%M:%S')
            elif "closed" in mode: 
                if hasattr(issue.fields, 'closed') and issue.fields.created:
                    resolved_date = datetime.strptime(issue.fields.closed[:19], '%Y-%m-%dT%H:%M:%S')
            else:
                print(f"❌ Unknown mode '{mode}' specified for bucketization.")
                return [], []
                                
            if resolved_date:
                year_week = get_year_week(resolved_date)
                issues_by_week[year_week].append(issue)
                resolution_dates.append(resolved_date)
                print(f"  📅 {issue.key}: Resolved {resolved_date.strftime('%Y-%m-%d')} (Week {year_week[1]}, {year_week[0]})")
            else:
                print(f"  ⚠️  {issue.key}: No resolution date found - skipping")
                
        except Exception as e:
            print(f"  ❌ Error processing {issue.key}: {e}")
            continue
    
    if not resolution_dates:
        print("❌ No issues with valid resolution dates found!")
        return [], []
    
    # Find the earliest and latest resolution dates
    earliest_date = min(resolution_dates)
    latest_date = max(resolution_dates)
    
    print(f"\n📊 Date range: {earliest_date.strftime('%Y-%m-%d')} to {latest_date.strftime('%Y-%m-%d')}")
    
    # Generate all weeks in the range
    current_date = earliest_date
    # Go to the start of the week (Monday)
    current_date = current_date - timedelta(days=current_date.weekday())
    
    weekly_buckets = []
    week_info = []
    
    while current_date <= latest_date:
        year_week = get_year_week(current_date)
        week_start = current_date
        week_end = current_date + timedelta(days=6)
        
        # Get issues for this week (if any)
        week_issues = issues_by_week.get(year_week, [])
        weekly_buckets.append(week_issues)
        
        # Store week information
        week_info.append((year_week[0], year_week[1], week_start, week_end))
        
        # Move to next week
        current_date += timedelta(weeks=1)
    
    return weekly_buckets, week_info


def parse_runrate_params(runrate_params_list):
    params = {}
    for entry in runrate_params_list:
        entry = str(entry).strip()

        params["mode"] = "weeks"  # default mode
        
        if entry.lower().startswith("weeks"):
            # e.g. "weeks 6"
            params["mode"] = "weeks"

            # dead code since i decided not to support number of weeks. Durations is completed determiend by jql filter time frame
            '''parts = entry.split(maxsplit=1)
            if len(parts) == 2 and parts[1].isdigit():
                params["weeks"] = int(parts[1])
            else:
                params["weeks"] = parts[1] if len(parts) == 2 else None
        '''
        elif entry.lower().startswith("days"):
            # e.g. "days 30"
            params["mode"] = "days"
        elif entry.lower().startswith("months"):
            # e.g. "months 3"
            params["mode"] = "months"
        elif entry.lower().startswith("years"):
            # e.g. "years 1"
            params["mode"] = "years"
        elif entry.lower().startswith("jql"):
            # e.g. "JQL project = tes and assignee = nadeem"
            jql_query = entry[3:].strip()  # remove "JQL"
            params["jql"] = jql_query

    return params




def _excel_escape_quotes(s: str) -> str:
    # Excel doubles double-quotes inside string literals
    return s.replace('"', '""')

def _make_hyperlink_formula(url: str, text: str) -> str:
    # Keep it simple: replace newlines for display; wrap handles line breaks visually
    text = text.replace("\n", " ")
    return f'=HYPERLINK("{_excel_escape_quotes(url)}","{_excel_escape_quotes(text)}")'


if len(sys.argv) < 3:
    print("Usage: python runrate_resolved.py <yaml_file> <timestamp")
    sys.exit(1)

yaml_file = sys.argv[1]
#filename = sys.argv[2]
timestamp = sys.argv[2]

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

mode = ""

# I don't think this code is doing anything useful. It always sets create_mode to True?! since 
# Determine if we will be INSERTING rows eventually vs just UPDATING existing rows in Excel/SharePoint
if "assignee.rate" in yaml_file.lower():
    print(f"assignee rate mode detected based on filename: {yaml_file}.")
    # You can set a flag or handle import-specific logic here if needed
    output_file = basename + "." + tablename + timestamp + ".assignee.rate.jira.csv"
    #mode = "assignee" #"resolved"
else:
    print("Error: YAML filename does not indicate 'assignee.rate' mode.")
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
    basename: children test.xlsx
    scope file: children test.xlsx.Resolved_Run_rate.20250921_183156.rate.yaml
    source: children test.xlsx
    table: Resolved_Run_rate
    params:
    - weeks 6
    - JQL project = tes and assignee = nadeem
'''

# the following were addded by scope.py in runrate yaml file
runrate_params_list = data.get('params',[])
runrate_table_row = data.get('row', None)
runrate_table_col = data.get('col', None)

runrate_params = parse_runrate_params(runrate_params_list)
print("Runrate params:", runrate_params)

jql_query = runrate_params.get("jql", "")
if not jql_query:
    print("Error: No JQL query specified in params.")
    sys.exit(1)

jira_filter_str = jql_query.replace("jql", "").strip()
JIRA_MAX_RESULTS = 1000  # adjust as needed

weeks = runrate_params.get("weeks", None)  # default to 6 weeks if not specified
days = runrate_params.get("days", None)  # optional days param
months =  runrate_params.get("months", None)  # optional months param
years = runrate_params.get("years", None)  # optional years param

#if (not weeks) and (not days) and (not months) and (not years):
if runrate_params.get("mode", "") == "":
    print("ERROR: No valid time frame (weeks/days/months/years) specified in params. Defaulting to 6 weeks.")
    sys.exit(1)

# Replace with your Jira Cloud credentials and URL

# Load environment variables from a .env file if present
#load_dotenv()
ENV_PATH = "../../../config/.env"
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


try:
    issues = jira.search_issues(jira_filter_str, maxResults=JIRA_MAX_RESULTS)
    print(f"✅ Found {len(issues)} issue(s) matching the filter.")
    for i, issue in enumerate(issues, start=1):
        print(f"{i}. {issue.key} — {issue.fields.summary}")
except Exception as e:
    print(f"❌ Failed to search issues: {e}")




# Now we need to write out the changes to a text file that can be picked up by update_sharepoint.py
changes_list = []

row = runrate_table_row + 1  # skip to next row after <> tag cell
col = runrate_table_col # integer! and will need to be convered to letter for openpyxl

from openpyxl.utils import get_column_letter

# write out the headers first
coord = f"{get_column_letter(col + 1)}{row}"
entry = f"{coord} = Assignee ||"
print (entry)
changes_list.append(entry)

# write out the timestamp in cell adjacent to <> so we can tell when the update occured
coord = f"{get_column_letter(col + 2)}{row - 1}"
now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
entry = f"{coord} = {now_str} ||"
print (entry)
changes_list.append(entry)

print(f"\n🔄 Bucketizing {len(issues)} issues by calendar weeks...")

assignee_list = []

# need list of all unique assignee since they will be in the excel cells table
for issue in issues:
    assignee  = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"   
    assignee_list.append(assignee)
    
unique_assignee_list = list(set(assignee_list))  # unique values
print(f"Found {len(unique_assignee_list)} unique assignees: {unique_assignee_list}")


# write out all the assignees in the header column
for index, assignee in enumerate(unique_assignee_list):
    print(f"{index}: Processing assignee {assignee}")    
    coord = f"{get_column_letter(col + 1)}{row + 1 + index}"
    entry = f"{coord} = {assignee} ||"
    print (entry)
    changes_list.append(entry)



if issues:
    # Bucketize issues by weeks
    #weekly_buckets_resolved, week_info_resolved = bucketize_issues_by_interval(issues,"open", runrate_params.get("mode", "weeks"),assignee_filter=assignee)
    weekly_buckets_resolved, week_info_resolved = bucketize_issues_by_interval(issues,"resolved",runrate_params.get("mode", "weeks"))
    #weekly_buckets_closed, week_info_closed = bucketize_issues_by_weeks(issues,"closed")
    
    print("Here's the weekly breakdown:")
    if weekly_buckets_resolved:
        # Print summary
        print_weekly_summary(weekly_buckets_resolved, week_info_resolved)

    '''print("Here's the resolved weekly breakdown:")
    if weekly_buckets_resolved:
        # Print summary
        print_weekly_summary(weekly_buckets_resolved, week_info_resolved)
    '''

# need to keep track of which week maps to which column so that both OPEN and CLOSE rates are under same colums per week
week_to_col = {}

# first get all the week numbers so get the min and max across both open and resolved
#for year, week_num, start_date, end_date in week_info:
#    week_to_col[week_num] = None

for year, week_num, start_date, end_date in week_info_resolved:
    week_to_col[week_num] = None


# Fill in any gaps in the week sequence
if week_to_col:
    min_week = min(week_to_col.keys())
    max_week = max(week_to_col.keys())
    
    print(f"Week range: {min_week} to {max_week}")
    
    # Add missing weeks in the range
    for week_num in range(min_week, max_week + 1):
        if week_num not in week_to_col:
            week_to_col[week_num] = None
            print(f"  Added missing week {week_num}")

# Sort week numbers in ascending order
sorted_week_to_col = sorted(week_to_col.keys())
print(f"Sorted week numbers: {sorted_week_to_col}")

# Now assign column numbers in order
for col_index, week_num in enumerate(sorted_week_to_col):
    print(f"week_to_col({week_num}) -> Column {col + 1 + col_index + 1}")
    week_to_col[week_num] = col + 1 + col_index + 1

# now write out the week headers
for i in sorted_week_to_col:
    coord = f"{get_column_letter(week_to_col.get(i))}{row}"
    entry = f"{coord} = Week {i} || "
    print(entry)
    changes_list.append(entry)


# now loop through each assignee and write out their counts per week
for assignee in unique_assignee_list:
    weekly_buckets_resolved, week_info_resolved = bucketize_issues_by_interval(issues,"resolved",runrate_params.get("mode", "weeks"), assignee_filter=assignee)
    #weekly_buckets_closed, week_info_closed = bucketize_issues_by_weeks(issues,"closed")

    print(f"Here's the weekly breakdown for assignee={assignee}:")

    if weekly_buckets_resolved:
        # Print summary
        print_weekly_summary(weekly_buckets_resolved, week_info_resolved)

    # now loop through the weeks and write out the counts
    for i, (bucket, (year, week_num, start_date, end_date)) in enumerate(zip(weekly_buckets_resolved, week_info_resolved)):
        #week_str = f"Week {i+1} ({year}-W{week_num:02d})"
        week_str = f"{start_date.strftime('%Y-%m-%d')}"
        date_range = f"{start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d/%Y')}"
        issue_count = len(bucket)
        
        #week_to_col[week_num] = col + 1 + i + 1
        #print(f"saving week_to_col('{week_num}' = {col + 1 + i + 1})")
        
        #coord = f"{get_column_letter(col + 1 + i + 1)}{row + 1}"
        #entry = f"{coord} = {len(bucket)} || "
        
        if (len(bucket) == 0):
            print (f"Skipping week {week_num} since no OPEN issues")
            continue

        print (f"Looking up week {week_num} in sorted_week_to_col, found column {week_to_col.get(week_num,'None')}")
        coord = f"{get_column_letter(week_to_col.get(week_num))}{row + 1}"

        jql = "key in ("
        for issue in bucket:
            jql += issue.key + ","
        jql = jql.rstrip(",") + ")"

        #entry = f"{coord} = {len(bucket)} || "
        hyperlink = _make_hyperlink_formula(f"https://fz96tw.atlassian.net/issues/?jql={jql}", f"{len(bucket)}") + " || "
        entry = f"{coord} = {hyperlink} || " 
        print (entry)
        changes_list.append(entry)
        row = row + 1   # move to next row for next assignee    


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

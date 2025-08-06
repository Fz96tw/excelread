import sys
import yaml
from jira import JIRA
import os
from dotenv import load_dotenv


import re

# Cache dictionary to avoid repeated calls
user_cache = {}

def get_user_display_name(account_id, jira_client):
    if account_id in user_cache:
        return user_cache[account_id]

    # Search users with account_id as query
    users = jira_client.search_users(query=account_id, maxResults=1)

    if users:
        # Check if the first user matches the accountId exactly
        user = users[0]
        if user.accountId == account_id:
            display_name = user.displayName
        else:
            display_name = "unknown"
    else:
        display_name = "unknown"

    user_cache[account_id] = display_name
    return display_name

def replace_account_ids_with_names(text, jira_client):
    import re
    def replacer(match):
        account_id = match.group(1)
        display_name = get_user_display_name(account_id, jira_client)
        return f"@{display_name}"
    return re.sub(r"\[~accountid:([a-zA-Z0-9:\-]+)\]", replacer, text)


if len(sys.argv) != 2:
    print("Usage: python read_jira.py <yaml_file>")
    sys.exit(1)

yaml_file = sys.argv[1]

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

output_file = basename + "." + tablename + ".jira.csv"

fields = data.get('fields', [])
field_values = [field.get('value') for field in fields if 'value' in field]
field_indexes = [field.get('index') for field in fields if 'index' in field]
field_values_str = ','.join(field_values)
field_indexes_str = ','.join(map(str, field_indexes))

print("Source file,", source)
print("basename,", basename)
print("Table,", tablename)
print("Field indexes,", field_indexes_str)
print("Field values,", field_values_str)

with open(output_file, "w") as outfile:
    outfile.write("Source file," + source + "\n")
    outfile.write("Basename," + basename + "\n")
    outfile.write("Scope file," + scope_file + "\n")    
    outfile.write("Table," + tablename + "\n")
    outfile.write("Field indexes," + field_indexes_str + "\n")
    outfile.write("Field values," + field_values_str + "\n")

jira_ids = data.get('jira_ids', [])
jira_filter_str = "id in (" + ','.join(jira_ids) + ")"
 
print(jira_filter_str)

# Replace with your Jira Cloud credentials and URL

# Load environment variables from a .env file if present
load_dotenv()
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

# Try running the search
try:
    issues = jira.search_issues(jira_filter_str, maxResults=10)
    #print(f"✅ Found {len(issues)} issue(s) matching the filter.")
    #for i, issue in enumerate(issues, start=1):
    #    print(f"{i}. {issue.key} — {issue.fields.summary}")
except Exception as e:
    print(f"❌ Failed to search issues: {e}")


print(f"Found {len(issues)} issues matching the filter:")


# Print only the fields specified in field_values_str for each issue
for issue in issues:
    values = [] 
    for field in field_values:
        value = getattr(issue.fields, field, None)
        if field == "assignee":
            value = issue.fields.assignee.displayName if issue.fields.assignee else "unassigned"
        elif field == "id":
            value = issue.id
        elif field == "key":
            value = issue.key
        elif field == "comments":
            if issue.fields.comment.comments:
                sorted_comments = sorted(issue.fields.comment.comments, key=lambda c: c.created, reverse=True)
                value = "\n".join([
                    f"{comment.created[:10]} - {comment.author.displayName}: {replace_account_ids_with_names(comment.body, jira)}"
                    for comment in sorted_comments
                ])
            else:
                value = "No comments"
                
        values.append(str(value))

    print(','.join(values))
    with open(output_file, "a") as outfile:
        outfile.write(','.join(values) + "\n")  
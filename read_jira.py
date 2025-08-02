import sys
import yaml
from jira import JIRA
import os
from dotenv import load_dotenv

if len(sys.argv) != 2:
    print("Usage: python read_jira.py <yaml_file>")
    sys.exit(1)

yaml_file = sys.argv[1]

with open(yaml_file, 'r') as f:
    data = yaml.safe_load(f)

fields = data.get('fields', [])
field_values = [field.get('value') for field in fields if 'value' in field]
field_indexes = [field.get('index') for field in fields if 'index' in field]
field_values_str = ','.join(field_values)
field_indexes_str = ','.join(map(str, field_indexes))

print("Field indexes:", field_indexes_str)
print("Field values:", field_values_str)

with open("Book1.jira.csv", "w") as outfile:
    outfile.write("Field indexes: " + field_indexes_str + "\n")
    outfile.write("Field values: " + field_values_str + "\n")

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

# Connect to Jira Cloud
jira = JIRA(
    server=JIRA_URL,
    basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN)
)

# Search issues using the JQL filter
issues = jira.search_issues(jira_filter_str)
print(f"Found {len(issues)} issues matching the filter:")

# Print only the fields specified in field_values_str for each issue
for issue in issues:
    for field in field_values:
        value = getattr(issue.fields, field, None)
        if field == "assignee":
            #print("field is assignee")
            value = issue.fields.assignee.displayName if issue.fields.assignee else None
            if value is None:
                value = "unassigned"
        elif field == id:
            value = issue.id
        elif field == "id":
            value = issue.key

    # Collect all field values for this issue
    values = []
    for field in field_values:
        value = getattr(issue.fields, field, None)
        if field == "assignee":
            value = issue.fields.assignee.displayName if issue.fields.assignee else "unassigned"
        elif field == "id":
            value = issue.id
        elif field == "key":
            value = issue.key
        #elif field == "sprint":
        #    value = issue.sprints[0].name if issue.sprints else "No Sprint"
        
        values.append(str(value))
    print(','.join(values))
    with open("Book1.jira.csv", "a") as outfile:
        outfile.write(','.join(values) + "\n") 
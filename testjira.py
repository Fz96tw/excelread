from jira import JIRA
from dotenv import load_dotenv
import os

load_dotenv()

JIRA_URL = os.environ.get("JIRA_URL")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")

jira = JIRA(server=JIRA_URL, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
print(f"Connected as: {jira.current_user()}")

# Very broad query
issues = jira.search_issues("order by created DESC", maxResults=5)
print(f"Found {len(issues)} issues")
for issue in issues:
    print(f"{issue.key} - {issue.fields.summary}")

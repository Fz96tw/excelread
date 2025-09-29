import sys
import yaml
from jira import JIRA
import os
from dotenv import load_dotenv
import re
#import ollama
from datetime import datetime
import json

# Cache dictionary to avoid repeated calls
user_cache = {}

import requests
from requests.auth import HTTPBasicAuth


# Cache dictionary to avoid repeated calls
user_cache = {}

# custom prompt appended to system prompt from sheet <ai...> tag
user_prompt = ""
JIRA_MAX_RESULTS = 200

model_name = "llama3.2:1b"  # Default model name

# Default to localhost unless overridden in env variable (set when in Docker)
SUMMARIZER_HOST = os.getenv("SUMMARIZER_HOST", "http://localhost:8000")


LLMCONFIG_FILE = "../../../config/llmconfig.json"


def get_summarized_comments(comments_list_asc):
    """
    Summarize comments for LLM processing.
    This function takes a list of comments in ascending order and returns a summarized version.
    """
    if not comments_list_asc:
        return "No comments available."

    # Only join if it's a list or tuple
    if isinstance(comments_list_asc, (list, tuple)):
        comments_str = "; ".join(comments_list_asc)
    else:
        comments_str = comments_list_asc  # already a string

    
    # comments_str was a single string before, but the service expects a list[str].
    # If you only have one string, wrap it in a list.
    comments = [comments_str]

    if llm_model == "OpenAI":
        ENDPOINT = "/summarize_openai"
    else:
        ENDPOINT = "/summarize_local"
    
    resp = requests.post(f"{SUMMARIZER_HOST}{ENDPOINT}", json=comments)

    if resp.status_code == 200:
        full_response = resp.json()["summary"]
    else:
        full_response = f"[ERROR] Service call failed: {resp.text}"    
    
    
    print(f"Full response: {full_response}")
     # Replace all newlines with semicolons
    full_response.rstrip("\n")
    full_response = full_response.replace("\n", "; ")
    full_response = full_response.replace("|", "/")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    #print(now_str)

    return  full_response


def get_user_display_name(account_id):
    if account_id in user_cache:
        return user_cache[account_id]

    url = f"{JIRA_URL}/rest/api/3/user?accountId={account_id}"
    response = requests.get(url, auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN))

    if response.status_code == 200:
        user_data = response.json()
        display_name = user_data.get("displayName", "unknown")
    else:
        display_name = "unknown"

    user_cache[account_id] = display_name
    return display_name

def get_user_display_name2(account_id, jira_client):
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


def replace_account_ids_with_names(text):
    def replacer(match):
        account_id = match.group(1)
        display_name = get_user_display_name(account_id)
        return f"@{display_name}"
    return re.sub(r"\[~accountid:([a-zA-Z0-9:\-]+)\]", replacer, text)


def replace_account_ids_with_names2(text, jira_client):
    import re
    def replacer(match):
        account_id = match.group(1)
        display_name = get_user_display_name(account_id, jira_client)
        return f"@{display_name}"
    return re.sub(r"\[~accountid:([a-zA-Z0-9:\-]+)\]", replacer, text)


import re

def move_brackets_to_front(lines):
    """
    Moves [JIRA-KEY] from end of string to the front.

    Args:
        lines (list[str]): List of strings like "Task name [KEY-1]"

    Returns:
        list[str]: Reformatted strings like "[KEY-1] Task name"
    """
    result = []
    
#    pattern = re.compile(r'^(.*)\s+(\[[^\]]+\])$')
    #pattern = re.compile(r'^(.*?)(?:\s+)(▫️\s*\[[^\]]+\]|\[[^\]]+\])$')
    pattern = re.compile(r'^(.*?)\s+(?:▫️\s*)?(\[[^\]]+\])$')



    for line in lines:
        match = pattern.match(line.strip())
        if match:
            text, ticket = match.groups()
            result.append(f"{ticket} {text}")
        else:
            result.append(line)  # leave unchanged if no match
    return result


def get_llm_model(llm_config_file):
    print("Current working directory:", os.getcwd())  # <-- debug
    if os.path.exists(llm_config_file):
        with open(llm_config_file, "r") as f:
            llm_model_set = json.load(f)
            m = llm_model_set.get("model")
            print(f"get_llm_model returning  {m}")
            return m
    else:
        print(f"ERROR: load_llm_config file {llm_config_file} was not found")
    
    return None



if len(sys.argv) != 3:
    print("Usage: python read_jira.py <yaml_file>")
    sys.exit(1)

yaml_file = sys.argv[1]
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

import_mode = False
execsummary_mode = False

# Determine if we will be INSERTING rows eventually vs just UPDATING existing rows in Excel/SharePoint
if "import" in yaml_file.lower():
    print("Import mode detected based on filename containing 'import'.")
    # You can set a flag or handle import-specific logic here if needed
    import_mode = True
    output_file = basename + "." + tablename + "." + timestamp + ".import.jira.csv"
# Determine if we are dealing wiht ExecSummary table here
elif "aisummary" in yaml_file.lower():
    print(f"ai summary mode detected based on filename = {yaml_file}")
    # You can set a flag or handle import-specific logic here if needed
    execsummary_mode = True
    output_file = basename + "." + tablename + "." + timestamp + ".aisummary.jira.csv"
else:
    import_mode = False
    execsummary_mode = False
    output_file = basename + "." + tablename + "." + timestamp + ".jira.csv"


llm_model = get_llm_model(LLMCONFIG_FILE)
if not llm_model:
    llm_model = "Local"

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

#jira_ids = data.get('jira_ids', [])
#jira_filter_str = "id in (" + ','.join(jira_ids) + ")"
jira_ids = data.get('jira_ids', [])

# IDs without JQL
filtered_ids = [jid for jid in jira_ids if 'jql' not in jid.lower()]

# IDs with "JQL"
jql_ids = [jid for jid in jira_ids if 'jql' in jid.lower()]
jira_filter_str = "id in (" + ','.join(filtered_ids) + ")" 
print(jira_filter_str)

# Replace with your Jira Cloud credentials and URL

# Load environment variables from a .env file if present
# -------------------------------
#load_dotenv()
# load .env from config folder
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

issues = []  # global issues list to hold results from both ID and JQL searches

if import_mode:
    print("Import mode is ON. Will be inserting new rows.")
    # only 1 JQL applicable when import table is used
    if len(jql_ids) > 1:
        print("Error: More than one JQL provided in import mode. Only one JQL is supported in import mode.")
        sys.exit(1)
    #TODO convert the jql result into a filtered_ids List so it's processed as list of indivudal jira IDs
    try:
        jql_query = jql_ids[0]
        jql_query = jql_query.lower().replace("jql ", "").strip()
        issues = jira.search_issues(jql_query, maxResults = JIRA_MAX_RESULTS)
        print(f"Found {len(issues)} issues for JQL query '{jql_query}':")
        if len(issues) == 0:
            print(f"No issues found for JQL query '{jql_query}'.")
            sys.exit(1)
        filtered_ids = [issue.key for issue in issues]
        print(f"Filtered IDs from JQL: {filtered_ids}")
        jql_ids = []  # Clear jql_ids to avoid re-processing later below
    except Exception as e:
        print(f"❌ Failed to search issues for JQL query '{jql_query}': {e}")
        sys.exit(1)
else:
    print("Import mode is OFF. Will be updating existing rows.")


if filtered_ids:  # make sure we have some JIRA IDs in the excel file otherwise the search will throw exception
    # Try running the search only if issues is empty (i.e., not already populated by import mode)
    if issues is None or len(issues) == 0:    
        try:
            issues = jira.search_issues(jira_filter_str, maxResults=JIRA_MAX_RESULTS)
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
            elif field == "timestamp":
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                value = now_str
            elif field == "headline":
                #value = "[" + issue.key + "] " + issue.fields.summary[:10] | "..."
                value = f"[{issue.key}] {issue.fields.summary[:25]}{'...' if len(issue.fields.summary) > 10 else ''}" 
                value += "  Status: " + issue.fields.status.name  
                value += "  Assignee: " + issue.fields.assignee.displayName  if issue.fields.assignee else "   Assignee: unassigned" 
                value += "  Type: " + issue.fields.issuetype.name  
                value += "  Created: " + issue.fields.created[:10] 
                print(f"headline value: {value}")
            elif field == "key":
                value = issue.key
            elif field == "url":
                value = "URL " + getattr(issue, 'key', None)     # set it to the issue key for now. will be converted to hyperlink by update_sharepoint.py
            elif field == "children":
                issuetype = getattr(issue.fields, "issuetype", None)
                if issuetype and getattr(issuetype, "name", "") == "Epic":
                    # Get all issues linked to this epic
                    print(f"Fetching child issues for epic {issue.key}")
                    epic_linked_issues = jira.search_issues(
                        f'"Epic Link" = {issue.key}', 
                        maxResults=JIRA_MAX_RESULTS
                    )
                    if epic_linked_issues:
                        # Sort issues by numeric part of key (e.g. "ABC-2" < "ABC-12")
                        epic_linked_issues = sorted(
                            epic_linked_issues,
                            key=lambda x: (x.key.split("-")[0], int(x.key.split("-")[1]))
                        )
                        child_summaries = [
                            f"▫️ {linked_issue.key} {linked_issue.fields.summary[:30]}{'...' if len(linked_issue.fields.summary) > 30 else ''}:{linked_issue.fields.status.name}:{linked_issue.fields.assignee.displayName if linked_issue.fields.assignee else 'unassigned'}"
                            for linked_issue in epic_linked_issues
                        ]
                        value = ";".join(child_summaries)
                    else:
                        value = ""
                else:
                    value = ""
            elif field == "links":
                #outward_links = []
                #inward_links = []
                linked_jira_str = []
                if hasattr(issue.fields, 'issuelinks'):
                    for link in issue.fields.issuelinks:
                        if hasattr(link, 'outwardIssue'):
                            linked_jira_str.append(f"▫️ {link.outwardIssue.key} {link.outwardIssue.fields.summary[:30]}[{link.type.outward}]".strip())
                            #outward_links.append(f"{link.type.outward} {link.outwardIssue.key}")
                        elif hasattr(link, 'inwardIssue'):
                            linked_jira_str.append(f"▫️ {link.inwardIssue.key} {link.inwardIssue.fields.summary[:30]}[{link.type.inward}]".strip())
                            #inward_links.append(f"{link.type.inward} {link.inwardIssue.key}")
                        # strip out first and trailing commas in linked_jira_ids
                    value = ";".join(linked_jira_str) if linked_jira_str else ""
                else:
                    value = ""            
                '''
                links = []
                if outward_links:
                    links.append("▫️ Outward: " + ", ".join(outward_links))
                if inward_links:
                    links.append("▫️ Inward: " + ", ".join(inward_links))
                value = ";".join(links) if links else ""
                '''

            elif field == "comments":
                if issue.fields.comment.comments:
                    sorted_comments = sorted(issue.fields.comment.comments, key=lambda c: c.created, reverse=True)
                    value = ";".join([
                        f"{comment.created[:10]} - {comment.author.displayName}: {replace_account_ids_with_names(comment.body)}"
                        for comment in sorted_comments
                    ])

                    from datetime import datetime
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    value = "As of " + now_str + ";" + value
                else:
                    value = "No comments"
            #elif field == "ai":
            elif field.lower().startswith("ai"):
                user_prompt = field.replace("ai ","") # just extract the user prompt after the ai tag
                if issue.fields.comment.comments:
                    sorted_comments = sorted(issue.fields.comment.comments, key=lambda c: c.created, reverse=False)
                    value = ";".join([
                        f"{comment.created[:10]} - {comment.author.displayName} wrote: {replace_account_ids_with_names(comment.body)}"
                        for comment in sorted_comments
                    ])
                    print(f"calling get_summarized_comments with: {value}")
                    ai_summarized = get_summarized_comments(value)
                    value = ai_summarized
                else:
                    value = "No comments"
            elif field == "synopsis":
                value_parts = []
                issuetype = getattr(issue.fields, 'issuetype', None)
                if issuetype and hasattr(issuetype, 'name'):
                    if issuetype.name == "Epic":
                        value_parts.append("Epic")
                if hasattr(issue.fields, 'subtasks'):
                    value_parts.append(f"sub-tasks {len(issue.fields.subtasks)}")
                value = "|".join(value_parts) if value_parts else ""
                # Add more text to the synopsis if needed below here
            
            #elif field == "ai":
            #    if value is None: # don't want to set this to None, so make it blank
            #        value = ""

            value_str =str(value).replace("\n","")
            values.append(value_str)

        print(','.join(values))
        with open(output_file, "a") as outfile:
            outfile.write('|'.join(values) + "\n")  

# Now process the JQL queries
if jql_ids:
    print("Processing JQL queries:")    
    
    for jql_id in jql_ids:
        jql_id = jql_id.lower()
        jql_query = jql_id.replace("jql ", "").strip()

        # Normalize to lowercase only for the JQL prefix
        #if jql_id.strip().lower().startswith("jql "):
        #    jql_query = jql_id.strip()[4:].strip()
        #else:
        #    jql_query = jql_id.strip()

        print(f"Running JQL query: {jql_query}")
        try:
            issues = jira.search_issues(jql_query, maxResults=JIRA_MAX_RESULTS)
            print(f"Found {len(issues)} issues for JQL query '{jql_query}':")
            if len(issues) == 0:
                print(f"No issues found for JQL query '{jql_query}'.")
                continue

            assignee_list = []
            status_list = []
            summary_list = []
            id_list = []
            key_list = []
            comments_list = []
            comments_list_asc = [] # for ascending order for LLM
            comments_summarized_list = []
            synopsis_list = []
        
            values = []

            for field in field_values:
                print(f"Processing field: {field}")
                generic_fields_list = []
                headline_list = []

                comments_list = []
                comments_list_asc = [] # for ascending order for LLM
                comments_summarized_list = []
                
                #TODO?? not sure if this is needed to avoid a latent bug?
                # values_list = []  # Reset for each field
                
                for issue in issues:
                    print(f"Processing issue: {issue.key}")

                    # reset so it contains comments for thsi issue only. But do not reset comments_list here!
                    comments_list_asc = [] 
                    
                    value = getattr(issue.fields, field, None)
                    if field == "assignee":
                        temp = (issue.fields.assignee.displayName) if issue.fields.assignee else "unassigned"
                        assignee_list.append(temp + "▫️ [" + issue.key + "]")
                    elif field == "summary":
                        temp = issue.fields.summary if issue.fields.summary else "No summary"
                        summary_list.append("▫️ [" + issue.key + "] " + temp)
                    elif field == "headline":
                        #temp = "[" + issue.key + "] " + issue.fields.summary[:10] 
                        temp = f"▫️ {issue.key} {issue.fields.summary[:15]}{'...' if len(issue.fields.summary) > 10 else ''}"
                        temp += "  Status: " + issue.fields.status.name  
                        temp += "  Assignee: " + issue.fields.assignee.displayName  if issue.fields.assignee else "   Assignee: unassigned" 
                        temp += "  Type: " + issue.fields.issuetype.name  
                        temp += "  Created: " + issue.fields.created[:10] 
                        headline_list.append(temp)
                        print(f"headline value: {temp}")
                    elif field == "status":
                        temp = issue.fields.status.name if issue.fields.status else "unknown"
                        status_list.append(temp + "▫️ [" + issue.key + "]")
                    elif field == "id":
                        id_list.append(issue.id)
                    elif field == "key":
                        key_list.append("▫️ " + issue.key)
                    elif field == "comments" or field == "ai" :   # always need to process comments even when only AI is requested in excel sheet
                        if issue.fields.comment.comments:   
                            sorted_comments_asc = sorted(issue.fields.comment.comments, key=lambda c: c.created) # ascending order for LLM   
                            sorted_comments = sorted(issue.fields.comment.comments, key=lambda c: c.created, reverse=True)
                            comments_list.append("▫️ [" + issue.key +"] ")
                            comments_list_asc.append("▫️ [" + issue.key +"] ")
                            comments_list.append("; ".join([
                                f"{comment.created[:10]} - {comment.author.displayName}: {replace_account_ids_with_names(comment.body)}"
                                for comment in sorted_comments
                            ]))
                            comments_list_asc.append("; ".join([
                                f"{comment.created[:10]} - {comment.author.displayName} wrote: {replace_account_ids_with_names(comment.body)}"
                                for comment in sorted_comments_asc
                            ]))
                            
                            print(f"*****comments_list_asc = {comments_list_asc}")
                            #comments_list.append(";")  # Add a semicolon after final comment for this issue
                            #comments_list_asc.append(";")  # Add a semicolon after final comment for this issue
                            ai_summarized = get_summarized_comments(comments_list_asc)
                            print(f"+++++ ai_summarized = {ai_summarized}")
                            comments_summarized_list.append("▫️ [" + issue.key + "] " + ai_summarized + ";")
                        
                        else:
                            comments_list.append("▫️ [" + issue.key + "] ")
                            comments_list.append("No comments;")
                            comments_list_asc.append("▫️ [" + issue.key + "] ")
                            comments_list_asc.append("No comments;")
                            comments_summarized_list.append("▫️ [" + issue.key + "]" + " No comments")
                    
                    elif field == "synopsis":
                        value_parts = []
                        issuetype = getattr(issue.fields, 'issuetype', None)
                        if issuetype and hasattr(issuetype, 'name'):
                            if issuetype.name == "Epic":
                                value_parts.append("Epic")
                        if hasattr(issue.fields, 'subtasks'):
                            value_parts.append(f"sub-tasks {len(issue.fields.subtasks)}")
                        synopsis_list = "|".join(value_parts) if value_parts else ""
                     
                    else:
                        value_str = str(value).replace("\n","")
                        print(f"Processing generic field: {field} with value: {value_str}")
                        generic_fields_list.append("▫️ [" + issue.key + "] " + value_str)

                    

                    #values.append(str(value))
                if field == "assignee":
                    print(f"Assignee list: {assignee_list}")
                    assignee_list.sort()
                    assignee_list = move_brackets_to_front(assignee_list)
                    assignee_str = ";".join(assignee_list)
                    value = assignee_str
                elif field == "headline":
                    print(f"Headline list: {headline_list}")
                    headline_list.sort()
                    headline_str = f"Total Issues: {len(headline_list)}"
                    count = sum(1 for h in headline_list if "Assignee: unassigned" in h)
                    headline_str += f"   Unassigned: {count}"
                    headline_str += "   Stories: " + str(len([h for h in headline_list if "Type: Story" in h]))
                    headline_str += "   Epics: " + str(len([h for h in headline_list if "Type: Epic" in h]))
                    headline_str += "   Tasks: " + str(len([h for h in headline_list if "Type: Task" in h]))
                    headline_str += "   Bugs: " + str(len([h for h in headline_list if "Type: Bug" in h])) + ";"
                    #headline_str += "   Sub-tasks: " + str(len([h for h in headline_list if "Type: Sub-task" in h]))
                    #headline_str += "   Issues: " + str(len([h for h in headline_list if "Type: Issue" in h]))
                    headline_str += ";".join(headline_list)
                    value = headline_str
                elif field == "timestamp":
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    value = now_str
                elif field == "url":
                    #jql_id = jql_id.tolower().replace("jql","")
                    value = "URL " + jql_id    # set it to the issue key for now. will be converted to hyperlink by update_sharepoint.py
                    #value = jql_query     # set it to the issue key for now. will be converted to hyperlink by update_sharepoint.py
                elif field == "status":
                    print(f"status list: {status_list}")
                    status_list.sort()
                    status_list = move_brackets_to_front(status_list)
                    status_str = ";".join(status_list)
                    value = status_str
                elif field == "summary":
                    summary_list.sort()
                    summary_str = ";".join(summary_list)
                    value = summary_str
                elif field == "id":
                    print(f"ID list: {id_list}")
                    id_str = ",".join(id_list)
                    value = id_str
                elif field == "key":
                    print(f"Key list: {key_list}")
                    #synopsis_str = ", ".join(key_list)  # put key into synopsis field, do not over
                    value = jql_id
                elif field == "comments":
                    # Flatten the list
                    cleaned_comments = ";".join(comments_list)
                    print(f"Comments list: {cleaned_comments}")
                    value = cleaned_comments
                elif field == "ai":
                    #print(f"Comments for AI summarization: {comments_list_asc}")
                    #value = comments_summarized_list
                    value = ";".join(comments_summarized_list)
                    print(f"AI summarized comments: {value}")
                elif field == "synopsis":
                    print(f"Synopsis list: {synopsis_list}")
                    final_value = ";".join(key_list) if key_list else ""
                    value = final_value + "; " + synopsis_list if synopsis_list else final_value
                    #value = synopsis_list
                else:
                    print(f"Field {field} is considered generic_field and will be processed as such.")
                    generic_fields_list.sort()
                    value = ";".join(generic_fields_list) if generic_fields_list else "NA"
                
                print(f"Final value for field {field}: {value}")



                values.append(str(value))
                
                
                
            print('|'.join(values))
            with open(output_file, "a") as outfile:
                outfile.write('|'.join(values) + "\n")
        except Exception as e:
            print(f"❌ Failed to run JQL query '{jql_id}': {e}")
            
            for field in field_values:
                if field == "key":
                    value = jql_id
                else:
                    value = "Bad JQL query"
            
            values.append(str(value))            
            print(','.join(values))
            with open(output_file, "a") as outfile:
                outfile.write('|'.join(values) + "\n")


print(f"Data written to {output_file}")
print(f"CSV_CREATED:{output_file}")

# process Exec Summary now
if "ExecSummary" in yaml_file:
    print(f"This is an ExecSummary yaml file = {yaml_file} ")

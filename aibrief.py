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



# this is how this script is called from resync, note the paramter list
# run_and_log(["python", "-u", proc_aisummary_script, yaml_file, timestamp], log, f"proc_aisummary.py {yaml_file}, {timestamp}")


import json
LLMCONFIG_FILE = "../../../config/llmconfig.json"

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


if len(sys.argv) < 3:
    print("Usage: python aisummary.py <yaml_file> <timestamp>")
    sys.exit(1)

yaml_file = sys.argv[1]
timestamp = sys.argv[2]



llm_model = get_llm_model(LLMCONFIG_FILE)
if not llm_model:
    llm_model = "Local"


with open(yaml_file, 'r') as f:
    data = yaml.safe_load(f)

fileinfo = data.get('fileinfo', {})
if not fileinfo:
    print("No fileinfo found in the YAML file.")
    sys.exit(1)
basename = fileinfo.get('basename')
tablename = fileinfo.get('table').replace(" ", "_") if fileinfo.get('table') else ""
source = fileinfo.get('source')
scope_file = fileinfo.get('scope file') # in this case this will match the yaml_file param passed to this script

if not basename:
    print("No 'basename'found in fileinfo. Expecting 'basename' key.")
    sys.exit(1)

if not tablename:
    print("No 'table' found in fileinfo. Expecting 'table' key.")
    sys.exit(1)

# Determine if we will be INSERTING rows eventually vs just UPDATING existing rows in Excel/SharePoint
if "aisummary.yaml" not in yaml_file.lower():
    print(f"ERROR: {yaml_file} is not a aisummary.yaml file, exiting without action.")
    sys.exit(1)


'''# Sample aisumamry.yaml format:
        fileinfo:
        basename: Breaker.xlsx
        scope file: Breaker.xlsx.Overall_Status.20250912_112941.aisummary.yaml
        source: Breaker.xlsx
        table: Overall_Status
        tables:
        - a_table.20250912_112941
        - b_table.20250912_112941
'''

# No fields are expected in aisummary.yaml
'''
fields = data.get('fields', [])
# Convert list of dicts into a dictionary
fields_dict = {field["value"]: field.get("index", "<blank>") for field in fields}

field_values = [field.get('value') for field in fields if 'value' in field]
field_indexes = [field.get('index') for field in fields if 'index' in field]
field_values_str = ','.join(field_values)
field_indexes_str = ','.join(map(str, field_indexes))
'''

print("Scope file:", scope_file )
print("Source file:", source)
print("basename:", basename)
print("Table,", tablename)
#print("Field indexes,", field_indexes_str)
#print("Field values,", field_values_str)

#jira_ids = data.get('jira_ids', [])
#jira_create_row = data.get('jira_create_rows',[])
refer_tables = data.get('tables',[])

print(f"{yaml_file} contains refer_tables: {refer_tables}")



import requests
from requests.auth import HTTPBasicAuth


# Default to localhost unless overridden in env variable (set when in Docker)
SUMMARIZER_HOST = os.getenv("SUMMARIZER_HOST", "http://localhost:8000")

def get_summarized_comments(context, sysprompt):
    """
    Summarize comments for LLM processing.
    This function takes a list of comments in ascending order and returns a summarized version.
    """
    if not context:
        return "No context provided."

    # Only join if it's a list or tuple
    if isinstance(context, (list, tuple)):
        comments_str = "; ".join(context)
    else:
        comments_str = context  # already a string

    # comments_str was a single string before, but the service expects a list[str].
    # If you only have one string, wrap it in a list.
    #context = [comments_str]

    prompt = sysprompt + ".\n\n" + context
    #prompt = sysprompt + "\n\n" + "\n".join(context)

    prompt_list = [prompt]
    print(f"calling LLM with prompt = {prompt_list[0][:255]}...")

    if llm_model == "OpenAI":
        ENDPOINT = "/summarize_openai"
    else:
        ENDPOINT = "/summarize_local"

    #resp = requests.post("http://localhost:8000/summarize", json=prompt_list)
    resp = requests.post(f"{SUMMARIZER_HOST}{ENDPOINT}", json=prompt_list)

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
    return  full_response



def build_llm_context(table_rows, table_name, timestamp):
    
    context = ""
    # first put in the sheet contents for this table
    for r in table_rows:
        # r is a list of cell values, join them into a string
        context += " | ".join(str(cell) for cell in r) + "\n"

     # now append the jiracsv contents
    jiracsv_pattern = f"{basename}.{table_name}.{timestamp}.aisummary.jira.csv"
    dir_path = os.getcwd()  # or the folder where your CSVs live

    # case-insensitive search
    matched_file = None
    for f in os.listdir(dir_path):
        if f.lower() == jiracsv_pattern.lower():
            matched_file = os.path.join(dir_path, f)
            break

    if matched_file:
        with open(matched_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            context += line
    else:
        print(f"Warning: file not found (case-insensitive match) for {jiracsv_pattern}")

    return context



from openpyxl import load_workbook

wb = load_workbook(basename)
ws = wb.active

table_rows = {}     # maps table_name -> list of rows
curr_table = None

SPECIAL_TAGS = ("<jira>", "<ai brief>")   # extend this if you have more tags
aibrief_cells = []   # list to store coordinates of <aibrief> cells

# Iterate with cell objects, not just values
for row in ws.iter_rows(values_only=False):
    row_values = [str(cell.value).strip() if cell.value is not None else "" for cell in row]

    print(f"reading row = {row_values}")

    # skip the row if all cells are blank
    if all(v == "" for v in row_values):
        continue

    # check each cell for special tags
    for cell in row:
        print(f"checking cell_value: {cell.value}")
        if cell.value and any(tag in str(cell.value) for tag in SPECIAL_TAGS):
            if "<ai brief>" in str(cell.value):
                print(f"found <ai brief> in str{cell.value} at coordinate={cell.coordinate} in row={row_values}")
                print(f"checking if tablename: {tablename} present")
                if tablename.replace("_"," ") in  str(cell.value):
                    print(f"found target tablename")
                    # Get the cell one row below in the same column
                    below_cell = ws.cell(row=cell.row + 1, column=cell.column)

                    print(f"Cell below is at {below_cell.coordinate} with value: {below_cell.value}")

                    aibrief_cells.append({
                        "coordinate": cell.coordinate,
                        "row": cell.row,
                        "column": cell.column,
                        "below_coordinate": below_cell.coordinate,
                        "below_value": below_cell.value
                    })

    # find if this row contains any special tag
    tag_cells = [v for v in row_values if any(tag in v for tag in SPECIAL_TAGS)]

    if tag_cells:
        # close current table if we were collecting
        if curr_table:
            print(f"Finished collecting rows for table '{curr_table}'")

        # check if this is a <jira> start
        jira_cells = [v for v in tag_cells if "<jira>" in v]
        if jira_cells:
            curr_table = jira_cells[0].rsplit("<jira>", 1)[0].rstrip().replace(" ", "_").lower()
            table_rows[curr_table] = []   # start fresh list
            print(f"Found <jira> table '{curr_table}'")
        else:
            # other tag encountered: stop collecting
            curr_table = None

        continue  # skip storing this header row itself

    # if inside a <jira> table, add rows
    if curr_table:
        table_rows[curr_table].append(row_values)

# Debug: print collected <aibrief> positions
print("Found <aibrief> tags at:")
for cell in aibrief_cells:
    print(f" - {cell['coordinate']} (row {cell['row']}, col {cell['column']})")


#------------------------------------------------------------------
# Dump all tables and their rows
# -----------------------------------------------------------------

context = ""
aibrief_context = ""

print("\n=== Dump of collected tables ===")
for table_name, rows in table_rows.items():
    print(f"\nTable: {table_name}")
    if (table_name in refer_tables):
        for r in rows:
            print("  ", r)
        context = build_llm_context(table_rows[table_name], table_name, timestamp)
        print(f"context generated = {context}")

        # Compose filename
        filename = f"{source}.{tablename}.{table_name}.aisummary.context.txt"
        # Save context to file
        with open(filename, "w", encoding="utf-8") as f:
            f.write(context)
        print(f"Context saved to {filename}")

        aibrief_context += "\n\n" + context
    else:
        print(f"{table_name} is not referred in {yaml_file} -> {refer_tables}")

# Compose filename
filename = f"{source}.{tablename}.aisummary.context.txt"
# Save context to file
with open(filename, "w", encoding="utf-8") as f:
    f.write(aibrief_context)
print(f"Context saved to {filename}")

sysprompt = "The following text is a csv data separated by | character.  Read all of it and summarize briefly as possible in the form of project status report for executive sumamry. highlight all milestones,  risks or blocking issues."

if isinstance(aibrief_context, list):
    aibrief_context = "\n".join(aibrief_context)

report = get_summarized_comments(aibrief_context, sysprompt)

# Compose filename
#filename = f"{os.path.splitext(source)[0]}.{tablename}.llm.txt"
filename = f"{source}.{tablename}.aisummary.llm.txt"
# Save context to file
with open(filename, "w", encoding="utf-8") as f:
    f.write(report)
print(f"LLM reponse saved to {filename}")

if aibrief_cells:
    #changes = f"{aibrief_cells[0]["coordinate"]} = {report} || "
    changes = f"{below_cell.coordinate} = {timestamp}:{report} || "
    #filename = f"{os.path.splitext(source)[0]}.{tablename}.changes.txt"
    filename = f"{source}.{tablename}.aisummary.changes.txt"
    # Save context to file
    with open(filename, "w", encoding="utf-8") as f:
        f.write(changes)
    print(f"changes written to {filename}")
else:
    print(f"aibrief_cells is empty so no changes.txt to write")

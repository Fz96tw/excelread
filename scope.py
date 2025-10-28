
import pandas as pd
import sys
import os
import yaml
import re
from googleapiclient.discovery import build
from google_oauth import *

'''from google_oauth import (
    get_google_flow,
    load_google_token,
    save_google_token,
    logout_google,
    is_google_logged_in,
)'''

from my_utils import *

'''def read_excel_rows(filename):
    df = pd.read_excel(filename, header=None)  # Treat all rows as data
    # Remove rows where all cells are NaN (i.e., completely blank)
    #df = df.dropna(how='all')
    return df.values.tolist()
'''

def read_excel_rows(filename, sheet_name=0):
    df = pd.read_excel(filename, sheet_name=sheet_name, header=None)
    return df.values.tolist()


# rename the googlelogin param to userlogin because that what is used as
def read_google_rows(googlelogin, spreadsheet_url_or_id, sheet_name=None):
    """
    Reads all rows from a Google Sheet, returns as list of lists.
    sheet_name: name of the sheet; defaults to first sheet if None.
    """
    # Extract spreadsheet ID if URL is given
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", spreadsheet_url_or_id)
    spreadsheet_id = match.group(1) if match else spreadsheet_url_or_id.strip()

    # Load user's saved credentials
    creds = load_google_token(googlelogin)
    if not creds or not creds.valid:
        raise Exception(f"❌ User {googlelogin} not logged in to Google Drive")

    service = build("sheets", "v4", credentials=creds)

    # If no sheet_name provided, get the first sheet
    if sheet_name is None:
        metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheet_name = metadata["sheets"][0]["properties"]["title"]

    print(f"Reading Google Sheet ID={spreadsheet_id}, sheet='{sheet_name}' for user={googlelogin}")
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=sheet_name
    ).execute()

    return result.get("values", [])


def set_output_filename(filename, sheet, table_name, timestamp, import_found=False, jira_create_found=False, runrate_found=False) -> str:
    print(f"set_output_filename called, timestamp = {timestamp}")
    #base_name = os.path.basename(filename)         # "Book1.xlsx"
    base_name = file_info['basename']       # expected to be "Book1.xlsx"  or googlesheet file name
    #name, ext = os.path.splitext(base_name)        # name = "Book1", ext = ".xlsx"
    outputfile = f"{base_name}.{sheet}.{table_name}.{timestamp}.scope.yaml"
    outputfile = f"{base_name}.{sheet}.{table_name}.{timestamp}.import.scope.yaml" if import_found else outputfile
    outputfile = f"{base_name}.{sheet}.{table_name}.{timestamp}.create.scope.yaml" if jira_create_found else outputfile
    outputfile = f"{base_name}.{sheet}.{table_name}.{timestamp}.rate.scope.yaml" if runrate_found else outputfile
    return outputfile  

def is_valid_jira_id(jira_id: str) -> bool:
    # Case 1: valid Jira issue key (case-insensitive)
    if re.match(r'^[A-Z][A-Z0-9]+-\d+$', jira_id, re.IGNORECASE):
        return True
    
    # Case 2: JQL query (case-insensitive)
    if jira_id.strip().lower().startswith("jql "):
        return True
    
    return False


import re

def extract_ai_summary_table_list(text: str, timestamp) -> list[str]:
    """
    Extracts all comma-separated substrings after <ai summary> in the given text.
    Spaces in substrings are replaced with underscores.
    """
    match = re.search(r"<ai brief>(.*)", text, re.IGNORECASE)
    if not match:
        return []
    
    # Get everything after <ai summary>
    substrings = match.group(1).strip()
    
    # Split by commas and normalize
#    return [s.strip().replace(" ", "_") for s in substrings.split(",") if s.strip()]
    return [s.strip().replace(" ", " ") for s in substrings.split(",") if s.strip()]


def extract_email_list(text: str) -> list[str]:
    """
    Extracts all comma-separated substrings after <ai summary> in the given text.
    Spaces in substrings are replaced with underscores.
    """
    match = re.search(r"<email>(.*)", text, re.IGNORECASE)
    if not match:
        return []
    
    # Get everything after <ai summary>
    substrings = match.group(1).strip()
    
    # Split by commas and normalize
#    return [s.strip().replace(" ", "_") for s in substrings.split(",") if s.strip()]
    return [s.strip().replace(" ", "_") for s in substrings.split(",") if s.strip()]



def extract_second_block(s: str):
    # Find all <...> blocks
    matches = re.findall(r"<(.*?)>", s)
    
    if len(matches) < 2:
        raise ValueError("Input string does not contain a second <...> block")
    
    # Take the second block and split by space
    parts = matches[1].split()
    if len(parts) != 2:
        raise ValueError("Second block must contain exactly two parts")
    
    text, number = parts[0], int(parts[1])
    return text, number


def extract_rate_params_list(s: str, timestamp) -> list[str]:
    
    print(f"extract_rate_params_list called with s={s} timestamp={timestamp}")    
    # Find all <...> blocks
    matches = re.findall(r"<(.*?)>", s)
    
    if len(matches) < 2:
        print(f"'{s}' input string does not contain a second <...> block")
        raise ValueError("Input string does not contain a second <...> block")
    
    # Take the second block and split by space
    #parts = matches[1].split()
    return_list = []
    return_list.append(matches[1])

    jql_part = s.split("jql", 1)[1].strip()
    if jql_part:
        return_list.append("JQL " + jql_part)
        print(f"JQL {jql_part} found and return_list {return_list}")
    else:
        print("ERROR: No JQL found in <jira resolved> table definition")
        raise ValueError("ERROR: No JQL found in <jira resolved> table definition")

    return return_list

def write_execsummary_yaml(jira_ids, filename, file_info, timestamp):
    # always create <exec summary> yaml files incase they're needed down the chain
    # step 1 hunt for jira id in all rows and build a list
    # step 2 hunt for jql in all the rows and get list of jira id and add to list from #1
    # step 3 Create ayaml new exec summary scope yaml file with all the Jira found in #1 #2
    # step 4 read_jira will process this yaml downstream
    print("ExecSumamry processing now")
    #cleaned_value = "ExecSummary"
    execsummary_scope_output_file = f"{filename}.{sheet}.{file_info['table']}.{timestamp}.aisummary.scope.yaml"
    

    file_info["scope file"] = execsummary_scope_output_file
    #file_info["table"] = cleaned_value

    with open(execsummary_scope_output_file, 'w') as f:
        yaml.dump({ "fileinfo": file_info }, f, default_flow_style=False)

    jira_fields = []

    jira_fields.append({"value": "key", "index": 0})
    jira_fields.append({"value": "summary", "index": 0})
    jira_fields.append({"value": "description", "index": 0})
    jira_fields.append({"value": "status", "index": 0})
    jira_fields.append({"value": "issuetype", "index": 0})
    jira_fields.append({"value": "priority", "index": 0})
    jira_fields.append({"value": "created", "index": 0})
    jira_fields.append({"value": "assignee", "index": 0})
    jira_fields.append({"value": "status", "index": 0})
    jira_fields.append({"value": "comments", "index": 0})


    with open(execsummary_scope_output_file, 'a') as f:
        yaml.dump({ "fields": jira_fields }, f, default_flow_style=False)
   
    if jira_ids:
        print(f"JIRA IDs found: {jira_ids}")

        # This won't/doesn't work when jira_id is a JQL.  Not sure why I ever thought thsi would work?!
        # Filter out jira_ids starting with "jql" (case-insensitive) since the excel table already has processed the jql and the Jira IDs are listed here already
        #jira_ids = [jid for jid in jira_ids if not jid.lower().startswith("jql")]

        # instead just dump the jira_ids to the scope file. read_jira.py will take care of it, ie run jql and get the jira ids.
         
        with open(execsummary_scope_output_file, 'a') as f:
            yaml.dump({"jira_ids": jira_ids}, f, default_flow_style=False)
            print(f"Fieldname args found for: {jira_fields_default_value}")
            yaml.dump({"field_args": jira_fields_default_value}, f, default_flow_style=False)

    else:
        print(f"ERROR: can't proceed, No JIRA IDs found to write to aisummary yaml file {execsummary_scope_output_file}")
        sys.exit(1)

    f.close()
    print("ExecSummary scope yaml file created successfully:", execsummary_scope_output_file)


def close_current_jira_table(jira_fields, jira_fields_default_value, jira_ids, jira_create_rows, scope_output_file, filename, file_info, timestamp): 
    print("close_current_jira_table called")

    if jira_fields and jira_create_rows:
            jira_fields.append({"value": "row", "index": -1})

    if jira_fields:
        with open(scope_output_file, 'a') as f:
            yaml.dump({ "fields": jira_fields }, f, default_flow_style=False)

    if jira_ids:
        print("closing out previous scope file")
        print(f"JIRA IDs found: {jira_ids}")
        with open(scope_output_file, 'a') as f:
            yaml.dump({"jira_ids": jira_ids}, f, default_flow_style=False)
            if jira_fields_default_value:
                print(f"Fieldname args found for: {jira_fields_default_value}")
                yaml.dump({"field_args": jira_fields_default_value}, f, default_flow_style=False)


        print("JIRA rows have been written to output file:", scope_output_file)
        print("Total rows processed:", row_count)
        # close the file
        f.close()

        # always write exec sumamry yaml even tho we don't know if
        # will be needed/used
        if is_google_sheet:
            write_execsummary_yaml(jira_ids, file_info['basename'], file_info, timestamp)  
        else:
            write_execsummary_yaml(jira_ids, filename, file_info, timestamp)  

    elif jira_create_rows:
        print("closing out previous scope file")


        print(f"JIRA CREATE ROWS found: {jira_create_rows}")
        with open(scope_output_file, 'a') as f:
            yaml.dump({"jira_create_rows": jira_create_rows}, f, default_flow_style=False)

        print("JIRA rows have been written to output file:", scope_output_file)
        print("Total rows processed:", row_count)
        # close the file
        f.close()
        
    else:
        print(f"No scope file create because No JIRA IDs found in table {file_info['table']} in file {filename}")


    #jira_table_found = False
    jira_ids = []
    jira_fields = []
    jira_fields_default_value = {}      # <jira><create> allows default values for jira fields 
    fields_found = False
    jira_import_found = False
    jira_create_found = False
    jira_create_rows = []
    runrate_found = False
    #cleaned_value = str(cell).strip().replace(" ", "_")        


def get_last_data_row_from_rows(rows):
    """
    Given rows from read_excel_rows(), return the last row index (0-based)
    and Excel-style row number (1-based) that has any non-empty cell.
    
    :param rows: List of rows (list of lists) from read_excel_rows()
    :return: (last_row_index, last_row_number)
    """
    last_index = None
    for i, row in enumerate(rows):
        if any(cell is not None and str(cell).strip() != "" for cell in row):
            last_index = i
    
    if last_index is None:
        return None, None  # No data at all
    
    return last_index, last_index + 1

#import pandas as pd  # or import numpy as np
def is_row_blank(row):
    return all(cell is None or pd.isna(cell) or str(cell).strip() == "" for cell in row)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python scope.py <filename> <sheet> <timestamp> <userlogin>")
        sys.exit(1)

    filename = sys.argv[1]
    sheet = sys.argv[2]
    timestamp = sys.argv[3]
    userlogin = sys.argv[4] 

    '''if ":" in filename_ex:
        filename, sheet = filename_ex.split(":", 1)
        # Use first sheet if sheet_name is empty
        sheet = sheet if sheet.strip() else 0
        filename_ex = filename_ex.replace(":",".")   # save for filename allowable character
    else:
        filename = filename_ex
        sheet = 0
    '''

    print(f"argv filename={filename} worksheet={sheet} timestamp={timestamp}")   

     # Detect if source is Google Sheet (simple heuristic: URL or just ID)
    is_google_sheet = isinstance(filename, str) and ("docs.google.com/spreadsheets" in filename or re.match(r"^[a-zA-Z0-9-_]{20,}$", filename))

    if is_google_sheet:
        print(f"Reading Google Sheet: {filename}, sheet: {sheet}")
        # For Google Sheets, assume userlogin is 'default' for now
        rows = read_google_rows(userlogin, filename, sheet_name=sheet)
    else:
        rows = read_excel_rows(filename, sheet_name=sheet)

    last_idx, last_excel_row = get_last_data_row_from_rows(rows)    # Find the last row where any column has a non-NaN value
    print(f"Last data row index (0-based): {last_idx}, Excel row number (1-based): {last_excel_row}")

    jira_ids = []
    jira_create_rows = []
    jira_fields_default_value = {}
    jira_fields = []
    file_info = []
    fields_found = False
    jira_table_found = False
    jira_import_found = False
    jira_create_found = False
    runrate_found = False
    scope_output_file = ""
    exec_summary_found = False  
    jira_id_exec_summary = []
    jira_fields_exec_summary = []
    exec_summary_cell = ""  # location of cell where the summary contents need to be placed

    #file_info.append({"source":filename, 'basename':os.path.basename(filename), "scope file":scope_output_file})
    #with open(scope_output_file, 'w') as f:
    #    yaml.dump({ "fileinfo": file_info}, f, default_flow_style=False)
    file_info = {
        "source": filename,
        "basename": os.path.basename(filename),
        "sheet": sheet
        #"scope file": scope_output_file
    }

    if is_google_sheet:
        doc_id = extract_google_doc_id(filename) or file_info["basename"]   
        file_info["basename"] = get_google_drive_filename(userlogin, doc_id) or doc_id

    
    row_count = 0
    for outer_idx, row in enumerate(rows):
        row_count += 1
        print(f"row count {row_count} is:{row}")

        if len(row) < 1:
            print("skipping blank row")
            continue


        value_counts = {}  # used to avoid field name clashes when using field_args in field name

        for idx, cell in enumerate(row):
            orig_case_cell_str = str(cell).replace("\n", " ").replace("\r", " ").strip() # save original case for export to scope file
            cell_str = str(cell).replace("\n", " ").replace("\r", " ").strip().lower()
            #print(f"****** cell_str = {cell_str}")
            if ("<ai brief>" in cell_str and len(str(cell_str)) > 9): 
                                               
                print(f"<ai brief> found in cell_str={cell_str}")

                if jira_table_found:
                    close_current_jira_table(jira_fields, jira_fields_default_value, jira_ids, jira_create_rows, scope_output_file, filename, file_info, timestamp)
                    jira_table_found = False
                    jira_ids = []
                    jira_fields = []
                    jira_fields_default_value = {}
                    fields_found = False
                    jira_import_found = False
                    jira_create_found = False
                    jira_create_rows = []

                exec_summary_found = True;
                exec_summary_cell = "";
                cleaned_value = str(cell).rsplit("<ai brief>", 1)[0].strip().replace(" ", "_")
                #scope_output_file = set_output_filename(filename, cleaned_value, timestamp, jira_import_found, jira_create_found)
                #scope_output_file = f"{filename}.{sheet}.{cleaned_value}.{timestamp}.aibrief.scope.yaml"
                scope_output_file = f"{file_info['basename']}.{sheet}.{cleaned_value}.{timestamp}.aibrief.scope.yaml"
                print(f"scope will be saved to: {scope_output_file}")
                file_info["scope file"] = scope_output_file
                file_info["table"] = cleaned_value
                with open(scope_output_file, 'w') as f:
                    yaml.dump({ "fileinfo": file_info }, f, default_flow_style=False)
       
                # this is the refer_tables list for aibrief processing downstream
                ai_table_list = extract_ai_summary_table_list(orig_case_cell_str, timestamp)
                with open(scope_output_file, 'a') as f:
                    yaml.dump({"tables":ai_table_list}, f, default_flow_style=False)

                continue # go on with next cell in row incase there's <email> in same row

            elif "<llm>" in cell_str:
                print(f"<llm> tag found in cell_str={cell_str}")
                match = re.search(r"<llm>(.*)",cell_str, re.IGNORECASE)
                if match:
                    llm_text = match.group(1).strip()
                    with open(scope_output_file, 'a') as f:
                        yaml.dump({"llm": llm_text}, f, default_flow_style=False)                    
                continue        # we may have <jira> in same row so continue processing

            elif "<email>" in cell_str and exec_summary_found:
                print(f"<email> found in cell_str={cell_str}")
                email_list = extract_email_list(cell_str)
                with open(scope_output_file, 'a') as f:
                    yaml.dump({"email":email_list}, f, default_flow_style=False)
                continue        # we may have <jira> in same row so continue processing

            elif "<cycletime>" in cell_str or "<statustime>" in cell_str:
                print(f"<cycletime> found in cell_str={cell_str}")
                #cell_after_tag = cell_str.split("<cycletime>", 1)[1].strip()
                #jira_proj_list = [s.strip().replace(" ", "_") for s in cell_after_tag.split(",") if s.strip()]
                #print(f"Jira projects found for cycletime: {jira_proj_list}")

                if jira_table_found:
                    close_current_jira_table(jira_fields, jira_fields_default_value, jira_ids, jira_create_rows, scope_output_file, filename, file_info, timestamp)
                    jira_table_found = False
                    jira_ids = []
                    jira_fields = []
                    jira_fields_default_value = {}
                    fields_found = False
                    jira_import_found = False
                    jira_create_found = False
                    jira_create_rows = []

                runrate_found = False #does not depend on jira_table_found

                if "<cycletime>" in cell_str:
                    # generate quickstart scope yaml file
                    cleaned_value = str(cell).rsplit("<cycletime>", 1)[0].strip().replace(" ", "_")
                    scope_output_file = f"{file_info['basename']}.{sheet}.{cleaned_value}.{timestamp}.cycletime.scope.yaml"
                else:
                    cleaned_value = str(cell).rsplit("<statustime>", 1)[0].strip().replace(" ", "_")
                    scope_output_file = f"{file_info['basename']}.{sheet}.{cleaned_value}.{timestamp}.statustime.scope.yaml"


                if "jql" in cell_str:
                    jql_str = cell_str.split("jql", 1)[1].strip()
                    if jql_str:
                        print(f"JQL found and added to jira_ids: {jql_str}")
                        #jira_ids.append("JQL " + import_jql)
                else:
                    print("ERROR: No JQL found in <cycletime> table definition")
                    raise ValueError("ERROR: No JQL found in <cycletime> table definition")
   
                print(f"scope will be saved to: {scope_output_file}")
                file_info["scope file"] = scope_output_file
                file_info["table"] = cleaned_value
                with open(scope_output_file, 'w') as f:
                    yaml.dump({ "fileinfo": file_info }, f, default_flow_style=False)
                       
                with open(scope_output_file, 'a') as f:
                    yaml.dump({"jql":jql_str}, f, default_flow_style=False)
                    # save the row and col info for where this was found in the excel sheet for use by runrate_resolved.py
                    yaml.dump({"row":row_count}, f, default_flow_style=False)
                    yaml.dump({"col":idx}, f, default_flow_style=False)
                    yaml.dump({"lastrow":last_excel_row}, f, default_flow_style=False)


                # Look ahead from the next row
                nonblank_count = 0
                print(f"start scan ahead at outer_idx={outer_idx}")
                for inner_idx in range(outer_idx + 1, len(rows)):
                    print(f"scan ahead rows[{inner_idx}]={rows[inner_idx]}")
                    if not is_row_blank(rows[inner_idx]):
                        nonblank_count += 1
                        print(f"not blank, incrementing nonblank_count to {nonblank_count}")
                    else:
                        print("blank row found, breaking out of scan ahead")
                        break  # Stop at the first non-blank row

                print(f"Row {outer_idx+1} has {nonblank_count} contiguous blank row(s) below it.")

                with open(scope_output_file, 'a') as f:
                    yaml.dump({"scan_ahead_nonblank_rows":nonblank_count}, f, default_flow_style=False)


                continue # get to next row
            
            elif "<quickstart>" in cell_str:
                print(f"<quickstart> found in cell_str={cell_str}")
                cell_after_tag = cell_str.split("<quickstart>", 1)[1].strip()
                jira_proj_list = [s.strip().replace(" ", "_") for s in cell_after_tag.split(",") if s.strip()]
                print(f"Jira projects found for quickstart: {jira_proj_list}")

                if jira_table_found:
                    close_current_jira_table(jira_fields, jira_fields_default_value, jira_ids, jira_create_rows, scope_output_file, filename, file_info, timestamp)
                    jira_table_found = False
                    jira_ids = []
                    jira_fields = []
                    jira_fields_default_value = {}
                    fields_found = False
                    jira_import_found = False
                    jira_create_found = False
                    jira_create_rows = []

                runrate_found = False #does not depend on jira_table_found

                # generate quickstart scope yaml file
                cleaned_value = str(cell).rsplit("<quickstart>", 1)[0].strip().replace(" ", "_")
                scope_output_file = f"{file_info['basename']}.{sheet}.{cleaned_value}.{timestamp}.quickstart.scope.yaml"

                print(f"scope will be saved to: {scope_output_file}")
                file_info["scope file"] = scope_output_file
                file_info["table"] = cleaned_value
                with open(scope_output_file, 'w') as f:
                    yaml.dump({ "fileinfo": file_info }, f, default_flow_style=False)
                       
                with open(scope_output_file, 'a') as f:
                    yaml.dump({"jira projects":jira_proj_list}, f, default_flow_style=False)
                    # save the row and col info for where this was found in the excel sheet for use by runrate_resolved.py
                    yaml.dump({"row":row_count}, f, default_flow_style=False)
                    yaml.dump({"col":idx}, f, default_flow_style=False)
                    yaml.dump({"lastrow":last_excel_row}, f, default_flow_style=False)


                continue # get to next row

            elif "<rate resolved>" in cell_str or "<rate assignee>" in cell_str:
                
                if jira_table_found:
                    close_current_jira_table(jira_fields, jira_fields_default_value, jira_ids, jira_create_rows, scope_output_file, filename, file_info, timestamp)
                    jira_table_found = False
                    jira_ids = []
                    jira_fields = []
                    jira_fields_default_value = {}
                    fields_found = False
                    jira_import_found = False
                    jira_create_found = False
                    jira_create_rows = []

                print(f"<rate resolved> or <rate assignee> found in cell_str={cell_str}")
                runrate_found  = True

                # call function to process runrate resolved now...
                # 1. it will get jira data based on jql provided
                # 2. get list of jira ids in result
                # 3. bucketize them based on resolve date create data row per assignee
                # 4. write to changes.txt file diectly. must include columns headers, and data.

                #scope_output_file = set_output_filename(filename, cleaned_value, timestamp, jira_import_found, jira_create_found)
                
                if "<rate resolved>" in cell_str:
                    cleaned_value = str(cell).rsplit("<rate resolved>", 1)[0].strip().replace(" ", "_")
                    scope_output_file = f"{file_info['basename']}.{sheet}.{cleaned_value}.{timestamp}.resolved.rate.scope.yaml"
                else:
                    cleaned_value = str(cell).rsplit("<rate assignee>", 1)[0].strip().replace(" ", "_")
                    scope_output_file = f"{file_info['basename']}.{sheet}.{cleaned_value}.{timestamp}.assignee.rate.scope.yaml"

                print(f"scope will be saved to: {scope_output_file}")
                file_info["scope file"] = scope_output_file
                file_info["table"] = cleaned_value
                with open(scope_output_file, 'w') as f:
                    yaml.dump({ "fileinfo": file_info }, f, default_flow_style=False)
       
                rate_params_list = extract_rate_params_list(cell_str, timestamp)
                with open(scope_output_file, 'a') as f:
                    yaml.dump({"params":rate_params_list}, f, default_flow_style=False)
                    # save the row and col info for where this was found in the excel sheet for use by runrate_resolved.py
                    yaml.dump({"row":row_count}, f, default_flow_style=False)
                    yaml.dump({"col":idx}, f, default_flow_style=False)

                # Look ahead from the next row
                nonblank_count = 0
                print(f"start scan ahead at outer_idx={outer_idx}")
                for inner_idx in range(outer_idx + 1, len(rows)):
                    print(f"scan ahead rows[{inner_idx}]={rows[inner_idx]}")
                    if not is_row_blank(rows[inner_idx]):
                        nonblank_count += 1
                        print(f"not blank, incrementing nonblank_count to {nonblank_count}")
                    else:
                        print("blank row found, breaking out of scan ahead")
                        break  # Stop at the first non-blank row

                print(f"Row {outer_idx+1} has {nonblank_count} contiguous blank row(s) below it.")

                with open(scope_output_file, 'a') as f:
                    yaml.dump({"scan_ahead_nonblank_rows":nonblank_count}, f, default_flow_style=False)


                break # get to next row 

            elif ("<jira>" in cell_str and len(str(cell_str)) > 6):  # greater than 6 because a table name is expected
  
                if jira_table_found:            
                    print("Found a NEW <jira> table or <ai brief> table")

                    if jira_fields and jira_create_rows:
                            jira_fields.append({"value": "row", "index": -1})   # add custom field that will contain the sheet row number of table

                    if jira_fields:
                        with open(scope_output_file, 'a') as f:
                            yaml.dump({ "fields": jira_fields }, f, default_flow_style=False)

                    if jira_ids:
                        print("closing out previous scope file")
                        print(f"JIRA IDs found: {jira_ids}")
                        with open(scope_output_file, 'a') as f:
                            yaml.dump({"jira_ids": jira_ids}, f, default_flow_style=False)
                            if jira_fields_default_value:   
                                print(f"Fieldname args found for: {jira_fields_default_value}")
                                yaml.dump({"field_args": jira_fields_default_value}, f, default_flow_style=False)


                        print("JIRA rows have been written to output file:", scope_output_file)
                        print("Total rows processed:", row_count)
                        # close the file
                        f.close()

                        # always write exec sumamry yaml even tho we don't know if
                        # will be needed/used
#                        write_execsummary_yaml(jira_ids, filename, file_info, timestamp)  

                    elif jira_create_rows:
                        print("closing out previous scope file")


                        print(f"JIRA CREATE ROWS found: {jira_create_rows}")
                        with open(scope_output_file, 'a') as f:
                            yaml.dump({"jira_create_rows": jira_create_rows}, f, default_flow_style=False)

                        print("JIRA rows have been written to output file:", scope_output_file)
                        print("Total rows processed:", row_count)
                        # close the file
                        f.close()
                        
                    else:
                        print(f"No scope file create because No JIRA IDs found in table {file_info['table']} in file {filename}")


                    #jira_table_found = False
                    jira_ids = []
                    jira_fields = []
                    jira_fields_default_value = {}
                    fields_found = False
                    jira_import_found = False
                    jira_create_found = False
                    jira_create_rows = []
                    runrate_found = False
                    #cleaned_value = str(cell).strip().replace(" ", "_")
                else:
                    jira_table_found = True
                    
                print(f"Found 'Jira Table' in cell index {idx} {row}")     

                if "jql" in cell_str:
                    jira_import_found = True
                    print("JQL import found in table name: ", cell_str)
                    import_jql = cell_str.split("jql", 1)[1].strip()
                    if import_jql:
                        print(f"Import JQL found and added to jira_ids: {import_jql}")
                        jira_ids.append("JQL " + import_jql)

                elif "create" in cell_str:
                    jira_create_found = True
                    print("CREATE found in table name: ", cell_str)

                runrate_found = False  # just make sure this is alwayd reset to false if we had a <rate> table before this. 
                cleaned_value = str(cell).rsplit("<jira>", 1)[0].strip().replace(" ", "_")
                scope_output_file = set_output_filename(filename, sheet, cleaned_value, timestamp, jira_import_found, jira_create_found, runrate_found)
                print(f"scope will be saved to: {scope_output_file}")
                file_info["scope file"] = scope_output_file
                file_info["table"] = cleaned_value
                with open(scope_output_file, 'w') as f:
                    yaml.dump({ "fileinfo": file_info }, f, default_flow_style=False)
       
                break   # break out of for loop and continue with next row.  Cannot have anything else in same row after <jira> table tag is found

            
            if not jira_table_found:
                #print(f"No 'Jira Table' found in this cell index {idx} Skipping to next cell.")
                continue  # continue to next cell in the row
                

            import re
            # remove non-breaking spaces and newlines, then lower case. 
            cell_str = str(cell).replace("\xa0", " ").replace("\n", " ").replace("\r", " ").lower().strip()

            match = re.search(r'<(.*?)>', cell_str)    
            if match and not fields_found:  # ignore <..> is found in other rows after we have already found the fields for the jira table
                value = match.group(1).strip()
                print(f"Found field definition in cell for field {value} at column index {idx}")

                #jira_fields.append({"value": value, "index": idx})

                # dual-use of default values here. pay attention...
                # scenario 1 
                # create mode. treated as default value for this field if specified in this cell 
                # Match everything after <...> if create mode then used as default value
                # 
                # scenario 2
                # for all other tables default_value is treated as the prompt for llm
                print(f"checking for fieldname args for {cell_str}...")
                match2 = re.search(r"<[^>]+>\s+(.+)", cell_str)
                value_counts = {}
                if match2:
                    default_value = match2.group(1)  
                    default_value = default_value.replace(",",";")#.replace(" ","")
                                    
                    # initialize or increment the counter
                    value_counts[value] = value_counts.get(value, 0) + 1
                    value = f"{value}_{value_counts[value]}"  # add numeric suffix
                    
                    jira_fields_default_value[value] = default_value
                    print(f"Found default value in cell for field {match} = {default_value}")
                    print(f"set jira_fields_default_value({value}) = {jira_fields_default_value.get(value)}")
                    
                else:
                    print(f"No fieldname arg found in {cell_str}")

                # at this point value may have been updated if there was a prompt string found above
                jira_fields.append({"value": value, "index": idx})


        if jira_fields and not fields_found:
            fields_found = True
            continue

        if fields_found and jira_create_found:
            print("Create Mode: active") 

            #if len(row) != len(jira_fields)
            
            this_row = ""
            # TODO: read all the needed jira field values from the sheet and store in jira_create_rows list
            print(f"dumping jira_fields_default_value {jira_fields_default_value}")
            for idx, field in enumerate(jira_fields):

                print(f"idx:{idx}  field:{field}")
                cell_index = field.get("index")
                cell = row[cell_index]
                print(f"cell at column index {cell_index} = {cell}")

                if pd.isna(cell):
                    field_name = field.get("value")
                    print(f"cell is empty so checking if default value for field '{field_name}' was specified")
                    default = jira_fields_default_value.get(field_name, "<blank>")
                    print(f"Default value set to '{default}' for field {field_name}")
                    cell_str = default
                else:
                    cell_str = str(cell).replace("\n", " ").replace("\r", " ").replace(",","|").strip().lower()
                
                this_row += cell_str + ","

            this_row += str(row_count) 
            this_row = this_row.rstrip(",")
            print(f"this_row scan completed: {this_row}")
            jira_create_rows.append(this_row)
                
        elif fields_found and not jira_import_found:
            # lookup the index of the field "key"
            index_of_id = next((field['index'] for field in jira_fields if field['value'] == "key"), None)
            if index_of_id is not None:
                cell_value = row[index_of_id]
                #if pd.notna(cell_value) and str(cell_value).strip():
                if is_valid_jira_id(str(cell_value).strip()):
                    jira_ids.append(cell_value)
                    jira_id_exec_summary.append(cell_value)
                else:
                    print(f"Ignoring Invalid JIRA ID found: {cell_value} in row {row[0]}")
            else:
                print(f"No <key> found in this row {row[0]}")

        print("---Moving to next row")
        
    
    print("Finished reading all rows")


    if jira_fields and jira_create_rows:
         jira_fields.append({"value": "row", "index": -1})

    with open(scope_output_file, 'a') as f:
        yaml.dump({ "fields": jira_fields }, f, default_flow_style=False)

    if jira_ids:
        print(f"JIRA IDs found: {jira_ids}")
        with open(scope_output_file, 'a') as f:
            yaml.dump({"jira_ids": jira_ids}, f, default_flow_style=False)
#            if len(jira_fields_default_value):
            print(f"Fieldname args found for: {jira_fields_default_value}")
            yaml.dump({"field_args": jira_fields_default_value}, f, default_flow_style=False)

    elif jira_create_rows:
        print(f"JIRA create rows found: {jira_create_rows}")
        with open(scope_output_file, 'a') as f:
            yaml.dump({"jira_create_rows": jira_create_rows}, f, default_flow_style=False)

    else:
        print(f"No JIRA IDs or JIRA Create Rows found in table {file_info['table']} in file {filename}")


    print("JIRA rows have been written to output file:", scope_output_file)
    print("Total rows processed:", len(rows))
    # close the file
    f.close()
    print("Scope file created successfully:", scope_output_file)
    
    # remmember to do this for the last table found in the sheet too!
    # but if this scope was being done on <ai brief> then no need
    # to make a aisummary.scope.yaml since it doesn't have any content on its own.
    if not exec_summary_found:
        if is_google_sheet:
            write_execsummary_yaml(jira_ids, file_info['basename'], file_info, timestamp)  
        else:
            write_execsummary_yaml(jira_ids, filename, file_info, timestamp)        



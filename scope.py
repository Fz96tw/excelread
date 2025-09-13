
import pandas as pd
import sys
import os
import yaml
import re


def read_excel_rows(filename):
    df = pd.read_excel(filename, header=None)  # Treat all rows as data
    # Remove rows where all cells are NaN (i.e., completely blank)
    #df = df.dropna(how='all')
    return df.values.tolist()


def set_output_filename(filename, table_name, timestamp, import_found=False, jira_create_found=False):
    print(f"set_output_filename called, timestamp = {timestamp}")
    base_name = os.path.basename(filename)         # "Book1.xlsx"
    #name, ext = os.path.splitext(base_name)        # name = "Book1", ext = ".xlsx"
    outputfile = f"{base_name}.{table_name}.{timestamp}.scope.yaml"
    outputfile = f"{base_name}.{table_name}.{timestamp}.import.scope.yaml" if import_found else outputfile
    outputfile = f"{base_name}.{table_name}.{timestamp}.create.scope.yaml" if jira_create_found else outputfile
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
    return [s.strip().replace(" ", "_") for s in substrings.split(",") if s.strip()]


def write_execsummary_yaml():
    # always create <exec summary> yaml files incase they're needed down the chain
    # step 1 hunt for jira id in all rows and build a list
    # step 2 hunt for jql in all the rows and get list of jira id and add to list from #1
    # step 3 Create ayaml new exec summary scope yaml file with all the Jira found in #1 #2
    # step 4 read_jira will process this yaml downstream
    print("ExecSumamry processing now")
    #cleaned_value = "ExecSummary"
    execsummary_scope_output_file = f"{filename}.{file_info["table"]}.{timestamp}.aisummary.scope.yaml"


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
        with open(execsummary_scope_output_file, 'a') as f:
            yaml.dump({"jira_ids": jira_ids}, f, default_flow_style=False)

    f.close()
    print("ExecSummary scope yaml file created successfully:", execsummary_scope_output_file)



if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scope.py <filename> <timestamp>")
        sys.exit(1)

    filename = sys.argv[1]
    timestamp = sys.argv[2]

    print(f"argv filename={filename}  timestamp={timestamp}")    
    rows = read_excel_rows(filename)
    
    jira_ids = []
    jira_create_rows = []
    jira_fields_default_value = {}
    jira_fields = []
    file_info = []
    fields_found = False
    jira_table_found = False
    jira_import_found = False
    jira_create_found = False
    scope_output_file = ""
    exec_summary_found = False  
    jira_id_exec_summary = []
    jira_fields_exec_summary = []
    exec_summary_cell = ""  # location of cell where the summary contents need to be placed

    #file_info.append({"source":filename, "basename":os.path.basename(filename), "scope file":scope_output_file})
    #with open(scope_output_file, 'w') as f:
    #    yaml.dump({ "fileinfo": file_info}, f, default_flow_style=False)
    file_info = {
        "source": filename,
        "basename": os.path.basename(filename),
        #"scope file": scope_output_file
    }
    
    row_count = 0
    for row in rows:
        row_count += 1
        print(f"row count {row_count} is:{row}")

        if len(row) < 1:
            print("skipping blank row")
            continue

        for idx, cell in enumerate(row):
            cell_str = str(cell).replace("\n", " ").replace("\r", " ").strip().lower()

            if "<ai brief>" in cell_str:
                print(f"<ai brief> found in cell_str={cell_str}")
                exec_summary_found = True;
                exec_summary_cell = "";
                cleaned_value = str(cell).rsplit("<ai brief>", 1)[0].strip().replace(" ", "_")
                #scope_output_file = set_output_filename(filename, cleaned_value, timestamp, jira_import_found, jira_create_found)
                scope_output_file = f"{filename}.{cleaned_value}.{timestamp}.aisummary.yaml"
                print(f"scope will be saved to: {scope_output_file}")
                file_info["scope file"] = scope_output_file
                file_info["table"] = cleaned_value
                with open(scope_output_file, 'w') as f:
                    yaml.dump({ "fileinfo": file_info }, f, default_flow_style=False)
       
                ai_table_list = extract_ai_summary_table_list(cell_str, timestamp)
                with open(scope_output_file, 'a') as f:
                    yaml.dump({"tables":ai_table_list}, f, default_flow_style=False)

                break   # break out of for loop and continue with next row
            
            
            elif ("<jira>" in cell_str and len(str(cell_str)) > 6) or ("<ai brief>" in cell_str and len(str(cell_str)) > 9):  # greater than 6 because a table name is expected
                if jira_table_found:
                
                    print("Found a NEW <jira> table or <ai brief> table")

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

                        print("JIRA rows have been written to output file:", scope_output_file)
                        print("Total rows processed:", row_count)
                        # close the file
                        f.close()

                        # always write exec sumamry yaml even tho we don't know if
                        # will be needed/used
                        write_execsummary_yaml()  

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

                cleaned_value = str(cell).rsplit("<jira>", 1)[0].strip().replace(" ", "_")
                scope_output_file = set_output_filename(filename, cleaned_value, timestamp, jira_import_found, jira_create_found)
                print(f"scope will be saved to: {scope_output_file}")
                file_info["scope file"] = scope_output_file
                file_info["table"] = cleaned_value
                with open(scope_output_file, 'w') as f:
                    yaml.dump({ "fileinfo": file_info }, f, default_flow_style=False)
       
                break   # break out of for loop and continue with next row

            
            if not jira_table_found:
                print(f"No 'Jira Table' found in this cell index {idx} Skipping to next cell.")
                continue  # continue to next cell in the row
                

            import re
            # remove non-breaking spaces and newlines, then lower case. 
            cell_str = str(cell).replace("\xa0", " ").replace("\n", " ").replace("\r", " ").lower().strip()

            match = re.search(r'<(.*?)>', cell_str)    
            if match and not fields_found:  # ignore <..> is found in other rows after we have already found the fields for the jira table
                value = match.group(1).strip()
                jira_fields.append({"value": value, "index": idx})

                # also read the default value for this field if specified in this cell 
                # Match everything after <...>
                match2 = re.search(r"<[^>]+>\s+(.+)", cell_str)
                if match2:
                    default_value = match2.group(1)  
                    default_value = default_value.replace(",","|").replace(" ","")
                    jira_fields_default_value[value] = default_value
                    print(f"Found default value in cell for field {match} = {default_value}")
                    print(f"set jira_fields_default_value({value}) = {jira_fields_default_value.get(value)}")


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
                
        elif fields_found:
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
    write_execsummary_yaml()



import sys
from openpyxl.styles import Alignment

import re

def is_valid_jira_id(jira_id):
    return re.match(r'^[A-Z][A-Z0-9]+-\d+$', jira_id) is not None or "JQL" not in jira_id

def is_JQL(jira_id):
    return "JQL" in jira_id

field_index_map = {}
jira_data = {}
change_list = []  # ← This will hold "A1=newvalue"-style strings
file_info = {}

def load_jira_file(filename):
    print(f"Loading JIRA data from {filename}")
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    if len(lines) < 6:
        raise ValueError("File must contain at least 6 header lines.")

    file_info['source'] = lines[0].strip().replace("Source file,", "").strip()
    file_info['basename'] = lines[1].strip().replace("Basename,", "").strip()
    file_info['scope file'] = lines[2].strip().replace("Scope file,", "").strip()
    file_info['table'] = lines[3].strip().replace("Table,", "").strip()

    print(f"lines[4]: {lines[4].strip()}")
    print(f"lines[5]: {lines[5].strip()}")

    # Parse field indexes and values from the first two lines
    index_line = lines[4].strip().replace("Field indexes,", "").strip()
    value_line = lines[5].strip().replace("Field values,", "").strip()

    #print(f"Index line: {index_line}")
    #print(f"Value line: {value_line}")

    index_values = [int(i.strip()) for i in index_line.split(',')]
    field_names = [v.strip() for v in value_line.split(',')]

    if len(index_values) != len(field_names):
        raise ValueError("Mismatch between number of field indexes and field names.")

    field_index_map = dict(zip(field_names, index_values))

    # Parse the remaining lines (data rows)
    for line in lines[6:]:
        line = line.strip()
        if not line:
            continue  # skip blank lines
        parts = [p.strip() for p in line.split(',')]
        print(f"Processing line: {line}")

        # >>>> New code fragment here <<<<
        if len(parts) != len(field_names):
            print("Warning: Mismatched field count.")
            continue

        record = dict(zip(field_names, parts))
        key = record.get("key")
        if not key:
            print("Warning: No key found in line.")
            continue
        # <<<< End of inserted fragment >>>>
        
        print(f"Record for {key}: {record}")
        jira_data[key] = record
        print(f"Added record for {key} to jira_data.")

    return field_index_map, jira_data


from openpyxl import load_workbook

def process_jira_table_blocks(filename):
    wb = load_workbook(filename)
    ws = wb.active

    printing = False  # Flag to track when we're in a Jira Table block

    for row in ws.iter_rows():
        #print(f"Processing row {row[0].row}: {[cell.value for cell in row]}")
        for cell in row:
            #print(f"Processing cell {cell.coordinate}: {cell.value}")
            cleaned_value = str(cell.value).strip().replace(" ", "_")
            #print(f"Cleaned cell value: {cleaned_value}")
            #if file_info["table"] in str(cell).strip().replace(" ", "_"):
            if file_info["table"] in cleaned_value:
                print(f"Found table header '{file_info['table']}' in cell {cell.coordinate}")
                printing = True
                break
            #if cell.value and "<jira>" in str(cell.value):
            #    if printing:
            #        print("Found start of new Jira Table. Exiting Jira Table block.")
            #        # Found another "Jira Table" — stop
            #        return

        if printing:
            first_cell = row[field_index_map["key"]].value
            print(first_cell)
            if (jira_data and first_cell in jira_data):
                print(f"Updating row {row[field_index_map["key"]].row} with data for {first_cell}")
                record = jira_data[first_cell]
                for field, index in field_index_map.items():
                    print(f"Checking field {field} at index {index}")
                    if field in record:
                        print(f"Updating field {field} at index {index} with value {record[field]}")
                        cell_value = record[field]
                        print(f"Cell value for {field}: {cell_value}")
                        if cell_value is not None:
                            #print(f"Setting cell value: {cell_value}")
                            #ws.cell(row=row[0].row, column=index + 1, value=cell_value)
                            target_cell = ws.cell(row=row[0].row, column=index + 1)
                            old_value = target_cell.value
                            old_value = str(old_value).replace("\n", ";") if old_value else None  # Replace newlines with semicolons for comparison
                            print(f"Old value for {target_cell.coordinate}: {old_value}")
                            print(f"Setting cell {target_cell.coordinate} = {cell_value}")  # <-- Coordinate logging
                            target_cell.value = cell_value.replace(";", "\n")  # Replace ; with newline
                                                    
                            # Enable text wrapping to show newlines
                            target_cell.alignment = Alignment(wrapText=True)

                            if field == "key" and is_valid_jira_id(cell_value):
                                target_cell.hyperlink = "https://fz96tw.atlassian.net/browse/" + cell_value  # The actual link
                                target_cell.style = "Hyperlink"  # Optional: makes it blue and underlined
                            elif field == "key" and is_JQL(cell_value):
                                target_cell.hyperlink = "https://fz96tw.atlassian.net/issues/?jql=" + cell_value.replace("JQL", "")  # The actual link
                                target_cell.style = "Hyperlink"
                            
                            # Save coordinate + value to list
                            change_list.append(f"{target_cell.coordinate}={cell_value.replace("\n",";")}||{old_value}")

            else:
                print(f"No data found for {first_cell} in jira_data.")
    
    # Save updates to the same file
    print(f"Saving updates to {filename}")
    wb.save(filename)                



if __name__ == "__main__":
    #main()
    if len(sys.argv) < 3:
        print("Usage: python update_excel.py <csv file> <xlsx file>")
        sys.exit(1)
    
    jiracsv = sys.argv[1]
    print(f"Received argument: {jiracsv}")
    xlfile = sys.argv[2]
    print(f"Received argument: {xlfile}")

    field_index_map, jira_data = load_jira_file(jiracsv)
    print(f"Loaded {len(jira_data)} records from {jiracsv}")
    
    for key, index in field_index_map.items():
        print(f"{key}: {index}")
    
    for key, record in jira_data.items():
        print(f"{key}: {record}")

    process_jira_table_blocks(xlfile)
    print("Finished processing Jira Table blocks.")

            
    if not change_list:
        print("No changes made.")
    else:
        changes_file = xlfile.replace(".xlsx", "_changes.txt")
        print(f"Writing changes to {changes_file}")
        with open(changes_file, "w") as f:
            for entry in change_list:
                if "||None" in entry:
                    entry = entry.replace("||None", "||")
                f.write(entry + "\n")
                print(entry)
    print(f"Changes written to {changes_file} with ({len(change_list)} entries).")


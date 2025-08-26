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

    # Create a mapping of field names to their respective indexes.
    field_index_map = dict(zip(field_names, index_values))

    # Now that we have the field names and indexes, we can parse the data rows.
    # Parse the remaining lines (ie. the data rows)
    for line in lines[6:]:
        line = line.strip()
        if not line:
            continue  # skip blank lines
        parts = [p.strip() for p in line.split(',')]
        print(f"Processing line: {line}")

        if len(parts) != len(field_names):
            print(f"Warning: Mismatched field count in {filename}. Make sure number of values provided matches number of fields.")
            continue

        # dictionary that maps field names to their corresponding values that we just read from the line
        # assumes the order of parts matches the order of field_names (in the jira.csv file)
        record = dict(zip(field_names, parts))
        key = record.get("key")
        if not key:
            print("Warning: No <key> field found in csv line. Check that the excel file table has a <key> column")
            continue
        
        print(f"Record for {key}: {record}")
        jira_data[key] = record # record contains all fields values for this jira ID
        print(f"Added record for {key} to jira_data.")

    return field_index_map, jira_data


from openpyxl import load_workbook

def process_jira_table_blocks_2(filename):
    wb = load_workbook(filename)
    ws = wb.active

    printing = False  # Flag to track when we're in a Jira Table block
    printing_import_mode = False # flag to track when we're in a jira table block in import mode

    for row in ws.iter_rows():
        #print(f"Processing row {row[0].row}: {[cell.value for cell in row]}")

        # skip just 1 more row because it contains the table header. I know it's a hack but it works for now
        #if printing and import_mode: 
        #    print("Skipping header row in import mode")
        #    continue

        for cell in row:
            #print(f"Processing cell {cell.coordinate}: {cell.value}")
            cleaned_value = str(cell.value).strip().replace(" ", "_")
            #print(f"Cleaned cell value: {cleaned_value}" + f" | file_info['table']: {file_info['table']}")
            #if file_info["table"] in str(cell).strip().replace(" ", "_"):
            if file_info["table"] in cleaned_value:
                print(f"Found table header '{file_info['table']}' in cell {cell.coordinate}")
                printing = True
                break
            
        print(f"Printing flag is {'ON' if printing else 'OFF'} for row {row[0].row}")
        print(f"Import mode is {'ON' if import_mode else 'OFF'}")

        if printing and not import_mode:
            print("About to process update row.")
            first_cell = row[field_index_map["key"]].value
            #print(first_cell)
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
        
        elif printing and not printing_import_mode:
                print("Hunting for starting cell for import mode")
                first_cell = row[field_index_map["key"]].value
                if "<key>" in str(first_cell).lower():
                    print("Found <key> header row, let's skip to next row")
                    printing_import_mode = True
                    continue
                else:
                    print("need to keep looking...")
                    
            
        elif printing and import_mode and printing_import_mode:
            print(f"About to process import row - checking column {field_index_map['key']}")
            first_cell = row[field_index_map["key"]].value
            print(f"First cell in import row: {first_cell}")
            #if (jira_data and first_cell is None):     # make sure it's a blank cell (will skip headers as good side effect)
            if jira_data and (first_cell is None or first_cell == ""):
                print("First cell is blank")
                print(f"Import mode: Adding new row for {first_cell}")
                index = field_index_map["key"]  # get the index of the "key" field to find the blank cell
                print("target index for 'key': ", index)
                target_cell = ws.cell(row=row[0].row, column=index + 1)
                # for loop through the key in jira_data
                #for key, record in jira_data.items():
                    #change_list.append(f"insert {target_cell.coordinate}={key}||{first_cell}")
                key_index = field_index_map["key"]

                if jira_data:
                    k, v = jira_data.popitem()
                    print(f"jira_data.popitem = {k}, {v}")
                    print(f"remaining jira_data items: {len(jira_data)}")
            
            
                print(f"{target_cell.coordinate}={k}||{first_cell}")
                change_list.append(f"{target_cell.coordinate}={k}||{first_cell}")

                if not jira_data:
                    print("Dictionary is empty, nothing to pop so exiting loop")
                    break
            

                # we just added all the row changes, so break out of the for loop. we're done with this table
                # not updating the downloaded excel file since we never use it. we are just after the change_list for import mode
                #print("Finished processing import row.")
                #break
            elif is_valid_jira_id(first_cell):
                print(f"This row already contains valid jira id {first_cell}. Will just update instead of overwriting.")

                # pop the first_cell from jira_ids if it exists
                if first_cell in jira_data:
                    print(f"Popping {first_cell} from jira_data for update.")
                    record = jira_data.pop(first_cell)
                    print(f"Remaining jira_data items: {len(jira_data)}")
                    break
                    # TODO: if there are Jira IDs in the table already it means we need to update them instead of insert
                    # Also if any jira in the table that aren't in the jql result then we need to delete those.
                    # These is a more complex scenario that we can handle later

                    # Call update process here. Mark the cell for strikeout if isn't in jira_ids for this JQL result

            else:
 
                print(f"Import mode: first_cell = {first_cell}. No blank 'key' cell found, skipping change_list for this row.")    
    
    # Save updates to the same file
    #print(f"Saving updates to {filename}")
    #wb.save(filename)                


def process_jira_table_blocks(filename):
    wb = load_workbook(filename)
    ws = wb.active

    printing = False  # Flag to track when we're in a Jira Table block
    printing_import_mode = False # flag to track when we're in a jira table block in import mode

    for row in ws.iter_rows():
        #print(f"Processing row {row[0].row}: {[cell.value for cell in row]}")

        # skip just 1 more row because it contains the table header. I know it's a hack but it works for now
        #if printing and import_mode: 
        #    print("Skipping header row in import mode")
        #    continue

        for cell in row:
            #print(f"Processing cell {cell.coordinate}: {cell.value}")
            cleaned_value = str(cell.value).strip().replace(" ", "_")
            #print(f"Cleaned cell value: {cleaned_value}" + f" | file_info['table']: {file_info['table']}")
            #if file_info["table"] in str(cell).strip().replace(" ", "_"):
            if file_info["table"] in cleaned_value:
                print(f"Found table header '{file_info['table']}' in cell {cell.coordinate}")
                printing = True
                break
            
        print(f"Printing flag is {'ON' if printing else 'OFF'} for row {row[0].row}")
        print(f"Import mode is {'ON' if import_mode else 'OFF'}")

        if printing and not import_mode:
            print("About to process update row.")
            first_cell = row[field_index_map["key"]].value
            #print(first_cell)
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
        
        elif printing and not printing_import_mode:
                print("Hunting for starting cell for import mode")
                first_cell = row[field_index_map["key"]].value
                if "<key>" in str(first_cell).lower():
                    print("Found <key> header row, let's skip to next row")
                    printing_import_mode = True
                    continue
                else:
                    print("need to keep looking...")
                    
            
        elif printing and import_mode and printing_import_mode:
            print(f"About to process import row - checking column {field_index_map['key']}")
            first_cell = row[field_index_map["key"]].value
            print(f"First cell in import row: {first_cell}")
            #if (jira_data and first_cell is None):     # make sure it's a blank cell (will skip headers as good side effect)
            if jira_data and (first_cell is None or first_cell == ""):
                print("First cell is blank")
                print(f"Import mode: Adding new row for {first_cell}")
   
                print(f"Updating row {row[field_index_map["key"]].row} with data for {first_cell}")
                #record = jira_data[first_cell]
                k, record = jira_data.popitem()
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
            elif not jira_data:
                print("No more items in jira_data to import, exiting loop.")
                break
            elif is_valid_jira_id(first_cell):
                print(f"This row already contains valid jira id {first_cell}. Will just update instead of overwriting.")

                # pop the first_cell from jira_ids if it exists
                if first_cell in jira_data:
                    print(f"Popping {first_cell} from jira_data for update.")
                    record = jira_data.pop(first_cell)
                    print(f"Remaining jira_data items: {len(jira_data)}")
                    
                    # TODO: if there are Jira IDs in the table already it means we need to update them instead of insert
                    # Also if any jira in the table that aren't in the jql result then we need to delete those.
                    # These is a more complex scenario that we can handle later

                    # Call update process here. 
                else:
                    # Mark the cell for strikeout if isn't in jira_ids for this JQL result
                    print(f"Strikeout {first_cell} not in jira_data, marking for strikeout.")
                    index = field_index_map["key"]  # get the index of the "key" field to find the blank cell
                    print("target index for 'key': ", index)

                    target_cell = ws.cell(row=row[0].row, column=index + 1)
                    old_value = target_cell.value
                    old_value = str(old_value).replace("\n", ";") if old_value else None  # Replace newlines with semicolons for comparison
                    print(f"Old value for {target_cell.coordinate}: {old_value}")
                    print(f"Setting cell {target_cell.coordinate} = {first_cell} (strikeout)")  # <-- Coordinate logging
                    target_cell.value = "!! " + first_cell  # add marker to indicate it needs strick out 
                    target_cell.font = target_cell.font.copy(strike=True)  # Apply strikeout
                    target_cell.alignment = Alignment(wrapText=True)                 
                    change_list.append(f"{target_cell.coordinate}={target_cell.value.replace("\n",";")}||{old_value}")

    else:
                # TODO: if there are Jira IDs in the table already it means we need to update them instead of insert
                # Also if any jira in the table that aren't in the jql result then we need to delete those.
                # These is a more complex scenario that we can handle later
                print(f"Import mode: first_cell = {first_cell}. No blank 'key' cell found, skipping change_list for this row.")    
    
    # Save updates to the same file
    #print(f"Saving updates to {filename}")
    #wb.save(filename)                


if __name__ == "__main__":
    #main()
    if len(sys.argv) < 3:
        print("Usage: python update_excel.py <csv file> <xlsx file>")
        sys.exit(1)
    
    jiracsv = sys.argv[1]
    print(f"Received argument: {jiracsv}")
    xlfile = sys.argv[2]
    print(f"Received argument: {xlfile}")

    if "import" in jiracsv.lower():
        print("Import mode detected based on filename containing 'import'.")
        # You can set a flag or handle import-specific logic here if needed
        import_mode = True
    else:
        import_mode = False

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
        #changes_file = xlfile.replace(".xlsx", ".changes.txt")

        if import_mode:
            changes_file = jiracsv.replace(".import.jira.csv", ".import.changes.txt")
        else:
            changes_file = jiracsv.replace(".jira.csv", ".changes.txt")
        
        print(f"Writing changes to {changes_file}")
        with open(changes_file, "w") as f:
            for entry in change_list:
                if "||None" in entry:
                    entry = entry.replace("||None", "||")
                f.write(entry + "\n")
                print(entry)
        print(f"Changes written to {changes_file} with ({len(change_list)} entries).")


import pandas as pd
import sys
import os
import yaml

def read_excel_rows(filename):
    df = pd.read_excel(filename)
    return df.values.tolist()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scope.py <filename>")
        sys.exit(1)
    filename = sys.argv[1]
    rows = read_excel_rows(filename)
    
    jira_ids = []
    jira_fields = []
    fields_found = False

    for row in rows:
        #print(row)
        for idx, cell in enumerate(row):
            if "<JIRA>" in str(cell):
                value = str(cell).replace("<JIRA>", "").strip()
                jira_fields.append({"value":value,"index":idx})
            # keep list of cells that a

        if jira_fields and not fields_found:
            fields_found = True
            base = os.path.splitext(os.path.basename(filename))[0]
            output_file = f"{base}.scope.yaml"
            with open(output_file, 'w') as f:
                yaml.dump({ "fields": jira_fields }, f, default_flow_style=False)
            continue

        if fields_found:
            # lookup the index of the field "ID"
            index_of_id = next((field['index'] for field in jira_fields if field['value'] == "key"), None)
            if index_of_id is not None:
                jira_ids.append(row[index_of_id])
        
    if jira_ids:
        print(f"JIRA IDs found: {jira_ids}")
        with open(output_file, 'a') as f:
            yaml.dump({"jira_ids": jira_ids}, f, default_flow_style=False)

    print("JIRA rows have been written to output file:", output_file)
    print("Total rows processed:", len(rows))
    # close the file
    f.close()

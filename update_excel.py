import sys

def load_jira_file(filename):
    field_index_map = {}
    jira_data = {}

    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    if len(lines) < 2:
        raise ValueError("File must contain at least two header lines.")

    # Parse field indexes and values from the first two lines
    index_line = lines[0].strip().replace("Field indexes:", "").strip()
    value_line = lines[1].strip().replace("Field values:", "").strip()

    index_values = [int(i.strip()) for i in index_line.split(',')]
    field_names = [v.strip() for v in value_line.split(',')]

    if len(index_values) != len(field_names):
        raise ValueError("Mismatch between number of field indexes and field names.")

    field_index_map = dict(zip(field_names, index_values))

    # Parse the remaining lines (data rows)
    for line in lines[2:]:
        line = line.strip()
        if not line:
            continue  # skip blank lines
        parts = [p.strip() for p in line.split(',')]
        key = parts[field_index_map["key"]]
        record = {field: parts[i] if i < len(parts) else None for field, i in field_index_map.items()}
        jira_data[key] = record

    return field_index_map, jira_data



if __name__ == "__main__":
    #main()
    if len(sys.argv) < 2:
        print("Usage: python update_excel.py <csv file>")
        sys.exit(1)
    
    jiracsv = sys.argv[1]
    print(f"Received argument: {jiracsv}")
    field_index_map, jira_data = load_jira_file(jiracsv)
    print(f"Loaded {len(jira_data)} records from {jiracsv}")
    
    for key, index in field_index_map.items():
        print(f"{key}: {index}")
    
    for key, record in jira_data.items():
        print(f"{key}: {record}")


import requests

SITE_ID = "cloudcurio.sharepoint.com,eb235850-d56c-4b42-9d05-71e84a2c56c3,4aedacc5-8071-414c-b10a-b40c4fc57048"
ACCESS_TOKEN = ""
            

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

# List root folder contents
url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root/children"
r = requests.get(url, headers=headers)

if r.status_code == 200:
    items = r.json().get("value", [])
    for item in items:  # assuming 'items' is your list of dictionaries
        name = item.get("name", "<Unnamed>")
        is_folder = item.get("folder", False)
        item_type = "(Folder)" if is_folder else "(File)"
        print(name, item_type)

else:
    print("Error:", r.status_code, r.text)

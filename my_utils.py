import re


def clean_sharepoint_url(url: str) -> str:
    """
    Cleans a SharePoint file URL by removing 'Shared Documents' or 'Shared Folders'
    so it can be used directly with pandas.read_excel/read_csv.
    """
    # Replace encoded space with normal space for safety
    url = url.replace("%20", " ")

    # Remove "Shared Documents" or "Shared Folders" segments
    url = re.sub(r"/Shared (Documents|Folders)", "", url, flags=re.IGNORECASE)

    # Fix spaces back to %20 for proper HTTP request
    return url.replace(" ", "%20")

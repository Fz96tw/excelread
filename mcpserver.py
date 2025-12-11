from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from datetime import datetime
from pathlib import Path
import csv

app = Flask(__name__)
CORS(app)  # Enable CORS for remote access

# Cache for user mappings
USER_MAPPINGS_CACHE = None
MAPPINGS_FILE = Path("./config/mcp.user.mapping.json")

def load_user_mappings():
    """Load user mappings from JSON config file"""
    global USER_MAPPINGS_CACHE
    
    print(f"[load_user_mappings] Loading from: {MAPPINGS_FILE}")
    
    if not MAPPINGS_FILE.exists():
        print(f"[load_user_mappings] ❌ ERROR: Config file not found: {MAPPINGS_FILE}")
        print(f"[load_user_mappings] Creating example config file...")
        
        # Create config directory if it doesn't exist
        MAPPINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Create example config
        example_config = {
            "mappings": [
                {
                    "api_key": "key-alice-abc123",
                    "username": "alice"
                },
                {
                    "api_key": "key-bob-def456",
                    "username": "bob"
                },
                {
                    "api_key": "dev-key-123",
                    "username": "demo"
                }
            ]
        }
        
        with open(MAPPINGS_FILE, 'w') as f:
            json.dump(example_config, f, indent=2)
        
        print(f"[load_user_mappings] ✓ Created example config at: {MAPPINGS_FILE}")
        USER_MAPPINGS_CACHE = example_config
        return example_config
    
    try:
        with open(MAPPINGS_FILE, 'r') as f:
            config = json.load(f)
            USER_MAPPINGS_CACHE = config
            print(f"[load_user_mappings] ✓ Loaded {len(config.get('mappings', []))} user mappings")
            return config
    except Exception as e:
        print(f"[load_user_mappings] ❌ ERROR loading config: {e}")
        return {"mappings": []}

def get_username_from_api_key(api_key: str) -> str:
    """Look up username from API key in config file"""
    global USER_MAPPINGS_CACHE
    
    # Load mappings if not cached
    #if USER_MAPPINGS_CACHE is None:
    load_user_mappings()  # always relod cache from file to reflect any changes
    
    print(f"[get_username_from_api_key] Looking up API key: {api_key}")
    
    # Search for API key in mappings
    mappings = USER_MAPPINGS_CACHE.get('mappings', [])
    for mapping in mappings:
        if mapping.get('api_key') == api_key:
            username = mapping.get('username')
            print(f"[get_username_from_api_key] ✓ Found username: {username}")
            return username
    
    print(f"[get_username_from_api_key] ❌ API key not found in mappings, using key as username")
    # If not found, use API key as username (fallback)
    return api_key

def get_user_folder(api_key: str) -> Path:
    """Get the vectorstore folder path for a given API key"""
    username = get_username_from_api_key(api_key)
    
    base_path = Path("./logs")
    user_folder = base_path / username / "vectorstore"
    
    print(f"[get_user_folder] API Key: {api_key}")
    print(f"[get_user_folder] Username: {username}")
    print(f"[get_user_folder] Folder path: {user_folder}")
    
    return user_folder

def read_csv_files(folder_path: Path) -> list:
    """Read all CSV files from a folder and return as documents"""
    print(f"[read_csv_files] Starting to read from: {folder_path}")
    documents = []
    
    if not folder_path.exists():
        print(f"[read_csv_files] ❌ ERROR: Folder does not exist: {folder_path}")
        return documents
    
    # Find all CSV files in the folder
    csv_files = list(folder_path.glob("*.csv"))
    print(f"[read_csv_files] Found {len(csv_files)} CSV files")
    
    for csv_file in csv_files:
        print(f"[read_csv_files] Processing: {csv_file.name}")
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
                print(f"[read_csv_files]   ✓ Read {len(rows)} rows from {csv_file.name}")
                
                # Convert CSV to document format
                # Combine all rows into content
                content_parts = []
                for row in rows:
                    row_text = ", ".join([f"{k}: {v}" for k, v in row.items()])
                    content_parts.append(row_text)
                
                doc = {
                    "id": csv_file.stem,  # filename without extension
                    "title": csv_file.name,
                    "content": "\n".join(content_parts),
                    "type": "csv",
                    "metadata": {
                        "filename": csv_file.name,
                        "filepath": str(csv_file),
                        "row_count": len(rows),
                        "columns": list(rows[0].keys()) if rows else [],
                        "modified": datetime.fromtimestamp(csv_file.stat().st_mtime).isoformat()
                    }
                }
                documents.append(doc)
                print(f"[read_csv_files]   ✓ Successfully added document: {csv_file.name}")
                
        except Exception as e:
            # Log error but continue with other files
            print(f"[read_csv_files]   ❌ ERROR reading {csv_file.name}: {e}")
            continue
    
    print(f"[read_csv_files] ✓ Completed. Total CSV documents: {len(documents)}")
    return documents

def read_aibrief_llm_txt_files(folder_path: Path) -> list:
    """Read all *.aibrief.llm.txt files from a folder and return as documents"""
    print(f"[read_aibrief_llm_txt_files] Starting to read from: {folder_path}")
    documents = []
    
    if not folder_path.exists():
        print(f"[read_aibrief_llm_txt_files] ❌ ERROR: Folder does not exist: {folder_path}")
        return documents
    
    # Find all .aibrief.llm.txt files in the folder
    txt_files = list(folder_path.glob("*.aibrief.llm.txt"))
    print(f"[read_aibrief_llm_txt_files] Found {len(txt_files)} .aibrief.llm.txt files")
    
    for txt_file in txt_files:
        print(f"[read_aibrief_llm_txt_files] Processing: {txt_file.name}")
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
                print(f"[read_aibrief_llm_txt_files]   ✓ Read {len(content)} characters from {txt_file.name}")
                
                # Extract base filename (remove .aibrief.llm.txt suffix)
                base_name = txt_file.name.replace('.aibrief.llm.txt', '')
                
                doc = {
                    "id": base_name,
                    "title": txt_file.name,
                    "content": content,
                    "type": "aibrief_llm",
                    "metadata": {
                        "filename": txt_file.name,
                        "filepath": str(txt_file),
                        "size_bytes": len(content),
                        "modified": datetime.fromtimestamp(txt_file.stat().st_mtime).isoformat()
                    }
                }
                documents.append(doc)
                print(f"[read_aibrief_llm_txt_files]   ✓ Successfully added document: {txt_file.name}")
                
        except Exception as e:
            # Log error but continue with other files
            print(f"[read_aibrief_llm_txt_files]   ❌ ERROR reading {txt_file.name}: {e}")
            continue
    
    print(f"[read_aibrief_llm_txt_files] ✓ Completed. Total .aibrief.llm.txt documents: {len(documents)}")
    return documents

# MCP Protocol Implementation
@app.route('/mcp/v1/retrieve', methods=['POST'])
def retrieve():
    """
    Main MCP retrieval endpoint - returns all CSV and .aibrief.llm.txt files from user's vectorstore folder
    Expects JSON: {"query": "search query", "max_results": 5}
    Query parameter is optional and ignored - all documents are always returned
    max_results: maximum number of files to return (default: None = all files)
    """
    try:
        # Get API key from request context (set by check_auth)
        api_key = request.api_key
        print(f"[/mcp/v1/retrieve] Request from API key: {api_key}")
        
        data = request.get_json() or {}
        query = data.get('query', '')  # Accept query but don't use it for filtering
        max_results = data.get('max_results')  # None means return all files
        
        print(f"[/mcp/v1/retrieve] Query: '{query}'")
        print(f"[/mcp/v1/retrieve] Max results: {max_results if max_results else 'unlimited'}")
        
        # Get user's vectorstore folder
        user_folder = get_user_folder(api_key)
        
        # Read all file types from the folder
        documents = []
        csv_docs = read_csv_files(user_folder)
        txt_docs = read_aibrief_llm_txt_files(user_folder)
        
        documents.extend(csv_docs)
        documents.extend(txt_docs)
        
        print(f"[/mcp/v1/retrieve] Total documents: {len(documents)} (CSV: {len(csv_docs)}, TXT: {len(txt_docs)})")
        
        # Return all documents (no filtering), optionally limit by max_results
        if max_results is not None:
            documents = documents[:max_results]
            print(f"[/mcp/v1/retrieve] Limited results to: {max_results}")
        
        results = [
            {
                "id": doc["id"],
                "title": doc["title"],
                "content": doc["content"],
                "type": doc["type"],
                "metadata": doc["metadata"]
            }
            for doc in documents
        ]
        
        response = {
            "query": query,
            "folder": str(user_folder),
            "results": results,
            "total_count": len(results),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        print(f"[/mcp/v1/retrieve] ✓ Returning {len(results)} documents")
        return jsonify(response)
    
    except Exception as e:
        print(f"[/mcp/v1/retrieve] ❌ ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/mcp/initialize', methods=['POST'])
def initialize():
    """
    MCP Initialize endpoint - called when LLM first connects
    This is the handshake that establishes the MCP connection
    """
    try:
        data = request.get_json()
        print(f"[/mcp/initialize] Received initialize request")
        print(f"[/mcp/initialize] Protocol version: {data.get('protocolVersion', 'not specified')}")
        print(f"[/mcp/initialize] Client info: {data.get('clientInfo', {})}")
        
        response = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "resources": {},
                "tools": {
                    "retrieve": {
                        "description": "Retrieve relevant documents based on a query",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query"
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Maximum number of results",
                                    "default": 5
                                }
                            },
                            "required": ["query"]
                        }
                    }
                },
                "prompts": {}
            },
            "serverInfo": {
                "name": "MCP Retriever Service",
                "version": "1.0.0"
            }
        }
        
        print(f"[/mcp/initialize] ✓ Initialization successful")
        return jsonify(response)
        
    except Exception as e:
        print(f"[/mcp/initialize] ❌ ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/mcp/v1/documents', methods=['GET'])
def list_documents():
    """
    List all CSV and .aibrief.llm.txt files in the user's vectorstore folder
    """
    try:
        api_key = request.api_key
        print(f"[/mcp/v1/documents GET] Request from API key: {api_key}")
        
        user_folder = get_user_folder(api_key)
        
        # Read both file types
        csv_docs = read_csv_files(user_folder)
        txt_docs = read_aibrief_llm_txt_files(user_folder)
        
        documents = []
        documents.extend(csv_docs)
        documents.extend(txt_docs)
        
        response = {
            "folder": str(user_folder),
            "documents": documents,
            "total": len(documents),
            "by_type": {
                "csv": len(csv_docs),
                "aibrief_llm": len(txt_docs)
            }
        }
        
        print(f"[/mcp/v1/documents GET] ✓ Returning {len(documents)} documents (CSV: {len(csv_docs)}, TXT: {len(txt_docs)})")
        return jsonify(response)
        
    except Exception as e:
        print(f"[/mcp/v1/documents GET] ❌ ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/mcp/v1/documents', methods=['POST'])
def add_document():
    """
    This endpoint is not supported with file-based storage
    Users should add CSV files directly to their vectorstore folder
    """
    api_key = request.api_key
    user_folder = get_user_folder(api_key)
    
    print(f"[/mcp/v1/documents POST] Request from API key: {api_key}")
    print(f"[/mcp/v1/documents POST] ⚠️  POST not supported - direct file upload required")
    
    return jsonify({
        "message": "To add documents, place CSV files in your vectorstore folder",
        "folder": str(user_folder),
        "instructions": f"Add CSV files to: {user_folder}"
    }), 200

@app.route('/health', methods=['GET'])
def health():
    """
    Health check endpoint
    """
    print(f"[/health] Health check request")
    response = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }
    print(f"[/health] ✓ Status: healthy")
    return jsonify(response)

# Authentication middleware
@app.before_request
def check_auth():
    """
    API key authentication - API key is used as folder identifier
    Any non-empty API key is accepted
    """
    # Skip auth for health and initialize endpoints
    if request.path in ['/health', '/mcp/initialize']:
        return None
    
    provided_key = request.headers.get('X-API-Key')
    
    if not provided_key or provided_key.strip() == '':
        return jsonify({"error": "Unauthorized - API Key required"}), 401
    
    # Store API key in request context for use in route handlers
    request.api_key = provided_key

if __name__ == '__main__':
    # Port is configurable via PORT environment variable, defaults to 5000
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    print(f"Starting MCP Retriever Service on port {port}")
    print(f"Debug mode: {debug}")
    print(f"API Key authentication: {'enabled' if os.environ.get('API_KEY') else 'using default dev key'}")
    print("\nAvailable routes:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.methods} {rule.rule}")
    print()
    
    app.run(host='0.0.0.0', port=port, debug=debug)
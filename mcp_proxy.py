#!/usr/bin/env python3
"""
MCP HTTP-to-stdio Proxy
Bridges Claude Desktop (stdio) to remote HTTP MCP servers
"""
import json
import sys
import logging
import requests
from typing import Any, Optional

# Configuration
REMOTE_MCP_URL = "https://untheoretic-letty-subliminally.ngrok-free.dev"  # Change to your remote server
#API_KEY = "dev-key-123"  # Your MCP server API key
API_KEY = ""  # Your MCP server API key, null since it's provdied as environment variable in the claude desktop config, and we don't want to hardcode it here

# Setup logging
logging.basicConfig(
    filename='/tmp/mcp_proxy.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class MCPProxy:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        if api_key:
            self.session.headers['X-API-Key'] = api_key
        self.session.headers['Content-Type'] = 'application/json'
    
    def call_remote(self, endpoint: str, data: dict) -> dict:
        """Make HTTP request to remote MCP server"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            logging.info(f"Calling {url} with data: {data}")
            response = self.session.post(url, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            logging.info(f"Response: {result}")
            return result
        except requests.exceptions.RequestException as e:
            logging.error(f"HTTP error: {e}")
            raise Exception(f"Failed to connect to remote MCP server: {e}")
    
    def handle_initialize(self, params: dict) -> dict:
        """Handle initialize by calling remote /mcp/initialize"""
        try:
            result = self.call_remote('/mcp/initialize', {
                'protocolVersion': params.get('protocolVersion', '2025-11-25'),
                'capabilities': params.get('capabilities', {}),
                'clientInfo': params.get('clientInfo', {})
            })
            return result
        except Exception as e:
            logging.error(f"Initialize error: {e}")
            # Fallback to local capabilities
            return {
                "protocolVersion": "2025-11-25",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "MCP HTTP Proxy",
                    "version": "1.0.0"
                }
            }
    
    def handle_tools_list(self, params: dict) -> dict:
        """Return available tools"""
        return {
            "tools": [
                {
                    "name": "retrieve",
                    "description": "Search and retrieve relevant documents from remote knowledge base",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 5
                            }
                        },
                        "required": ["query"]
                    }
                }
            ]
        }
    
    def handle_prompts_list(self, params: dict) -> dict:
        """Return available prompts (empty for now)"""
        return {
            "prompts": []
        }
    
    def handle_resources_list(self, params: dict) -> dict:
        """Return available resources (empty for now)"""
        return {
            "resources": []
        }
    
    def handle_tools_call(self, params: dict) -> dict:
        """Handle tool call by proxying to remote server"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        logging.info(f"Tool call: {tool_name} with args: {arguments}")
        
        if tool_name == "retrieve":
            try:
                # Call remote retrieve endpoint
                result = self.call_remote('/mcp/v1/retrieve', arguments)
                
                # Format response for Claude
                results = result.get('results', [])
                
                if results:
                    content = f"Found {len(results)} document(s) from remote server:\n\n"
                    for i, doc in enumerate(results, 1):
                        content += f"{i}. **{doc['title']}**\n"
                        content += f"   {doc['content']}\n"
                        if 'metadata' in doc:
                            content += f"   Metadata: {doc['metadata']}\n"
                        content += "\n"
                else:
                    query = arguments.get('query', '')
                    content = f"No documents found matching '{query}' on remote server"
                
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": content
                        }
                    ]
                }
            except Exception as e:
                logging.error(f"Retrieve error: {e}")
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error retrieving from remote server: {str(e)}"
                        }
                    ],
                    "isError": True
                }
        else:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Unknown tool: {tool_name}"
                    }
                ],
                "isError": True
            }
    
    def handle_notification(self, params: dict) -> None:
        """Handle notifications (no response needed)"""
        logging.info("Received notification (no response needed)")
        return None
    
    def handle_request(self, request: dict) -> dict:
        """Route requests to appropriate handlers"""
        method = request.get("method")
        params = request.get("params", {})
        
        logging.info(f"Received request: {method}")
        
        # Handle notifications (they don't need responses)
        if method and method.startswith("notifications/"):
            self.handle_notification(params)
            return None
        
        handlers = {
            "initialize": self.handle_initialize,
            "tools/list": self.handle_tools_list,
            "tools/call": self.handle_tools_call,
            "prompts/list": self.handle_prompts_list,
            "resources/list": self.handle_resources_list
        }

        handler = handlers.get(method)
        
        if not handler:
            return {
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
        
        try:
            result = handler(params)
            
            # 🔥 THIS is the key part
            if isinstance(result, dict) and "error" in result:
                return {"error": result["error"]}
            
            return {"result": result}
        
        except Exception as e:
            return {
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }   

    def run(self):
        """Main loop: read from stdin, write to stdout"""
        logging.info(f"MCP Proxy started, connecting to {self.base_url}")
        
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    request = json.loads(line)
                    request_id = request.get("id")
                    
                    logging.debug(f"Request {request_id}: {request}")
                       
                    response_payload = self.handle_request(request)

                    if response_payload is None:
                        continue  # notification

                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        **response_payload   # merges either {"result": ...} OR {"error": ...}
                    }

                    print(json.dumps(response), flush=True)

                except json.JSONDecodeError as e:
                    logging.error(f"JSON decode error: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"}
                    }
                    print(json.dumps(error_response), flush=True)
                
                except Exception as e:
                    logging.error(f"Error processing request: {e}", exc_info=True)
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id") if 'request' in locals() else None,
                        "error": {"code": -32603, "message": str(e)}
                    }
                    print(json.dumps(error_response), flush=True)
        
        except KeyboardInterrupt:
            logging.info("Proxy stopped by user")
        except Exception as e:
            logging.error(f"Fatal error: {e}", exc_info=True)

def main():
    # You can override these via environment variables
    import os
    remote_url = os.environ.get('MCP_REMOTE_URL', REMOTE_MCP_URL)
    api_key = os.environ.get('MCP_API_KEY', API_KEY)
    
    proxy = MCPProxy(remote_url, api_key)
    proxy.run()

if __name__ == "__main__":
    main()
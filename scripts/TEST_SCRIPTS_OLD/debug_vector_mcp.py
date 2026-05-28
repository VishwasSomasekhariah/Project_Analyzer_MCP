#!/usr/bin/env python3

import asyncio
import json
from mcp_use import MCPClient

async def debug_vector_mcp():
    """Debug the MCP vector query response structure."""
    
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    collection_name = "helloworldapp-benchmarking"
    query = "How does the Manager class work?"
    
    try:
        client = MCPClient.from_config_file(config_file)
        session = await client.create_session("mcp-analysis-server")
        
        result = await session.call_tool(
            "query_vector_only",
            {
                "query": query,
                "collection_name": collection_name,
                "max_results": 3,
                "output_format": "json",
            }
        )
        
        print("=== MCP Result Structure ===")
        print(f"Type: {type(result)}")
        print(f"Attributes: {dir(result)}")
        
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        print(f"\n=== Content Structure ===")
        print(f"Type: {type(result_content)}")
        print(f"Attributes: {dir(result_content)}")
        
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        print(f"\n=== Content Text ===")
        print(f"Length: {len(content_text)}")
        print(f"First 500 chars:")
        print(repr(content_text[:500]))
        
        # Try to parse as JSON
        try:
            parsed = json.loads(content_text)
            print(f"\n=== Parsed JSON ===")
            print(f"Type: {type(parsed)}")
            print(f"Keys: {list(parsed.keys()) if isinstance(parsed, dict) else 'Not a dict'}")
            
            if isinstance(parsed, dict):
                print(f"Raw results: {type(parsed.get('raw_results', 'missing'))}")
                print(f"Raw results count: {len(parsed.get('raw_results', []))}")
                
                # Check embedded CLI JSON in ai_response
                ai_response = parsed.get('ai_response', '')
                print(f"\n=== Embedded CLI JSON ===")
                print(f"AI Response length: {len(ai_response)}")
                try:
                    cli_json = json.loads(ai_response)
                    print(f"CLI JSON keys: {list(cli_json.keys()) if isinstance(cli_json, dict) else 'Not a dict'}")
                    if isinstance(cli_json, dict) and "results" in cli_json:
                        print(f"CLI Results count: {len(cli_json['results'])}")
                        if cli_json['results']:
                            print(f"First CLI result keys: {list(cli_json['results'][0].keys())}")
                except json.JSONDecodeError as e:
                    print(f"AI response is not valid JSON: {e}")
                    print(f"First 1000 chars of ai_response:")
                    print(repr(ai_response[:1000]))
                
        except json.JSONDecodeError as e:
            print(f"\n=== JSON Parse Error ===")
            print(f"Error: {e}")
            print("Content is not valid JSON")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_vector_mcp())
#!/usr/bin/env python3

"""
Test MCP tool specifically for raw results fields
"""

import asyncio
import json
from mcp_use import MCPClient

async def test_raw_results_mcp():
    """Test raw results via MCP"""
    
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("mcp-analysis-server")
    
    result = await session.call_tool(
        "query_cpg_rag",
        {
            "user_query": "What classes are defined?",
            "project_name": "HelloWorldApp",
            "max_agent_iterations": 3
        }
    )
    
    # Extract result content
    result_content = result.content[0] if isinstance(result.content, list) else result.content
    content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
    
    try:
        result_data = json.loads(content_text)
        
        print("🔍 MCP Result Keys:")
        for key in sorted(result_data.keys()):
            print(f"  - {key}")
        
        print(f"\n✅ Has raw_query_results: {'raw_query_results' in result_data}")
        print(f"✅ Has all_executed_queries: {'all_executed_queries' in result_data}")
        print(f"✅ Has raw_results: {'raw_results' in result_data}")
        
        if 'raw_query_results' in result_data:
            raw_results = result_data['raw_query_results']
            print(f"📊 raw_query_results count: {len(raw_results)}")
            if raw_results:
                print(f"📋 First raw result: {raw_results[0]}")
        
        if 'all_executed_queries' in result_data:
            all_queries = result_data['all_executed_queries'] 
            print(f"📊 all_executed_queries count: {len(all_queries)}")
            if all_queries:
                print(f"📋 First query keys: {list(all_queries[0].keys())}")
                if 'cli_output' in all_queries[0]:
                    cli_output = all_queries[0]['cli_output']
                    print(f"📋 CLI output length: {len(cli_output) if cli_output else 0}")
                    if cli_output:
                        print(f"📋 CLI output preview: {cli_output[:200]}...")
        
        # Save result
        with open('/opt/genpod/test_raw_results_mcp.json', 'w') as f:
            json.dump(result_data, f, indent=2)
        
        print(f"\n💾 Result saved to: test_raw_results_mcp.json")
        
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse JSON: {e}")
        print(f"Raw content: {content_text[:500]}...")

if __name__ == "__main__":
    asyncio.run(test_raw_results_mcp())
#!/usr/bin/env python3
"""
Test the exact architectural query from comparative analysis in standalone CPG tool
"""

import asyncio
import json
from mcp_use import MCPClient

async def test_architectural_query():
    """Test the exact query from comparative analysis"""
    
    # Same query as comparative analysis T001 scenario  
    test_query = "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?"
    
    print(f"🔍 Testing CPG tool with architectural query:")
    print(f"Query: {test_query}")
    print()
    
    try:
        client = MCPClient.from_config_file("/opt/genpod/file_watcher_mcp_config.json")
        session = await client.create_session("mcp-analysis-server")
        
        result = await session.call_tool(
            "query_cpg_only",
            {
                "user_query": test_query,
                "config_path": "/opt/genpod/neo4j_config.json",
                "max_results": 50,
                "enable_synthesis": True,
                "enable_advanced_rag": True
            }
        )
        
        # Parse result
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        
        try:
            result_data = json.loads(content_text)
            
            print(f"✅ Status: {result_data.get('status', 'unknown')}")
            print(f"✅ Workflow: {result_data.get('workflow', 'unknown')}")
            print(f"✅ Analysis type: {result_data.get('analysis_type', 'unknown')}")
            
            raw_results = result_data.get("raw_results", [])
            print(f"✅ Raw results count: {len(raw_results)}")
            
            if raw_results:
                print(f"✅ First result keys: {list(raw_results[0].keys())}")
                print(f"✅ Sample result: {json.dumps(raw_results[0], indent=2)[:500]}...")
            else:
                print("❌ No raw results returned")
                
            entities = result_data.get("entities_extracted", {})
            print(f"✅ Entities extracted: {entities}")
            
            synthesis = result_data.get("synthesis", "")
            print(f"✅ Synthesis length: {len(synthesis)}")
            
            # Save full result for analysis
            with open("/opt/genpod/architectural_query_result.json", "w") as f:
                json.dump(result_data, f, indent=2)
                
            print(f"\n📁 Full result saved to: architectural_query_result.json")
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing failed: {e}")
            print(f"Raw response: {content_text[:1000]}...")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_architectural_query())
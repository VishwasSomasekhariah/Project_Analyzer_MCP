#!/usr/bin/env python3
"""
Debug script to test MCP tool responses and identify structure issues
"""
import asyncio
import json
from mcp_use import MCPClient

async def test_mcp_tools():
    """Test all three MCP tools to see their actual response structure"""
    
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    test_query = "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?"
    collection_name = "helloworldapp-benchmarking"
    project_path = "/opt/HelloWorldApp"
    
    print("🧪 Testing MCP Tools Response Structure")
    print("=" * 60)
    
    try:
        client = MCPClient.from_config_file(config_file)
        session = await client.create_session("mcp-analysis-server")
        
        # Test 1: Vector-only query
        print("\n1️⃣ Testing query_vector_only")
        print("-" * 40)
        
        vector_result = await session.call_tool(
            "query_vector_only",
            {
                "query": test_query,
                "collection_name": collection_name,
                "max_results": 5,
                "output_format": "json"
            }
        )
        
        print(f"Vector result type: {type(vector_result)}")
        print(f"Vector result content: {vector_result.content}")
        if hasattr(vector_result, 'is_error'):
            print(f"Vector result is_error: {vector_result.is_error}")
        else:
            print("Vector result error status: unknown")
        
        # Parse and save vector result content
        vector_content = vector_result.content[0].text if vector_result.content else "No content"
        with open("/opt/genpod/debug_vector_result.txt", "w") as f:
            f.write(vector_content)
        print("Vector result saved to debug_vector_result.txt")
        
        # Try to parse as JSON
        if vector_content:
            try:
                vector_json = json.loads(vector_content)
                print(f"Vector JSON keys: {list(vector_json.keys()) if isinstance(vector_json, dict) else 'Not a dict'}")
                with open("/opt/genpod/debug_vector_result.json", "w") as f:
                    json.dump(vector_json, f, indent=2)
            except:
                print("Vector content is not JSON")
        
        # Test 2: CPG-only query  
        print("\n2️⃣ Testing query_cpg_only")
        print("-" * 40)
        
        # Use a simple Cypher query for testing
        test_cypher = "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 5"
        
        cpg_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": test_cypher,
                "config_path": "/opt/genpod/neo4j_config.json",
                "max_results": 10,
                "user_query": test_query,
                "enable_synthesis": True
            }
        )
        
        print(f"CPG result type: {type(cpg_result)}")
        print(f"CPG result is_error: {cpg_result.is_error}")
        
        # Parse and save CPG result content
        cpg_content = cpg_result.content[0].text if cpg_result.content else "No content"
        with open("/opt/genpod/debug_cpg_result.txt", "w") as f:
            f.write(cpg_content)
        print("CPG result saved to debug_cpg_result.txt")
        
        # Try to parse as JSON
        if cpg_content:
            try:
                cpg_json = json.loads(cpg_content)
                print(f"CPG JSON keys: {list(cpg_json.keys()) if isinstance(cpg_json, dict) else 'Not a dict'}")
                with open("/opt/genpod/debug_cpg_result.json", "w") as f:
                    json.dump(cpg_json, f, indent=2)
            except:
                print("CPG content is not JSON")
        
        # Test 3: Comprehensive analysis
        print("\n3️⃣ Testing comprehensive_code_analysis")
        print("-" * 40)
        
        try:
            comprehensive_result = await session.call_tool(
                "comprehensive_code_analysis",
                {
                    "user_query": test_query,
                    "collection_name": collection_name,
                    "max_results": 5,
                    "project_path": project_path
                }
            )
            
            print(f"Comprehensive result type: {type(comprehensive_result)}")
            print(f"Comprehensive result is_error: {comprehensive_result.is_error}")
            
            # Parse and save comprehensive result content
            comp_content = comprehensive_result.content[0].text if comprehensive_result.content else "No content"
            with open("/opt/genpod/debug_comprehensive_result.txt", "w") as f:
                f.write(comp_content)
            print("Comprehensive result saved to debug_comprehensive_result.txt")
            
            # Try to parse as JSON
            if comp_content:
                try:
                    comp_json = json.loads(comp_content)
                    print(f"Comprehensive JSON keys: {list(comp_json.keys()) if isinstance(comp_json, dict) else 'Not a dict'}")
                    with open("/opt/genpod/debug_comprehensive_result.json", "w") as f:
                        json.dump(comp_json, f, indent=2)
                except:
                    print("Comprehensive content is not JSON")
            
        except Exception as comprehensive_error:
            print(f"❌ Comprehensive analysis failed: {comprehensive_error}")
            
            # Save error details
            error_details = {
                "error": str(comprehensive_error),
                "error_type": type(comprehensive_error).__name__
            }
            with open("/opt/genpod/debug_comprehensive_error.json", "w") as f:
                json.dump(error_details, f, indent=2)
            print("Error details saved to debug_comprehensive_error.json")
        
        await session.close()
        await client.close()
        
        print("\n✅ Debug test completed!")
        print("📁 Check the debug_*.json files for detailed structures")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_mcp_tools())
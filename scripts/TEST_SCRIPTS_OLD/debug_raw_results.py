#!/usr/bin/env python3

"""
Debug script to check if raw results are being captured in workflow
"""

import asyncio
import json
import sys

# Add project root to Python path
sys.path.insert(0, '/opt/genpod')

async def debug_raw_results():
    """Debug the workflow to see raw results"""
    
    from src.core.adaptive_cpg_agent_workflow import execute_adaptive_cpg_workflow
    
    print("🔍 Debugging raw results in workflow...")
    
    result = await execute_adaptive_cpg_workflow(
        user_query="What classes are defined in this project?",
        project_name="HelloWorldApp",
        max_iterations=3
    )
    
    print(f"\n📊 Workflow Result Keys: {list(result.keys())}")
    
    # Check for raw results
    raw_query_results = result.get("raw_query_results", [])
    all_executed_queries = result.get("all_executed_queries", [])
    
    print(f"\n🔍 raw_query_results count: {len(raw_query_results)}")
    print(f"🔍 all_executed_queries count: {len(all_executed_queries)}")
    
    if raw_query_results:
        print(f"\n📋 First raw_query_result:")
        print(json.dumps(raw_query_results[0], indent=2)[:500] + "...")
    else:
        print(f"\n❌ raw_query_results is empty!")
    
    if all_executed_queries:
        print(f"\n📋 First executed_query keys: {list(all_executed_queries[0].keys())}")
        if "cli_output" in all_executed_queries[0]:
            cli_output = all_executed_queries[0]["cli_output"]
            print(f"🔍 CLI output length: {len(cli_output) if cli_output else 0}")
            if cli_output:
                print(f"🔍 CLI output preview: {cli_output[:200]}...")
        else:
            print(f"❌ No cli_output in executed query!")
    else:
        print(f"\n❌ all_executed_queries is empty!")
    
    # Save for inspection
    with open('/opt/genpod/debug_raw_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n💾 Full debug result saved to: debug_raw_results.json")

if __name__ == "__main__":
    asyncio.run(debug_raw_results())
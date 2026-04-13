"""
Test script to verify the cancel scope error fix in query_cpg_rag MCP tool.
"""

import asyncio
import json
import logging

# Configure logging to see any errors
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from mcp_use import MCPClient


async def main():
    """Test the query_cpg_rag MCP tool and check for cancel scope errors."""

    print("="*70)
    print("Testing query_cpg_rag MCP Tool (Cancel Scope Fix)")
    print("="*70)

    config_file = "/opt/genpod/file_watcher_mcp_config.json"

    # Create MCP client and session
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("mcp-analysis-server")

    try:
        # Call the query_cpg_rag tool
        result = await session.call_tool(
            "query_cpg_rag",
            {
                "user_query": "What classes are defined in HelloWorldApp?",
                "project_name": "HelloWorldApp",
                "config_path": "/opt/genpod/neo4j_config.json",
                "schema_path": "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
                "llm_model": "gpt-4o",
                "max_cot_iterations": 10,
                "max_verifier_iterations": 10,
                "parallel_agents": True,
                "enable_verification": True,
                "enable_entity_resolution": True,
                "enable_observer": False
            }
        )

        print("\n" + "="*70)
        print("RESULT")
        print("="*70)

        # Parse result
        if hasattr(result, 'content') and result.content:
            content = result.content[0].text if result.content else str(result)
            result_dict = json.loads(content)

            print(f"Status: {result_dict.get('status')}")
            print(f"Confidence: {result_dict.get('response', {}).get('confidence')}")
            print(f"Citations: {len(result_dict.get('citations', []))}")
            print(f"Verified: {result_dict.get('verified_count')}")
            print(f"Execution time: {result_dict.get('execution_time_ms')}ms")
        else:
            print(f"Raw result: {result}")

        print("\n" + "="*70)
        print("TEST COMPLETE - Watch server logs for cancel scope errors")
        print("="*70)

    finally:
        print("\nClosing client session...")
        # Note: This may also cause cancel scope errors if not handled properly
        # The key is whether the SERVER logs show errors
        pass


if __name__ == "__main__":
    asyncio.run(main())

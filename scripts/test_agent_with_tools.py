#!/usr/bin/env python3
"""
Direct test of AdaptiveQueryAgent with schema tools enabled.
"""

import asyncio
import json
import logging
from src.core.llm_service import LLMService
from src.core.workflow.adaptive_query_agent import AdaptiveQueryAgent
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from src.mcp_use.cypher_mcp_client import CypherMCPClient

logging.basicConfig(level=logging.INFO)


async def main():
    print("=" * 80)
    print("AGENT WITH SCHEMA TOOLS TEST")
    print("=" * 80)

    # Initialize services
    llm_service = LLMService()
    print("✅ LLM service initialized")

    # Initialize Cypher server
    cypher_server = CypherMCPClient("neo4j_config.json")
    await cypher_server.initialize()
    print("✅ Cypher server initialized")

    # Initialize schema manager
    schema_manager = DynamicSchemaManager(cypher_server)
    await schema_manager.initialize()
    print("✅ Schema manager initialized")

    # Create minimal approach packet for a simple query
    approach_packet = {
        'text': 'Find the CreateWorkers function in the WorkerFactory class',
        'active_premises': [
            {'text': 'WorkerFactory is a Type node'},
            {'text': 'CreateWorkers is a Function node contained in WorkerFactory'}
        ]
    }

    # Get filtered schema for this query
    schema = await schema_manager.get_filtered_schema(approach_packet['text'])

    print(f"\n✅ Filtered schema ready: {len(schema['nodes'])} node types\n")

    # Create agent with schema tools ENABLED
    agent = AdaptiveQueryAgent(
        approach_index=0,
        approach_details={'type': 'test'},
        user_query="Find WorkerFactory.CreateWorkers",
        schema=schema,
        project_name="HelloWorldApp",
        llm_service=llm_service,
        cypher_server=cypher_server,
        max_iterations=3,
        approach_packet=approach_packet,
        schema_manager=schema_manager,
        use_query_plans=False,  # Disable query plans for simplicity
        use_schema_tools=True  # 🛠️ ENABLE SCHEMA TOOLS!
    )

    print("=" * 80)
    print("RUNNING AGENT WITH SCHEMA TOOLS")
    print("=" * 80)

    result = await agent.run()

    print("\n" + "=" * 80)
    print("RESULT")
    print("=" * 80)

    print(f"\nAnswer: {result['answer']}")
    print(f"Queries executed: {result['queries_executed']}")
    print(f"Total results: {result['total_results']}")
    print(f"Tokens used: {result['tokens_used']}")
    print(f"Quality: {result['quality']}")

    if 'discovered_data' in result:
        print(f"\nData points: {len(result['discovered_data'])}")

    await cypher_server.close()

    print("\n" + "=" * 80)
    print("✅ TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

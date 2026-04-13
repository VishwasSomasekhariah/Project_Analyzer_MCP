#!/usr/bin/env python3
"""Test the enhanced IR pipeline exploration for computed metrics."""
import asyncio
import logging
from src.core.graph_rag.ir import MultiAgentIRCoT
from src.core.graph_rag.core.config import SystemConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def test_exploration():
    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        llm_model="gpt-4o",
    )

    system = MultiAgentIRCoT(config)
    await system.initialize()

    # Test query asking for cyclomatic complexity (a computed metric)
    query = "What is the cyclomatic complexity of each method in HelloWorldApp?"
    print(f"\n{'='*60}")
    print(f"Query: {query}")
    print(f"{'='*60}\n")

    try:
        result = await system.run(user_query=query)

        print(f"\n{'='*60}")
        print("FINAL ANSWER:")
        print(f"{'='*60}")
        print(result.answer)

        print(f"\n{'='*60}")
        print("CITATIONS:")
        print(f"{'='*60}")
        for citation in result.citations:
            print(f"  - {citation}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    await system.shutdown()

if __name__ == '__main__':
    asyncio.run(test_exploration())

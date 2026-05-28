"""
Test script for the new graph_rag module.

This tests that the refactored module works identically to test_multi_agent_cot.py
"""

import asyncio
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import from the NEW graph_rag module
from src.core.graph_rag import (
    MultiAgentCoT,
    SystemConfig,
    __version__,
)


async def main():
    """Test the new graph_rag module with the same query as test_multi_agent_cot.py"""

    print(f"\n{'='*70}")
    print(f"Testing NEW graph_rag Module v{__version__}")
    print(f"{'='*70}\n")

    # Same configuration as test_multi_agent_cot.py
    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        llm_model="gpt-4o",
        max_cot_iterations=10,
        max_verifier_iterations=5,
        parallel_cot_agents=True,
        verification_enabled=True,
        entity_resolution_enabled=True,
    )

    # Initialize the multi-agent system
    system = MultiAgentCoT(config, enable_observer=True)
    await system.initialize()

    # Same query as in test_multi_agent_cot.py
    query = "Analyze the overall architecture of the HelloWorldApp."

    # Run the query
    response = await system.run(query)

    # Output results
    print(f"\n{'='*70}")
    print("PRODUCTION API RESPONSE")
    print(f"{'='*70}")

    print(f"Answer length: {len(response.answer)} chars")
    print(f"Confidence: {response.confidence.value}")
    print(f"Citations: {len(response.citations)} items")
    print(f"Verified: {response.verified_count}")
    print(f"Unverified: {response.unverified_count}")
    print(f"Token usage: {response.token_usage.total_tokens:,} total tokens")
    print(f"Execution time: {response.execution_time_ms}ms")
    print(f"Sub-queries: {response.sub_queries_count}")
    print(f"LLM calls: {response.llm_calls_count}")

    # Save full response
    output_file = "graph_rag_test_response.json"
    response_dict = response.model_dump()
    with open(output_file, 'w') as f:
        json.dump(response_dict, f, indent=2, default=str)
    print(f"\nFull response saved to: {output_file}")

    print(f"\n{'='*70}")
    print("TEST COMPLETE - graph_rag module works!")
    print(f"{'='*70}\n")

    return response


if __name__ == "__main__":
    asyncio.run(main())

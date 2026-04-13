"""
Test the IR-based pipeline (MultiAgentIRCoT) with a simple query.
"""

import asyncio
import sys
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from src.core.graph_rag import SystemConfig
from src.core.graph_rag.ir import MultiAgentIRCoT


async def test_ir_pipeline():
    """Test the IR pipeline with a simple query."""
    print("=" * 70)
    print("Testing IR-based Pipeline (MultiAgentIRCoT)")
    print("=" * 70)

    # Configuration with IR pipeline enabled
    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        llm_model="gpt-4o",
        max_cot_iterations=10,
        use_ir_pipeline=True,  # Explicitly enable IR pipeline
    )

    print(f"\nConfiguration:")
    print(f"  - use_ir_pipeline: {config.use_ir_pipeline}")
    print(f"  - llm_model: {config.llm_model}")

    # Initialize the system
    print("\nInitializing MultiAgentIRCoT...")
    system = MultiAgentIRCoT(config)
    await system.initialize()
    print("Initialization complete.")

    # Test query - same as earlier tests
    query = "What are the key methods in the HelloWorldApp and their cyclomatic complexity?"
    print(f"\nQuery: {query}")
    print("-" * 70)

    try:
        # Run the query
        response = await system.run(query)

        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"Confidence: {response.confidence.value}")
        print(f"Execution Time: {response.execution_time_ms}ms")
        print(f"Token Usage: {response.token_usage.total_tokens:,} tokens")
        print(f"Citations: {len(response.citations)} items")
        print("\nAnswer:")
        print("-" * 70)
        print(response.answer[:2000] if len(response.answer) > 2000 else response.answer)

        if response.citations:
            print("\n\nCitations:")
            print("-" * 70)
            for i, citation in enumerate(response.citations[:5], 1):
                print(f"  {i}. {citation}")

    except Exception as e:
        print(f"\nError during query execution: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        await system.shutdown()
        print("\nSystem shutdown complete.")


if __name__ == "__main__":
    asyncio.run(test_ir_pipeline())

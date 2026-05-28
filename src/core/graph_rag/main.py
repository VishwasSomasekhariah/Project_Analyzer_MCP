"""
Main entry point for the Graph RAG Multi-Agent System.

This script demonstrates how to use the modular Graph RAG package
for code analysis queries over a Neo4j Code Property Graph.

Usage:
    python -m src.core.graph_rag.main [query]

Example:
    python -m src.core.graph_rag.main "Analyze the architecture of HelloWorldApp"
"""

import asyncio
import json
import sys

from src.core.graph_rag import (
    MultiAgentCoT,
    SystemConfig,
    __version__,
)
from src.core.graph_rag.ir import MultiAgentIRCoT


async def main(query: str = None):
    """
    Run the ToT/CoT multi-agent system.

    Args:
        query: Optional query string. Uses default if not provided.
    """
    print(f"Graph RAG Multi-Agent System v{__version__}")
    print("=" * 70)

    # Default configuration - can be customized
    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        llm_model="gpt-4o",
        max_cot_iterations=10,
        max_verifier_iterations=5,
        parallel_cot_agents=True,
        verification_enabled=True,
        entity_resolution_enabled=True,
        use_ir_pipeline=True,  # Feature flag: True = new IR pipeline, False = old CoT+Verifier
    )

    # Initialize the multi-agent system based on feature flag
    if config.use_ir_pipeline:
        print("Using IR-based pipeline (IRPlannerAgent + IRValidator + CypherCompiler)")
        system = MultiAgentIRCoT(config)
    else:
        print("Using legacy CoT+Verifier pipeline")
        system = MultiAgentCoT(config, enable_observer=True)
    await system.initialize()

    # Use provided query or default
    if not query:
        query = "Analyze the overall architecture of the HelloWorldApp."

    # Run the query
    response = await system.run(query)

    # Output results
    print(f"\n{'='*70}")
    print("PRODUCTION API RESPONSE (JSON)")
    print(f"{'='*70}")

    # Export to JSON (what a caller would receive)
    response_dict = response.model_dump()

    # Pretty print summary
    print(f"Response contains:")
    print(f"  - answer: {len(response.answer)} chars")
    print(f"  - confidence: {response.confidence.value}")
    print(f"  - citations: {len(response.citations)} items")
    print(f"  - token_usage: {response.token_usage.total_tokens:,} total tokens")
    print(f"  - execution_time_ms: {response.execution_time_ms}")
    print(f"  - original_query: '{response.original_query}'")

    # Optionally save full response to file
    output_file = "production_response.json"
    with open(output_file, 'w') as f:
        json.dump(response_dict, f, indent=2, default=str)
    print(f"\nFull response saved to: {output_file}")
    print(f"{'='*70}\n")

    return response


def run():
    """Entry point for CLI usage."""
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    asyncio.run(main(query))


if __name__ == "__main__":
    run()

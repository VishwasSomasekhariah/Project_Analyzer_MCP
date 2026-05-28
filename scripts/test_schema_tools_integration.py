#!/usr/bin/env python3
"""
Test Schema Tools Integration

Tests the full AdaptiveQueryAgent with use_schema_tools=True
"""

import asyncio
import logging
from src.core.workflow.adaptive_cpg_workflow import AdaptiveCPGWorkflow

# Set logging
logging.basicConfig(level=logging.INFO)


async def main():
    print("=" * 80)
    print("SCHEMA TOOLS INTEGRATION TEST")
    print("=" * 80)

    # Test query
    query = "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?"

    print(f"\n🎯 Query: {query}\n")

    # Create workflow with use_schema_tools=True
    workflow = AdaptiveCPGWorkflow(
        neo4j_config_path="neo4j_config.json",
        use_schema_tools=True  # 🛠️ ENABLE SCHEMA TOOLS
    )

    print("✅ Workflow initialized with schema tools enabled\n")

    # Run workflow
    print("=" * 80)
    print("RUNNING WORKFLOW")
    print("=" * 80)

    result = await workflow.run(query)

    print("\n" + "=" * 80)
    print("RESULT")
    print("=" * 80)

    print(f"\nFinal Answer:\n{result['final_answer']}\n")
    print(f"Total Queries: {result.get('total_queries_executed', 0)}")
    print(f"Total Tokens: {result.get('total_tokens_used', 0)}")
    print(f"Total Cost: ${result.get('total_cost', 0):.4f}")
    print(f"Execution Time: {result.get('execution_time_seconds', 0):.2f}s")

    print("\n" + "=" * 80)
    print("✅ TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

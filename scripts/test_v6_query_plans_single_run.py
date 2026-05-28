#!/usr/bin/env python3
"""
Quick test of V6 query plan mode - single run.
"""
import asyncio
import json
from pathlib import Path
from src.core.workflow.adaptive_cpg_workflow import execute_adaptive_cpg_workflow


async def main():
    """Run a single test with the subquery from V5 Run 1 SQ2."""

    # This is the exact query from V5 Run 1 SQ2 that failed
    test_query = "What are the key architectural components and how do they interact?"

    print("=" * 80)
    print("V6 QUERY PLAN MODE - SINGLE RUN TEST")
    print("=" * 80)
    print(f"Query: {test_query}")
    print()
    print("🚀 Starting workflow with use_query_plans=True...")
    print()

    try:
        result = await execute_adaptive_cpg_workflow(
            user_query=test_query,
            project_name="HelloWorldApp",
            neo4j_config="neo4j_config.json",
            max_iterations=2  # Just 2 iterations for quick test
        )

        # Save result
        output_file = Path("test_v6_single_run_output.json")
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)

        print()
        print("=" * 80)
        print("RESULTS")
        print("=" * 80)
        print(f"Success: {result.get('success', False)}")
        print(f"Final Answer: {result.get('final_answer', 'N/A')[:200]}...")
        print(f"Confidence: {result.get('confidence_score', 0.0)}")
        print()
        print(f"✅ Full output saved to: {output_file}")
        print()

        # Show approach details
        if 'approach_results' in result:
            print("Approach Results:")
            for idx, approach in enumerate(result['approach_results'], 1):
                print(f"  {idx}. {approach.get('approach_name', 'Unknown')}")
                print(f"     Queries Executed: {approach.get('queries_executed', 0)}")
                print(f"     Data Found: {approach.get('data_found', 0)} items")

                # Show mode info if available
                if 'queries_executed' in approach and len(approach['queries_executed']) > 0:
                    first_query = approach['queries_executed'][0]
                    mode = first_query.get('mode', 'unknown')
                    print(f"     Mode: {mode}")

                    if mode == 'plan' and 'steps' in first_query:
                        print(f"     Query Plan Steps: {len(first_query['steps'])}")
                        if 'failed_at_step' in first_query:
                            print(f"     Failed at Step: {first_query['failed_at_step']}")

        print()
        print("=" * 80)

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())

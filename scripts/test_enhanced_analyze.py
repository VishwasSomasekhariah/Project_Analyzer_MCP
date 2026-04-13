#!/usr/bin/env python3
"""
Test enhanced ANALYZE step with query plan validation.
"""

import asyncio
from src.core.workflow.adaptive_cpg_workflow import execute_adaptive_cpg_workflow

async def main():
    print("=" * 80)
    print("TESTING ENHANCED ANALYZE STEP")
    print("=" * 80)
    
    query = "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?"
    
    print(f"\nQuery: {query}\n")
    print("Running workflow with enhanced ANALYZE step...")
    print("Expected improvement: Should stop after 1 iteration per subquery when results are sufficient\n")
    
    result = await execute_adaptive_cpg_workflow(
        user_query=query,
        project_name="HelloWorldApp",
        neo4j_config="neo4j_config.json",
        use_schema_tools=True  # Using schema tools from V8
    )
    
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    
    print(f"\nFinal Answer: {result['final_answer'][:200]}...")
    print(f"\nTotal Queries: {result.get('total_queries_executed', 0)}")
    print(f"Execution Time: {result.get('execution_time_seconds', 0):.2f}s")
    print(f"Total Cost: ${result.get('total_cost', 0):.4f}")
    
    # Check iteration counts per approach
    traces = result.get('approach_execution_traces', {})
    print("\n📊 Queries per Subquery:")
    for key in sorted(traces.keys()):
        approach = traces[key]
        name = approach.get('approach_name', f'Approach {key}')
        queries = approach.get('queries_executed', 0)
        is_sufficient = approach.get('is_sufficient', False)
        print(f"  {name}: {queries} iterations (sufficient: {is_sufficient})")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(main())

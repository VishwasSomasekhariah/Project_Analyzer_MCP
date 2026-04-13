#!/usr/bin/env python3
"""
Test all 4 subqueries multiple times to verify consistency.
"""
import asyncio
import json
import sys

sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
import yaml


SUBQUERIES = {
    "SQ1": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
    "SQ2": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
    "SQ3": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
    "SQ4": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name"
}


async def main():
    print("=" * 100)
    print("ALL SUBQUERIES CONSISTENCY CHECK (3 runs each)")
    print("=" * 100)
    print()

    # Initialize once
    print("Initializing DynamicSchemaManager...")
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/all_subqueries_consistency_cache.json",
        yaml_schema=yaml_schema,
        embedding_model='all-MiniLM-L6-v2'
    )

    await schema_manager.initialize_background()
    print("✅ Initialized")
    print()

    all_results = {}

    for sq_id, query in SUBQUERIES.items():
        print(f"{sq_id}: {query[:80]}...")
        print("-" * 100)

        runs = []
        for i in range(3):
            result = schema_manager.extract_types_from_query(
                query_text=query,
                similarity_threshold=0.60,
                method='hybrid',
                alpha=0.3,
                return_scores=True
            )

            runs.append({
                'node_types': result['node_types'],
                'relationship_types': result['relationship_types']
            })

            if i == 0:
                print(f"  Nodes: {', '.join(result['node_types'])}")
                print(f"  Rels:  {', '.join(result['relationship_types']) if result['relationship_types'] else '(none)'}")

        # Check consistency
        all_node_types = [set(r['node_types']) for r in runs]
        all_rel_types = [set(r['relationship_types']) for r in runs]

        nodes_consistent = all(nt == all_node_types[0] for nt in all_node_types)
        rels_consistent = all(rt == all_rel_types[0] for rt in all_rel_types)

        print(f"  Consistent: {'✅ YES' if (nodes_consistent and rels_consistent) else '❌ NO'}")
        print()

        all_results[sq_id] = {
            'query': query,
            'consistent': nodes_consistent and rels_consistent,
            'runs': runs
        }

    # Summary
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print()

    all_consistent = all(r['consistent'] for r in all_results.values())

    if all_consistent:
        print("✅✅✅ ALL SUBQUERIES PERFECTLY CONSISTENT ✅✅✅")
        print()
        print("Every subquery produces identical results across 3 runs.")
        print("The system is fully deterministic and reproducible.")
    else:
        print("❌ INCONSISTENCIES DETECTED")
        for sq_id, data in all_results.items():
            if not data['consistent']:
                print(f"  {sq_id}: INCONSISTENT")

    print()

    # Show detailed breakdown
    print("Detailed Results:")
    print("-" * 100)
    print()

    for sq_id, data in all_results.items():
        print(f"{sq_id}:")
        print(f"  Nodes: {', '.join(data['runs'][0]['node_types'])}")
        print(f"  Rels:  {', '.join(data['runs'][0]['relationship_types']) if data['runs'][0]['relationship_types'] else '(none)'}")
        print(f"  Consistent: {'✅ YES' if data['consistent'] else '❌ NO'}")
        print()

    # Save results
    output_path = "/tmp/all_subqueries_consistency_results.json"
    with open(output_path, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"Detailed results saved to: {output_path}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

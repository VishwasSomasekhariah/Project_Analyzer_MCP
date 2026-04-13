#!/usr/bin/env python3
"""
Consistency Check: Run same extraction multiple times to verify determinism.

Tests:
1. Are similarity scores deterministic across runs?
2. Do we get the same extracted types every time?
3. Is there any randomness/variability?
"""
import asyncio
import json
import sys

sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
import yaml


async def main():
    print("=" * 100)
    print("CONSISTENCY CHECK: Running Same Extraction Multiple Times")
    print("=" * 100)
    print()

    # Initialize once
    print("Initializing DynamicSchemaManager...")
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/consistency_check_cache.json",
        yaml_schema=yaml_schema,
        embedding_model='all-MiniLM-L6-v2'
    )

    await schema_manager.initialize_background()
    print("✅ Initialized")
    print()

    # Test query (SQ1 - the problematic one)
    query = "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'"

    print(f"Test Query: {query}")
    print()
    print("Running extraction 5 times...")
    print("-" * 100)

    runs = []
    for i in range(5):
        result = schema_manager.extract_types_from_query(
            query_text=query,
            similarity_threshold=0.60,
            top_k=5,
            method='hybrid',
            alpha=0.3,
            return_scores=True
        )

        runs.append({
            'run_id': i + 1,
            'node_types': result['node_types'],
            'relationship_types': result['relationship_types'],
            'node_scores': result.get('node_scores', {}),
            'rel_scores': result.get('rel_scores', {})
        })

        print(f"Run {i+1}:")
        print(f"  Nodes: {', '.join(result['node_types'])}")
        print(f"  Rels:  {', '.join(result['relationship_types'])}")
        print()

    # Compare all runs
    print("=" * 100)
    print("CONSISTENCY ANALYSIS")
    print("=" * 100)
    print()

    # Check if all runs produced same extracted types
    all_node_types = [set(r['node_types']) for r in runs]
    all_rel_types = [set(r['relationship_types']) for r in runs]

    nodes_consistent = all(nt == all_node_types[0] for nt in all_node_types)
    rels_consistent = all(rt == all_rel_types[0] for rt in all_rel_types)

    print(f"Extracted Node Types Consistent: {'✅ YES' if nodes_consistent else '❌ NO'}")
    print(f"Extracted Rel Types Consistent:  {'✅ YES' if rels_consistent else '❌ NO'}")
    print()

    # Compare similarity scores across runs
    print("Similarity Score Comparison:")
    print("-" * 100)

    # Get all node types from first run
    all_types = list(runs[0]['node_scores'].keys())

    print("\nNode Scores Across Runs:")
    print(f"{'Type':<15} {'Run 1':<12} {'Run 2':<12} {'Run 3':<12} {'Run 4':<12} {'Run 5':<12} {'Variance':<10}")
    print("-" * 100)

    max_variance = 0.0
    for node_type in all_types:
        scores = [r['node_scores'][node_type]['score'] for r in runs]
        variance = max(scores) - min(scores)
        max_variance = max(max_variance, variance)

        score_strs = [f"{s:.6f}" for s in scores]
        print(f"{node_type:<15} {score_strs[0]:<12} {score_strs[1]:<12} {score_strs[2]:<12} {score_strs[3]:<12} {score_strs[4]:<12} {variance:.8f}")

    print()
    print(f"Maximum Score Variance: {max_variance:.10f}")
    print()

    # Same for relationships
    all_rels = list(runs[0]['rel_scores'].keys())
    print("\nRelationship Scores Across Runs:")
    print(f"{'Type':<15} {'Run 1':<12} {'Run 2':<12} {'Run 3':<12} {'Run 4':<12} {'Run 5':<12} {'Variance':<10}")
    print("-" * 100)

    max_rel_variance = 0.0
    for rel_type in all_rels:
        scores = [r['rel_scores'][rel_type]['score'] for r in runs]
        variance = max(scores) - min(scores)
        max_rel_variance = max(max_rel_variance, variance)

        score_strs = [f"{s:.6f}" for s in scores]
        print(f"{rel_type:<15} {score_strs[0]:<12} {score_strs[1]:<12} {score_strs[2]:<12} {score_strs[3]:<12} {score_strs[4]:<12} {variance:.8f}")

    print()
    print(f"Maximum Rel Variance: {max_rel_variance:.10f}")
    print()

    # Summary
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print()

    if nodes_consistent and rels_consistent and max_variance < 1e-6 and max_rel_variance < 1e-6:
        print("✅✅✅ PERFECTLY DETERMINISTIC ✅✅✅")
        print()
        print("Results:")
        print("  • Extracted types identical across all runs")
        print("  • Similarity scores identical (variance < 0.000001)")
        print("  • System is fully reproducible")
    elif nodes_consistent and rels_consistent:
        print("✅ PRACTICALLY DETERMINISTIC")
        print()
        print("Results:")
        print("  • Extracted types identical across all runs")
        print(f"  • Similarity scores vary slightly (max variance: {max(max_variance, max_rel_variance):.10f})")
        print("  • Variance likely due to floating-point precision")
    else:
        print("❌ NON-DETERMINISTIC BEHAVIOR DETECTED")
        print()
        print("Issues:")
        if not nodes_consistent:
            print("  • Node types differ between runs")
            for i, nt in enumerate(all_node_types):
                print(f"    Run {i+1}: {nt}")
        if not rels_consistent:
            print("  • Relationship types differ between runs")
            for i, rt in enumerate(all_rel_types):
                print(f"    Run {i+1}: {rt}")

    print()

    # Save detailed comparison
    comparison = {
        "query": query,
        "threshold": 0.60,
        "num_runs": 5,
        "consistency": {
            "nodes_consistent": nodes_consistent,
            "rels_consistent": rels_consistent,
            "max_node_score_variance": max_variance,
            "max_rel_score_variance": max_rel_variance
        },
        "runs": runs
    }

    output_path = "/tmp/consistency_check_results.json"
    with open(output_path, 'w') as f:
        json.dump(comparison, f, indent=2)

    print(f"Detailed results saved to: {output_path}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Test alpha=0.15 across all 4 subqueries.

From alpha variation test, we know alpha=0.15:
- Captures CONTAINS (score 0.6740 > threshold 0.60)
- Maintains semantic strength for Type/Function
- Should improve relationship extraction vs alpha=0.3
"""
import asyncio
import json
import yaml
import sys
from pathlib import Path

sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


# Ground truth subqueries (validated via actual Cypher execution)
SUBQUERIES = {
    "SQ1": {
        "query": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
        "description": "Find function by name within a specific type",
        "expected_nodes": ["Type", "Function"],
        "expected_rels": ["CONTAINS"]
    },
    "SQ2": {
        "query": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
        "description": "Find constructor calls and their declaring types",
        "expected_nodes": ["Type", "Function"],
        "expected_rels": ["CONTAINS", "CALLS"]
    },
    "SQ3": {
        "query": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
        "description": "Find return statements with new instantiations",
        "expected_nodes": ["Type", "Function", "Statement"],
        "expected_rels": ["CONTAINS", "CALLS"]
    },
    "SQ4": {
        "query": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name",
        "description": "Find variable declarations with new instantiations",
        "expected_nodes": ["Type", "Function", "Variable"],
        "expected_rels": ["CONTAINS", "REFERENCES"]
    }
}


async def main():
    print("=" * 100)
    print("TESTING ALPHA=0.15 ACROSS ALL SUBQUERIES")
    print("=" * 100)
    print()
    print("Configuration:")
    print("  Alpha: 0.15 (very semantic - 85% embeddings, 15% BM25)")
    print("  Threshold: 0.60")
    print("  Method: hybrid")
    print()
    print("Expected Improvement over alpha=0.3:")
    print("  • Better CONTAINS extraction (0.6740 vs 0.5827)")
    print("  • Should capture relationship in SQ1")
    print()
    print("=" * 100)
    print()

    # Initialize
    print("Initializing DynamicSchemaManager...")
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/alpha_015_test_cache.json",
        yaml_schema=yaml_schema,
        embedding_model='all-MiniLM-L6-v2'
    )

    await schema_manager.initialize_background()
    print("✅ Initialized")
    print()

    results = []
    for sq_id, sq_data in SUBQUERIES.items():
        print(f"{sq_id}: {sq_data['description']}")
        print(f"  Query: {sq_data['query'][:80]}...")
        print()

        # Extract with alpha=0.15
        result = schema_manager.extract_types_from_query(
            query_text=sq_data['query'],
            similarity_threshold=0.60,
            top_k=5,
            method='hybrid',
            alpha=0.15,  # Testing this value
            return_scores=True
        )

        expected_nodes = set(sq_data['expected_nodes'])
        extracted_nodes = set(result['node_types'])

        expected_rels = set(sq_data['expected_rels'])
        extracted_rels = set(result['relationship_types'])

        # Calculate metrics
        node_tp = len(expected_nodes & extracted_nodes)
        node_precision = node_tp / len(extracted_nodes) if extracted_nodes else 0
        node_recall = node_tp / len(expected_nodes) if expected_nodes else 0
        node_f1 = 2 * (node_precision * node_recall) / (node_precision + node_recall) if (node_precision + node_recall) > 0 else 0

        rel_tp = len(expected_rels & extracted_rels)
        rel_precision = rel_tp / len(extracted_rels) if extracted_rels else 0
        rel_recall = rel_tp / len(expected_rels) if expected_rels else 0
        rel_f1 = 2 * (rel_precision * rel_recall) / (rel_precision + rel_recall) if (rel_precision + rel_recall) > 0 else 0

        results.append({
            'sq_id': sq_id,
            'expected_nodes': sq_data['expected_nodes'],
            'extracted_nodes': result['node_types'],
            'expected_rels': sq_data['expected_rels'],
            'extracted_rels': result['relationship_types'],
            'node_metrics': {
                'precision': node_precision,
                'recall': node_recall,
                'f1': node_f1,
                'missing': list(expected_nodes - extracted_nodes),
                'extra': list(extracted_nodes - expected_nodes)
            },
            'rel_metrics': {
                'precision': rel_precision,
                'recall': rel_recall,
                'f1': rel_f1,
                'missing': list(expected_rels - extracted_rels),
                'extra': list(extracted_rels - expected_rels)
            },
            'scores': {
                'node_scores': result.get('node_scores', {}),
                'rel_scores': result.get('rel_scores', {})
            }
        })

        print(f"  Expected Nodes: {', '.join(sorted(expected_nodes))}")
        print(f"  Extracted:      {', '.join(result['node_types'])}")
        print(f"  Node Metrics:   Precision={node_precision:.2f}, Recall={node_recall:.2f}, F1={node_f1:.3f}")
        print()

        print(f"  Expected Rels:  {', '.join(sorted(expected_rels))}")
        print(f"  Extracted:      {', '.join(result['relationship_types']) if result['relationship_types'] else '(none)'}")
        print(f"  Rel Metrics:    Precision={rel_precision:.2f}, Recall={rel_recall:.2f}, F1={rel_f1:.3f}")
        print()

        if node_precision == 1.0 and node_recall == 1.0 and rel_precision == 1.0 and rel_recall == 1.0:
            print(f"  ✅✅✅ PERFECT EXTRACTION!")
        elif node_precision == 1.0 and node_recall == 1.0:
            print(f"  ✅ PERFECT NODE EXTRACTION!")
            if rel_recall < 1.0:
                print(f"  ⚠️  Missing relationships: {', '.join(expected_rels - extracted_rels)}")
        elif node_recall == 1.0:
            print(f"  ✅ Perfect node recall")
            print(f"  ⚠️  Extra nodes: {', '.join(extracted_nodes - expected_nodes)}")
        else:
            print(f"  ❌ Missing nodes: {', '.join(expected_nodes - extracted_nodes)}")

        print()
        print("-" * 100)
        print()

    # Summary
    print("=" * 100)
    print("SUMMARY - ALPHA=0.15")
    print("=" * 100)
    print()

    avg_node_precision = sum(r['node_metrics']['precision'] for r in results) / len(results)
    avg_node_recall = sum(r['node_metrics']['recall'] for r in results) / len(results)
    avg_node_f1 = sum(r['node_metrics']['f1'] for r in results) / len(results)

    avg_rel_precision = sum(r['rel_metrics']['precision'] for r in results) / len(results)
    avg_rel_recall = sum(r['rel_metrics']['recall'] for r in results) / len(results)
    avg_rel_f1 = sum(r['rel_metrics']['f1'] for r in results) / len(results)

    perfect_node_count = sum(1 for r in results if r['node_metrics']['precision'] == 1.0 and r['node_metrics']['recall'] == 1.0)
    perfect_recall_nodes = all(r['node_metrics']['recall'] == 1.0 for r in results)
    perfect_recall_rels = all(r['rel_metrics']['recall'] == 1.0 for r in results)

    print(f"Node Metrics:")
    print(f"  Average Precision: {avg_node_precision:.3f}")
    print(f"  Average Recall:    {avg_node_recall:.3f}")
    print(f"  Average F1:        {avg_node_f1:.3f}")
    print(f"  Perfect Recall:    {'✅ YES' if perfect_recall_nodes else '❌ NO'}")
    print(f"  Perfect Extractions: {perfect_node_count}/4")
    print()

    print(f"Relationship Metrics:")
    print(f"  Average Precision: {avg_rel_precision:.3f}")
    print(f"  Average Recall:    {avg_rel_recall:.3f}")
    print(f"  Average F1:        {avg_rel_f1:.3f}")
    print(f"  Perfect Recall:    {'✅ YES' if perfect_recall_rels else '❌ NO'}")
    print()

    # Comparison with alpha=0.3
    print("=" * 100)
    print("COMPARISON: Alpha=0.15 vs Alpha=0.3")
    print("=" * 100)
    print()

    # Previous results with alpha=0.3 (from complete workflow test)
    alpha_03_results = {
        'avg_node_precision': 0.850,
        'avg_node_recall': 1.000,
        'avg_node_f1': 0.893,
        'avg_rel_precision': 0.500,
        'avg_rel_recall': 0.250,
        'avg_rel_f1': 0.334
    }

    print(f"{'Metric':<25} {'α=0.3 (old)':<15} {'α=0.15 (new)':<15} {'Change':<15}")
    print("-" * 100)
    print(f"{'Node Precision':<25} {alpha_03_results['avg_node_precision']:<15.3f} {avg_node_precision:<15.3f} {avg_node_precision - alpha_03_results['avg_node_precision']:+.3f}")
    print(f"{'Node Recall':<25} {alpha_03_results['avg_node_recall']:<15.3f} {avg_node_recall:<15.3f} {avg_node_recall - alpha_03_results['avg_node_recall']:+.3f}")
    print(f"{'Node F1':<25} {alpha_03_results['avg_node_f1']:<15.3f} {avg_node_f1:<15.3f} {avg_node_f1 - alpha_03_results['avg_node_f1']:+.3f}")
    print()
    print(f"{'Relationship Precision':<25} {alpha_03_results['avg_rel_precision']:<15.3f} {avg_rel_precision:<15.3f} {avg_rel_precision - alpha_03_results['avg_rel_precision']:+.3f}")
    print(f"{'Relationship Recall':<25} {alpha_03_results['avg_rel_recall']:<15.3f} {avg_rel_recall:<15.3f} {avg_rel_recall - alpha_03_results['avg_rel_recall']:+.3f}")
    print(f"{'Relationship F1':<25} {alpha_03_results['avg_rel_f1']:<15.3f} {avg_rel_f1:<15.3f} {avg_rel_f1 - alpha_03_results['avg_rel_f1']:+.3f}")
    print()

    # Recommendation
    print("=" * 100)
    print("RECOMMENDATION")
    print("=" * 100)
    print()

    if avg_node_f1 >= alpha_03_results['avg_node_f1'] and avg_rel_f1 > alpha_03_results['avg_rel_f1']:
        print("✅✅✅ ALPHA=0.15 IS BETTER! ✅✅✅")
        print()
        print("Improvements:")
        if avg_rel_recall > alpha_03_results['avg_rel_recall']:
            print(f"  • Better relationship recall: {avg_rel_recall:.2f} vs {alpha_03_results['avg_rel_recall']:.2f}")
        if avg_rel_f1 > alpha_03_results['avg_rel_f1']:
            print(f"  • Better relationship F1: {avg_rel_f1:.3f} vs {alpha_03_results['avg_rel_f1']:.3f}")
        if avg_node_precision >= alpha_03_results['avg_node_precision']:
            print(f"  • Maintains high node precision: {avg_node_precision:.2f}")
        print()
        print("**RECOMMENDATION: Switch default alpha from 0.3 → 0.15**")
    elif avg_rel_recall > alpha_03_results['avg_rel_recall']:
        print("⚖️  ALPHA=0.15 HAS TRADE-OFFS")
        print()
        print("Pros:")
        print(f"  • Better relationship recall: {avg_rel_recall:.2f} vs {alpha_03_results['avg_rel_recall']:.2f}")
        if avg_rel_f1 > alpha_03_results['avg_rel_f1']:
            print(f"  • Better relationship F1: {avg_rel_f1:.3f} vs {alpha_03_results['avg_rel_f1']:.3f}")
        print()
        print("Cons:")
        if avg_node_precision < alpha_03_results['avg_node_precision']:
            print(f"  • Lower node precision: {avg_node_precision:.2f} vs {alpha_03_results['avg_node_precision']:.2f}")
        if avg_node_f1 < alpha_03_results['avg_node_f1']:
            print(f"  • Lower node F1: {avg_node_f1:.3f} vs {alpha_03_results['avg_node_f1']:.3f}")
        print()
        print("**RECOMMENDATION: Consider alpha=0.15 if relationship extraction is critical**")
    else:
        print("❌ ALPHA=0.3 REMAINS BETTER")
        print()
        print("**RECOMMENDATION: Keep default alpha=0.3**")

    print()

    # Save detailed results
    output = {
        'config': {
            'alpha': 0.15,
            'threshold': 0.60,
            'method': 'hybrid'
        },
        'overall_metrics': {
            'node_precision': avg_node_precision,
            'node_recall': avg_node_recall,
            'node_f1': avg_node_f1,
            'rel_precision': avg_rel_precision,
            'rel_recall': avg_rel_recall,
            'rel_f1': avg_rel_f1
        },
        'comparison_vs_alpha_03': {
            'node_precision_delta': avg_node_precision - alpha_03_results['avg_node_precision'],
            'node_f1_delta': avg_node_f1 - alpha_03_results['avg_node_f1'],
            'rel_recall_delta': avg_rel_recall - alpha_03_results['avg_rel_recall'],
            'rel_f1_delta': avg_rel_f1 - alpha_03_results['avg_rel_f1']
        },
        'subquery_results': results
    }

    output_path = "/tmp/alpha_015_all_subqueries_results.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Detailed results saved to: {output_path}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

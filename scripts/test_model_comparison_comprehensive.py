#!/usr/bin/env python3
"""
Comprehensive embedding model comparison across all 4 subqueries.

Tests pure semantic similarity (no explicit keyword help) to reveal true model performance.
Uses top_k and higher threshold for selectivity.
"""
import asyncio
import yaml
import sys
import time
import json
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


# Ground truth: VALIDATED by executing actual Cypher queries against CPG
# See /tmp/ground_truth_validation_results.json for validation details
GROUND_TRUTH = {
    "SQ1": {
        "query": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
        "expected_nodes": ["Type", "Function"],
        "expected_rels": ["CONTAINS"],
        "validation": "Verified by query: MATCH (t:Type)-[:CONTAINS]->(f:Function) WHERE t.name='WorkerFactory' AND f.name='CreateWorkers'"
    },
    "SQ2": {
        "query": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
        "expected_nodes": ["Type", "Function"],
        "expected_rels": ["CONTAINS", "CALLS"],
        "validation": "Verified - needs CONTAINS to locate declaring Type for each constructor, plus CALLS to find constructors"
    },
    "SQ3": {
        "query": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
        "expected_nodes": ["Type", "Function", "Statement"],
        "expected_rels": ["CONTAINS", "CALLS"],
        "validation": "Verified - CALLS edges are from Function (not Statement), CONTAINS for navigation"
    },
    "SQ4": {
        "query": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name",
        "expected_nodes": ["Type", "Function", "Variable"],
        "expected_rels": ["CONTAINS", "REFERENCES"],
        "validation": "Verified - needs REFERENCES to trace from Variable to constructor Functions"
    }
}


async def test_model_on_subquery(model_name: str, sq_id: str, sq_data: dict, yaml_schema: dict, server, top_k: int, threshold: float):
    """Test a single model on a single subquery."""

    # Create schema manager with this model
    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file=f"/tmp/test_comp_{model_name.replace('/', '_')}_cache.json",
        yaml_schema=yaml_schema,
        embedding_model=model_name
    )

    # Initialize if not already
    if schema_manager._reconciled_schema is None:
        await schema_manager.initialize_background()

    # Extract types with similarity scores
    start_extract = time.time()

    result = schema_manager.extract_types_from_query(
        sq_data['query'],
        similarity_threshold=threshold,
        top_k=top_k,
        method='hybrid',
        alpha=0.3,
        return_scores=True  # Get detailed similarity scores
    )

    extract_time = time.time() - start_extract

    # Calculate precision/recall
    expected_nodes = set(sq_data['expected_nodes'])
    extracted_nodes = set(result['node_types'])

    expected_rels = set(sq_data['expected_rels'])
    extracted_rels = set(result['relationship_types'])

    # Node metrics
    node_tp = len(expected_nodes & extracted_nodes)  # True positives
    node_fp = len(extracted_nodes - expected_nodes)  # False positives
    node_fn = len(expected_nodes - extracted_nodes)  # False negatives

    node_precision = node_tp / len(extracted_nodes) if extracted_nodes else 0
    node_recall = node_tp / len(expected_nodes) if expected_nodes else 0
    node_f1 = 2 * (node_precision * node_recall) / (node_precision + node_recall) if (node_precision + node_recall) > 0 else 0

    # Rel metrics
    rel_tp = len(expected_rels & extracted_rels)
    rel_fp = len(extracted_rels - expected_rels)
    rel_fn = len(expected_rels - extracted_rels)

    rel_precision = rel_tp / len(extracted_rels) if extracted_rels else 0
    rel_recall = rel_tp / len(expected_rels) if expected_rels else 0
    rel_f1 = 2 * (rel_precision * rel_recall) / (rel_precision + rel_recall) if (rel_precision + rel_recall) > 0 else 0

    return {
        'sq_id': sq_id,
        'model': model_name,
        'extract_time_ms': extract_time * 1000,
        'node_types': result['node_types'],
        'relationship_types': result['relationship_types'],
        'node_metrics': {
            'precision': node_precision,
            'recall': node_recall,
            'f1': node_f1,
            'expected': list(expected_nodes),
            'extracted': list(extracted_nodes),
            'missing': list(expected_nodes - extracted_nodes),
            'extra': list(extracted_nodes - expected_nodes)
        },
        'rel_metrics': {
            'precision': rel_precision,
            'recall': rel_recall,
            'f1': rel_f1,
            'expected': list(expected_rels),
            'extracted': list(extracted_rels),
            'missing': list(expected_rels - extracted_rels),
            'extra': list(extracted_rels - expected_rels)
        },
        'similarity_scores': {
            'node_scores': result.get('node_scores', {}),
            'rel_scores': result.get('rel_scores', {}),
            'threshold': result.get('threshold', threshold),
            'method': result.get('method', 'hybrid'),
            'alpha': result.get('alpha', 0.3)
        }
    }


async def main():
    print("=" * 100)
    print("COMPREHENSIVE EMBEDDING MODEL COMPARISON - ALL 4 SUBQUERIES")
    print("=" * 100)
    print()

    # Configuration
    models = [
        'all-MiniLM-L6-v2',
        'microsoft/codebert-base',
    ]

    top_k = 5  # Limit to top 5 per category
    threshold = 0.20  # Higher threshold for selectivity

    print(f"Configuration:")
    print(f"  Top-K: {top_k}")
    print(f"  Threshold: {threshold}")
    print(f"  Method: hybrid (alpha=0.3)")
    print()

    # Initialize server once
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    # Test each model
    all_results = []

    for model_name in models:
        print(f"\n{'='*100}")
        print(f"Testing Model: {model_name}")
        print(f"{'='*100}\n")

        # Initialize once per model
        schema_manager = DynamicSchemaManager(
            cypher_server=server,
            cache_file=f"/tmp/test_comp_{model_name.replace('/', '_')}_cache.json",
            yaml_schema=yaml_schema,
            embedding_model=model_name
        )

        print("Initializing...")
        start_init = time.time()
        await schema_manager.initialize_background()
        init_time = time.time() - start_init
        print(f"✅ Initialization: {init_time:.2f}s\n")

        # Test on all subqueries
        for sq_id, sq_data in GROUND_TRUTH.items():
            print(f"  {sq_id}: ", end="", flush=True)
            try:
                result = await test_model_on_subquery(
                    model_name, sq_id, sq_data, yaml_schema, server, top_k, threshold
                )
                all_results.append(result)

                # Quick summary
                node_f1 = result['node_metrics']['f1']
                rel_f1 = result['rel_metrics']['f1']
                print(f"Node F1={node_f1:.2f}, Rel F1={rel_f1:.2f} ✓")

            except Exception as e:
                print(f"❌ FAILED: {e}")
                import traceback
                traceback.print_exc()

    # Detailed comparison by subquery
    print("\n" + "=" * 100)
    print("DETAILED RESULTS BY SUBQUERY")
    print("=" * 100)

    for sq_id in ["SQ1", "SQ2", "SQ3", "SQ4"]:
        print(f"\n{'─'*100}")
        print(f"{sq_id}: {GROUND_TRUTH[sq_id]['query'][:80]}...")
        print(f"{'─'*100}")

        sq_results = [r for r in all_results if r['sq_id'] == sq_id]

        print(f"\nExpected:")
        print(f"  Nodes: {GROUND_TRUTH[sq_id]['expected_nodes']}")
        print(f"  Rels:  {GROUND_TRUTH[sq_id]['expected_rels']}")
        print()

        for result in sq_results:
            model_short = result['model'].split('/')[-1]
            print(f"{model_short}:")
            print(f"  Extracted Nodes ({len(result['node_types'])}): {result['node_types']}")
            print(f"  Extracted Rels  ({len(result['relationship_types'])}): {result['relationship_types']}")
            print(f"  Node F1: {result['node_metrics']['f1']:.3f} (P={result['node_metrics']['precision']:.2f}, R={result['node_metrics']['recall']:.2f})")
            print(f"  Rel F1:  {result['rel_metrics']['f1']:.3f} (P={result['rel_metrics']['precision']:.2f}, R={result['rel_metrics']['recall']:.2f})")

            if result['node_metrics']['missing']:
                print(f"  ⚠️  Missing nodes: {result['node_metrics']['missing']}")
            if result['node_metrics']['extra']:
                print(f"  ℹ️  Extra nodes: {result['node_metrics']['extra']}")
            if result['rel_metrics']['missing']:
                print(f"  ⚠️  Missing rels: {result['rel_metrics']['missing']}")
            print()

    # Aggregate metrics
    print("\n" + "=" * 100)
    print("AGGREGATE PERFORMANCE")
    print("=" * 100)
    print()

    for model_name in models:
        model_short = model_name.split('/')[-1]
        model_results = [r for r in all_results if r['model'] == model_name]

        avg_node_f1 = sum(r['node_metrics']['f1'] for r in model_results) / len(model_results)
        avg_rel_f1 = sum(r['rel_metrics']['f1'] for r in model_results) / len(model_results)
        avg_time = sum(r['extract_time_ms'] for r in model_results) / len(model_results)

        print(f"{model_short}:")
        print(f"  Average Node F1: {avg_node_f1:.3f}")
        print(f"  Average Rel F1:  {avg_rel_f1:.3f}")
        print(f"  Average Time:    {avg_time:.2f}ms")
        print()

    # Save results
    output_file = "/tmp/comprehensive_model_comparison.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"📄 Full results saved to: {output_file}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Test the new threshold (0.60) with EnrichmentDescription.
Verify it maintains perfect recall while improving precision.
"""
import asyncio
import yaml
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


# Ground truth from validated Cypher queries
GROUND_TRUTH = {
    "SQ1": {
        "query": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
        "expected_nodes": ["Type", "Function"],
        "expected_rels": ["CONTAINS"]
    },
    "SQ2": {
        "query": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
        "expected_nodes": ["Type", "Function"],
        "expected_rels": ["CONTAINS", "CALLS"]
    },
    "SQ3": {
        "query": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
        "expected_nodes": ["Type", "Function", "Statement"],
        "expected_rels": ["CONTAINS", "CALLS"]
    },
    "SQ4": {
        "query": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name",
        "expected_nodes": ["Type", "Function", "Variable"],
        "expected_rels": ["CONTAINS", "REFERENCES"]
    }
}


async def main():
    print("=" * 100)
    print("TESTING NEW THRESHOLD (0.60) WITH ENRICHMENTDESCRIPTION")
    print("=" * 100)
    print()

    # Initialize
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/test_new_threshold_cache.json",
        yaml_schema=yaml_schema,
        embedding_model='all-MiniLM-L6-v2'
    )

    await schema_manager.initialize_background()

    print("Testing with NEW default threshold (0.60)...")
    print()

    results = []
    for sq_id, sq_data in GROUND_TRUTH.items():
        # Extract using NEW default threshold (0.60)
        result = schema_manager.extract_types_from_query(
            sq_data['query']
            # No threshold specified - uses new default 0.60
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

        results.append({
            'sq_id': sq_id,
            'expected': len(expected_nodes),
            'extracted': len(extracted_nodes),
            'precision': node_precision,
            'recall': node_recall,
            'f1': node_f1,
            'node_types': result['node_types'],
            'missing': list(expected_nodes - extracted_nodes)
        })

        print(f"{sq_id}:")
        print(f"  Expected:  {', '.join(sorted(expected_nodes))}")
        print(f"  Extracted: {', '.join(result['node_types'])}")
        print(f"  Precision: {node_precision:.2f} ({node_tp}/{len(extracted_nodes)} correct)")
        print(f"  Recall:    {node_recall:.2f} ({node_tp}/{len(expected_nodes)} found)")
        print(f"  F1:        {node_f1:.3f}")

        if node_recall == 1.0 and node_precision == 1.0:
            print(f"  ✅ PERFECT!")
        elif node_recall == 1.0:
            print(f"  ✅ Perfect recall (all required found)")
        else:
            print(f"  ❌ Missing: {', '.join(expected_nodes - extracted_nodes)}")
        print()

    # Summary
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print()

    avg_precision = sum(r['precision'] for r in results) / len(results)
    avg_recall = sum(r['recall'] for r in results) / len(results)
    avg_f1 = sum(r['f1'] for r in results) / len(results)
    perfect_recall = all(r['recall'] == 1.0 for r in results)

    print(f"Average Precision: {avg_precision:.3f}")
    print(f"Average Recall:    {avg_recall:.3f}")
    print(f"Average F1:        {avg_f1:.3f}")
    print(f"Perfect Recall:    {'✅ YES' if perfect_recall else '❌ NO'}")
    print()

    if avg_precision >= 0.80 and perfect_recall:
        print("✅✅✅ SUCCESS! Threshold 0.60 is OPTIMAL! ✅✅✅")
        print()
        print("Benefits:")
        print("  • Perfect recall (100%)")
        print(f"  • High precision ({avg_precision:.0%})")
        print(f"  • Excellent F1 ({avg_f1:.3f})")
        print("  • Minimal noise for LLM")
    else:
        print("⚠️  Threshold may need adjustment")


if __name__ == "__main__":
    asyncio.run(main())

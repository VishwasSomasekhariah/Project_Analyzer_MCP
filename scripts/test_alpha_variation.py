#!/usr/bin/env python3
"""
Test different alpha values to see their impact on extraction.

Alpha controls the hybrid scoring balance:
- alpha=0.0: 100% embeddings (pure semantic)
- alpha=0.3: 70% embeddings, 30% BM25 (current optimal)
- alpha=0.5: 50% embeddings, 50% BM25 (balanced)
- alpha=0.7: 30% embeddings, 70% BM25 (keyword-heavy)
- alpha=1.0: 0% embeddings, 100% BM25 (pure keyword)
"""
import asyncio
import json
import sys

sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
import yaml


# Test with SQ1 (the problematic one with extra types)
TEST_QUERY = "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'"
EXPECTED_NODES = {"Type", "Function"}
EXPECTED_RELS = {"CONTAINS"}


async def main():
    print("=" * 100)
    print("ALPHA VARIATION TEST")
    print("=" * 100)
    print()
    print("Testing how alpha (hybrid scoring balance) affects type extraction.")
    print()
    print("Alpha values:")
    print("  0.0 = 100% embeddings, 0% BM25 (pure semantic)")
    print("  0.3 = 70% embeddings, 30% BM25 (current optimal)")
    print("  0.5 = 50% embeddings, 50% BM25 (balanced)")
    print("  0.7 = 30% embeddings, 70% BM25 (keyword-heavy)")
    print("  1.0 = 0% embeddings, 100% BM25 (pure keyword)")
    print()
    print("=" * 100)
    print()

    # Initialize once
    print("Initializing DynamicSchemaManager...")
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/alpha_variation_cache.json",
        yaml_schema=yaml_schema,
        embedding_model='all-MiniLM-L6-v2'
    )

    await schema_manager.initialize_background()
    print("✅ Initialized")
    print()

    print(f"Test Query: {TEST_QUERY}")
    print()
    print(f"Expected: {', '.join(sorted(EXPECTED_NODES))} | {', '.join(sorted(EXPECTED_RELS))}")
    print()
    print("-" * 100)
    print()

    # Test different alpha values
    alpha_values = [0.0, 0.15, 0.2, 0.3, 0.5, 0.7, 0.85, 1.0]
    results = []

    for alpha in alpha_values:
        result = schema_manager.extract_types_from_query(
            query_text=TEST_QUERY,
            similarity_threshold=0.60,
            method='hybrid',
            alpha=alpha,
            return_scores=True
        )

        extracted_nodes = set(result['node_types'])
        extracted_rels = set(result['relationship_types'])

        # Calculate metrics
        node_tp = len(EXPECTED_NODES & extracted_nodes)
        node_precision = node_tp / len(extracted_nodes) if extracted_nodes else 0
        node_recall = node_tp / len(EXPECTED_NODES) if EXPECTED_NODES else 0
        node_f1 = 2 * (node_precision * node_recall) / (node_precision + node_recall) if (node_precision + node_recall) > 0 else 0

        rel_tp = len(EXPECTED_RELS & extracted_rels)
        rel_precision = rel_tp / len(extracted_rels) if extracted_rels else 0
        rel_recall = rel_tp / len(EXPECTED_RELS) if EXPECTED_RELS else 0

        results.append({
            'alpha': alpha,
            'node_types': result['node_types'],
            'relationship_types': result['relationship_types'],
            'node_scores': result.get('node_scores', {}),
            'rel_scores': result.get('rel_scores', {}),
            'metrics': {
                'node_precision': node_precision,
                'node_recall': node_recall,
                'node_f1': node_f1,
                'rel_precision': rel_precision,
                'rel_recall': rel_recall
            }
        })

        config_label = {
            0.0: "pure semantic",
            0.15: "very semantic",
            0.2: "mostly semantic",
            0.3: "current optimal",
            0.5: "balanced",
            0.7: "keyword-heavy",
            0.85: "very keyword",
            1.0: "pure keyword"
        }.get(alpha, "hybrid")

        print(f"Alpha = {alpha:.2f} ({config_label}):")
        print(f"  Nodes: {', '.join(result['node_types'])}")
        print(f"  Rels:  {', '.join(result['relationship_types']) if result['relationship_types'] else '(none)'}")
        print(f"  Node Precision: {node_precision:.2f}, Recall: {node_recall:.2f}, F1: {node_f1:.3f}")
        print(f"  Rel Precision: {rel_precision:.2f}, Recall: {rel_recall:.2f}")

        if node_precision == 1.0 and node_recall == 1.0:
            print(f"  ✅ PERFECT NODE EXTRACTION!")
        elif node_recall == 1.0:
            print(f"  ✅ Perfect recall, but extra: {', '.join(extracted_nodes - EXPECTED_NODES)}")
        else:
            print(f"  ❌ Missing: {', '.join(EXPECTED_NODES - extracted_nodes)}")
        print()

    # Summary comparison
    print("=" * 100)
    print("COMPARISON TABLE")
    print("=" * 100)
    print()

    print(f"{'Alpha':<8} {'Config':<20} {'Extracted Nodes':<40} {'Precision':<10} {'Recall':<8} {'F1':<8}")
    print("-" * 100)

    for r in results:
        config_name = {
            0.0: "pure semantic",
            0.15: "very semantic",
            0.2: "mostly semantic",
            0.3: "current optimal",
            0.5: "balanced",
            0.7: "keyword-heavy",
            0.85: "very keyword",
            1.0: "pure keyword"
        }.get(r['alpha'], "hybrid")

        nodes_str = ', '.join(r['node_types'])[:40]
        print(f"{r['alpha']:<8.1f} {config_name:<20} {nodes_str:<40} {r['metrics']['node_precision']:<10.2f} {r['metrics']['node_recall']:<8.2f} {r['metrics']['node_f1']:<8.3f}")

    print()

    # Score changes across alpha values
    print("=" * 100)
    print("SCORE CHANGES ACROSS ALPHA VALUES")
    print("=" * 100)
    print()

    # Track specific types
    key_types = ['Type', 'Function', 'Project', 'File', 'Namespace', 'CONTAINS', 'CALLS']

    print(f"{'Type':<15} {'α=0.0':<10} {'α=0.15':<10} {'α=0.3':<10} {'α=0.5':<10} {'α=0.85':<10} {'α=1.0':<10} {'Trend':<20}")
    print("-" * 100)

    for key_type in key_types:
        scores = []
        for r in results:
            if key_type in r['node_scores']:
                scores.append(r['node_scores'][key_type]['score'])
            elif key_type in r['rel_scores']:
                scores.append(r['rel_scores'][key_type]['score'])
            else:
                scores.append(None)

        # Get specific alpha values for comparison
        score_0 = next((r['node_scores'].get(key_type, r['rel_scores'].get(key_type, {})).get('score', 0) for r in results if r['alpha'] == 0.0), 0)
        score_015 = next((r['node_scores'].get(key_type, r['rel_scores'].get(key_type, {})).get('score', 0) for r in results if r['alpha'] == 0.15), 0)
        score_03 = next((r['node_scores'].get(key_type, r['rel_scores'].get(key_type, {})).get('score', 0) for r in results if r['alpha'] == 0.3), 0)
        score_05 = next((r['node_scores'].get(key_type, r['rel_scores'].get(key_type, {})).get('score', 0) for r in results if r['alpha'] == 0.5), 0)
        score_085 = next((r['node_scores'].get(key_type, r['rel_scores'].get(key_type, {})).get('score', 0) for r in results if r['alpha'] == 0.85), 0)
        score_10 = next((r['node_scores'].get(key_type, r['rel_scores'].get(key_type, {})).get('score', 0) for r in results if r['alpha'] == 1.0), 0)

        # Determine trend
        if score_10 > score_0:
            trend = "↑ BM25 helps"
        elif score_0 > score_10:
            trend = "↓ Embeddings better"
        else:
            trend = "→ No change"

        print(f"{key_type:<15} {score_0:<10.4f} {score_015:<10.4f} {score_03:<10.4f} {score_05:<10.4f} {score_085:<10.4f} {score_10:<10.4f} {trend:<20}")

    print()

    # Recommendations
    print("=" * 100)
    print("RECOMMENDATIONS")
    print("=" * 100)
    print()

    best_f1 = max(results, key=lambda r: r['metrics']['node_f1'])
    best_precision = max(results, key=lambda r: r['metrics']['node_precision'])
    best_recall = max(results, key=lambda r: r['metrics']['node_recall'])

    print(f"Best F1 Score: alpha={best_f1['alpha']} (F1={best_f1['metrics']['node_f1']:.3f})")
    print(f"Best Precision: alpha={best_precision['alpha']} (Precision={best_precision['metrics']['node_precision']:.2f})")
    print(f"Best Recall: alpha={best_recall['alpha']} (Recall={best_recall['metrics']['node_recall']:.2f})")
    print()

    # Save results
    output_path = "/tmp/alpha_variation_results.json"
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Detailed results saved to: {output_path}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

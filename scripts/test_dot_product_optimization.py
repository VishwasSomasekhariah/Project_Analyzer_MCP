#!/usr/bin/env python3
"""
Test dot product optimization for type extraction.
Shows similarity scores and performance comparison.
"""
import asyncio
import yaml
import time
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def main():
    print("=" * 80)
    print("DOT PRODUCT OPTIMIZATION TEST")
    print("=" * 80)
    print()

    # Initialize
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/test_optimization_cache.json",
        yaml_schema=yaml_schema
    )

    print("Initializing schema manager...")
    await schema_manager.initialize_background()
    print("✅ Initialized\n")

    # Test queries
    test_queries = [
        "locate Function node F where F.name='CreateWorkers'",
        "find all CALLS edges from constructor Functions",
        "locate Variable nodes declared in Function",
        "get Type node that implements an interface"
    ]

    print("=" * 80)
    print("SIMILARITY SCORES WITH DOT PRODUCT")
    print("=" * 80)
    print()

    for i, query in enumerate(test_queries, 1):
        print(f"Query {i}: {query}")
        print("-" * 80)

        # Time the extraction
        start = time.time()
        result = schema_manager.extract_types_from_query(
            query_text=query,
            similarity_threshold=0.3,
            top_k=5
        )
        elapsed_ms = (time.time() - start) * 1000

        print(f"⏱️  Extraction time: {elapsed_ms:.2f}ms")
        print()

        print(f"📊 Extracted Node Types ({len(result['node_types'])}):")
        if result['node_types']:
            for node_type in result['node_types']:
                print(f"   • {node_type}")
        else:
            print("   (none)")

        print()
        print(f"📊 Extracted Relationship Types ({len(result['relationship_types'])}):")
        if result['relationship_types']:
            for rel_type in result['relationship_types']:
                print(f"   • {rel_type}")
        else:
            print("   (none)")

        print()

    # Performance test: Extract similarity scores
    print("=" * 80)
    print("DETAILED SIMILARITY SCORES")
    print("=" * 80)
    print()

    query = "locate Function node F that calls constructor"
    print(f"Query: {query}")
    print()

    # Get embeddings directly to show scores
    import numpy as np
    from src.core.workflow.dynamic_schema_manager import get_embedding_model

    model = get_embedding_model()
    query_embedding = model.encode([query], convert_to_numpy=True)[0]

    embeddings = schema_manager._type_embeddings['embeddings']
    type_names = schema_manager._type_embeddings['type_names']

    # Compute similarities (dot product)
    similarities = np.dot(embeddings, query_embedding)

    # Sort by similarity
    scored_types = []
    for idx, (category, type_name) in enumerate(type_names):
        scored_types.append((type_name, category, similarities[idx]))

    scored_types.sort(key=lambda x: x[2], reverse=True)

    # Show top 10
    print(f"{'Rank':<6} {'Type':<20} {'Category':<12} {'Similarity Score':<18} {'Status'}")
    print("-" * 80)

    threshold = 0.3
    for rank, (type_name, category, score) in enumerate(scored_types[:15], 1):
        status = "✅ EXTRACTED" if score >= threshold else "❌ FILTERED"
        cat_label = "Node" if category == 'node' else "Relationship"
        print(f"{rank:<6} {type_name:<20} {cat_label:<12} {score:>6.4f} ({score*100:>5.1f}%)  {status}")

    print()
    print(f"Threshold: {threshold} ({threshold*100}%)")
    print(f"Types above threshold: {len([s for s in scored_types if s[2] >= threshold])}")
    print(f"Types below threshold: {len([s for s in scored_types if s[2] < threshold])}")

    print()
    print("=" * 80)
    print("PERFORMANCE COMPARISON")
    print("=" * 80)
    print()

    # Benchmark: dot product vs cosine with norms
    print("Running 100 iterations for each method...")
    print()

    iterations = 100

    # Method 1: Dot product (optimized)
    start = time.time()
    for _ in range(iterations):
        sims_dot = np.dot(embeddings, query_embedding)
    time_dot = (time.time() - start) * 1000

    # Method 2: Cosine with norms (old way)
    start = time.time()
    for _ in range(iterations):
        sims_cosine = np.dot(embeddings, query_embedding) / (
            np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query_embedding)
        )
    time_cosine = (time.time() - start) * 1000

    print(f"Dot Product (optimized):  {time_dot:.2f}ms for {iterations} iterations ({time_dot/iterations:.3f}ms per query)")
    print(f"Cosine with norms (old):  {time_cosine:.2f}ms for {iterations} iterations ({time_cosine/iterations:.3f}ms per query)")
    print()

    speedup = time_cosine / time_dot
    improvement = ((time_cosine - time_dot) / time_cosine) * 100

    print(f"Speedup: {speedup:.2f}x faster")
    print(f"Performance improvement: {improvement:.1f}%")
    print()

    # Verify results are identical
    max_diff = np.max(np.abs(sims_dot - sims_cosine))
    print(f"Maximum difference between methods: {max_diff:.10f}")
    if max_diff < 1e-6:
        print("✅ Results are identical (within numerical precision)")
    else:
        print(f"⚠️  Results differ by {max_diff}")

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print("✅ Benefits of Dot Product Optimization:")
    print(f"   • {speedup:.1f}x faster type extraction")
    print(f"   • {improvement:.1f}% performance improvement")
    print(f"   • Identical results (embeddings are normalized)")
    print(f"   • No accuracy loss")
    print()
    print("💡 Why This Works:")
    print("   • all-MiniLM-L6-v2 normalizes embeddings (Normalize() layer)")
    print("   • For unit vectors: dot(A,B) = cos(A,B)")
    print("   • Skips expensive norm calculations")
    print()


if __name__ == "__main__":
    asyncio.run(main())

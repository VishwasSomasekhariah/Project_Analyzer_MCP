#!/usr/bin/env python3
"""
Debug why Type node is not being extracted for SQ1.
"""
import asyncio
import yaml
import sys
import numpy as np
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def main():
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/debug_type_cache.json",
        yaml_schema=yaml_schema
    )

    print("Initializing...")
    await schema_manager.initialize_background()
    print()

    subquery = "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'"

    print("=" * 80)
    print("DEBUGGING TYPE EXTRACTION")
    print("=" * 80)
    print(f"Subquery: {subquery}")
    print()

    # Check with current defaults (threshold=0.15, alpha=0.3)
    print("Test 1: Current defaults (threshold=0.15, alpha=0.3)")
    result = schema_manager.extract_types_from_query(
        subquery,
        similarity_threshold=0.15,
        alpha=0.3,
        method='hybrid',
        top_k=10  # Increase to see more
    )
    print(f"  Extracted nodes: {result['node_types']}")
    print(f"  Type in list: {'Type' in result['node_types']}")
    print()

    # Check with lower threshold
    print("Test 2: Lower threshold (threshold=0.10, alpha=0.3)")
    result2 = schema_manager.extract_types_from_query(
        subquery,
        similarity_threshold=0.10,
        alpha=0.3,
        method='hybrid',
        top_k=10
    )
    print(f"  Extracted nodes: {result2['node_types']}")
    print(f"  Type in list: {'Type' in result2['node_types']}")
    print()

    # Check with even lower threshold
    print("Test 3: Very low threshold (threshold=0.05, alpha=0.3)")
    result3 = schema_manager.extract_types_from_query(
        subquery,
        similarity_threshold=0.05,
        alpha=0.3,
        method='hybrid',
        top_k=10
    )
    print(f"  Extracted nodes: {result3['node_types']}")
    print(f"  Type in list: {'Type' in result3['node_types']}")
    print()

    # Check raw scores to see what Type is scoring
    print("=" * 80)
    print("RAW SIMILARITY SCORES FOR NODE TYPES")
    print("=" * 80)

    # Access internal methods to get scores
    from src.mcp.embedding_manager import get_embedding_model
    model = get_embedding_model()

    query_embedding = model.encode([subquery], convert_to_numpy=True)[0]

    # Get embeddings from schema manager
    embeddings = schema_manager._type_embeddings
    type_names = schema_manager._type_names

    # Calculate both BM25 and embedding scores
    bm25_scores = schema_manager._bm25_scorer.score(subquery)
    embedding_raw = np.dot(embeddings, query_embedding)

    # Normalize embeddings
    embedding_normalized = (embedding_raw - embedding_raw.min()) / (embedding_raw.max() - embedding_raw.min() + 1e-10)

    # Hybrid scores
    alpha = 0.3
    hybrid_scores = alpha * bm25_scores + (1 - alpha) * embedding_normalized

    # Find Type node scores
    print(f"\nScores for all node types (threshold=0.15, top_k=10):")
    print(f"{'Type Name':<20} {'BM25':>10} {'Embedding':>12} {'Hybrid':>10} {'Above 0.15?'}")
    print("-" * 75)

    for i, type_name in enumerate(type_names):
        if i < len(embeddings):  # Node types
            above_threshold = "✓" if hybrid_scores[i] >= 0.15 else "✗"
            print(f"{type_name:<20} {bm25_scores[i]:>10.4f} {embedding_normalized[i]:>12.4f} {hybrid_scores[i]:>10.4f} {above_threshold}")

    print()
    print("=" * 80)

asyncio.run(main())

#!/usr/bin/env python3
"""
Debug why Type is not extracted for SQ1 despite being explicitly mentioned.
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
        cache_file="/tmp/debug_type_score.json",
        yaml_schema=yaml_schema
    )

    print("Initializing...")
    await schema_manager.initialize_background()
    print()

    subquery = "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'"

    print("=" * 80)
    print("DEBUGGING TYPE EXTRACTION FOR SQ1")
    print("=" * 80)
    print(f"Subquery: {subquery}")
    print()

    # Access embeddings
    from src.core.workflow.dynamic_schema_manager import get_embedding_model
    model = get_embedding_model()

    query_embedding = model.encode([subquery], convert_to_numpy=True)[0]

    embeddings = schema_manager._type_embeddings['embeddings']
    type_names = schema_manager._type_embeddings['type_names']

    # BM25 scores
    bm25_scores = schema_manager._bm25_scorer.score(subquery)

    # Embedding scores (raw)
    embedding_raw = np.dot(embeddings, query_embedding)

    # Normalize embeddings
    embedding_normalized = (embedding_raw - embedding_raw.min()) / (embedding_raw.max() - embedding_raw.min() + 1e-10)

    # Hybrid scores (alpha=0.3)
    alpha = 0.3
    hybrid_scores = alpha * bm25_scores + (1 - alpha) * embedding_normalized

    # Find Type node
    print("SCORES FOR NODE TYPES:")
    print(f"{'Type Name':<20} {'BM25':>10} {'Embedding':>12} {'Hybrid':>10} {'> 0.15?'}")
    print("-" * 75)

    for i, (category, type_name) in enumerate(type_names):
        if category == 'node':
            above = "✓ YES" if hybrid_scores[i] >= 0.15 else "✗ NO"
            highlight = ">>>" if type_name == 'Type' else "   "
            print(f"{highlight} {type_name:<17} {bm25_scores[i]:>10.4f} {embedding_normalized[i]:>12.4f} {hybrid_scores[i]:>10.4f} {above}")

    print()
    print("=" * 80)

asyncio.run(main())

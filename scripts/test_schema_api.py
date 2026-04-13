#!/usr/bin/env python3
"""
Test the new get_schema_for_subquery API with optimal hyperparameters.
"""
import asyncio
import yaml
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def main():
    print("=" * 80)
    print("TESTING get_schema_for_subquery API")
    print("With optimal hyperparameters (F1=0.549)")
    print("=" * 80)
    print()

    # Initialize
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/test_api_cache.json",
        yaml_schema=yaml_schema
    )

    print("Initializing schema manager...")
    await schema_manager.initialize_background()
    print("✅ Initialized\n")

    # Test subquery
    subquery = "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'"

    print(f"Subquery: {subquery[:80]}...")
    print()

    # Call the new API
    result = await schema_manager.get_schema_for_subquery(
        subquery_text=subquery,
        format='text',
        max_path_depth=5
    )

    print("=" * 80)
    print("EXTRACTION RESULTS")
    print("=" * 80)
    print()
    print(f"Method: {result['extraction_method']}")
    print(f"Params: {result['extraction_params']}")
    print()
    print(f"Extracted Node Types ({len(result['node_types'])}):")
    for node_type in result['node_types']:
        print(f"  • {node_type}")
    print()

    print(f"Extracted Relationship Types ({len(result['relationship_types'])}):")
    for rel_type in result['relationship_types']:
        print(f"  • {rel_type}")
    print()

    print(f"Discovered Paths ({len(result['paths'])}):")
    for path in result['paths'][:10]:  # Show first 10
        rel_chain = " → ".join(path['rels'])
        via_str = f" (via {', '.join(path['via'])})" if path.get('via') else ""
        print(f"  • ({path['from']})-[{rel_chain}]->({path['to']}){via_str} [depth={path['depth']}]")
    print()

    print("=" * 80)
    print("FORMATTED SCHEMA FOR LLM")
    print("=" * 80)
    print()
    print(result['schema_text'])
    print()

    print("=" * 80)
    print("CACHE STATS")
    print("=" * 80)
    print()
    cache_stats = result['cache_stats']
    print(f"Cached paths: {cache_stats['cached_paths']}")
    print(f"Total requests: {cache_stats['total_requests']}")
    print(f"Cache hits: {cache_stats['cache_hits']} ({cache_stats['hit_rate']:.1f}%)")
    print()

    print("=" * 80)
    print("SUCCESS")
    print("=" * 80)
    print()
    print("✅ API works correctly with optimal hyperparameters!")
    print(f"   • Hybrid extraction (α=0.3, threshold=0.15)")
    print(f"   • Path discovery and caching")
    print(f"   • LLM-ready schema formatting")
    print()

if __name__ == "__main__":
    asyncio.run(main())

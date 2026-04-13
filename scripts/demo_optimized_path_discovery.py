#!/usr/bin/env python3
"""
Optimized path discovery with relationship filtering.
Demonstrates the performance difference between:
- Unfiltered path discovery (discovers ALL relationships)
- Filtered path discovery (only extracted relationships)
"""
import asyncio
import json
import yaml
import sys
from datetime import datetime
sys.path.insert(0, '/opt/genpod')

from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from src.core.cypher_server_service import CypherServerService

# Example decomposed query
decomposed_query = {
    "user_query": "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?",
    "intent": "lookup",
    "premises": [
        "WorkerFactory.CreateWorkers exists as a Function node",
        "Object instantiation is represented via CALLS edges to constructor functions",
        "Classes are Type nodes"
    ],
    "subqueries": [
        {
            "id": 1,
            "text": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
            "dependencies": []
        }
    ]
}

async def main():
    print("=" * 80)
    print("OPTIMIZED PATH DISCOVERY - WITH RELATIONSHIP FILTERING")
    print("=" * 80)
    print()

    # Load YAML schema
    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    # Initialize cypher server
    cypher_server = CypherServerService(config_file_path="neo4j_config.json")
    await cypher_server.start()

    # Initialize schema manager
    schema_manager = DynamicSchemaManager(
        cypher_server=cypher_server,
        yaml_schema=yaml_schema,
        cache_file="/tmp/optimized_cache.json"
    )

    await schema_manager.initialize_background()

    print("\n" + "=" * 80)
    print("COMPARISON TEST: UNFILTERED vs FILTERED PATH DISCOVERY")
    print("=" * 80)
    print()

    # Test subquery
    subquery = decomposed_query['subqueries'][0]
    premises_text = "\n".join(f"- {p}" for p in decomposed_query['premises'])
    combined_text = f"Premises:\n{premises_text}\n\nSubquery:\n{subquery['text']}"

    # Extract types
    extracted = schema_manager.extract_types_from_query(combined_text)

    print(f"🎯 EXTRACTED FROM QUERY:")
    print(f"   Node types: {extracted['node_types']}")
    print(f"   Relationship types: {extracted['relationship_types']}")
    print()

    # Pick one source→target pair for testing
    source = "Function"
    target = "Type"

    print(f"{'─' * 80}")
    print(f"TEST 1: UNFILTERED PATH DISCOVERY (current approach)")
    print(f"{'─' * 80}")
    print(f"Source: {source}, Target: {target}")
    print(f"Relationship filter: NONE (discovers ALL relationships)")
    print(f"Max depth: 3")
    print()

    start = datetime.now()
    unfiltered_paths = await schema_manager._discover_path_on_demand(
        source, target,
        relationship_types=None,  # No filter - discover ALL
        max_depth=3
    )
    unfiltered_time = (datetime.now() - start).total_seconds() * 1000

    print(f"✅ Found {len(unfiltered_paths)} path patterns in {unfiltered_time:.1f}ms")
    print(f"\nPaths discovered:")
    for i, path in enumerate(unfiltered_paths[:5], 1):
        rels = ' → '.join(path['rels'])
        via = f" (via {', '.join(path['via'])})" if path['via'] else ""
        print(f"   {i}. {rels}{via} [depth={path['depth']}, count={path['count']}]")
    if len(unfiltered_paths) > 5:
        print(f"   ... and {len(unfiltered_paths) - 5} more")

    # Get unique relationships in unfiltered paths
    unfiltered_rels = set()
    for path in unfiltered_paths:
        unfiltered_rels.update(path['rels'])
    print(f"\n   Relationships in paths: {sorted(unfiltered_rels)}")
    print()

    print(f"{'─' * 80}")
    print(f"TEST 2: FILTERED PATH DISCOVERY (optimized approach)")
    print(f"{'─' * 80}")
    print(f"Source: {source}, Target: {target}")
    print(f"Relationship filter: {extracted['relationship_types']}")
    print(f"Max depth: 5 (adaptive - APOC stops early if paths found)")
    print()

    start = datetime.now()
    filtered_paths = await schema_manager._discover_path_on_demand(
        source, target,
        relationship_types=extracted['relationship_types'],  # Filter by extracted!
        max_depth=5  # Higher max, but APOC stops early
    )
    filtered_time = (datetime.now() - start).total_seconds() * 1000

    print(f"✅ Found {len(filtered_paths)} path patterns in {filtered_time:.1f}ms")
    print(f"\nPaths discovered:")
    for i, path in enumerate(filtered_paths[:5], 1):
        rels = ' → '.join(path['rels'])
        via = f" (via {', '.join(path['via'])})" if path['via'] else ""
        print(f"   {i}. {rels}{via} [depth={path['depth']}, count={path['count']}]")
    if len(filtered_paths) > 5:
        print(f"   ... and {len(filtered_paths) - 5} more")

    # Get unique relationships in filtered paths
    filtered_rels = set()
    for path in filtered_paths:
        filtered_rels.update(path['rels'])
    print(f"\n   Relationships in paths: {sorted(filtered_rels)}")
    print()

    print("=" * 80)
    print("PERFORMANCE COMPARISON")
    print("=" * 80)
    print()
    print(f"Unfiltered (discover all relationships):")
    print(f"   • Time: {unfiltered_time:.1f}ms")
    print(f"   • Paths found: {len(unfiltered_paths)}")
    print(f"   • Relationships: {sorted(unfiltered_rels)}")
    print()
    print(f"Filtered (only extracted relationships):")
    print(f"   • Time: {filtered_time:.1f}ms")
    print(f"   • Paths found: {len(filtered_paths)}")
    print(f"   • Relationships: {sorted(filtered_rels)}")
    print()

    speedup = unfiltered_time / filtered_time if filtered_time > 0 else 0
    print(f"⚡ Speedup: {speedup:.2f}x faster with filtering")
    print()

    print("=" * 80)
    print("ANALYSIS")
    print("=" * 80)
    print()

    # Check which extracted relationships appear in paths
    extracted_rels = set(extracted['relationship_types'])
    matched = filtered_rels.intersection(extracted_rels)
    unmatched_extracted = extracted_rels - filtered_rels
    unmatched_in_paths = filtered_rels - extracted_rels

    print(f"📊 Extracted relationships: {sorted(extracted_rels)}")
    print(f"✅ Found in filtered paths: {sorted(matched)}")
    if unmatched_extracted:
        print(f"⚠️  Extracted but not found: {sorted(unmatched_extracted)}")
        print(f"   → These relationships don't exist between {source} and {target} in this CPG")
    if unmatched_in_paths:
        print(f"❓ In paths but not extracted: {sorted(unmatched_in_paths)}")
        print(f"   → This shouldn't happen with filtering!")
    print()

    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()
    print("✅ USE FILTERED PATH DISCOVERY:")
    print("   1. Faster APOC traversal (only explores relevant edges)")
    print("   2. Returns only semantically relevant paths")
    print("   3. Cache stores paths that match query intent")
    print("   4. Use adaptive depth (e.g., max=5, APOC stops early)")
    print()
    print("❌ DON'T USE UNFILTERED:")
    print("   1. Slower (traverses all relationship types)")
    print("   2. Returns paths with relationships not mentioned in query")
    print("   3. Cache pollution with irrelevant paths")
    print()

    await cypher_server.stop()

if __name__ == "__main__":
    asyncio.run(main())

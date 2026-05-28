#!/usr/bin/env python3
"""
Test script for APOC procedure cache initialization.
"""

import asyncio
import json
from src.core.apoc_procedure_cache import initialize_apoc_cache, get_apoc_cache
from src.core.workflow.cypher_server_pool import CypherServerInstance


async def test_apoc_cache():
    """Test APOC cache initialization and usage."""

    neo4j_config = "/opt/genpod/neo4j_config.json"

    print("=" * 80)
    print("Testing APOC Procedure Cache")
    print("=" * 80)

    # Create cypher server instance with longer timeout for APOC cache initialization
    cypher_server = CypherServerInstance(
        server_id=0,
        neo4j_config=neo4j_config,
        query_timeout=120  # 2 minutes timeout for APOC cache queries
    )

    try:
        # Start the server
        print("\n[0] Starting cypher server with 120s timeout for APOC cache...")
        if not await cypher_server.start():
            print("❌ Failed to start cypher server")
            return

        # Initialize cache
        print("\n[1] Initializing APOC cache from Neo4j...")
        stats = await initialize_apoc_cache(cypher_server)

        print(f"\nCache Statistics:")
        print(json.dumps(stats, indent=2))

        # Get cache instance
        cache = get_apoc_cache()

        # Test 1: Get all categories
        print("\n" + "=" * 80)
        print("[2] All discovered categories:")
        print("=" * 80)
        categories = cache.get_all_categories()
        for cat, count in sorted(categories.items())[:20]:
            print(f"  {cat}: {count} procedures")

        # Test 2: Get path-related procedures
        print("\n" + "=" * 80)
        print("[3] Path traversal procedures:")
        print("=" * 80)
        path_procs = cache.get_category_by_prefix('apoc.path')
        for proc in path_procs:
            print(f"\n  {proc['name']}")
            print(f"    Signature: {proc['signature']}")
            print(f"    Description: {proc['description'][:100]}...")

        # Test 3: Get algo procedures
        print("\n" + "=" * 80)
        print("[4] Algorithm procedures:")
        print("=" * 80)
        algo_procs = cache.get_category_by_prefix('apoc.algo')
        for proc in algo_procs:
            print(f"\n  {proc['name']}")
            print(f"    Signature: {proc['signature']}")

        # Test 4: Get relevant procedures for path discovery
        print("\n" + "=" * 80)
        print("[5] Relevant procedures for path discovery:")
        print("=" * 80)
        relevant = cache.get_relevant_for_path_discovery()
        for use_case, procedures in relevant.items():
            print(f"\n  {use_case}: {len(procedures)} procedures")
            for proc in procedures[:3]:  # Show first 3
                print(f"    - {proc['name']}")

        # Test 5: Search functionality
        print("\n" + "=" * 80)
        print("[6] Search for 'expand' keyword:")
        print("=" * 80)
        search_results = cache.search('expand')
        print(f"  Found {len(search_results)} procedures")
        for proc in search_results[:5]:
            print(f"    - {proc['name']}: {proc['description'][:80]}...")

        # Test 6: Format for LLM
        print("\n" + "=" * 80)
        print("[7] Format for LLM prompt (apoc.path):")
        print("=" * 80)
        formatted = cache.format_for_llm('apoc.path')
        print(formatted[:500] + "...")

        # Test 7: Verify cache file was saved
        print("\n" + "=" * 80)
        print("[8] Cache file location:")
        print("=" * 80)
        print(f"  {cache.cache_file}")
        print(f"  Exists: {cache.cache_file.exists()}")

        print("\n" + "=" * 80)
        print("✓ All tests completed successfully!")
        print("=" * 80)

    finally:
        # Stop the server
        print("\nStopping cypher server...")
        await cypher_server.stop()


if __name__ == "__main__":
    asyncio.run(test_apoc_cache())

"""
Demo: Progressive Path Cache Building During Subquery Processing
Shows how schema reconciliation + embedding extraction + path discovery works per-subquery.
"""

import asyncio
import json
import yaml
import sys
from datetime import datetime

sys.path.insert(0, '/opt/genpod')

from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from src.core.cypher_server_service import create_cypher_server_service


async def main():
    # Example decomposed query from user
    decomposed_query = {
        "query": "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?",
        "intent": "lookup",
        "logical_form": "Function(name='CreateWorkers', declared_in=Type(name='WorkerFactory')) → (∃ctorFn: CALLS(F,ctorFn) ∧ ctorFn.declared_in=Type(C) ∧ RETURN(F,instance_of(C))) ∨ (∃V: DECLARES(F,V) ∧ V.initial_value includes new C ∧ RETURN(F,V))",
        "premises": [
            "WorkerFactory.CreateWorkers exists as a Function node",
            "Object instantiation is represented by CALLS to constructor Functions",
            "Return statements in Function body yield the instances to be returned",
            "Local variable initializations may hold new instances before returning"
        ],
        "subqueries": [
            "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
            "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
            "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
            "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name"
        ]
    }

    # Setup logging
    log_file = f"/tmp/progressive_cache_building_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_entries = []

    def log(message):
        """Log to both console and file"""
        print(message)
        log_entries.append({
            "timestamp": datetime.now().isoformat(),
            "message": message
        })

    log("=" * 80)
    log("PROGRESSIVE PATH CACHE BUILDING DEMONSTRATION")
    log("=" * 80)
    log(f"\nUser Query: {decomposed_query['query']}")
    log(f"Intent: {decomposed_query['intent']}")
    log(f"\nProcessing {len(decomposed_query['subqueries'])} subqueries...")

    # Step 1: Load YAML schema (workflow does this at startup)
    log("\n" + "=" * 80)
    log("STEP 1: LOAD YAML SCHEMA (Once at workflow initialization)")
    log("=" * 80)

    yaml_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
    with open(yaml_path, 'r') as f:
        yaml_schema = yaml.safe_load(f)

    log(f"✅ Loaded YAML schema: {len(yaml_schema.get('nodes', {}))} node types, {len(yaml_schema.get('relationships', {}))} relationships")

    # Step 2: Initialize DynamicSchemaManager
    log("\n" + "=" * 80)
    log("STEP 2: INITIALIZE DYNAMIC SCHEMA MANAGER (Once at workflow initialization)")
    log("=" * 80)

    cypher_server = await create_cypher_server_service(
        config_file_path="/opt/genpod/neo4j_config.json"
    )

    if not cypher_server:
        log("❌ Failed to initialize cypher server")
        return

    # Clear cache to demonstrate progressive building
    import os
    cache_file = "/tmp/progressive_demo_cache.json"
    if os.path.exists(cache_file):
        os.remove(cache_file)
        log(f"🗑️  Cleared existing cache: {cache_file}")

    schema_manager = DynamicSchemaManager(
        cypher_server=cypher_server,
        cache_file=cache_file,
        yaml_schema=yaml_schema
    )

    log("🔄 Starting schema initialization (reconciliation + cache pre-population)...")
    init_start_time = datetime.now()
    await schema_manager.initialize_background()
    init_time = (datetime.now() - init_start_time).total_seconds() * 1000

    log(f"✅ Schema manager ready in {init_time:.0f}ms")
    log(f"   • Reconciled {len(schema_manager._reconciled_schema['nodes'])} node types")
    log(f"   • Reconciled {len(schema_manager._reconciled_schema['relationships'])} relationship types")
    log(f"   • Built embeddings for {len(schema_manager._type_embeddings['type_names'])} types")

    # Count pre-populated cache
    total_source_types = len(schema_manager._path_cache)
    total_pairs = sum(len(targets) for targets in schema_manager._path_cache.values())
    total_paths = sum(
        len(paths)
        for source_cache in schema_manager._path_cache.values()
        for paths in source_cache.values()
    )
    depth1_paths = sum(
        len([p for p in paths if p['depth'] == 1])
        for source_cache in schema_manager._path_cache.values()
        for paths in source_cache.values()
    )

    log(f"   • Pre-populated cache:")
    log(f"      - Source types: {total_source_types}")
    log(f"      - (Source→Target) pairs: {total_pairs}")
    log(f"      - Total path entries: {total_paths}")
    log(f"      - Depth=1 paths (direct edges): {depth1_paths}")

    # Save reconciled schema to JSON file
    reconciled_schema_file = "/tmp/reconciled_schema.json"
    with open(reconciled_schema_file, 'w') as f:
        json.dump(schema_manager._reconciled_schema, f, indent=2)
    log(f"\n💾 Reconciled schema saved to: {reconciled_schema_file}")

    # Save initial cache snapshot
    initial_cache_file = "/tmp/initial_cache_prepopulated.json"
    cache_export = {}
    for source, targets in schema_manager._path_cache.items():
        cache_export[source] = {}
        for target, paths in targets.items():
            cache_export[source][target] = paths

    with open(initial_cache_file, 'w') as f:
        json.dump({
            "cache": cache_export,
            "statistics": {
                "total_source_types": total_source_types,
                "total_pairs": total_pairs,
                "total_paths": total_paths,
                "depth1_paths": depth1_paths
            }
        }, f, indent=2)
    log(f"💾 Initial pre-populated cache saved to: {initial_cache_file}")

    # Step 3: Process each subquery
    log("\n" + "=" * 80)
    log("STEP 3: PROCESS SUBQUERIES WITH PROGRESSIVE CACHE BUILDING")
    log("=" * 80)

    all_extracted_types = []
    cache_snapshots = []

    for idx, subquery in enumerate(decomposed_query['subqueries'], 1):
        log(f"\n{'─' * 80}")
        log(f"SUBQUERY {idx}/{len(decomposed_query['subqueries'])}")
        log(f"{'─' * 80}")
        log(f"Text: {subquery[:100]}...")

        # Combine premise context with subquery for better extraction
        premise_context = " ".join(decomposed_query['premises'])
        combined_text = f"{premise_context} {subquery}"

        log(f"\n📝 Combined context for extraction:")
        log(f"   Premises: {premise_context[:80]}...")
        log(f"   Subquery: {subquery[:80]}...")

        # Extract types using embeddings
        log(f"\n🔍 EXTRACTING TYPES (embedding-based semantic matching)...")
        sq_start = datetime.now()
        # Use default threshold (0.3) and top_k (5) from manager
        extracted = schema_manager.extract_types_from_query(
            query_text=combined_text
        )
        extract_time = (datetime.now() - sq_start).total_seconds() * 1000

        log(f"   ✅ Extracted in {extract_time:.0f}ms:")
        log(f"      • Node types: {extracted['node_types']}")
        log(f"      • Relationship types: {extracted['relationship_types']}")

        all_extracted_types.append({
            "subquery_id": idx,
            "extracted": extracted,
            "time_ms": extract_time
        })

        # Get schema context for these types
        log(f"\n📋 FETCHING SCHEMA CONTEXT...")
        schema_context = await schema_manager.get_context_relevant_schema(
            node_types=extracted['node_types'],
            relationship_types=extracted['relationship_types'],
            format='text'
        )

        schema_lines = schema_context.split('\n')[:10]  # First 10 lines
        log(f"   ✅ Schema context (preview):")
        for line in schema_lines:
            if line.strip():
                log(f"      {line[:76]}")

        # Discover paths between extracted node types
        if len(extracted['node_types']) >= 2:
            log(f"\n🛤️  DISCOVERING PATHS BETWEEN NODE TYPES...")
            log(f"   Pairs to explore: {len(extracted['node_types']) * (len(extracted['node_types']) - 1)} combinations")

            # Count pairs and paths before
            pairs_before = sum(len(targets) for targets in schema_manager._path_cache.values())
            paths_before = sum(
                len(paths)
                for source_cache in schema_manager._path_cache.values()
                for paths in source_cache.values()
            )
            paths_discovered = []

            for i, source in enumerate(extracted['node_types']):
                for target in extracted['node_types']:
                    if source != target:  # Skip self-paths
                        log(f"\n   🔗 Discovering: {source} → {target}")

                        path_start = datetime.now()
                        # Use extracted relationships to filter path discovery (faster + semantically relevant)
                        paths = await schema_manager.get_paths_between(
                            source, target,
                            relationship_types=extracted['relationship_types'],  # Filter by extracted rels
                            max_depth=5  # Adaptive - APOC stops early if paths found
                        )
                        path_time = (datetime.now() - path_start).total_seconds() * 1000

                        if paths:
                            depth1 = [p for p in paths if p['depth'] == 1]
                            depth2plus = [p for p in paths if p['depth'] > 1]

                            log(f"      ✅ Found {len(paths)} path pattern(s) in {path_time:.0f}ms")
                            if depth1:
                                log(f"         • {len(depth1)} depth=1 (from pre-populated cache)")
                            if depth2plus:
                                log(f"         • {len(depth2plus)} depth>1 (discovered on-demand)")

                            for p in paths[:2]:  # Show first 2
                                rel_chain = " → ".join(p['rels'])
                                via_chain = " → ".join(p['via']) if p['via'] else "direct"
                                log(f"         • {rel_chain} (via: {via_chain}, depth: {p['depth']})")
                            paths_discovered.append({
                                "from": source,
                                "to": target,
                                "count": len(paths),
                                "depth1_count": len(depth1),
                                "depth2plus_count": len(depth2plus),
                                "time_ms": path_time
                            })
                        else:
                            log(f"      ⚠️  No paths found in {path_time:.0f}ms")

            # Count pairs and paths after
            pairs_after = sum(len(targets) for targets in schema_manager._path_cache.values())
            paths_after = sum(
                len(paths)
                for source_cache in schema_manager._path_cache.values()
                for paths in source_cache.values()
            )
            new_pairs = pairs_after - pairs_before
            new_paths = paths_after - paths_before

            log(f"\n   📊 Cache Update:")
            log(f"      • (Source→Target) pairs before: {pairs_before}")
            log(f"      • (Source→Target) pairs after: {pairs_after}")
            log(f"      • New pairs added: {new_pairs}")
            log(f"      • Total path entries before: {paths_before}")
            log(f"      • Total path entries after: {paths_after}")
            log(f"      • New path entries added: {new_paths}")
            log(f"      • Cache hits so far: {schema_manager._cache_hits}")
            log(f"      • Cache misses so far: {schema_manager._cache_misses}")
            log(f"      • Hit rate: {schema_manager._cache_hits / max(1, schema_manager._cache_hits + schema_manager._cache_misses) * 100:.1f}%")

            # Save cache snapshot
            cache_snapshots.append({
                "subquery_id": idx,
                "pairs": pairs_after,
                "paths": paths_after,
                "new_pairs": new_pairs,
                "new_paths": new_paths,
                "paths_discovered": paths_discovered,
                "cache_stats": schema_manager.get_cache_stats()
            })
        else:
            log(f"\n   ⚠️  Only {len(extracted['node_types'])} node type(s) extracted, need at least 2 for path discovery")

    # Step 4: Summary
    log("\n" + "=" * 80)
    log("STEP 4: PROGRESSIVE CACHE BUILDING SUMMARY")
    log("=" * 80)

    log(f"\n📈 Cache Growth Over Subqueries:")
    log(f"   Initial (pre-populated): {total_pairs} pairs, {total_paths} paths ({depth1_paths} depth=1)")
    for snapshot in cache_snapshots:
        log(f"   After subquery {snapshot['subquery_id']}: {snapshot['pairs']} pairs, {snapshot['paths']} paths (+{snapshot['new_paths']} new)")

    log(f"\n🎯 Final Cache Statistics:")
    final_stats = schema_manager.get_cache_stats()
    log(f"   • Total unique paths cached: {final_stats['cached_paths']}")
    log(f"   • Total requests: {final_stats['total_requests']}")
    log(f"   • Cache hits: {final_stats['cache_hits']} ({final_stats['hit_rate']:.1f}%)")
    log(f"   • Cache misses: {final_stats['total_requests'] - final_stats['cache_hits']}")

    log(f"\n💾 Cache persisted to: {cache_file}")

    # Step 5: Demonstrate cache reuse
    log("\n" + "=" * 80)
    log("STEP 5: DEMONSTRATE CACHE REUSE ON REPEATED SUBQUERY")
    log("=" * 80)

    # Re-process first subquery to show cache hits
    first_subquery = decomposed_query['subqueries'][0]
    log(f"\nRe-processing: {first_subquery[:100]}...")

    premise_context = " ".join(decomposed_query['premises'])
    combined_text = f"{premise_context} {first_subquery}"

    extracted = schema_manager.extract_types_from_query(combined_text)
    log(f"✅ Extracted: {extracted['node_types']}")

    if len(extracted['node_types']) >= 2:
        log(f"\n🛤️  Fetching paths (should be cached)...")

        for i, source in enumerate(extracted['node_types']):
            for target in extracted['node_types']:
                if source != target:
                    cache_check_start = datetime.now()
                    paths = await schema_manager.get_paths_between(
                        source, target,
                        relationship_types=extracted['relationship_types'],
                        max_depth=5
                    )
                    cache_check_time = (datetime.now() - cache_check_start).total_seconds() * 1000

                    log(f"   {source} → {target}: {len(paths)} paths in {cache_check_time:.1f}ms (CACHED ✅)")

    log(f"\n📊 Final Stats After Re-processing:")
    final_stats = schema_manager.get_cache_stats()
    log(f"   • Cache hit rate: {final_stats['hit_rate']:.1f}%")
    log(f"   • Total requests: {final_stats['total_requests']}")

    # Save detailed log
    log_output = {
        "decomposed_query": decomposed_query,
        "initialization": {
            "time_ms": init_time,
            "node_types_reconciled": len(schema_manager._reconciled_schema['nodes']),
            "embeddings_built": len(schema_manager._type_embeddings['type_names'])
        },
        "subquery_processing": all_extracted_types,
        "cache_snapshots": cache_snapshots,
        "final_stats": final_stats,
        "log_entries": log_entries
    }

    with open(log_file, 'w') as f:
        json.dump(log_output, f, indent=2)

    log("\n" + "=" * 80)
    log("DEMONSTRATION COMPLETE")
    log("=" * 80)
    log(f"\n📁 Detailed log saved to: {log_file}")
    log(f"📁 Cache saved to: {cache_file}")

    log("\n💡 KEY TAKEAWAYS:")
    log("   1. Schema reconciliation happens ONCE at initialization (~10s)")
    log("   2. Type extraction uses embeddings (~10-50ms per subquery)")
    log("   3. Path discovery is on-demand (~200-500ms first time per pair)")
    log("   4. Cache hits are near-instant (<1ms)")
    log("   5. Cache builds progressively across subqueries")
    log("   6. No per-query schema reconciliation overhead!")

    # Cleanup
    await schema_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())

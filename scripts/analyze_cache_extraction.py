#!/usr/bin/env python3
"""
Analyze what types were extracted per subquery and what was cached.
This helps verify that the cache structure matches the extraction results.
"""
import json
import sys
sys.path.insert(0, '/opt/genpod')

# Load the detailed log
log_file = "/tmp/progressive_cache_building_20251103_211850.log"
cache_file = "/tmp/progressive_demo_cache.json"

print("=" * 80)
print("CACHE EXTRACTION ANALYSIS")
print("=" * 80)
print()

# Load cache
with open(cache_file, 'r') as f:
    cache = json.load(f)

# Load log
with open(log_file, 'r') as f:
    log_data = json.load(f)

print("📋 SUBQUERY-BY-SUBQUERY EXTRACTION & CACHE ANALYSIS")
print("=" * 80)
print()

for idx, subquery_log in enumerate(log_data['subquery_processing'], 1):
    print(f"{'─' * 80}")
    print(f"SUBQUERY {idx}")
    print(f"{'─' * 80}")

    # Show extracted types
    extracted = subquery_log.get('extracted', {})
    node_types = extracted.get('node_types', [])
    rel_types = extracted.get('relationship_types', [])

    print(f"\n🔍 EXTRACTED FROM QUERY TEXT:")
    print(f"   Node Types ({len(node_types)}): {node_types}")
    print(f"   Relationship Types ({len(rel_types)}): {rel_types}")

    # Calculate expected source→target pairs
    print(f"\n📊 EXPECTED SOURCE→TARGET PAIRS TO EXPLORE:")
    print(f"   {len(node_types)} source types × {len(node_types)-1} target types = {len(node_types) * (len(node_types) - 1)} pairs")

    expected_pairs = []
    for source in node_types:
        for target in node_types:
            if source != target:
                expected_pairs.append(f"{source} → {target}")

    print(f"\n   Expected pairs:")
    for pair in expected_pairs[:10]:  # Show first 10
        print(f"      • {pair}")
    if len(expected_pairs) > 10:
        print(f"      ... and {len(expected_pairs) - 10} more")

    print(f"\n🛤️  ACTUAL PATHS DISCOVERED (from cache snapshots):")

    # Get cache snapshot for this subquery
    cache_snapshot = None
    for snapshot in log_data.get('cache_snapshots', []):
        if snapshot['subquery_id'] == idx:
            cache_snapshot = snapshot
            break

    if cache_snapshot:
        new_paths = cache_snapshot.get('new_paths_discovered', [])
        print(f"   New paths discovered: {len(new_paths)}")

        if new_paths:
            for path_info in new_paths[:10]:  # Show first 10
                source = path_info.get('source', 'Unknown')
                target = path_info.get('target', 'Unknown')
                patterns = path_info.get('patterns', [])
                print(f"      ✅ {source} → {target}: {len(patterns)} path pattern(s)")
                for pattern in patterns[:2]:  # Show first 2 patterns
                    rels = pattern.get('rels', [])
                    via = pattern.get('via', [])
                    print(f"         • {' → '.join(rels)}" + (f" (via {', '.join(via)})" if via else ""))
        else:
            print(f"      (No new paths found - all were cached or empty)")

        # Show cache stats
        stats = cache_snapshot.get('cache_stats', {})
        print(f"\n   Cache Statistics After This Subquery:")
        print(f"      • Total cache entries: {cache_snapshot.get('cache_size', 0)}")
        print(f"      • Cache hits so far: {stats.get('hits', 0)}")
        print(f"      • Cache misses so far: {stats.get('misses', 0)}")
        print(f"      • Hit rate: {stats.get('hit_rate', 0):.1%}")

    print()

print("=" * 80)
print("FINAL CACHE STRUCTURE ANALYSIS")
print("=" * 80)
print()

# Analyze the final cache
total_source_targets = 0
total_paths = 0
non_empty_pairs = 0

for source, targets in cache.items():
    for target, paths in targets.items():
        total_source_targets += 1
        if paths:  # Non-empty
            non_empty_pairs += 1
            total_paths += len(paths)
            print(f"✅ {source} → {target}: {len(paths)} path pattern(s)")
            for path in paths[:3]:  # Show first 3
                rels = path.get('rels', [])
                via = path.get('via', [])
                depth = path.get('depth', 0)
                count = path.get('count', 0)
                print(f"      • Depth {depth}: {' → '.join(rels)}" + (f" (via {', '.join(via)})" if via else "") + f" [{count} instances]")
            if len(paths) > 3:
                print(f"      ... and {len(paths) - 3} more patterns")

print(f"\n📊 CACHE SUMMARY:")
print(f"   • Total source→target pairs cached: {total_source_targets}")
print(f"   • Pairs with paths: {non_empty_pairs}")
print(f"   • Pairs with no paths (cached negative results): {total_source_targets - non_empty_pairs}")
print(f"   • Total path patterns stored: {total_paths}")
print()

print("=" * 80)
print("KEY INSIGHTS")
print("=" * 80)
print()
print("1. Node types are extracted using embedding similarity matching")
print("2. Relationship types are extracted but NOT directly used for caching")
print("3. Cache stores SOURCE→TARGET pairs (node types only)")
print("4. Empty arrays mean 'no path exists' - this prevents re-querying DB")
print("5. Multiple path patterns can exist between same source→target pair")
print()

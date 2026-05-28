#!/usr/bin/env python3
"""
Analyze: What relationships were EXTRACTED vs what relationships appear in CACHED PATHS
This reveals whether extracted relationships are used to filter path discovery.
"""
import json
import sys
sys.path.insert(0, '/opt/genpod')

log_file = "/tmp/progressive_cache_building_20251103_211850.log"
cache_file = "/tmp/progressive_demo_cache.json"

print("=" * 80)
print("EXTRACTED RELATIONSHIPS vs CACHED PATH RELATIONSHIPS")
print("=" * 80)
print()

# Load log and cache
with open(log_file, 'r') as f:
    log_data = json.load(f)

with open(cache_file, 'r') as f:
    cache = json.load(f)

# Extract all relationships used in cached paths
relationships_in_cache = set()
for source, targets in cache.items():
    for target, paths in targets.items():
        if paths:  # Only non-empty paths
            for path in paths:
                rels = path.get('rels', [])
                relationships_in_cache.update(rels)

print("🔍 RELATIONSHIPS FOUND IN CACHED PATHS:")
print(f"   {sorted(relationships_in_cache)}")
print()

print("=" * 80)
print("SUBQUERY-BY-SUBQUERY COMPARISON")
print("=" * 80)
print()

for idx, subquery_log in enumerate(log_data['subquery_processing'], 1):
    print(f"{'─' * 80}")
    print(f"SUBQUERY {idx}")
    print(f"{'─' * 80}")
    print()

    # Extracted types
    extracted = subquery_log.get('extracted', {})
    node_types = extracted.get('node_types', [])
    rel_types = extracted.get('relationship_types', [])

    print(f"🎯 EXTRACTED BY EMBEDDING SIMILARITY:")
    print(f"   Node types: {node_types}")
    print(f"   Relationship types: {rel_types}")
    print()

    # Find corresponding cache snapshot
    cache_snapshot = None
    for snapshot in log_data.get('cache_snapshots', []):
        if snapshot['subquery_id'] == idx:
            cache_snapshot = snapshot
            break

    if cache_snapshot:
        paths_discovered = cache_snapshot.get('paths_discovered', [])

        print(f"🛤️  PATHS ACTUALLY DISCOVERED IN CPG:")
        if not paths_discovered:
            print(f"   (No paths with data)")
        else:
            for path_info in paths_discovered:
                source = path_info.get('from', 'Unknown')
                target = path_info.get('to', 'Unknown')
                count = path_info.get('count', 0)
                time_ms = path_info.get('time_ms', 0)

                if count > 0:
                    # Look up actual path patterns from cache
                    cache_paths = cache.get(source, {}).get(target, [])
                    if cache_paths:
                        print(f"\n   {source} → {target}: {count} pattern(s)")
                        for i, pattern in enumerate(cache_paths[:3], 1):
                            rels = pattern.get('rels', [])
                            via = pattern.get('via', [])
                            depth = pattern.get('depth', 0)
                            pattern_count = pattern.get('count', 0)

                            rel_chain = ' → '.join(rels)
                            via_info = f" (via {', '.join(via)})" if via else ""
                            print(f"      Pattern {i}: {rel_chain}{via_info} [depth={depth}, count={pattern_count}]")

                        if len(cache_paths) > 3:
                            print(f"      ... and {len(cache_paths) - 3} more patterns")
                else:
                    print(f"   {source} → {target}: cached (from previous subquery)")

        print()
        print(f"🤔 ANALYSIS:")

        # Check which extracted relationships appear in paths
        rels_in_paths = set()
        for path_info in paths_discovered:
            source = path_info.get('from', 'Unknown')
            target = path_info.get('to', 'Unknown')
            cache_paths = cache.get(source, {}).get(target, [])
            for pattern in cache_paths:
                rels_in_paths.update(pattern.get('rels', []))

        if rel_types:
            matched = rels_in_paths.intersection(set(rel_types))
            unmatched = set(rel_types) - rels_in_paths

            if matched:
                print(f"   ✅ Extracted relationships that appear in paths: {sorted(matched)}")
            if unmatched:
                print(f"   ⚠️  Extracted relationships NOT in paths: {sorted(unmatched)}")

            if not rels_in_paths:
                print(f"   ℹ️  No paths with relationships discovered yet (all empty or cached)")
        else:
            print(f"   ℹ️  No relationships extracted for this subquery")

    print()

print("=" * 80)
print("OVERALL ANALYSIS")
print("=" * 80)
print()

# Collect all extracted relationships across all subqueries
all_extracted_rels = set()
for subquery_log in log_data['subquery_processing']:
    extracted = subquery_log.get('extracted', {})
    rel_types = extracted.get('relationship_types', [])
    all_extracted_rels.update(rel_types)

print(f"📊 ALL RELATIONSHIPS EXTRACTED ACROSS SUBQUERIES:")
print(f"   {sorted(all_extracted_rels)}")
print()

print(f"📊 RELATIONSHIPS ACTUALLY IN CACHED PATHS:")
print(f"   {sorted(relationships_in_cache)}")
print()

matched_rels = relationships_in_cache.intersection(all_extracted_rels)
unmatched_extracted = all_extracted_rels - relationships_in_cache
unmatched_cached = relationships_in_cache - all_extracted_rels

print(f"✅ EXTRACTED & FOUND IN PATHS: {sorted(matched_rels)}")
print(f"⚠️  EXTRACTED BUT NOT IN PATHS: {sorted(unmatched_extracted)}")
print(f"❓ IN PATHS BUT NOT EXTRACTED: {sorted(unmatched_cached)}")
print()

print("=" * 80)
print("KEY FINDINGS")
print("=" * 80)
print()
print("1. Extracted relationships (from embedding similarity) are NOT used to filter paths")
print("2. Path discovery finds ALL relationship chains between extracted node types")
print("3. The extracted relationships help with semantic matching of node types")
print("4. Actual paths may use relationships that weren't explicitly extracted")
print("5. Some extracted relationships may not exist in this specific CPG")
print()
print("QUESTION: Should extracted relationships be used to filter discovered paths?")
print("   Option A (current): Discover all paths, regardless of relationships")
print("   Option B (alternative): Only discover paths using extracted relationships")
print()

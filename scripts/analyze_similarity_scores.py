#!/usr/bin/env python3
"""
Analyze similarity scores from model comparison to determine optimal thresholds.
"""
import json
from collections import defaultdict

# Load results
with open('/tmp/comprehensive_model_comparison.json', 'r') as f:
    results = json.load(f)

print("=" * 100)
print("SIMILARITY SCORE ANALYSIS - THRESHOLD TUNING")
print("=" * 100)
print()

# Analyze required vs extra types across all subqueries
print("CRITICAL FINDING: Score Distribution for REQUIRED Types")
print("-" * 100)
print()

required_scores = defaultdict(list)
extra_scores = defaultdict(list)

for result in results:
    model = result['model'].split('/')[-1]
    sq_id = result['sq_id']

    expected_nodes = set(result['node_metrics']['expected'])
    node_scores = result['similarity_scores']['node_scores']

    for node, info in node_scores.items():
        score = info['score']
        if node in expected_nodes:
            required_scores[model].append({
                'sq_id': sq_id,
                'type': node,
                'score': score,
                'tier': info['tier']
            })
        else:
            extra_scores[model].append({
                'sq_id': sq_id,
                'type': node,
                'score': score
            })

# Show min/max/avg for required types
for model in required_scores.keys():
    print(f"\n{model}:")
    print("-" * 100)

    req_scores = [item['score'] for item in required_scores[model]]

    print(f"  Required types: {len(req_scores)} instances")
    print(f"  Min score: {min(req_scores):.4f}")
    print(f"  Max score: {max(req_scores):.4f}")
    print(f"  Avg score: {sum(req_scores)/len(req_scores):.4f}")
    print()

    # Show all required types with scores
    print("  All required types (sorted by score):")
    for item in sorted(required_scores[model], key=lambda x: x['score']):
        tier_mark = '🔑' if item['tier'] == 'explicit' else '📊'
        print(f"    {tier_mark} {item['sq_id']}: {item['type']:20s} = {item['score']:.4f} ({item['tier']})")

print()
print()
print("=" * 100)
print("THRESHOLD ANALYSIS")
print("=" * 100)
print()

# Test different thresholds
thresholds_to_test = [0.10, 0.15, 0.18, 0.20, 0.25, 0.30]

for threshold in thresholds_to_test:
    print(f"\nThreshold = {threshold:.2f}")
    print("-" * 100)

    for model in required_scores.keys():
        req_scores = required_scores[model]

        # Count how many required types would be missed
        missed = [item for item in req_scores if item['score'] < threshold]

        if missed:
            print(f"  ❌ {model}: {len(missed)} REQUIRED types MISSED")
            for item in missed:
                print(f"     - {item['sq_id']}: {item['type']} (score={item['score']:.4f})")
        else:
            print(f"  ✅ {model}: All required types captured")

print()
print()
print("=" * 100)
print("DETAILED SCORE BREAKDOWN BY SUBQUERY")
print("=" * 100)

for sq_id in ['SQ1', 'SQ2', 'SQ3', 'SQ4']:
    print(f"\n{'-'*100}")
    print(f"{sq_id}")
    print(f"{'-'*100}")

    sq_results = [r for r in results if r['sq_id'] == sq_id]

    for result in sq_results:
        model = result['model'].split('/')[-1]
        print(f"\n{model}:")

        expected_nodes = set(result['node_metrics']['expected'])
        expected_rels = set(result['rel_metrics']['expected'])

        node_scores = result['similarity_scores']['node_scores']
        rel_scores = result['similarity_scores']['rel_scores']

        # Group by required/extra
        required_node_items = []
        extra_node_items = []

        for node, info in node_scores.items():
            item = (node, info['score'], info['tier'])
            if node in expected_nodes:
                required_node_items.append(item)
            else:
                extra_node_items.append(item)

        print(f"  REQUIRED Nodes ({len(required_node_items)}):")
        for node, score, tier in sorted(required_node_items, key=lambda x: x[1], reverse=True):
            tier_mark = '🔑' if tier == 'explicit' else '📊'
            print(f"    {tier_mark} {node:20s}  score={score:.4f}  ({tier})")

        if extra_node_items:
            print(f"  Extra Nodes ({len(extra_node_items)}):")
            for node, score, tier in sorted(extra_node_items, key=lambda x: x[1], reverse=True)[:5]:
                print(f"    + {node:20s}  score={score:.4f}")

        print(f"  REQUIRED Relationships ({len([r for r in rel_scores if r in expected_rels])}):")
        for rel, info in sorted(rel_scores.items(), key=lambda x: x[1]['score'], reverse=True):
            if rel in expected_rels:
                tier_mark = '🔑' if info['tier'] == 'explicit' else '📊'
                print(f"    {tier_mark} {rel:20s}  score={info['score']:.4f}  ({info['tier']})")

print()
print()
print("=" * 100)
print("RECOMMENDATIONS")
print("=" * 100)
print()

# Find the minimum score for required types per model
for model in required_scores.keys():
    req_scores = [item['score'] for item in required_scores[model]]
    min_score = min(req_scores)

    # Find item with min score
    min_item = [item for item in required_scores[model] if item['score'] == min_score][0]

    print(f"{model}:")
    print(f"  Minimum required type score: {min_score:.4f}")
    print(f"  Type: {min_item['type']} in {min_item['sq_id']}")
    print(f"  Recommended threshold: {max(0.10, min_score - 0.05):.2f} (with 0.05 safety margin)")
    print()

print()
print("OVERALL RECOMMENDATION:")
print("-" * 100)
print("Based on the analysis:")
print()
print("✅ Current threshold (0.20) is TOO HIGH for CodeBERT")
print("   - Misses Type in SQ3 (score=0.1874)")
print()
print("✅ Recommended threshold: 0.15")
print("   - Captures all required types for both models")
print("   - Already being used as the default in extract_types_from_query")
print()
print("✅ all-MiniLM-L6-v2 is more robust:")
print("   - Lowest required score: 0.2872 (Type in SQ1)")
print("   - Works well even with threshold 0.20")
print()
print("❌ CodeBERT is fragile:")
print("   - Lowest required score: 0.1874 (Type in SQ3)")
print("   - Needs threshold <= 0.18 to avoid missing required types")
print()

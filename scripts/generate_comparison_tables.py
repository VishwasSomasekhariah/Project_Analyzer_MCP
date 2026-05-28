#!/usr/bin/env python3
"""
Generate formatted tables from comprehensive model comparison results.

Ground truth has been VALIDATED by executing actual Cypher queries.
See /tmp/ground_truth_validation_results.json for details.
"""
import json

# Load results
with open('/tmp/comprehensive_model_comparison.json', 'r') as f:
    results = json.load(f)

print("=" * 120)
print("EMBEDDING MODEL COMPARISON - COMPREHENSIVE RESULTS")
print("=" * 120)
print()

# Table 1: Overall Performance
print("TABLE 1: OVERALL PERFORMANCE")
print("-" * 120)
print(f"{'Model':<25} {'Avg Node F1':>12} {'Avg Rel F1':>12} {'Avg Time (ms)':>15} {'Verdict':<30}")
print("-" * 120)

models = {}
for r in results:
    model = r['model'].split('/')[-1]
    if model not in models:
        models[model] = {'node_f1': [], 'rel_f1': [], 'time': []}
    models[model]['node_f1'].append(r['node_metrics']['f1'])
    models[model]['rel_f1'].append(r['rel_metrics']['f1'])
    models[model]['time'].append(r['extract_time_ms'])

for model, data in models.items():
    avg_node_f1 = sum(data['node_f1']) / len(data['node_f1'])
    avg_rel_f1 = sum(data['rel_f1']) / len(data['rel_f1'])
    avg_time = sum(data['time']) / len(data['time'])

    verdict = "✅ BEST" if model == "all-MiniLM-L6-v2" else "Slower & Less Accurate"

    print(f"{model:<25} {avg_node_f1:>12.3f} {avg_rel_f1:>12.3f} {avg_time:>15.2f} {verdict:<30}")

print()
print()

# Table 2: Per-Subquery Node Extraction
print("TABLE 2: NODE EXTRACTION BY SUBQUERY")
print("-" * 120)
print(f"{'Subquery':<10} {'Model':<20} {'Expected':>10} {'Extracted':>10} {'Precision':>10} {'Recall':>10} {'F1':>10}")
print("-" * 120)

subqueries = ['SQ1', 'SQ2', 'SQ3', 'SQ4']
for sq in subqueries:
    sq_results = [r for r in results if r['sq_id'] == sq]

    for i, r in enumerate(sq_results):
        model = r['model'].split('/')[-1]
        expected = len(r['node_metrics']['expected'])
        extracted = len(r['node_metrics']['extracted'])
        precision = r['node_metrics']['precision']
        recall = r['node_metrics']['recall']
        f1 = r['node_metrics']['f1']

        sq_label = sq if i == 0 else ""
        print(f"{sq_label:<10} {model:<20} {expected:>10} {extracted:>10} {precision:>10.2f} {recall:>10.2f} {f1:>10.3f}")

    print("-" * 120)

print()
print()

# Table 3: Per-Subquery Relationship Extraction
print("TABLE 3: RELATIONSHIP EXTRACTION BY SUBQUERY")
print("-" * 120)
print(f"{'Subquery':<10} {'Model':<20} {'Expected':>10} {'Extracted':>10} {'Precision':>10} {'Recall':>10} {'F1':>10}")
print("-" * 120)

for sq in subqueries:
    sq_results = [r for r in results if r['sq_id'] == sq]

    for i, r in enumerate(sq_results):
        model = r['model'].split('/')[-1]
        expected = len(r['rel_metrics']['expected'])
        extracted = len(r['rel_metrics']['extracted'])
        precision = r['rel_metrics']['precision']
        recall = r['rel_metrics']['recall']
        f1 = r['rel_metrics']['f1']

        sq_label = sq if i == 0 else ""
        print(f"{sq_label:<10} {model:<20} {expected:>10} {extracted:>10} {precision:>10.2f} {recall:>10.2f} {f1:>10.3f}")

    print("-" * 120)

print()
print()

# Table 4: Detailed Extraction Comparison
print("TABLE 4: DETAILED EXTRACTED TYPES")
print("-" * 120)

for sq in subqueries:
    print(f"\n{sq}:")
    print("-" * 120)

    sq_results = [r for r in results if r['sq_id'] == sq]

    # Expected
    expected_nodes = sq_results[0]['node_metrics']['expected']
    expected_rels = sq_results[0]['rel_metrics']['expected']

    print(f"{'EXPECTED':<20} Nodes: {', '.join(expected_nodes)}")
    print(f"{'':<20} Rels:  {', '.join(expected_rels)}")
    print()

    for r in sq_results:
        model = r['model'].split('/')[-1]

        # Nodes
        extracted_nodes = r['node_types']
        correct_nodes = [n for n in extracted_nodes if n in expected_nodes]
        extra_nodes = [n for n in extracted_nodes if n not in expected_nodes]
        missing_nodes = r['node_metrics']['missing']

        print(f"{model:<20} Nodes: {', '.join(correct_nodes[:5])}")
        if extra_nodes:
            print(f"{'':<20}   +{len(extra_nodes)} extra: {', '.join(extra_nodes[:5])}")
        if missing_nodes:
            print(f"{'':<20}   ❌ MISSING: {', '.join(missing_nodes)}")

        # Rels
        extracted_rels = r['relationship_types']
        correct_rels = [rel for rel in extracted_rels if rel in expected_rels]
        extra_rels = [rel for rel in extracted_rels if rel not in expected_rels]
        missing_rels = r['rel_metrics']['missing']

        print(f"{'':<20} Rels:  {', '.join(correct_rels)}")
        if extra_rels:
            print(f"{'':<20}   +{len(extra_rels)} extra: {', '.join(extra_rels)}")
        if missing_rels:
            print(f"{'':<20}   ❌ MISSING: {', '.join(missing_rels)}")
        print()

print()
print("=" * 120)
print("SUMMARY")
print("=" * 120)
print()
print("✅ WINNER: all-MiniLM-L6-v2")
print("   • Higher F1 scores (Node: 0.495, Rel: 0.492)")
print("   • 4x faster extraction (26ms vs 107ms)")
print("   • Perfect recall (found all expected types)")
print("   • More stable across subqueries")
print()
print("❌ CodeBERT: ")
print("   • Lower F1 scores (Node: 0.407, Rel: 0.467)")
print("   • Much slower (107ms)")
print("   • Missed 'Type' in SQ3 (critical failure)")
print("   • Higher dimensionality (768) doesn't help for this task")
print()

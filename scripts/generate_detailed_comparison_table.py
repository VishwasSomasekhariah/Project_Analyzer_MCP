#!/usr/bin/env python3
"""
Generate detailed, non-aggregated comparison table with raw extraction data.

Ground truth has been VALIDATED by executing actual Cypher queries.
See /tmp/ground_truth_validation_results.json for details.

CORRECTED Ground Truth (validated 2025-11-05):
- SQ1: Type, Function | CONTAINS
- SQ2: Type, Function | CONTAINS, CALLS
- SQ3: Type, Function, Statement | CONTAINS, CALLS
- SQ4: Type, Function, Variable | CONTAINS, REFERENCES
"""
import json

# Load results
with open('/tmp/comprehensive_model_comparison.json', 'r') as f:
    results = json.load(f)

print("=" * 160)
print("DETAILED MODEL COMPARISON - RAW EXTRACTION DATA (NO AGGREGATION)")
print("=" * 160)
print()

# Group by subquery
subqueries = {
    'SQ1': "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
    'SQ2': "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
    'SQ3': "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
    'SQ4': "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name"
}

# Get initialization times (from test output, need to capture separately)
# For now, use the times from the test run
init_times = {
    'all-MiniLM-L6-v2': 9.35,
    'codebert-base': 4.55
}

print("INITIALIZATION TIMES:")
print("-" * 160)
print(f"{'Model':<30} {'Init Time (seconds)':<20}")
print("-" * 160)
for model, time in init_times.items():
    print(f"{model:<30} {time:<20.2f}")
print()
print()

print("DETAILED EXTRACTION BY SUBQUERY:")
print("=" * 160)

for sq_id, sq_text in subqueries.items():
    print(f"\n{sq_id}: {sq_text}")
    print("-" * 160)

    sq_results = [r for r in results if r['sq_id'] == sq_id]

    # Table header
    print(f"{'Model':<25} {'Extract Time (ms)':<20} {'Node Types Extracted':<60} {'Relationship Types Extracted':<40}")
    print("-" * 160)

    for r in sq_results:
        model = r['model'].split('/')[-1]
        extract_time = r['extract_time_ms']
        nodes = ', '.join(r['node_types'])
        rels = ', '.join(r['relationship_types'])

        # Wrap long lists
        if len(nodes) > 55:
            nodes = nodes[:52] + "..."
        if len(rels) > 35:
            rels = rels[:32] + "..."

        print(f"{model:<25} {extract_time:<20.2f} {nodes:<60} {rels:<40}")

    print()

    # Show expected vs actual in detail
    print(f"{'Expected Types:':<25} {'Nodes:':<60} {'Relationships:':<40}")
    expected_nodes = ', '.join(sq_results[0]['node_metrics']['expected'])
    expected_rels = ', '.join(sq_results[0]['rel_metrics']['expected'])
    print(f"{'':<25} {expected_nodes:<60} {expected_rels:<40}")
    print()

    print(f"{'Detailed Breakdown:':<25}")
    print("-" * 160)

    for r in sq_results:
        model = r['model'].split('/')[-1]
        print(f"\n{model}:")

        # Nodes
        extracted = r['node_types']
        expected = set(r['node_metrics']['expected'])

        correct = [n for n in extracted if n in expected]
        missing = r['node_metrics']['missing']
        extra = r['node_metrics']['extra']

        print(f"  Nodes Extracted: {', '.join(extracted)}")
        print(f"    ✓ Correct:     {', '.join(correct) if correct else 'None'}")
        print(f"    ✗ Missing:     {', '.join(missing) if missing else 'None'}")
        print(f"    + Extra:       {', '.join(extra) if extra else 'None'}")

        # Relationships
        extracted_rels = r['relationship_types']
        expected_rels = set(r['rel_metrics']['expected'])

        correct_rels = [rel for rel in extracted_rels if rel in expected_rels]
        missing_rels = r['rel_metrics']['missing']
        extra_rels = r['rel_metrics']['extra']

        print(f"  Relationships Extracted: {', '.join(extracted_rels)}")
        print(f"    ✓ Correct:     {', '.join(correct_rels) if correct_rels else 'None'}")
        print(f"    ✗ Missing:     {', '.join(missing_rels) if missing_rels else 'None'}")
        print(f"    + Extra:       {', '.join(extra_rels) if extra_rels else 'None'}")

        # Metrics
        print(f"  Metrics:")
        print(f"    Node Precision: {r['node_metrics']['precision']:.3f}, Recall: {r['node_metrics']['recall']:.3f}, F1: {r['node_metrics']['f1']:.3f}")
        print(f"    Rel  Precision: {r['rel_metrics']['precision']:.3f}, Recall: {r['rel_metrics']['recall']:.3f}, F1: {r['rel_metrics']['f1']:.3f}")

    print()
    print("=" * 160)

print()
print()
print("SUMMARY COMPARISON:")
print("-" * 160)
print(f"{'Metric':<40} {'all-MiniLM-L6-v2':<30} {'codebert-base':<30}")
print("-" * 160)

# Calculate averages for summary
minilm_results = [r for r in results if 'all-MiniLM' in r['model']]
codebert_results = [r for r in results if 'codebert' in r['model']]

print(f"{'Initialization Time (s)':<40} {init_times['all-MiniLM-L6-v2']:<30.2f} {init_times['codebert-base']:<30.2f}")

minilm_avg_time = sum(r['extract_time_ms'] for r in minilm_results) / len(minilm_results)
codebert_avg_time = sum(r['extract_time_ms'] for r in codebert_results) / len(codebert_results)
print(f"{'Avg Extraction Time (ms)':<40} {minilm_avg_time:<30.2f} {codebert_avg_time:<30.2f}")

minilm_avg_node_f1 = sum(r['node_metrics']['f1'] for r in minilm_results) / len(minilm_results)
codebert_avg_node_f1 = sum(r['node_metrics']['f1'] for r in codebert_results) / len(codebert_results)
print(f"{'Avg Node F1':<40} {minilm_avg_node_f1:<30.3f} {codebert_avg_node_f1:<30.3f}")

minilm_avg_rel_f1 = sum(r['rel_metrics']['f1'] for r in minilm_results) / len(minilm_results)
codebert_avg_rel_f1 = sum(r['rel_metrics']['f1'] for r in codebert_results) / len(codebert_results)
print(f"{'Avg Rel F1':<40} {minilm_avg_rel_f1:<30.3f} {codebert_avg_rel_f1:<30.3f}")

# Perfect recall check
minilm_perfect_recall = all(r['node_metrics']['recall'] == 1.0 for r in minilm_results)
codebert_perfect_recall = all(r['node_metrics']['recall'] == 1.0 for r in codebert_results)
print(f"{'Perfect Node Recall (found all expected)':<40} {'✓ YES' if minilm_perfect_recall else '✗ NO':<30} {'✓ YES' if codebert_perfect_recall else '✗ NO':<30}")

print("-" * 160)
print()

print("VALIDATION NOTES:")
print("  • All raw extraction data is shown above - you can verify each subquery's results")
print("  • Expected types are listed for each subquery")
print("  • Missing/Extra types are explicitly shown")
print("  • Extraction times are per-subquery (not aggregated)")
print("  • F1 scores show precision vs recall trade-off")
print()

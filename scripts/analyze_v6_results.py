#!/usr/bin/env python3
"""Analyze V6 benchmark results for completeness and performance."""
import json
from pathlib import Path

def analyze_run(run_num):
    """Analyze a single run's output."""
    filepath = f"benchmark_results_v6/run_{run_num}_output.json"

    with open(filepath, 'r') as f:
        data = json.load(f)

    # Extract key metrics
    metrics = data.get('metrics', {})
    subquery_results = data.get('subquery_results', [])
    raw_query_results = data.get('raw_query_results', [])

    # Count successful subqueries
    successful = sum(1 for sq in subquery_results if sq.get('status') == 'successful')
    total_subqueries = len(subquery_results)

    # Analyze subqueries
    subquery_details = []
    for sq in subquery_results:
        sq_info = {
            'index': sq.get('approach_index'),
            'status': sq.get('status'),
            'iterations': sq.get('iterations', 0),
            'data_collected': len(sq.get('data_collected', [])),
            'error': sq.get('error_messages', [None])[0] if sq.get('error_messages') else None
        }
        subquery_details.append(sq_info)

    return {
        'run': run_num,
        'time_seconds': metrics.get('total_time_seconds', 0),
        'status': data.get('status', 'unknown'),
        'subqueries_successful': successful,
        'subqueries_total': total_subqueries,
        'raw_data_found': len(raw_query_results),
        'response_length': len(data.get('response', '')),
        'response_preview': data.get('response', '')[:200],
        'tokens_used': data.get('total_tokens_used', 0),
        'cost_usd': data.get('total_estimated_cost_usd', 0),
        'subquery_details': subquery_details
    }

def main():
    print("=" * 80)
    print("V6 BENCHMARK ANALYSIS - Query Plan Mode")
    print("=" * 80)
    print()

    all_runs = []
    for run_num in range(1, 6):
        try:
            result = analyze_run(run_num)
            all_runs.append(result)

            print(f"{'=' * 80}")
            print(f"RUN {run_num}")
            print(f"{'=' * 80}")
            print(f"  Time: {result['time_seconds']:.2f}s")
            print(f"  Status: {result['status']}")
            print(f"  Subqueries: {result['subqueries_successful']}/{result['subqueries_total']} successful")
            print(f"  Raw Data Found: {result['raw_data_found']} items")
            print(f"  Response Length: {result['response_length']} chars")
            print(f"  Tokens: {result['tokens_used']:,}")
            print(f"  Cost: ${result['cost_usd']:.4f}")
            print()
            print(f"  Response Preview:")
            print(f"  {result['response_preview']}...")
            print()
            print(f"  Subquery Details:")
            for sq in result['subquery_details']:
                status_icon = "✅" if sq['status'] == 'successful' else "❌"
                print(f"    {status_icon} SQ{sq['index']}: {sq['status']} - "
                      f"Iterations: {sq['iterations']}, Data: {sq['data_collected']} items")
                if sq['error']:
                    print(f"       Error: {sq['error'][:100]}")
            print()

        except Exception as e:
            print(f"ERROR analyzing run {run_num}: {e}")
            print()

    # Overall summary
    print(f"{'=' * 80}")
    print("OVERALL SUMMARY")
    print(f"{'=' * 80}")

    avg_time = sum(r['time_seconds'] for r in all_runs) / len(all_runs)
    avg_tokens = sum(r['tokens_used'] for r in all_runs) / len(all_runs)
    avg_cost = sum(r['cost_usd'] for r in all_runs) / len(all_runs)
    success_rate = sum(1 for r in all_runs if r['subqueries_successful'] == r['subqueries_total']) / len(all_runs) * 100

    print(f"  Runs Completed: {len(all_runs)}/5")
    print(f"  Success Rate: {success_rate:.1f}% (all subqueries successful)")
    print(f"  Avg Time: {avg_time:.2f}s")
    print(f"  Avg Tokens: {avg_tokens:,.0f}")
    print(f"  Avg Cost: ${avg_cost:.4f}")
    print()

    # Check for data vs response mismatch
    mismatches = [r for r in all_runs if r['raw_data_found'] > 0 and 'couldn\'t find' in r['response_preview'].lower()]
    if mismatches:
        print(f"⚠️  ISSUE DETECTED: {len(mismatches)} runs found data but reported 'not found'")
        for r in mismatches:
            print(f"    Run {r['run']}: Found {r['raw_data_found']} items but response says 'couldn't find'")

    print()

if __name__ == '__main__':
    main()

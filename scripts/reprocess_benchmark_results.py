#!/usr/bin/env python3
"""
Reprocess existing benchmark results with fixed metrics extraction.
This script reads the workflow output files and regenerates metrics/charts.
"""

import json
import glob
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

def extract_metrics_from_result(result: dict, run_number: int) -> dict:
    """Extract metrics from workflow output using correct field names."""

    # Get per-approach data
    tokens_per_approach = result.get('tokens_per_approach', {})
    cost_per_approach = result.get('cost_per_approach', {})
    approach_statuses = result.get('approach_statuses', {})
    approach_traces = result.get('approach_execution_traces', {})

    # Calculate totals
    total_subqueries = len(tokens_per_approach)
    successful_subqueries = sum(1 for status in approach_statuses.values() if status == 'success')
    total_queries = len(result.get('all_executed_queries', []))
    total_tokens = result.get('total_tokens_used', 0)
    total_cost = result.get('total_estimated_cost_usd', 0.0)

    # Build subquery details
    subquery_details = []
    for approach_idx in sorted(tokens_per_approach.keys(), key=lambda x: int(x)):
        approach_tokens = tokens_per_approach.get(approach_idx, 0)
        approach_cost = cost_per_approach.get(approach_idx, 0.0)
        approach_status = approach_statuses.get(approach_idx, 'unknown')
        trace = approach_traces.get(approach_idx, {})
        queries_executed = trace.get('queries_executed', 0)

        subquery_details.append({
            'name': f'SQ{int(approach_idx) + 1}',
            'queries_executed': queries_executed,
            'tokens_used': approach_tokens,
            'cost': round(approach_cost, 4),
            'status': approach_status
        })

    return {
        'run_number': run_number,
        'timestamp': datetime.now().isoformat(),
        'total_time_seconds': 0.0,  # Not available from workflow output
        'success': result.get('status') == 'success',
        'final_answer': result.get('response', ''),
        'confidence_score': 0.0,  # Not available
        'workflow_output_file': f'benchmark_results/run_{run_number}_output.json',
        'phase0_time': 0.0,
        'phase1_time': 0.0,
        'total_subqueries': total_subqueries,
        'successful_subqueries': successful_subqueries,
        'total_queries_executed': total_queries,
        'total_tokens_used': total_tokens,
        'total_cost': round(total_cost, 4),
        'subquery_details': subquery_details
    }


def generate_charts(all_metrics: list, output_dir: Path):
    """Generate performance charts."""

    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract data
    run_numbers = [m['run_number'] for m in all_metrics]
    query_counts = [m['total_queries_executed'] for m in all_metrics]
    token_counts = [m['total_tokens_used'] for m in all_metrics]
    costs = [m['total_cost'] for m in all_metrics]
    success_rates = [(m['successful_subqueries'] / max(m['total_subqueries'], 1)) * 100
                     for m in all_metrics]

    # Calculate averages
    avg_queries = sum(query_counts) / len(query_counts)
    avg_tokens = sum(token_counts) / len(token_counts)
    avg_cost = sum(costs) / len(costs)

    # Create 2x2 subplot
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Benchmark Performance Metrics (5 Runs)', fontsize=16, fontweight='bold')

    # 1. Query Count Per Run
    ax1.plot(run_numbers, query_counts, marker='o', linewidth=2, markersize=8, color='#2E86AB')
    ax1.axhline(y=avg_queries, color='red', linestyle='--', linewidth=1, label=f'Avg: {avg_queries:.1f}')
    ax1.set_xlabel('Run Number', fontsize=11)
    ax1.set_ylabel('Total Queries', fontsize=11)
    ax1.set_title('Query Count Per Run', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # 2. Token Usage Per Run
    ax2.plot(run_numbers, token_counts, marker='s', linewidth=2, markersize=8, color='#A23B72')
    ax2.axhline(y=avg_tokens, color='red', linestyle='--', linewidth=1,
                label=f'Avg: {avg_tokens:,.0f}K')
    ax2.set_xlabel('Run Number', fontsize=11)
    ax2.set_ylabel('Total Tokens (Thousands)', fontsize=11)
    ax2.set_title('Token Usage Per Run', fontsize=12, fontweight='bold')
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x/1000:.0f}K'))
    ax2.grid(True, alpha=0.3)
    ax2.legend()

    # 3. Execution Cost Per Run
    ax3.plot(run_numbers, costs, marker='^', linewidth=2, markersize=8, color='#F18F01')
    ax3.axhline(y=avg_cost, color='red', linestyle='--', linewidth=1, label=f'Avg: ${avg_cost:.4f}')
    ax3.set_xlabel('Run Number', fontsize=11)
    ax3.set_ylabel('Cost (USD)', fontsize=11)
    ax3.set_title('Execution Cost Per Run', fontsize=12, fontweight='bold')
    ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:.2f}'))
    ax3.grid(True, alpha=0.3)
    ax3.legend()

    # 4. Subquery Success Rate Per Run
    ax4.plot(run_numbers, success_rates, marker='D', linewidth=2, markersize=8, color='#06A77D')
    ax4.axhline(y=100, color='green', linestyle='--', linewidth=1, alpha=0.5, label='Target: 100%')
    ax4.set_xlabel('Run Number', fontsize=11)
    ax4.set_ylabel('Success Rate (%)', fontsize=11)
    ax4.set_title('Subquery Success Rate Per Run', fontsize=12, fontweight='bold')
    ax4.set_ylim([0, 105])
    ax4.grid(True, alpha=0.3)
    ax4.legend()

    # Annotate success rates
    for i, (x, y) in enumerate(zip(run_numbers, success_rates)):
        if y < 100:  # Only annotate if not 100%
            ax4.annotate(f'{y:.0f}%', xy=(x, y), xytext=(0, 10),
                        textcoords='offset points', ha='center', fontsize=9)
        else:
            ax4.plot(x, y, 'go', markersize=10)  # Green dot for 100%

    plt.tight_layout()
    chart_path = output_dir / 'multi_metric_comparison.png'
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    print(f"✅ Saved: {chart_path}")
    plt.close()

    # Create execution time breakdown (simplified - we don't have timing data)
    fig, ax = plt.subplots(figsize=(12, 6))

    # Use query counts as proxy for execution time
    bar_width = 0.6
    bars = ax.bar(run_numbers, query_counts, bar_width,
                   label='Query Execution', color='#F18F01', alpha=0.8)

    # Add value labels on bars
    for bar, queries in zip(bars, query_counts):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
               f'{queries}',
               ha='center', va='bottom', fontsize=11, fontweight='bold')

    # Add average line info box
    avg_queries_val = sum(query_counts) / len(query_counts)
    min_queries = min(query_counts)
    max_queries = max(query_counts)

    textstr = f'Avg: {avg_queries_val:.1f}\nMin: {min_queries}\nMax: {max_queries}'
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
    ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=10,
           verticalalignment='top', bbox=props)

    ax.set_xlabel('Run Number', fontsize=12)
    ax.set_ylabel('Queries Executed', fontsize=12)
    ax.set_title('Query Execution Per Run', fontsize=14, fontweight='bold')
    ax.set_xticks(run_numbers)
    ax.grid(True, axis='y', alpha=0.3)

    plt.tight_layout()
    breakdown_path = output_dir / 'execution_time_breakdown.png'
    plt.savefig(breakdown_path, dpi=150, bbox_inches='tight')
    print(f"✅ Saved: {breakdown_path}")
    plt.close()


def main():
    print("=" * 80)
    print("REPROCESSING BENCHMARK RESULTS WITH FIXED METRICS EXTRACTION")
    print("=" * 80)

    # Find all result files
    result_files = sorted(glob.glob('/opt/genpod/benchmark_results/run_*_output.json'))

    if not result_files:
        print("❌ No benchmark result files found!")
        return

    print(f"\nFound {len(result_files)} result files")

    all_metrics = []

    # Extract metrics from each file
    for i, filepath in enumerate(result_files, 1):
        with open(filepath) as f:
            result = json.load(f)

        metrics = extract_metrics_from_result(result, i)
        all_metrics.append(metrics)

        print(f"\nRUN {i}:")
        print(f"  Subqueries: {metrics['successful_subqueries']}/{metrics['total_subqueries']} successful")
        print(f"  Queries: {metrics['total_queries_executed']}")
        print(f"  Tokens: {metrics['total_tokens_used']:,}")
        print(f"  Cost: ${metrics['total_cost']:.4f}")

    # Save corrected metrics JSON
    output_dir = Path('/opt/genpod/benchmark_results_workerz')
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_file = output_dir / 'benchmark_metrics.json'
    with open(metrics_file, 'w') as f:
        json.dump(all_metrics, f, indent=2)
    print(f"\n✅ Saved corrected metrics: {metrics_file}")

    # Generate charts
    print("\nGenerating charts...")
    generate_charts(all_metrics, output_dir)

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS:")
    print("=" * 80)

    total_queries = sum(m['total_queries_executed'] for m in all_metrics)
    total_tokens = sum(m['total_tokens_used'] for m in all_metrics)
    total_cost = sum(m['total_cost'] for m in all_metrics)
    avg_success_rate = sum(m['successful_subqueries'] / max(m['total_subqueries'], 1)
                           for m in all_metrics) / len(all_metrics) * 100

    print(f"Total Queries: {total_queries}")
    print(f"Avg Queries/Run: {total_queries / len(all_metrics):.1f}")
    print(f"Total Tokens: {total_tokens:,}")
    print(f"Avg Tokens/Run: {total_tokens / len(all_metrics):,.0f}")
    print(f"Total Cost: ${total_cost:.4f}")
    print(f"Avg Cost/Run: ${total_cost / len(all_metrics):.4f}")
    print(f"Avg Success Rate: {avg_success_rate:.1f}%")
    print("=" * 80)

    print("\n✅ Reprocessing complete!")
    print(f"📊 Charts saved to: {output_dir}")


if __name__ == '__main__':
    main()

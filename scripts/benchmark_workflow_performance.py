#!/usr/bin/env python3
"""
Performance Benchmarking Script for Adaptive CPG Agent Workflow

Runs the same query multiple times and generates performance comparison graphs.
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from src.core.workflow.adaptive_cpg_workflow import execute_adaptive_cpg_workflow


async def run_single_benchmark(run_number: int, query: str) -> Dict[str, Any]:
    """
    Run a single workflow execution and collect metrics.

    Args:
        run_number: The run iteration number
        query: The user query to execute

    Returns:
        Dictionary containing all performance metrics for this run
    """
    print(f"\n{'='*80}")
    print(f"RUN {run_number}/5: Starting benchmark")
    print(f"{'='*80}")

    start_time = time.time()

    # Execute workflow
    result = await execute_adaptive_cpg_workflow(
        user_query=query,
        project_name="HelloWorldApp",
        neo4j_config="neo4j_config.json",
        use_schema_tools=True  # 🛠️ V8: Enable tool-based schema discovery
    )

    end_time = time.time()
    total_time = end_time - start_time

    # Save complete workflow output as JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(f"benchmark_results_enhanced_V2/run_{run_number}_output.json")
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    print(f"✅ Saved complete workflow output: {output_file}")

    # Extract metrics from result
    metrics = {
        'run_number': run_number,
        'timestamp': datetime.now().isoformat(),
        'total_time_seconds': round(total_time, 2),
        'success': result.get('success', False),
        'final_answer': result.get('final_answer', ''),
        'confidence_score': result.get('confidence_score', 0.0),
        'workflow_output_file': str(output_file),

        # Phase timing
        'phase0_time': 0.0,
        'phase1_time': 0.0,

        # Subquery metrics
        'total_subqueries': 0,
        'successful_subqueries': 0,
        'total_queries_executed': 0,
        'total_tokens_used': 0,
        'total_cost': 0.0,

        # Per-subquery details
        'subquery_details': []
    }

    # Extract phase timing from trace if available
    if 'trace_file' in result:
        try:
            trace_path = Path(result['trace_file'])
            if trace_path.exists():
                with open(trace_path, 'r') as f:
                    trace_data = json.load(f)

                # Extract phase 0 timing
                decomp_steps = [s for s in trace_data.get('steps', [])
                               if s.get('step_name') == 'phase0_decomposition']
                if decomp_steps:
                    metrics['phase0_time'] = decomp_steps[0].get('duration_seconds', 0.0)

                # Extract phase 1 timing
                exec_steps = [s for s in trace_data.get('steps', [])
                             if s.get('step_name') == 'phase1_execution']
                if exec_steps:
                    metrics['phase1_time'] = exec_steps[0].get('duration_seconds', 0.0)
        except Exception as e:
            print(f"Warning: Could not extract trace data: {e}")

    # Extract metrics from actual workflow output structure
    # The workflow uses: tokens_per_approach, cost_per_approach, approach_statuses, etc.

    # Get per-approach data
    tokens_per_approach = result.get('tokens_per_approach', {})
    cost_per_approach = result.get('cost_per_approach', {})
    approach_statuses = result.get('approach_statuses', {})
    approach_traces = result.get('approach_execution_traces', {})
    failed_approaches = result.get('failed_approaches', [])

    # Total subqueries = number of approaches
    metrics['total_subqueries'] = len(tokens_per_approach)

    # Successful subqueries = approaches with "success" status
    metrics['successful_subqueries'] = sum(
        1 for status in approach_statuses.values() if status == 'success'
    )

    # Use totals from workflow output (already calculated correctly)
    metrics['total_queries_executed'] = len(result.get('all_executed_queries', []))
    metrics['total_tokens_used'] = result.get('total_tokens_used', 0)
    metrics['total_cost'] = result.get('total_estimated_cost_usd', 0.0)

    # Build per-subquery details
    for approach_idx in sorted(tokens_per_approach.keys(), key=lambda x: int(x)):
        approach_tokens = tokens_per_approach.get(approach_idx, 0)
        approach_cost = cost_per_approach.get(approach_idx, 0.0)
        approach_status = approach_statuses.get(approach_idx, 'unknown')

        # Get queries executed for this approach
        trace = approach_traces.get(approach_idx, {})
        queries_executed = trace.get('queries_executed', 0)

        subquery_detail = {
            'name': f'Approach_{approach_idx}',
            'iterations': 1,  # Current workflow doesn't track iterations per approach
            'queries_executed': queries_executed,
            'tokens_used': approach_tokens,
            'cost': round(approach_cost, 4),
            'status': approach_status,
            'quality_grade': 0.0,  # Not available in current output
            'confidence': 'Unknown'  # Not available in current output
        }
        metrics['subquery_details'].append(subquery_detail)

    # Round totals
    metrics['total_cost'] = round(metrics['total_cost'], 4)

    print(f"\n{'='*80}")
    print(f"RUN {run_number}/5: Completed in {total_time:.2f}s")
    print(f"  Subqueries: {metrics['successful_subqueries']}/{metrics['total_subqueries']} successful")
    print(f"  Queries: {metrics['total_queries_executed']} total")
    print(f"  Tokens: {metrics['total_tokens_used']:,}")
    print(f"  Cost: ${metrics['total_cost']:.4f}")
    print(f"{'='*80}")

    return metrics


async def run_benchmark_suite(query: str, num_runs: int = 5) -> List[Dict[str, Any]]:
    """
    Run multiple benchmark iterations.

    Args:
        query: The user query to benchmark
        num_runs: Number of times to run the benchmark

    Returns:
        List of metrics dictionaries, one per run
    """
    all_metrics = []

    print(f"\n{'#'*80}")
    print(f"BENCHMARK SUITE: Running {num_runs} iterations")
    print(f"Query: {query}")
    print(f"{'#'*80}")

    for i in range(1, num_runs + 1):
        metrics = await run_single_benchmark(i, query)
        all_metrics.append(metrics)

        # Small delay between runs to avoid rate limiting
        if i < num_runs:
            print(f"\nWaiting 2 seconds before next run...")
            await asyncio.sleep(2)

    return all_metrics


def generate_performance_graphs(all_metrics: List[Dict[str, Any]], output_dir: Path):
    """
    Generate comprehensive performance comparison graphs.

    Args:
        all_metrics: List of metrics from all runs
        output_dir: Directory to save graphs
    """
    output_dir.mkdir(exist_ok=True)

    # Extract data for plotting
    run_numbers = [m['run_number'] for m in all_metrics]
    total_times = [m['total_time_seconds'] for m in all_metrics]
    phase0_times = [m['phase0_time'] for m in all_metrics]
    phase1_times = [m['phase1_time'] for m in all_metrics]
    query_counts = [m['total_queries_executed'] for m in all_metrics]
    token_counts = [m['total_tokens_used'] for m in all_metrics]
    costs = [m['total_cost'] for m in all_metrics]
    success_rates = [m['successful_subqueries'] / max(m['total_subqueries'], 1) * 100
                     for m in all_metrics]

    # Set up the style
    plt.style.use('seaborn-v0_8-darkgrid')
    colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#6A994E']

    # Figure 1: Execution Time Breakdown (Stacked Bar)
    fig1, ax1 = plt.subplots(figsize=(12, 6))

    other_times = [total - (p0 + p1) for total, p0, p1 in zip(total_times, phase0_times, phase1_times)]

    x = np.arange(len(run_numbers))
    width = 0.6

    p1 = ax1.bar(x, phase0_times, width, label='Phase 0 (Decomposition)', color='#2E86AB')
    p2 = ax1.bar(x, phase1_times, width, bottom=phase0_times, label='Phase 1 (Execution)', color='#A23B72')
    p3 = ax1.bar(x, other_times, width,
                 bottom=[p0 + p1 for p0, p1 in zip(phase0_times, phase1_times)],
                 label='Other (Synthesis, I/O)', color='#F18F01')

    # Add total time labels on top of bars
    for i, (x_pos, total) in enumerate(zip(x, total_times)):
        ax1.text(x_pos, total + 1, f'{total:.1f}s', ha='center', va='bottom', fontweight='bold')

    ax1.set_xlabel('Run Number', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Time (seconds)', fontsize=12, fontweight='bold')
    ax1.set_title('Execution Time Breakdown Across Runs', fontsize=14, fontweight='bold', pad=20)
    ax1.set_xticks(x)
    ax1.set_xticklabels([f'Run {i}' for i in run_numbers])
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)

    # Add statistics box
    avg_time = np.mean(total_times)
    std_time = np.std(total_times)
    stats_text = f'Avg: {avg_time:.1f}s ± {std_time:.1f}s\nMin: {min(total_times):.1f}s\nMax: {max(total_times):.1f}s'
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes,
             fontsize=10, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    fig1.savefig(output_dir / 'execution_time_breakdown.png', dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_dir / 'execution_time_breakdown.png'}")
    plt.close(fig1)

    # Figure 2: Multi-Metric Comparison (2x2 grid)
    fig2, ((ax2a, ax2b), (ax2c, ax2d)) = plt.subplots(2, 2, figsize=(14, 10))

    # Query Count
    ax2a.plot(run_numbers, query_counts, marker='o', linewidth=2, markersize=8, color='#2E86AB')
    ax2a.fill_between(run_numbers, query_counts, alpha=0.3, color='#2E86AB')
    ax2a.set_xlabel('Run Number', fontweight='bold')
    ax2a.set_ylabel('Total Queries', fontweight='bold')
    ax2a.set_title('Query Count Per Run', fontweight='bold', pad=10)
    ax2a.grid(True, alpha=0.3)
    ax2a.axhline(y=np.mean(query_counts), color='red', linestyle='--', linewidth=1, label=f'Avg: {np.mean(query_counts):.1f}')
    ax2a.legend()

    # Token Usage
    ax2b.plot(run_numbers, [t/1000 for t in token_counts], marker='s', linewidth=2, markersize=8, color='#A23B72')
    ax2b.fill_between(run_numbers, [t/1000 for t in token_counts], alpha=0.3, color='#A23B72')
    ax2b.set_xlabel('Run Number', fontweight='bold')
    ax2b.set_ylabel('Tokens (thousands)', fontweight='bold')
    ax2b.set_title('Token Usage Per Run', fontweight='bold', pad=10)
    ax2b.grid(True, alpha=0.3)
    ax2b.axhline(y=np.mean(token_counts)/1000, color='red', linestyle='--', linewidth=1,
                 label=f'Avg: {np.mean(token_counts)/1000:.1f}K')
    ax2b.legend()

    # Cost
    ax2c.plot(run_numbers, costs, marker='^', linewidth=2, markersize=8, color='#F18F01')
    ax2c.fill_between(run_numbers, costs, alpha=0.3, color='#F18F01')
    ax2c.set_xlabel('Run Number', fontweight='bold')
    ax2c.set_ylabel('Cost (USD)', fontweight='bold')
    ax2c.set_title('Execution Cost Per Run', fontweight='bold', pad=10)
    ax2c.grid(True, alpha=0.3)
    ax2c.axhline(y=np.mean(costs), color='red', linestyle='--', linewidth=1,
                 label=f'Avg: ${np.mean(costs):.4f}')
    ax2c.legend()

    # Success Rate
    ax2d.bar(run_numbers, success_rates, color='#6A994E', alpha=0.7, edgecolor='black', linewidth=1.5)
    ax2d.set_xlabel('Run Number', fontweight='bold')
    ax2d.set_ylabel('Success Rate (%)', fontweight='bold')
    ax2d.set_title('Subquery Success Rate Per Run', fontweight='bold', pad=10)
    ax2d.set_ylim(0, 105)
    ax2d.grid(True, alpha=0.3, axis='y')
    ax2d.axhline(y=100, color='green', linestyle='--', linewidth=2, label='Target: 100%')
    for i, (run, rate) in enumerate(zip(run_numbers, success_rates)):
        ax2d.text(run, rate + 2, f'{rate:.0f}%', ha='center', va='bottom', fontweight='bold')
    ax2d.legend()

    plt.tight_layout()
    fig2.savefig(output_dir / 'multi_metric_comparison.png', dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_dir / 'multi_metric_comparison.png'}")
    plt.close(fig2)

    # Figure 3: Per-Subquery Performance Heatmap
    fig3, ax3 = plt.subplots(figsize=(12, 8))

    # Extract subquery names from first run (should be consistent)
    subquery_names = [sq['name'] for sq in all_metrics[0]['subquery_details']]
    num_subqueries = len(subquery_names)

    # Build matrix: rows = subqueries, cols = runs, values = quality_grade
    quality_matrix = []
    for sq_idx in range(num_subqueries):
        row = []
        for run_metrics in all_metrics:
            sq_details = run_metrics['subquery_details']
            if sq_idx < len(sq_details):
                row.append(sq_details[sq_idx]['quality_grade'])
            else:
                row.append(0.0)
        quality_matrix.append(row)

    quality_matrix = np.array(quality_matrix)

    # Create heatmap
    im = ax3.imshow(quality_matrix, cmap='RdYlGn', aspect='auto', vmin=0, vmax=1)

    # Set ticks and labels
    ax3.set_xticks(np.arange(len(run_numbers)))
    ax3.set_yticks(np.arange(num_subqueries))
    ax3.set_xticklabels([f'Run {i}' for i in run_numbers])
    ax3.set_yticklabels(subquery_names)

    # Add colorbar
    cbar = plt.colorbar(im, ax=ax3)
    cbar.set_label('Quality Grade', rotation=270, labelpad=20, fontweight='bold')

    # Add text annotations
    for i in range(num_subqueries):
        for j in range(len(run_numbers)):
            text = ax3.text(j, i, f'{quality_matrix[i, j]:.2f}',
                           ha='center', va='center', color='black', fontweight='bold')

    ax3.set_title('Subquery Quality Grades Across Runs', fontsize=14, fontweight='bold', pad=20)
    ax3.set_xlabel('Run Number', fontweight='bold')
    ax3.set_ylabel('Subquery', fontweight='bold')

    plt.tight_layout()
    fig3.savefig(output_dir / 'subquery_quality_heatmap.png', dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_dir / 'subquery_quality_heatmap.png'}")
    plt.close(fig3)

    print("\n✅ All performance graphs generated successfully!")


def generate_summary_report(all_metrics: List[Dict[str, Any]], output_path: Path):
    """
    Generate a markdown summary report.

    Args:
        all_metrics: List of metrics from all runs
        output_path: Path to save the markdown report
    """
    with open(output_path, 'w') as f:
        f.write("# Workflow Performance Benchmark Report\n\n")
        f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Query**: {all_metrics[0].get('query', 'N/A')}\n\n")
        f.write(f"**Number of Runs**: {len(all_metrics)}\n\n")

        f.write("---\n\n")
        f.write("## Overall Statistics\n\n")

        # Calculate statistics
        total_times = [m['total_time_seconds'] for m in all_metrics]
        query_counts = [m['total_queries_executed'] for m in all_metrics]
        token_counts = [m['total_tokens_used'] for m in all_metrics]
        costs = [m['total_cost'] for m in all_metrics]
        success_rates = [m['successful_subqueries'] / max(m['total_subqueries'], 1) * 100
                        for m in all_metrics]

        f.write("| Metric | Average | Std Dev | Min | Max |\n")
        f.write("|--------|---------|---------|-----|-----|\n")
        f.write(f"| **Execution Time (s)** | {np.mean(total_times):.2f} | {np.std(total_times):.2f} | {min(total_times):.2f} | {max(total_times):.2f} |\n")
        f.write(f"| **Query Count** | {np.mean(query_counts):.1f} | {np.std(query_counts):.1f} | {min(query_counts)} | {max(query_counts)} |\n")
        f.write(f"| **Token Usage** | {np.mean(token_counts):.0f} | {np.std(token_counts):.0f} | {min(token_counts)} | {max(token_counts)} |\n")
        f.write(f"| **Cost (USD)** | ${np.mean(costs):.4f} | ${np.std(costs):.4f} | ${min(costs):.4f} | ${max(costs):.4f} |\n")
        f.write(f"| **Success Rate (%)** | {np.mean(success_rates):.1f} | {np.std(success_rates):.1f} | {min(success_rates):.1f} | {max(success_rates):.1f} |\n\n")

        f.write("---\n\n")
        f.write("## Per-Run Details\n\n")

        for metrics in all_metrics:
            f.write(f"### Run {metrics['run_number']}\n\n")
            f.write(f"- **Total Time**: {metrics['total_time_seconds']:.2f}s\n")
            f.write(f"  - Phase 0 (Decomposition): {metrics['phase0_time']:.2f}s\n")
            f.write(f"  - Phase 1 (Execution): {metrics['phase1_time']:.2f}s\n")
            f.write(f"- **Subqueries**: {metrics['successful_subqueries']}/{metrics['total_subqueries']} successful\n")
            f.write(f"- **Total Queries**: {metrics['total_queries_executed']}\n")
            f.write(f"- **Total Tokens**: {metrics['total_tokens_used']:,}\n")
            f.write(f"- **Total Cost**: ${metrics['total_cost']:.4f}\n")
            f.write(f"- **Confidence Score**: {metrics['confidence_score']:.2f}\n")
            f.write(f"- **Workflow Output**: `{metrics.get('workflow_output_file', 'N/A')}`\n\n")

            # Include final answer
            final_answer = metrics.get('final_answer', '')
            if final_answer:
                f.write(f"**Final Answer**:\n")
                f.write(f"> {final_answer}\n\n")

            f.write("**Subquery Breakdown**:\n\n")
            for sq in metrics['subquery_details']:
                f.write(f"- **{sq['name']}**:\n")
                f.write(f"  - Iterations: {sq['iterations']}\n")
                f.write(f"  - Queries: {sq['queries_executed']}\n")
                f.write(f"  - Tokens: {sq['tokens_used']:,}\n")
                f.write(f"  - Cost: ${sq['cost']:.4f}\n")
                f.write(f"  - Quality: {sq['quality_grade']:.2f}\n")
                f.write(f"  - Confidence: {sq['confidence']}\n\n")

            f.write("---\n\n")

    print(f"✅ Saved: {output_path}")


async def main():
    """Main entry point for benchmark suite."""
    # Configuration
    # QUERY = "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?"
    QUERY = "What are the two parameters passed to Helper.FormatMessage?"
    # QUERY = "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?"
    NUM_RUNS = 5
    OUTPUT_DIR = Path("benchmark_results_enhanced_V2")

    # Run benchmarks
    all_metrics = await run_benchmark_suite(QUERY, NUM_RUNS)

    # Save raw metrics
    OUTPUT_DIR.mkdir(exist_ok=True)
    metrics_file = OUTPUT_DIR / "benchmark_metrics.json"
    with open(metrics_file, 'w') as f:
        json.dump(all_metrics, f, indent=2)
    print(f"\n✅ Saved raw metrics: {metrics_file}")

    # Generate graphs
    print("\n" + "="*80)
    print("GENERATING PERFORMANCE GRAPHS")
    print("="*80)
    generate_performance_graphs(all_metrics, OUTPUT_DIR)

    # Generate summary report
    print("\n" + "="*80)
    print("GENERATING SUMMARY REPORT")
    print("="*80)
    report_file = OUTPUT_DIR / "benchmark_report.md"
    generate_summary_report(all_metrics, report_file)

    print("\n" + "#"*80)
    print("BENCHMARK SUITE COMPLETED")
    print("#"*80)
    print(f"\nResults saved to: {OUTPUT_DIR.absolute()}")
    print(f"\n📊 Summary Files:")
    print(f"  - benchmark_metrics.json - Aggregated metrics from all runs")
    print(f"  - benchmark_report.md - Detailed markdown report")
    print(f"\n📈 Performance Graphs:")
    print(f"  - execution_time_breakdown.png - Phase timing breakdown")
    print(f"  - multi_metric_comparison.png - Query/token/cost/success metrics")
    print(f"  - subquery_quality_heatmap.png - Quality grades across runs")
    print(f"\n📝 Individual Run Outputs:")
    for i in range(1, NUM_RUNS + 1):
        print(f"  - run_{i}_output.json - Complete workflow output for run {i}")
    print(f"\n💡 To view a specific run's final answer:")
    print(f"  cat {OUTPUT_DIR}/run_1_output.json | jq '.final_answer'")


if __name__ == "__main__":
    asyncio.run(main())

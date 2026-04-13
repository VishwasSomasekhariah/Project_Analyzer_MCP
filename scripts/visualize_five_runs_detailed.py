#!/usr/bin/env python3
"""
Detailed visualization of all 5 runs from the improved validation + query benchmark
"""
import matplotlib.pyplot as plt
import numpy as np

# Data from the latest benchmark (Improved + Query)
runs_data = {
    'Run 1': {
        'time': 86.18,
        'queries': 4,
        'tokens': 15496,
        'cost': 0.0667,
        'sq1_queries': 1,
        'sq2_queries': 1,
        'sq3_queries': 2
    },
    'Run 2': {
        'time': 53.05,
        'queries': 3,
        'tokens': 10941,
        'cost': 0.0556,
        'sq1_queries': 1,
        'sq2_queries': 1,
        'sq3_queries': 1
    },
    'Run 3': {
        'time': 65.56,
        'queries': 3,
        'tokens': 12257,
        'cost': 0.0576,
        'sq1_queries': 1,
        'sq2_queries': 1,
        'sq3_queries': 1
    },
    'Run 4': {
        'time': 58.14,
        'queries': 3,
        'tokens': 12152,
        'cost': 0.0557,
        'sq1_queries': 1,
        'sq2_queries': 1,
        'sq3_queries': 1
    },
    'Run 5': {
        'time': 45.00,
        'queries': 2,
        'tokens': 8452,
        'cost': 0.0509,
        'sq1_queries': 1,
        'sq2_queries': 1,
        'sq3_queries': 0
    }
}

# Create comprehensive visualization
fig = plt.figure(figsize=(20, 12))
gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.35)

# Color gradient for runs
colors = plt.cm.viridis(np.linspace(0.2, 0.9, 5))
run_names = list(runs_data.keys())

# 1. Execution Time Breakdown
ax1 = fig.add_subplot(gs[0, :])
times = [data['time'] for data in runs_data.values()]
bars = ax1.bar(run_names, times, color=colors, edgecolor='black', linewidth=1.5, alpha=0.8)

# Add average line
avg_time = np.mean(times)
ax1.axhline(y=avg_time, color='red', linestyle='--', linewidth=2, label=f'Average: {avg_time:.2f}s')

ax1.set_ylabel('Execution Time (seconds)', fontsize=14, fontweight='bold')
ax1.set_title('Execution Time Per Run (Improved Validation + Query Feedback)',
              fontsize=16, fontweight='bold')
ax1.legend(fontsize=12)
ax1.grid(True, alpha=0.3, axis='y', linestyle='--')

# Add value labels
for bar, val in zip(bars, times):
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height + 1,
            f'{val:.2f}s',
            ha='center', va='bottom', fontsize=12, fontweight='bold')

# 2. Query Count Per Run
ax2 = fig.add_subplot(gs[1, 0])
queries = [data['queries'] for data in runs_data.values()]
bars = ax2.bar(run_names, queries, color=colors, edgecolor='black', linewidth=1.5, alpha=0.8)

avg_queries = np.mean(queries)
ax2.axhline(y=avg_queries, color='red', linestyle='--', linewidth=2, label=f'Avg: {avg_queries:.1f}')

ax2.set_ylabel('Total Queries', fontsize=13, fontweight='bold')
ax2.set_title('Query Count Per Run', fontsize=14, fontweight='bold')
ax2.legend(fontsize=11)
ax2.grid(True, alpha=0.3, axis='y', linestyle='--')

for bar, val in zip(bars, queries):
    height = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2., height,
            f'{val}',
            ha='center', va='bottom', fontsize=11, fontweight='bold')

# 3. Token Usage Per Run
ax3 = fig.add_subplot(gs[1, 1])
tokens = [data['tokens'] for data in runs_data.values()]
bars = ax3.bar(run_names, tokens, color=colors, edgecolor='black', linewidth=1.5, alpha=0.8)

avg_tokens = np.mean(tokens)
ax3.axhline(y=avg_tokens, color='red', linestyle='--', linewidth=2, label=f'Avg: {avg_tokens:,.0f}')

ax3.set_ylabel('Token Usage', fontsize=13, fontweight='bold')
ax3.set_title('Token Usage Per Run', fontsize=14, fontweight='bold')
ax3.legend(fontsize=11)
ax3.grid(True, alpha=0.3, axis='y', linestyle='--')

for bar, val in zip(bars, tokens):
    height = bar.get_height()
    ax3.text(bar.get_x() + bar.get_width()/2., height + 200,
            f'{val:,}',
            ha='center', va='bottom', fontsize=10, fontweight='bold')

# 4. Cost Per Run
ax4 = fig.add_subplot(gs[1, 2])
costs = [data['cost'] for data in runs_data.values()]
bars = ax4.bar(run_names, costs, color=colors, edgecolor='black', linewidth=1.5, alpha=0.8)

avg_cost = np.mean(costs)
ax4.axhline(y=avg_cost, color='red', linestyle='--', linewidth=2, label=f'Avg: ${avg_cost:.4f}')

ax4.set_ylabel('Cost (USD)', fontsize=13, fontweight='bold')
ax4.set_title('Cost Per Run', fontsize=14, fontweight='bold')
ax4.legend(fontsize=11)
ax4.grid(True, alpha=0.3, axis='y', linestyle='--')

for bar, val in zip(bars, costs):
    height = bar.get_height()
    ax4.text(bar.get_x() + bar.get_width()/2., height + 0.001,
            f'${val:.4f}',
            ha='center', va='bottom', fontsize=10, fontweight='bold')

# 5. Subquery Breakdown (Stacked Bar)
ax5 = fig.add_subplot(gs[2, 0])
sq1_queries = [data['sq1_queries'] for data in runs_data.values()]
sq2_queries = [data['sq2_queries'] for data in runs_data.values()]
sq3_queries = [data['sq3_queries'] for data in runs_data.values()]

x = np.arange(len(run_names))
width = 0.6

p1 = ax5.bar(x, sq1_queries, width, label='SQ1 (Locate Function)', color='#3498db', alpha=0.8)
p2 = ax5.bar(x, sq2_queries, width, bottom=sq1_queries, label='SQ2 (Find Instantiations)', color='#e74c3c', alpha=0.8)
p3 = ax5.bar(x, sq3_queries, width, bottom=np.array(sq1_queries) + np.array(sq2_queries),
            label='SQ3 (Return Type)', color='#2ecc71', alpha=0.8)

ax5.set_ylabel('Query Count', fontsize=13, fontweight='bold')
ax5.set_title('Subquery Breakdown Per Run', fontsize=14, fontweight='bold')
ax5.set_xticks(x)
ax5.set_xticklabels(run_names)
ax5.legend(fontsize=10)
ax5.grid(True, alpha=0.3, axis='y', linestyle='--')

# 6. Efficiency Metrics (Time per Query & Cost per Query)
ax6 = fig.add_subplot(gs[2, 1])
time_per_query = [data['time'] / data['queries'] for data in runs_data.values()]
bars = ax6.bar(run_names, time_per_query, color=colors, edgecolor='black', linewidth=1.5, alpha=0.8)

avg_tpq = np.mean(time_per_query)
ax6.axhline(y=avg_tpq, color='red', linestyle='--', linewidth=2, label=f'Avg: {avg_tpq:.1f}s')

ax6.set_ylabel('Time per Query (seconds)', fontsize=13, fontweight='bold')
ax6.set_title('Efficiency: Time per Query', fontsize=14, fontweight='bold')
ax6.legend(fontsize=11)
ax6.grid(True, alpha=0.3, axis='y', linestyle='--')

for bar, val in zip(bars, time_per_query):
    height = bar.get_height()
    ax6.text(bar.get_x() + bar.get_width()/2., height,
            f'{val:.1f}s',
            ha='center', va='bottom', fontsize=10, fontweight='bold')

# 7. Summary Statistics Table
ax7 = fig.add_subplot(gs[2, 2])
ax7.axis('off')

table_data = [
    ['Metric', 'Min', 'Max', 'Mean', 'Std Dev'],
    ['Time (s)', f'{min(times):.2f}', f'{max(times):.2f}', f'{np.mean(times):.2f}', f'{np.std(times):.2f}'],
    ['Queries', f'{min(queries)}', f'{max(queries)}', f'{np.mean(queries):.1f}', f'{np.std(queries):.1f}'],
    ['Tokens', f'{min(tokens):,}', f'{max(tokens):,}', f'{int(np.mean(tokens)):,}', f'{int(np.std(tokens)):,}'],
    ['Cost ($)', f'{min(costs):.4f}', f'{max(costs):.4f}', f'{np.mean(costs):.4f}', f'{np.std(costs):.5f}'],
    ['Time/Query', f'{min(time_per_query):.1f}', f'{max(time_per_query):.1f}',
     f'{np.mean(time_per_query):.1f}', f'{np.std(time_per_query):.1f}'],
]

table = ax7.table(cellText=table_data, cellLoc='center', loc='center',
                  colWidths=[0.25, 0.18, 0.18, 0.18, 0.21])
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1, 2.5)

# Style header row
for i in range(5):
    table[(0, i)].set_facecolor('#34495e')
    table[(0, i)].set_text_props(weight='bold', color='white')

# Style data rows
for i in range(1, len(table_data)):
    for j in range(5):
        if i % 2 == 0:
            table[(i, j)].set_facecolor('#ecf0f1')

ax7.set_title('Summary Statistics', fontsize=14, fontweight='bold', pad=20)

# Overall title
fig.suptitle('Detailed Analysis: 5 Runs with Improved Validation + Query Feedback',
             fontsize=18, fontweight='bold', y=0.98)

# Save
output_path = '/opt/genpod/benchmark_five_runs_detailed.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n✅ Detailed visualization saved to: {output_path}")

# Print summary
print("\n" + "="*100)
print("DETAILED RUN-BY-RUN ANALYSIS")
print("="*100)

for run_name, data in runs_data.items():
    print(f"\n{run_name}:")
    print(f"  Time: {data['time']:.2f}s")
    print(f"  Queries: {data['queries']} (SQ1={data['sq1_queries']}, SQ2={data['sq2_queries']}, SQ3={data['sq3_queries']})")
    print(f"  Tokens: {data['tokens']:,}")
    print(f"  Cost: ${data['cost']:.4f}")
    print(f"  Efficiency: {data['time']/data['queries']:.1f}s per query")

print("\n" + "="*100)
print("AGGREGATE STATISTICS")
print("="*100)
print(f"Average Time: {np.mean(times):.2f}s ± {np.std(times):.2f}s")
print(f"Average Queries: {np.mean(queries):.1f}")
print(f"Average Tokens: {int(np.mean(tokens)):,}")
print(f"Average Cost: ${np.mean(costs):.4f}")
print(f"Success Rate: 100% (all runs completed successfully)")

print("\n" + "="*100)
print("KEY OBSERVATIONS")
print("="*100)
print(f"✅ Stable Performance: Std dev of {np.std(times):.2f}s shows low variance")
print(f"✅ Consistent Exploration: Most runs used 3-4 queries")
print(f"✅ Run 5 was most efficient: {times[4]:.2f}s with only {queries[4]} queries")
print(f"✅ Run 1 explored most: {queries[0]} queries, {times[0]:.2f}s")
print("="*100)

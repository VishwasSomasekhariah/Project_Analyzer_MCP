#!/usr/bin/env python3
"""
Visualize benchmark timing comparison across ALL three validation feedback approaches
"""
import matplotlib.pyplot as plt
import numpy as np

# Data from ALL three benchmarks
benchmarks = {
    'Original\nValidation': {
        'runs': [77.41, 42.10, 77.34, 30.78, 37.45],
        'avg_queries': 1.6,
        'avg_tokens': 7552,
        'avg_cost': 0.0439,
        'description': 'Errors at bottom, no failed query'
    },
    'Improved\n(no query)': {
        'runs': [118.36, 53.41, 409.01, 57.97, 34.61],
        'avg_queries': 3.2,
        'avg_tokens': 12729,
        'avg_cost': 0.0620,
        'description': 'Errors at top, forceful, no failed query'
    },
    'Improved\n+ Query': {
        'runs': [86.18, 53.05, 65.56, 58.14, 45.00],
        'avg_queries': 3.2,
        'avg_tokens': 12564,
        'avg_cost': 0.0582,
        'description': 'Errors at top, forceful, WITH failed query'
    }
}

# Create figure
fig = plt.figure(figsize=(18, 11))
gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.35)

# Color scheme
colors = ['#3498db', '#e74c3c', '#2ecc71']

# 1. Execution Time Per Run (Line Chart)
ax1 = fig.add_subplot(gs[0, :])
for i, (name, data) in enumerate(benchmarks.items()):
    runs = data['runs']
    ax1.plot(range(1, len(runs) + 1), runs, marker='o', linewidth=2.5,
             markersize=10, label=name, color=colors[i], alpha=0.8)

ax1.set_xlabel('Run Number', fontsize=13, fontweight='bold')
ax1.set_ylabel('Execution Time (seconds)', fontsize=13, fontweight='bold')
ax1.set_title('Execution Time Per Run - All Three Approaches', fontsize=15, fontweight='bold')
ax1.legend(loc='upper right', fontsize=11)
ax1.grid(True, alpha=0.3, linestyle='--')
ax1.set_xticks(range(1, 6))
ax1.set_ylim(0, 450)

# 2. Average Time Comparison (Bar Chart)
ax2 = fig.add_subplot(gs[1, 0])
names = list(benchmarks.keys())
avg_times = [np.mean(data['runs']) for data in benchmarks.values()]

bars = ax2.bar(names, avg_times, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)
ax2.set_ylabel('Average Time (seconds)', fontsize=12, fontweight='bold')
ax2.set_title('Average Execution Time', fontsize=13, fontweight='bold')
ax2.grid(True, alpha=0.3, axis='y', linestyle='--')
ax2.set_ylim(0, max(avg_times) * 1.2)

# Add value labels
for bar, val in zip(bars, avg_times):
    height = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2., height,
            f'{val:.1f}s',
            ha='center', va='bottom', fontsize=11, fontweight='bold')

# 3. Query Count Comparison
ax3 = fig.add_subplot(gs[1, 1])
query_counts = [data['avg_queries'] for data in benchmarks.values()]
bars = ax3.bar(names, query_counts, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)
ax3.set_ylabel('Average Queries', fontsize=12, fontweight='bold')
ax3.set_title('Query Count Comparison', fontsize=13, fontweight='bold')
ax3.grid(True, alpha=0.3, axis='y', linestyle='--')

for bar, val in zip(bars, query_counts):
    height = bar.get_height()
    ax3.text(bar.get_x() + bar.get_width()/2., height,
            f'{val:.1f}',
            ha='center', va='bottom', fontsize=11, fontweight='bold')

# 4. Cost Comparison
ax4 = fig.add_subplot(gs[1, 2])
costs = [data['avg_cost'] for data in benchmarks.values()]
bars = ax4.bar(names, costs, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)
ax4.set_ylabel('Average Cost (USD)', fontsize=12, fontweight='bold')
ax4.set_title('Cost Comparison', fontsize=13, fontweight='bold')
ax4.grid(True, alpha=0.3, axis='y', linestyle='--')

for bar, val in zip(bars, costs):
    height = bar.get_height()
    ax4.text(bar.get_x() + bar.get_width()/2., height,
            f'${val:.4f}',
            ha='center', va='bottom', fontsize=10, fontweight='bold')

# 5. Time Distribution (Box Plot)
ax5 = fig.add_subplot(gs[2, 0])
data_to_plot = [data['runs'] for data in benchmarks.values()]
bp = ax5.boxplot(data_to_plot, tick_labels=names, patch_artist=True, widths=0.6)

for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.6)

ax5.set_ylabel('Execution Time (seconds)', fontsize=12, fontweight='bold')
ax5.set_title('Time Distribution Across Runs', fontsize=13, fontweight='bold')
ax5.grid(True, alpha=0.3, axis='y', linestyle='--')

# 6. Percentage Changes (using Original as baseline)
ax6 = fig.add_subplot(gs[2, 1:])

baseline = np.mean(benchmarks['Original\nValidation']['runs'])
changes_improved_no_query = ((np.mean(benchmarks['Improved\n(no query)']['runs']) - baseline) / baseline) * 100
changes_improved_with_query = ((np.mean(benchmarks['Improved\n+ Query']['runs']) - baseline) / baseline) * 100

comparison_data = {
    'Improved\n(no query)\nvs Original': changes_improved_no_query,
    'Improved + Query\nvs Original': changes_improved_with_query,
    'Improved + Query\nvs Improved (no query)': ((np.mean(benchmarks['Improved\n+ Query']['runs']) -
                                                    np.mean(benchmarks['Improved\n(no query)']['runs'])) /
                                                   np.mean(benchmarks['Improved\n(no query)']['runs'])) * 100
}

labels = list(comparison_data.keys())
values = list(comparison_data.values())
colors_bars = ['#e74c3c' if v > 0 else '#2ecc71' for v in values]

bars = ax6.barh(labels, values, color=colors_bars, alpha=0.7, edgecolor='black', linewidth=1.5)

ax6.set_xlabel('Percentage Change (%)', fontsize=12, fontweight='bold')
ax6.set_title('Performance Impact Comparison\n(Green = Faster, Red = Slower)',
              fontsize=13, fontweight='bold')
ax6.axvline(x=0, color='black', linewidth=2, linestyle='-')
ax6.grid(True, alpha=0.3, axis='x', linestyle='--')

# Add value labels
for bar, val in zip(bars, values):
    width = bar.get_width()
    ax6.text(width + (8 if width > 0 else -8), bar.get_y() + bar.get_height()/2.,
            f'{val:+.1f}%',
            ha='left' if width > 0 else 'right', va='center',
            fontsize=12, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.8))

# Overall title
fig.suptitle('Complete Benchmark Analysis: Validation Feedback Evolution',
             fontsize=17, fontweight='bold', y=0.98)

# Save
output_path = '/opt/genpod/benchmark_timing_all_three.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n✅ Visualization saved to: {output_path}")

# Print comprehensive summary
print("\n" + "="*100)
print("COMPREHENSIVE BENCHMARK TIMING SUMMARY")
print("="*100)

for i, (name, data) in enumerate(benchmarks.items(), 1):
    print(f"\n{i}. {name.replace(chr(10), ' ')}:")
    print(f"   Runs: {data['runs']}")
    print(f"   Average: {np.mean(data['runs']):.2f}s ± {np.std(data['runs']):.2f}s")
    print(f"   Range: {min(data['runs']):.2f}s - {max(data['runs']):.2f}s")
    print(f"   Avg Queries: {data['avg_queries']}")
    print(f"   Avg Tokens: {data['avg_tokens']:,}")
    print(f"   Avg Cost: ${data['avg_cost']:.4f}")
    print(f"   Description: {data['description']}")

print("\n" + "="*100)
print("KEY FINDINGS:")
print("="*100)

baseline = np.mean(benchmarks['Original\nValidation']['runs'])
improved_no_query = np.mean(benchmarks['Improved\n(no query)']['runs'])
improved_with_query = np.mean(benchmarks['Improved\n+ Query']['runs'])

print(f"\n1. Improved (no query) vs Original:")
print(f"   Time: {changes_improved_no_query:+.1f}% (WORSE - more exploration but gave up)")
print(f"   Queries: +100% (explored more alternatives)")

print(f"\n2. Improved + Query vs Original:")
print(f"   Time: {changes_improved_with_query:+.1f}% (slightly slower but explores more)")
print(f"   Queries: +100% (explores alternatives)")

print(f"\n3. Improved + Query vs Improved (no query):")
print(f"   Time: {comparison_data['Improved + Query\\nvs Improved (no query)']:+.1f}% ⭐ BEST IMPROVEMENT!")
print(f"   Showing the failed query helped LLM avoid repeating mistakes")

print("\n" + "="*100)
print("CONCLUSION:")
print("="*100)
print("✅ Adding the failed query to validation feedback:")
print("   - Reduced execution time by 54% compared to validation feedback without query")
print("   - Helped LLM learn from its mistakes instead of repeating them")
print("   - Maintained same query exploration depth (3.2 queries avg)")
print("   - Slightly increased cost vs original but much better than improved (no query)")
print("="*100)

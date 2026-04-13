#!/usr/bin/env python3
"""
Visualize benchmark timing comparison across different validation feedback approaches
"""
import matplotlib.pyplot as plt
import numpy as np
import json
from pathlib import Path

# Data from benchmarks
benchmarks = {
    'Original Validation\nFeedback': {
        'runs': [77.41, 42.10, 77.34, 30.78, 37.45],
        'avg_queries': 1.6,
        'avg_tokens': 7552,
        'avg_cost': 0.0439,
        'description': 'Validation errors at bottom of prompt, no failed query shown'
    },
    'Improved Validation\n(no query)': {
        'runs': [118.36, 53.41, 409.01, 57.97, 34.61],
        'avg_queries': 3.2,
        'avg_tokens': 12729,
        'avg_cost': 0.0620,
        'description': 'Validation errors at top, forceful messaging, no failed query'
    }
}

# Create figure with multiple subplots
fig = plt.figure(figsize=(16, 10))
gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)

# Color scheme
colors = ['#3498db', '#e74c3c', '#2ecc71']
bar_colors = ['#3498db', '#e74c3c']

# 1. Execution Time Per Run (Line Chart)
ax1 = fig.add_subplot(gs[0, :])
for i, (name, data) in enumerate(benchmarks.items()):
    runs = data['runs']
    ax1.plot(range(1, len(runs) + 1), runs, marker='o', linewidth=2,
             markersize=8, label=name, color=bar_colors[i])

ax1.set_xlabel('Run Number', fontsize=12, fontweight='bold')
ax1.set_ylabel('Execution Time (seconds)', fontsize=12, fontweight='bold')
ax1.set_title('Execution Time Per Run - Comparison', fontsize=14, fontweight='bold')
ax1.legend(loc='upper right', fontsize=10)
ax1.grid(True, alpha=0.3, linestyle='--')
ax1.set_xticks(range(1, 6))

# 2. Average Metrics Comparison (Bar Chart)
ax2 = fig.add_subplot(gs[1, 0])
metrics = ['Avg Time (s)', 'Avg Queries', 'Avg Tokens/100', 'Avg Cost ($)']
original = [
    np.mean(benchmarks['Original Validation\nFeedback']['runs']),
    benchmarks['Original Validation\nFeedback']['avg_queries'],
    benchmarks['Original Validation\nFeedback']['avg_tokens'] / 100,
    benchmarks['Original Validation\nFeedback']['avg_cost'] * 100
]
improved = [
    np.mean(benchmarks['Improved Validation\n(no query)']['runs']),
    benchmarks['Improved Validation\n(no query)']['avg_queries'],
    benchmarks['Improved Validation\n(no query)']['avg_tokens'] / 100,
    benchmarks['Improved Validation\n(no query)']['avg_cost'] * 100
]

x = np.arange(len(metrics))
width = 0.35

bars1 = ax2.bar(x - width/2, original, width, label='Original', color=bar_colors[0], alpha=0.8)
bars2 = ax2.bar(x + width/2, improved, width, label='Improved', color=bar_colors[1], alpha=0.8)

ax2.set_xlabel('Metrics', fontsize=11, fontweight='bold')
ax2.set_ylabel('Value (scaled)', fontsize=11, fontweight='bold')
ax2.set_title('Average Metrics Comparison', fontsize=12, fontweight='bold')
ax2.set_xticks(x)
ax2.set_xticklabels(metrics, rotation=15, ha='right', fontsize=9)
ax2.legend()
ax2.grid(True, alpha=0.3, axis='y', linestyle='--')

# Add value labels on bars
for bars in [bars1, bars2]:
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.1f}',
                ha='center', va='bottom', fontsize=8)

# 3. Time Distribution (Box Plot)
ax3 = fig.add_subplot(gs[1, 1])
data_to_plot = [benchmarks['Original Validation\nFeedback']['runs'],
                benchmarks['Improved Validation\n(no query)']['runs']]
bp = ax3.boxplot(data_to_plot, labels=['Original', 'Improved'],
                 patch_artist=True, widths=0.6)

for patch, color in zip(bp['boxes'], bar_colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.6)

ax3.set_ylabel('Execution Time (seconds)', fontsize=11, fontweight='bold')
ax3.set_title('Time Distribution Across Runs', fontsize=12, fontweight='bold')
ax3.grid(True, alpha=0.3, axis='y', linestyle='--')

# 4. Percentage Change Comparison
ax4 = fig.add_subplot(gs[2, 0])
change_metrics = ['Time', 'Queries', 'Tokens', 'Cost']
changes = [
    ((np.mean(improved_val) - np.mean(original_val)) / np.mean(original_val)) * 100
    for improved_val, original_val in [
        ([np.mean(benchmarks['Improved Validation\n(no query)']['runs'])],
         [np.mean(benchmarks['Original Validation\nFeedback']['runs'])]),
        ([benchmarks['Improved Validation\n(no query)']['avg_queries']],
         [benchmarks['Original Validation\nFeedback']['avg_queries']]),
        ([benchmarks['Improved Validation\n(no query)']['avg_tokens']],
         [benchmarks['Original Validation\nFeedback']['avg_tokens']]),
        ([benchmarks['Improved Validation\n(no query)']['avg_cost']],
         [benchmarks['Original Validation\nFeedback']['avg_cost']])
    ]
]

colors_change = ['#e74c3c' if c > 0 else '#2ecc71' for c in changes]
bars = ax4.barh(change_metrics, changes, color=colors_change, alpha=0.7)

ax4.set_xlabel('Percentage Change (%)', fontsize=11, fontweight='bold')
ax4.set_title('Impact of Improved Validation Feedback\n(Negative = Better)',
              fontsize=12, fontweight='bold')
ax4.axvline(x=0, color='black', linewidth=1, linestyle='-')
ax4.grid(True, alpha=0.3, axis='x', linestyle='--')

# Add value labels
for i, (bar, change) in enumerate(zip(bars, changes)):
    width = bar.get_width()
    ax4.text(width + (5 if width > 0 else -5), bar.get_y() + bar.get_height()/2.,
            f'{change:+.1f}%',
            ha='left' if width > 0 else 'right', va='center', fontsize=10, fontweight='bold')

# 5. Summary Statistics Table
ax5 = fig.add_subplot(gs[2, 1])
ax5.axis('off')

table_data = [
    ['Metric', 'Original', 'Improved', 'Change'],
    ['Avg Time (s)', f'{np.mean(benchmarks["Original Validation\nFeedback"]["runs"]):.2f}',
     f'{np.mean(benchmarks["Improved Validation\n(no query)"]["runs"]):.2f}',
     f'{changes[0]:+.1f}%'],
    ['Std Dev (s)', f'{np.std(benchmarks["Original Validation\nFeedback"]["runs"]):.2f}',
     f'{np.std(benchmarks["Improved Validation\n(no query)"]["runs"]):.2f}', '-'],
    ['Min Time (s)', f'{min(benchmarks["Original Validation\nFeedback"]["runs"]):.2f}',
     f'{min(benchmarks["Improved Validation\n(no query)"]["runs"]):.2f}', '-'],
    ['Max Time (s)', f'{max(benchmarks["Original Validation\nFeedback"]["runs"]):.2f}',
     f'{max(benchmarks["Improved Validation\n(no query)"]["runs"]):.2f}', '-'],
    ['Avg Queries', f'{benchmarks["Original Validation\nFeedback"]["avg_queries"]:.1f}',
     f'{benchmarks["Improved Validation\n(no query)"]["avg_queries"]:.1f}',
     f'{changes[1]:+.1f}%'],
    ['Avg Cost ($)', f'${benchmarks["Original Validation\nFeedback"]["avg_cost"]:.4f}',
     f'${benchmarks["Improved Validation\n(no query)"]["avg_cost"]:.4f}',
     f'{changes[3]:+.1f}%'],
]

table = ax5.table(cellText=table_data, cellLoc='center', loc='center',
                  colWidths=[0.3, 0.2, 0.2, 0.2])
table.auto_set_font_size(False)
table.set_fontsize(9)
table.scale(1, 2)

# Style header row
for i in range(4):
    table[(0, i)].set_facecolor('#34495e')
    table[(0, i)].set_text_props(weight='bold', color='white')

# Style data rows
for i in range(1, len(table_data)):
    for j in range(4):
        if i % 2 == 0:
            table[(i, j)].set_facecolor('#ecf0f1')

ax5.set_title('Summary Statistics', fontsize=12, fontweight='bold', pad=20)

# Overall title
fig.suptitle('Benchmark Timing Analysis: Original vs Improved Validation Feedback',
             fontsize=16, fontweight='bold', y=0.98)

# Save the figure
output_path = '/opt/genpod/benchmark_timing_comparison.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n✅ Visualization saved to: {output_path}")

# Print summary
print("\n" + "="*80)
print("BENCHMARK TIMING SUMMARY")
print("="*80)

for name, data in benchmarks.items():
    print(f"\n{name}:")
    print(f"  Runs: {data['runs']}")
    print(f"  Average: {np.mean(data['runs']):.2f}s")
    print(f"  Std Dev: {np.std(data['runs']):.2f}s")
    print(f"  Min: {min(data['runs']):.2f}s | Max: {max(data['runs']):.2f}s")
    print(f"  Avg Queries: {data['avg_queries']}")
    print(f"  Avg Tokens: {data['avg_tokens']:,}")
    print(f"  Avg Cost: ${data['avg_cost']:.4f}")

print("\n" + "="*80)
print("CHANGES (Original → Improved):")
print("="*80)
print(f"  Time:    {changes[0]:+.1f}%")
print(f"  Queries: {changes[1]:+.1f}%")
print(f"  Tokens:  {changes[2]:+.1f}%")
print(f"  Cost:    {changes[3]:+.1f}%")
print("="*80)

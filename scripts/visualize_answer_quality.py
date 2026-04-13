#!/usr/bin/env python3
"""
Visualize answer quality and completeness across all 5 benchmark runs
"""
import matplotlib.pyplot as plt
import numpy as np
import json

# Load run data
runs_data = {}
for i in range(1, 6):
    with open(f'benchmark_results/run_{i}_output.json', 'r') as f:
        data = json.load(f)
        response = data['response']

        # Check for all three worker classes
        has_workerA = 'WorkerA' in response
        has_workerB = 'WorkerB' in response
        has_workerC = 'WorkerC' in response
        complete = has_workerA and has_workerB and has_workerC

        runs_data[f'Run {i}'] = {
            'time': [86.18, 53.05, 65.56, 58.14, 45.00][i-1],  # From visualize_five_runs_detailed.py
            'queries': [4, 3, 3, 3, 2][i-1],
            'tokens': [15496, 10941, 12257, 12152, 8452][i-1],
            'cost': [0.0667, 0.0556, 0.0576, 0.0557, 0.0509][i-1],
            'has_workerA': has_workerA,
            'has_workerB': has_workerB,
            'has_workerC': has_workerC,
            'complete': complete,
            'answer_score': (int(has_workerA) + int(has_workerB) + int(has_workerC)) / 3.0
        }

# Create comprehensive visualization
fig = plt.figure(figsize=(20, 12))
gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.35)

# Color gradient
colors = plt.cm.viridis(np.linspace(0.2, 0.9, 5))
run_names = list(runs_data.keys())

# 1. Answer Completeness Score (Main metric)
ax1 = fig.add_subplot(gs[0, :])
answer_scores = [data['answer_score'] * 100 for data in runs_data.values()]
bars = ax1.bar(run_names, answer_scores, color=colors, edgecolor='black', linewidth=1.5, alpha=0.8)

# Add threshold line at 100%
ax1.axhline(y=100, color='green', linestyle='--', linewidth=2, label='Complete Answer (100%)')

ax1.set_ylabel('Answer Completeness (%)', fontsize=14, fontweight='bold')
ax1.set_title('Answer Quality Per Run - How Many Classes Were Identified? (WorkerA, WorkerB, WorkerC)',
              fontsize=16, fontweight='bold')
ax1.legend(fontsize=12)
ax1.grid(True, alpha=0.3, axis='y', linestyle='--')
ax1.set_ylim(0, 110)

# Add value labels and status
for bar, val, run_key in zip(bars, answer_scores, run_names):
    height = bar.get_height()
    status = "✅ COMPLETE" if val == 100 else "❌ INCOMPLETE"
    ax1.text(bar.get_x() + bar.get_width()/2., height + 2,
            f'{val:.0f}%\n{status}',
            ha='center', va='bottom', fontsize=11, fontweight='bold')

# 2. Class Detection Breakdown (Stacked)
ax2 = fig.add_subplot(gs[1, 0])
workerA_detected = [1 if data['has_workerA'] else 0 for data in runs_data.values()]
workerB_detected = [1 if data['has_workerB'] else 0 for data in runs_data.values()]
workerC_detected = [1 if data['has_workerC'] else 0 for data in runs_data.values()]

x = np.arange(len(run_names))
width = 0.25

ax2.bar(x - width, workerA_detected, width, label='WorkerA', color='#3498db', alpha=0.8)
ax2.bar(x, workerB_detected, width, label='WorkerB', color='#e74c3c', alpha=0.8)
ax2.bar(x + width, workerC_detected, width, label='WorkerC', color='#2ecc71', alpha=0.8)

ax2.set_ylabel('Detected (1) or Not (0)', fontsize=13, fontweight='bold')
ax2.set_title('Individual Class Detection', fontsize=14, fontweight='bold')
ax2.set_xticks(x)
ax2.set_xticklabels(run_names)
ax2.legend(fontsize=11)
ax2.set_ylim(0, 1.2)
ax2.grid(True, alpha=0.3, axis='y', linestyle='--')

# 3. Execution Time vs Answer Quality
ax3 = fig.add_subplot(gs[1, 1])
times = [data['time'] for data in runs_data.values()]
scatter_colors = ['green' if score == 100 else 'red' for score in answer_scores]

scatter = ax3.scatter(times, answer_scores, c=scatter_colors, s=300, alpha=0.6, edgecolors='black', linewidth=2)

# Add run labels
for i, (time, score, run) in enumerate(zip(times, answer_scores, run_names)):
    ax3.annotate(run, (time, score), fontsize=10, fontweight='bold',
                ha='center', va='center')

ax3.set_xlabel('Execution Time (seconds)', fontsize=13, fontweight='bold')
ax3.set_ylabel('Answer Completeness (%)', fontsize=13, fontweight='bold')
ax3.set_title('Execution Time vs Answer Quality', fontsize=14, fontweight='bold')
ax3.grid(True, alpha=0.3, linestyle='--')
ax3.axhline(y=100, color='green', linestyle='--', linewidth=1, alpha=0.5)

# 4. Query Count vs Answer Quality
ax4 = fig.add_subplot(gs[1, 2])
queries = [data['queries'] for data in runs_data.values()]

scatter = ax4.scatter(queries, answer_scores, c=scatter_colors, s=300, alpha=0.6, edgecolors='black', linewidth=2)

# Add run labels
for i, (q, score, run) in enumerate(zip(queries, answer_scores, run_names)):
    ax4.annotate(run, (q, score), fontsize=10, fontweight='bold',
                ha='center', va='center')

ax4.set_xlabel('Total Queries', fontsize=13, fontweight='bold')
ax4.set_ylabel('Answer Completeness (%)', fontsize=13, fontweight='bold')
ax4.set_title('Query Count vs Answer Quality', fontsize=14, fontweight='bold')
ax4.grid(True, alpha=0.3, linestyle='--')
ax4.axhline(y=100, color='green', linestyle='--', linewidth=1, alpha=0.5)

# 5. Success Rate Summary
ax5 = fig.add_subplot(gs[2, 0])
complete_count = sum(1 for score in answer_scores if score == 100)
incomplete_count = len(answer_scores) - complete_count

pie_data = [complete_count, incomplete_count]
pie_labels = [f'Complete\n{complete_count}/5 ({complete_count*20}%)',
              f'Incomplete\n{incomplete_count}/5 ({incomplete_count*20}%)']
pie_colors = ['#2ecc71', '#e74c3c']

wedges, texts, autotexts = ax5.pie(pie_data, labels=pie_labels, colors=pie_colors,
                                     autopct='', startangle=90, textprops={'fontsize': 12, 'fontweight': 'bold'})

ax5.set_title('Overall Success Rate', fontsize=14, fontweight='bold')

# 6. Summary Table
ax6 = fig.add_subplot(gs[2, 1:])
ax6.axis('off')

table_data = [
    ['Run', 'Time (s)', 'Queries', 'Cost ($)', 'WorkerA', 'WorkerB', 'WorkerC', 'Complete?'],
]

for run_name, data in runs_data.items():
    table_data.append([
        run_name,
        f'{data["time"]:.1f}s',
        str(data['queries']),
        f'${data["cost"]:.4f}',
        '✓' if data['has_workerA'] else '✗',
        '✓' if data['has_workerB'] else '✗',
        '✓' if data['has_workerC'] else '✗',
        '✅' if data['complete'] else '❌'
    ])

table = ax6.table(cellText=table_data, cellLoc='center', loc='center',
                  colWidths=[0.12, 0.12, 0.10, 0.12, 0.12, 0.12, 0.12, 0.15])
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1, 2.5)

# Style header row
for i in range(8):
    table[(0, i)].set_facecolor('#34495e')
    table[(0, i)].set_text_props(weight='bold', color='white')

# Style data rows - green for complete, red for incomplete
for i in range(1, len(table_data)):
    is_complete = runs_data[f'Run {i}']['complete']
    bg_color = '#d5f4e6' if is_complete else '#fadbd8'

    for j in range(8):
        table[(i, j)].set_facecolor(bg_color)

ax6.set_title('Detailed Run Summary', fontsize=14, fontweight='bold', pad=20)

# Overall title
fig.suptitle('Answer Quality Analysis: 5 Runs with Improved Validation + Query Feedback',
             fontsize=18, fontweight='bold', y=0.98)

# Save
output_path = '/opt/genpod/benchmark_answer_quality.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n✅ Answer quality visualization saved to: {output_path}")

# Print insights
print("\n" + "="*100)
print("KEY INSIGHTS FROM ANSWER QUALITY ANALYSIS")
print("="*100)
print(f"\n✅ Complete Answers: {complete_count}/5 ({complete_count*20}%)")
print(f"   Runs that found ALL THREE classes (WorkerA, WorkerB, WorkerC): {[i+1 for i, score in enumerate(answer_scores) if score == 100]}")
print(f"\n❌ Incomplete Answers: {incomplete_count}/5 ({incomplete_count*20}%)")
print(f"   Runs that did NOT find all classes: {[i+1 for i, score in enumerate(answer_scores) if score < 100]}")

print("\n🔍 Correlation Analysis:")
print(f"   • Run 1: {times[0]:.1f}s, {queries[0]} queries → {'COMPLETE' if answer_scores[0] == 100 else 'INCOMPLETE'}")
print(f"   • Run 3: {times[2]:.1f}s, {queries[2]} queries → {'COMPLETE' if answer_scores[2] == 100 else 'INCOMPLETE'}")
print(f"   • Run 5: {times[4]:.1f}s, {queries[4]} queries → {'COMPLETE' if answer_scores[4] == 100 else 'INCOMPLETE'} (FASTEST)")

print("\n⚠️  IMPORTANT FINDING:")
print("   - Run 5 was the FASTEST (45.00s) but FAILED to find the answer")
print("   - Runs 1 & 3 succeeded but took longer (86.18s and 65.56s)")
print("   - More queries does NOT guarantee better answers (correlation unclear)")
print("   - The schema's lack of INSTANTIATES relationship makes this challenging")
print("="*100 + "\n")

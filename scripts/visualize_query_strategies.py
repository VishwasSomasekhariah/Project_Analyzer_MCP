#!/usr/bin/env python3
"""
Visualize the different query strategies used across successful and failed runs
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np

fig, axes = plt.subplots(3, 2, figsize=(18, 14))
fig.suptitle('Query Strategy Analysis: Why 60% of Runs Failed', fontsize=18, fontweight='bold', y=0.98)

# Color scheme
success_color = '#2ecc71'
fail_color = '#e74c3c'
warning_color = '#f39c12'

# ===== RUN 1 - SUCCESS =====
ax = axes[0, 0]
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')
ax.set_title('RUN 1: ✅ SUCCESS (86.2s)', fontsize=14, fontweight='bold', color=success_color, pad=10)

# Query flow
y_pos = 8
ax.text(5, y_pos, 'Query 1: Locate CreateWorkers function', ha='center', fontsize=10,
        bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', edgecolor='black'))

y_pos -= 1.5
ax.arrow(5, y_pos + 0.3, 0, -0.2, head_width=0.3, head_length=0.1, fc='black', ec='black')

y_pos -= 0.8
ax.text(5, y_pos, '🎯 Query 2: Statement.text CONTAINS "new"', ha='center', fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor=success_color, edgecolor='black', alpha=0.7))

y_pos -= 1.2
ax.text(5, y_pos, 'Result: Found WorkerA, WorkerB, WorkerC', ha='center', fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=success_color))

y_pos -= 1.5
ax.text(5, y_pos, 'Queries 3-4: Return type validation', ha='center', fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgray', edgecolor='black'))

ax.text(5, 1.5, '✅ SUCCESS PATTERN:', ha='center', fontsize=11, fontweight='bold', color=success_color)
ax.text(5, 0.8, 'Direct code text examination', ha='center', fontsize=9)

# ===== RUN 3 - SUCCESS =====
ax = axes[0, 1]
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')
ax.set_title('RUN 3: ✅ SUCCESS (65.6s)', fontsize=14, fontweight='bold', color=success_color, pad=10)

y_pos = 8
ax.text(5, y_pos, 'Query 1: Locate CreateWorkers function', ha='center', fontsize=10,
        bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', edgecolor='black'))

y_pos -= 1.5
ax.arrow(5, y_pos + 0.3, 0, -0.2, head_width=0.3, head_length=0.1, fc='black', ec='black')

y_pos -= 0.8
ax.text(5, y_pos, '🎯 Query 2-3: CALLS relationship trace', ha='center', fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor=success_color, edgecolor='black', alpha=0.7))

y_pos -= 1.2
ax.text(5, y_pos, 'Result: Found WorkerA, WorkerB, WorkerC', ha='center', fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=success_color))

y_pos -= 1.5
ax.text(5, y_pos, 'Query 4: Acknowledged limitation', ha='center', fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgray', edgecolor='black'))

ax.text(5, 1.5, '✅ SUCCESS PATTERN:', ha='center', fontsize=11, fontweight='bold', color=success_color)
ax.text(5, 0.8, 'CALLS relationship tracing', ha='center', fontsize=9)

# ===== RUN 2 - FAIL =====
ax = axes[1, 0]
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')
ax.set_title('RUN 2: ❌ FAILED (53.0s)', fontsize=14, fontweight='bold', color=fail_color, pad=10)

y_pos = 8
ax.text(5, y_pos, 'Query 1: Locate CreateWorkers function', ha='center', fontsize=10,
        bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', edgecolor='black'))

y_pos -= 1.5
ax.arrow(5, y_pos + 0.3, 0, -0.2, head_width=0.3, head_length=0.1, fc='black', ec='black')

y_pos -= 0.8
ax.text(5, y_pos, 'Query 2: RETURN f (generic)', ha='center', fontsize=10,
        bbox=dict(boxstyle='round,pad=0.5', facecolor=warning_color, edgecolor='black', alpha=0.7))

y_pos -= 1.5
ax.arrow(5, y_pos + 0.3, 0, -0.2, head_width=0.3, head_length=0.1, fc='black', ec='black')

y_pos -= 0.8
ax.text(5, y_pos, '❌ Query 3: IMPLEMENTS relationship', ha='center', fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor=fail_color, edgecolor='black', alpha=0.7))

y_pos -= 1.2
ax.text(5, y_pos, 'Result: EMPTY (relationship doesn\'t exist)', ha='center', fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=fail_color))

ax.text(5, 1.5, '❌ FAILURE PATTERN:', ha='center', fontsize=11, fontweight='bold', color=fail_color)
ax.text(5, 0.8, 'Tried non-existent IMPLEMENTS edge', ha='center', fontsize=9)

# ===== RUN 4 - FAIL (WORST) =====
ax = axes[1, 1]
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')
ax.set_title('RUN 4: ❌ FAILED (58.1s) - WORST', fontsize=14, fontweight='bold', color=fail_color, pad=10)

y_pos = 8
ax.text(5, y_pos, 'Query 1: Locate CreateWorkers function', ha='center', fontsize=10,
        bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', edgecolor='black'))

y_pos -= 1.5
ax.arrow(5, y_pos + 0.3, 0, -0.2, head_width=0.3, head_length=0.1, fc='black', ec='black')

y_pos -= 0.8
ax.text(5, y_pos, '🚨 Query 2: LLM GAVE UP', ha='center', fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#c0392b', edgecolor='black', alpha=0.9))

y_pos -= 1.2
ax.text(5, y_pos, 'Returned hardcoded message:\n"Schema does not support..."', ha='center', fontsize=8,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=fail_color))

y_pos -= 1.5
ax.text(5, y_pos, '🚨 Query 3: LLM GAVE UP AGAIN', ha='center', fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#c0392b', edgecolor='black', alpha=0.9))

ax.text(5, 1.5, '❌ WORST FAILURE:', ha='center', fontsize=11, fontweight='bold', color='#c0392b')
ax.text(5, 0.8, 'Premature surrender - no alternatives tried', ha='center', fontsize=9)

# ===== RUN 5 - FAIL =====
ax = axes[2, 0]
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')
ax.set_title('RUN 5: ❌ FAILED (45.0s) - Fastest but Wrong', fontsize=14, fontweight='bold', color=fail_color, pad=10)

y_pos = 8
ax.text(5, y_pos, 'Query 1: Locate CreateWorkers function', ha='center', fontsize=10,
        bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', edgecolor='black'))

y_pos -= 1.5
ax.arrow(5, y_pos + 0.3, 0, -0.2, head_width=0.3, head_length=0.1, fc='black', ec='black')

y_pos -= 0.8
ax.text(5, y_pos, '❌ Query 2: IMPLEMENTS relationship', ha='center', fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor=fail_color, edgecolor='black', alpha=0.7))

y_pos -= 1.2
ax.text(5, y_pos, 'Result: EMPTY (relationship doesn\'t exist)', ha='center', fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=fail_color))

y_pos -= 1.5
ax.text(5, y_pos, 'Stopped after 2 queries (gave up)', ha='center', fontsize=9,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgray', edgecolor='black'))

ax.text(5, 1.5, '❌ FAILURE PATTERN:', ha='center', fontsize=11, fontweight='bold', color=fail_color)
ax.text(5, 0.8, 'Tried IMPLEMENTS, got empty, quit early', ha='center', fontsize=9)

# ===== SUMMARY BOX =====
ax = axes[2, 1]
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')
ax.set_title('ROOT CAUSE SUMMARY', fontsize=14, fontweight='bold', pad=10)

summary_text = """
THE CORE PROBLEM:
Schema lacks direct INSTANTIATES relationship
   (Function)-[:INSTANTIATES]->(Type) ❌

SUCCESSFUL WORKAROUNDS:
✅ Statement.text filtering (Run 1)
✅ CALLS relationship (Run 3)

FAILED ATTEMPTS:
❌ IMPLEMENTS relationship (Runs 2, 5)
❌ Hardcoded surrender (Run 4)

THE INCONSISTENCY ISSUE:
• Why didn't all runs try Statement.text?
• No explicit fallback guidance
• LLM exploration is non-deterministic
• 60% failure rate due to wrong paths

SOLUTION NEEDED:
Add explicit prompt guidance:
"When direct relationships don't exist,
 try Statement.text CONTAINS pattern"
"""

ax.text(5, 5, summary_text, ha='center', va='center', fontsize=9,
        bbox=dict(boxstyle='round,pad=1', facecolor='#ecf0f1', edgecolor='black', linewidth=2),
        family='monospace')

plt.tight_layout()
output_path = '/opt/genpod/benchmark_query_strategy_analysis.png'
plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
print(f"\n✅ Query strategy visualization saved to: {output_path}")

print("\n" + "="*100)
print("ACTIONABLE INSIGHTS")
print("="*100)
print("\n1. SUCCESSFUL RUNS USED TWO DIFFERENT STRATEGIES:")
print("   - Run 1: Statement.text CONTAINS 'new' (direct code inspection)")
print("   - Run 3: CALLS relationship tracing (indirect via function calls)")

print("\n2. FAILED RUNS PURSUED WRONG PATHS:")
print("   - Runs 2 & 5: Tried IMPLEMENTS relationship (doesn't exist)")
print("   - Run 4: Gave up immediately without trying alternatives")

print("\n3. THE VALIDATION FEEDBACK IS WORKING:")
print("   - All runs had 100% success on SQ1 and SQ2 (1 query each)")
print("   - The schema validator prevented invalid queries from reaching Neo4j")
print("   - BUT: It didn't guide the LLM toward Statement.text fallback")

print("\n4. RECOMMENDATION - ADD FALLBACK GUIDANCE:")
print("   When validation feedback detects missing relationships like INSTANTIATES,")
print("   explicitly suggest: 'Try querying Statement.text for instantiation patterns'")

print("\n5. EXPECTED IMPROVEMENT:")
print("   Current success rate: 40% (2/5)")
print("   With fallback guidance: Potentially 80-100%")
print("="*100 + "\n")

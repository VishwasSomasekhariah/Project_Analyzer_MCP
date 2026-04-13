#!/usr/bin/env python3
"""
Analyze workflow trace PKL file.

Shows function calls, inputs, outputs, and flow.
"""

import pickle
import sys
from pathlib import Path
from typing import Any, Dict, List
import json

def load_trace(filepath: str) -> Dict[str, Any]:
    """Load trace from JSON or pickle file."""
    if filepath.endswith('.json'):
        with open(filepath, 'r') as f:
            return json.load(f)
    else:
        with open(filepath, 'rb') as f:
            return pickle.load(f)

def print_trace_summary(trace_data: Dict[str, Any]):
    """Print high-level summary."""
    print("=" * 80)
    print("📊 WORKFLOW TRACE SUMMARY")
    print("=" * 80)
    print(f"Timestamp: {trace_data['timestamp']}")
    print(f"Total Traces: {trace_data['total_traces']}")
    print()

def print_function_call_tree(traces: List[Dict[str, Any]]):
    """Print function call tree."""
    print("=" * 80)
    print("🌲 FUNCTION CALL TREE")
    print("=" * 80)

    for i, trace in enumerate(traces, 1):
        func_name = trace['function'].split('.')[-1]
        duration = trace.get('duration_ms', 0)
        error = trace.get('error')

        # Status indicator
        if error:
            status = "❌ ERROR"
        else:
            status = "✅ OK"

        # Indentation based on function type
        if 'WorkflowNodes' in trace['function']:
            indent = "  "
        elif 'ResearchEngine' in trace['function']:
            indent = "    "
        elif 'AdaptiveQueryAgent' in trace['function']:
            indent = "      "
        else:
            indent = "        "

        print(f"{i:3d}. {indent}{status} {func_name} ({duration:.1f}ms)")

        if error:
            print(f"      {indent}└─ Error: {error[:100]}")

    print()

def print_detailed_trace(traces: List[Dict[str, Any]], trace_id: int = None):
    """Print detailed trace for specific call or all."""
    print("=" * 80)
    print("🔍 DETAILED TRACES")
    print("=" * 80)

    traces_to_show = traces if trace_id is None else [t for t in traces if t['trace_id'] == trace_id]

    for trace in traces_to_show:
        print(f"\n{'='*80}")
        print(f"Trace ID: {trace['trace_id']}")
        print(f"Function: {trace['function']}")
        print(f"Timestamp: {trace['timestamp']}")
        print(f"Duration: {trace.get('duration_ms', 0):.2f}ms")
        print(f"{'='*80}")

        # Args
        if trace['args']:
            print("\n📥 ARGS:")
            for i, arg in enumerate(trace['args']):
                print(f"  [{i}] {_format_value(arg)}")

        # Kwargs
        if trace['kwargs']:
            print("\n📥 KWARGS:")
            for key, value in trace['kwargs'].items():
                print(f"  {key}: {_format_value(value)}")

        # Result
        if trace['result'] is not None:
            print("\n📤 RESULT:")
            print(f"  {_format_value(trace['result'])}")

        # Error
        if trace['error']:
            print("\n❌ ERROR:")
            print(f"  {trace['error']}")
            if trace['error_traceback']:
                print("\n🔥 TRACEBACK:")
                print(trace['error_traceback'])

    print()

def _format_value(value: Any, indent: int = 0) -> str:
    """Format value for display."""
    prefix = "  " * indent

    if value is None:
        return "None"
    elif isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 100:
            return f"{repr(value[:100])}..."
        return repr(value)
    elif isinstance(value, dict):
        if '_type' in value:
            # Special formatted dict
            return f"<{value['_type']}> {value.get('_repr', '')}"
        else:
            # Regular dict
            if len(value) > 5:
                return f"dict({len(value)} keys: {list(value.keys())[:5]}...)"
            else:
                return json.dumps(value, indent=2, default=str)
    elif isinstance(value, list):
        if len(value) > 5:
            return f"list({len(value)} items, sample: {value[:2]})"
        else:
            return json.dumps(value, indent=2, default=str)
    else:
        return str(value)

def print_state_flow(traces: List[Dict[str, Any]]):
    """Print state transitions."""
    print("=" * 80)
    print("🔄 STATE FLOW")
    print("=" * 80)

    for trace in traces:
        result = trace.get('result')
        if isinstance(result, dict) and result.get('_type') == 'AgentState':
            print(f"\n{trace['trace_id']:3d}. {trace['function'].split('.')[-1]}")
            print(f"     Node: {result.get('current_node', 'N/A')}")
            print(f"     Execution Group: {result.get('current_execution_group', 'N/A')}")
            print(f"     Completed Subqueries: {result.get('completed_subqueries', [])}")
            print(f"     More Batches: {result.get('more_batches_remaining', 'N/A')}")

            packets = result.get('approach_packets')
            if packets:
                print(f"     Packets: {packets.get('total_packets', 0)} packets")
                print(f"     Groups: {packets.get('execution_groups', [])}")

    print()

def print_errors_summary(traces: List[Dict[str, Any]]):
    """Print summary of errors."""
    errors = [t for t in traces if t.get('error')]

    if not errors:
        print("✅ No errors found in trace")
        return

    print("=" * 80)
    print("❌ ERRORS SUMMARY")
    print("=" * 80)

    for trace in errors:
        print(f"\nTrace ID: {trace['trace_id']}")
        print(f"Function: {trace['function']}")
        print(f"Error: {trace['error']}")
        print(f"Duration: {trace.get('duration_ms', 0):.2f}ms")

    print()

def print_performance_summary(traces: List[Dict[str, Any]]):
    """Print performance metrics."""
    print("=" * 80)
    print("⚡ PERFORMANCE SUMMARY")
    print("=" * 80)

    # Group by function
    by_function = {}
    for trace in traces:
        func = trace['function'].split('.')[-1]
        duration = trace.get('duration_ms', 0)

        if func not in by_function:
            by_function[func] = []
        by_function[func].append(duration)

    # Calculate stats
    print(f"\n{'Function':<40} {'Calls':<10} {'Avg (ms)':<12} {'Total (ms)':<12}")
    print("-" * 80)

    sorted_funcs = sorted(by_function.items(), key=lambda x: sum(x[1]), reverse=True)
    for func, durations in sorted_funcs:
        count = len(durations)
        avg = sum(durations) / count
        total = sum(durations)
        print(f"{func:<40} {count:<10} {avg:>10.1f} {total:>12.1f}")

    print()

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_workflow_trace.py <trace_file.pkl> [trace_id]")
        print()
        print("Options:")
        print("  trace_file.pkl  - Pickle file with workflow trace")
        print("  trace_id        - (Optional) Show detailed trace for specific ID")
        sys.exit(1)

    trace_file = sys.argv[1]
    trace_id = int(sys.argv[2]) if len(sys.argv) > 2 else None

    if not Path(trace_file).exists():
        print(f"❌ Error: File not found: {trace_file}")
        sys.exit(1)

    # Load trace
    print(f"📂 Loading trace from {trace_file}...")
    trace_data = load_trace(trace_file)
    traces = trace_data['traces']

    # Print summaries
    print_trace_summary(trace_data)
    print_function_call_tree(traces)
    print_state_flow(traces)
    print_errors_summary(traces)
    print_performance_summary(traces)

    # Detailed trace if requested
    if trace_id is not None:
        print_detailed_trace(traces, trace_id)
    else:
        response = input("\n🔍 Show detailed traces? (y/N): ")
        if response.lower() == 'y':
            print_detailed_trace(traces)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Analyze which subqueries were actually useful from the test run."""
import pickle

# Load the state pickle
with open('/opt/genpod/STATE.pkl', 'rb') as f:
    state = pickle.load(f)

# Get approach packets to see subquery texts
packets = state.get('approach_packets', {}).get('packets', {})

print("=" * 80)
print("SUBQUERY ANALYSIS")
print("=" * 80)
print()

# Get approach traces to see which were used
traces = state.get('approach_execution_traces', {})

# Sort by approach index
for idx in sorted(packets.keys()):
    packet = packets[idx]
    trace = traces.get(idx, {})

    print(f"[{idx}] {packet.get('text', 'N/A')}")
    print(f"    Results: {trace.get('queries_executed', 0)} queries, quality: {trace.get('approach_quality_grade', 0):.2f}")

    # Check if this approach had results
    approach_raw = state.get('approach_raw_results', {}).get(idx, {})
    total_results = approach_raw.get('total_results', 0)
    print(f"    Data found: {total_results} results")

    # Check data_points_used
    data_points_used = trace.get('data_points_used', [])
    print(f"    Data used in synthesis: {len(data_points_used)} points")
    print()

print("=" * 80)
print("SYNTHESIS SUMMARY")
print("=" * 80)

# Get the final citations to see which approaches were used
discovered_data = state.get('discovered_data', [])
print(f"Total data discovered: {len(discovered_data)}")

# Count which approaches contributed
approaches_with_citations = {idx for idx, trace in traces.items() if len(trace.get('data_points_used', [])) > 0}
print(f"Approaches that contributed to final answer: {sorted(approaches_with_citations)}")
print()

# Show the final response
response = state.get('response', '')
print("FINAL ANSWER:")
print(response[:500] + "..." if len(response) > 500 else response)

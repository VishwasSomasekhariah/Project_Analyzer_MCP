"""
Helper script to inspect saved approach packet pickle files.

Usage:
    python3 inspect_approach_packets.py <pickle_file>
    python3 inspect_approach_packets.py approach_packets/approaches_*.pkl
"""

import pickle
import sys
import json
from pathlib import Path


def inspect_pickle(pickle_file: str):
    """Load and display approach packet data from pickle file."""

    print("=" * 100)
    print(f"INSPECTING: {pickle_file}")
    print("=" * 100)

    try:
        with open(pickle_file, 'rb') as f:
            data = pickle.load(f)

        print(f"\nTimestamp: {data.get('timestamp')}")
        print(f"User Query: {data.get('user_query')}")
        print(f"Project: {data.get('project_name')}")
        print(f"Total Approaches: {data.get('total_approaches')}")

        print("\n" + "=" * 100)
        print("APPROACH PACKETS")
        print("=" * 100)

        for i, approach in enumerate(data.get('approaches', []), 1):
            print(f"\n[{i}] {approach.get('approach_name', 'Unnamed')}")
            print("-" * 100)
            print(f"Description: {approach.get('description', 'N/A')}")
            print(f"Target Nodes: {approach.get('target_nodes', [])}")
            print(f"Key Attributes: {approach.get('key_attributes', [])}")
            print(f"Relationships: {approach.get('relationships', [])}")

            # Show strategy (truncated if too long)
            strategy = approach.get('strategy', '')
            if len(strategy) > 200:
                print(f"Strategy: {strategy[:200]}...")
            else:
                print(f"Strategy: {strategy}")

            # Show corrections if any
            if approach.get('corrections_applied'):
                print(f"\nCorrections Applied:")
                for correction in approach['corrections_applied']:
                    print(f"  - {correction}")

        print("\n" + "=" * 100)
        print("RAW JSON (for detailed inspection)")
        print("=" * 100)
        print(json.dumps(data, indent=2, default=str))

    except FileNotFoundError:
        print(f"❌ File not found: {pickle_file}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading pickle file: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def list_available_pickles():
    """List all available approach packet pickle files."""

    pickle_dir = Path("approach_packets")
    if not pickle_dir.exists():
        print("No approach_packets directory found.")
        return []

    pickle_files = sorted(pickle_dir.glob("approaches_*.pkl"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not pickle_files:
        print("No approach packet pickle files found.")
        return []

    print("\nAvailable approach packet files:")
    for i, pf in enumerate(pickle_files, 1):
        print(f"  [{i}] {pf.name} (modified: {pf.stat().st_mtime})")

    return pickle_files


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 inspect_approach_packets.py <pickle_file>")
        print("\nOr browse available files:\n")
        pickle_files = list_available_pickles()

        if pickle_files:
            print("\nTo inspect the most recent file, run:")
            print(f"  python3 inspect_approach_packets.py {pickle_files[0]}")
    else:
        pickle_file = sys.argv[1]
        inspect_pickle(pickle_file)

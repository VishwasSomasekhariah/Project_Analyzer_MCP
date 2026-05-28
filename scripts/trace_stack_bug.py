#!/usr/bin/env python3
"""
Trace the stack-based containment algorithm to find the bug.
"""

# Simplified nodes from Manager.cs in order by start_point
nodes = [
    {"name": "File", "start": (0, 0), "end": (26, 0), "type": "File"},
    {"name": "Manager", "start": (5, 4), "end": (24, 5), "type": "Type"},
    {"name": "Run", "start": (7, 8), "end": (17, 9), "type": "Function"},
    {"name": "Run_Block", "start": (8, 8), "end": (17, 9), "type": "Block"},
    {"name": "WriteLine_1", "start": (9, 12), "end": (9, 58), "type": "Statement"},
    {"name": "workers_decl", "start": (10, 12), "end": (10, 77), "type": "Statement"},
    {"name": "comment_1", "start": (12, 12), "end": (12, 55), "type": "Literal"},
    {"name": "foreach", "start": (13, 12), "end": (16, 13), "type": "Statement"},
    {"name": "foreach_Block", "start": (14, 12), "end": (16, 13), "type": "Block"},
    {"name": "Process", "start": (15, 16), "end": (15, 33), "type": "Statement"},
    {"name": "comment_2", "start": (19, 8), "end": (19, 46), "type": "Literal"},
    {"name": "Notify", "start": (20, 8), "end": (23, 9), "type": "Function"},
    {"name": "Notify_Block", "start": (21, 8), "end": (23, 9), "type": "Block"},
    {"name": "WriteLine_2", "start": (22, 12), "end": (22, 75), "type": "Statement"},
]

def start_point_before(a, b):
    """Return True if 'a' is strictly before 'b'."""
    return (a[0] < b[0]) or (a[0] == b[0] and a[1] < b[1])

def end_point_after(a, b):
    """Return True if 'a' is strictly after 'b'."""
    return (a[0] > b[0]) or (a[0] == b[0] and a[1] > b[1])

def trace_algorithm():
    """Trace the stack-based containment algorithm."""
    stack = [nodes[0]]  # Start with File node
    relationships = []

    print(f"Initial stack: [{nodes[0]['name']}]\n")

    for node in nodes[1:]:
        print(f"Processing: {node['name']} at {node['start']} to {node['end']}")
        print(f"  Current stack (top to bottom): {[n['name'] for n in reversed(stack)]}")

        startA = node["start"]
        endA = node["end"]

        # Pop until we find a node that encloses this node
        found_parent = False
        while len(stack) > 1:
            top = stack[-1]
            startB = top["start"]
            endB = top["end"]

            encloses_start = not start_point_before(startA, startB)
            encloses_end = not end_point_after(endA, endB)

            print(f"  Checking against: {top['name']} at {startB} to {endB}")
            print(f"    encloses_start: {encloses_start}, encloses_end: {encloses_end}")

            if encloses_start and encloses_end:
                # top encloses node
                relationships.append(f"{top['name']} -> {node['name']}")
                print(f"  ✓ CONTAINS: {top['name']} -> {node['name']}")
                found_parent = True
                break
            else:
                print(f"  ✗ Does not enclose, popping {top['name']}")
                stack.pop()

        # If we exhausted non-file parents, attach to file
        if len(stack) == 1 and not found_parent:
            top = stack[-1]
            relationships.append(f"{top['name']} -> {node['name']}")
            print(f"  ✓ CONTAINS (fallback to File): {top['name']} -> {node['name']}")

        # Push current node onto stack
        stack.append(node)
        print(f"  Stack after push: {[n['name'] for n in stack]}\n")

    print("\n=== RELATIONSHIPS ===")
    for rel in relationships:
        print(rel)

    print("\n=== CHECKING FOR BUG ===")
    # Check if Run_Block contains WriteLine_2 (which is WRONG!)
    wrong_rel = "Run_Block -> WriteLine_2"
    if wrong_rel in relationships:
        print(f"❌ BUG FOUND: {wrong_rel}")
        print("   WriteLine_2 is at (22,12) which is OUTSIDE Run_Block's range (8,8) to (17,9)!")
    else:
        print("✓ No bug detected in traced relationships")

if __name__ == "__main__":
    trace_algorithm()

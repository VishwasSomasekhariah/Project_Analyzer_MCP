#!/usr/bin/env python3
"""
Diagnostic script to identify duplicate CONTAINS relationships in the CPG.
"""

import yaml

# Load schema
with open('/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/project_knowledgebase_graph_schema.yaml', 'r') as f:
    schema = yaml.safe_load(f)

def get_applicable_relationships(parent_type, child_type):
    """Mimics the _get_applicable_relationships() method"""
    valid_relationships = []
    all_rels = schema.get("relationships", {})

    for rel_name, rel_def in all_rels.items():
        valid_from = rel_def.get("from", [])
        valid_to = rel_def.get("to", [])

        if isinstance(valid_from, str):
            valid_from = [valid_from]
        if isinstance(valid_to, str):
            valid_to = [valid_to]

        if (parent_type in valid_from) and (child_type in valid_to):
            valid_relationships.append(rel_name)

    return valid_relationships

# Test cases
print("=== Testing relationship lookups ===\n")

print("1. Block → Statement:")
rels = get_applicable_relationships("Block", "Statement")
print(f"   Result: {rels}")
print(f"   Count: {len(rels)}\n")

print("2. File → Statement:")
rels = get_applicable_relationships("File", "Statement")
print(f"   Result: {rels}")
print(f"   Count: {len(rels)}\n")

print("3. Function → Block:")
rels = get_applicable_relationships("Function", "Block")
print(f"   Result: {rels}")
print(f"   Count: {len(rels)}\n")

print("4. Block → Literal:")
rels = get_applicable_relationships("Block", "Literal")
print(f"   Result: {rels}")
print(f"   Count: {len(rels)}\n")

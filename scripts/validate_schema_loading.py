#!/usr/bin/env python3

import yaml
import json

# Path to the schema file
schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"

print("="*80)
print("SCHEMA VALIDATION: Comparing original file vs parsed dict")
print("="*80)

# 1. Read the original YAML file as text
print("\n1. ORIGINAL YAML FILE CONTENT (first 1000 chars):")
print("-"*50)
with open(schema_path, 'r') as f:
    original_content = f.read()
print(original_content[:1000])
print("... (truncated)")

# 2. Parse the YAML file into a dict (same as what the code does)
print("\n2. PARSED SCHEMA DICT (same as state['schema']):")
print("-"*50)
with open(schema_path, 'r') as f:
    schema_dict = yaml.safe_load(f)

print("Keys in schema_dict:", list(schema_dict.keys()))

print("\nNodes section:")
if 'nodes' in schema_dict:
    for node_type, node_info in list(schema_dict['nodes'].items())[:3]:  # First 3 nodes
        print(f"  {node_type}: {node_info}")

print("\nRelationships section:")
if 'relationships' in schema_dict:
    for rel_type, rel_info in list(schema_dict['relationships'].items())[:3]:  # First 3 relationships
        print(f"  {rel_type}: {rel_info}")

# 3. What gets passed to the audit
print("\n3. WHAT GETS PASSED TO AUDIT (_format_complete_schema_for_audit):")
print("-"*50)
try:
    formatted_for_audit = yaml.dump(schema_dict, default_flow_style=False, sort_keys=True)
    print(formatted_for_audit[:800])
    print("... (truncated)")
except Exception as e:
    print(f"Error formatting: {e}")
    formatted_for_audit = json.dumps(schema_dict, indent=2)
    print(formatted_for_audit[:800])

# 4. Key differences check
print("\n4. KEY ANALYSIS:")
print("-"*50)

# Check Function node specifically
if 'nodes' in schema_dict and 'Function' in schema_dict['nodes']:
    function_node = schema_dict['nodes']['Function']
    print(f"Function node attributes: {function_node.get('attributes', [])}")
    print(f"Number of Function attributes: {len(function_node.get('attributes', []))}")
else:
    print("Function node not found or no attributes")

# Check if the dict contains the detailed attribute lists
print(f"\nTotal schema dict size: {len(str(schema_dict))} characters")
print(f"Original file size: {len(original_content)} characters")

print("\n" + "="*80)
print("CONCLUSION: Are we losing information when parsing YAML?")
print("="*80)
#!/usr/bin/env python3
import yaml

# Load schema
with open('/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/project_knowledgebase_graph_schema.yaml', 'r') as f:
    schema = yaml.safe_load(f)

print("=" * 80)
print("SCHEMA VALIDATION - Which node types have 'name' attribute?")
print("=" * 80)

for node_type, node_def in schema['nodes'].items():
    attrs = node_def.get('attributes', [])
    has_name = 'name' in attrs
    has_statements = 'statements' in attrs
    
    status = "✅" if has_name else "❌"
    print(f"{status} {node_type:15s} - name: {has_name:5s}  statements: {has_statements}")

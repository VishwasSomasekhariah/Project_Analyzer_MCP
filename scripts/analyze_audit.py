#!/usr/bin/env python3
import yaml

# Load schema
with open('/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/project_knowledgebase_graph_schema.yaml', 'r') as f:
    schema = yaml.safe_load(f)

# Actual properties from Neo4j queries
actual_properties = {
    'Project': ['project_checksum', 'project_path', 'name', 'version', 'build_properties', 'target_framework', 'dependencies', 'type', 'output_type', 'config_metadata', 'created_at', 'modified_at'],
    'File': ['file_path', 'name', 'end_point', 'type', 'import_aliases', 'imports', 'start_byte', 'start_point', 'end_byte', 'file_checksum'],
    'Function': ['body', 'return_type', 'parameters', 'type_kind', 'modifier', 'end_point', 'file_path', 'type', 'symbols_location', 'name', 'start_byte', 'start_point', 'end_byte'],
    'Type': ['body', 'type_kind', 'modifier', 'end_point', 'file_path', 'type', 'symbols_location', 'name', 'start_byte', 'start_point', 'end_byte'],
    'Variable': ['file_path', 'type_kind', 'name', 'end_point', 'type', 'symbols_location', 'start_byte', 'start_point', 'end_byte'],
    'Namespace': ['file_path', 'end_point', 'type_kind', 'name', 'type', 'symbols_location', 'body', 'start_byte', 'start_point', 'end_byte'],
    'Macro': [],  # No results
    'Block': ['file_path', 'name', 'end_point', 'type', 'symbols_location', 'type_kind', 'start_byte', 'start_point', 'end_byte'],
    'Literal': ['type_kind', 'end_point', 'file_path', 'symbols_location', 'type', 'literal_type', 'start_byte', 'start_point', 'end_byte'],
    'Statement': ['type_kind', 'end_point', 'file_path', 'statement_type', 'name', 'type', 'symbols_location', 'start_byte', 'start_point', 'end_byte']
}

print("=" * 120)
print("COMPREHENSIVE SCHEMA VALIDATION AUDIT")
print("=" * 120)

violations_found = False

for node_type in schema['nodes'].keys():
    schema_attrs = set(schema['nodes'][node_type]['attributes'])
    actual_attrs = set(actual_properties.get(node_type, []))
    
    # Find differences
    extra_props = actual_attrs - schema_attrs  # In Neo4j but not in schema
    missing_props = schema_attrs - actual_attrs  # In schema but not in Neo4j
    
    if not actual_attrs:
        print(f"\n⚠️  {node_type}:")
        print(f"    No nodes found in database (cannot audit)")
        continue
    
    if extra_props or missing_props:
        violations_found = True
        print(f"\n❌ {node_type}:")
        print(f"    Schema defines: {sorted(schema_attrs)}")
        print(f"    Neo4j has:      {sorted(actual_attrs)}")
        
        if extra_props:
            print(f"    ")
            print(f"    🔴 EXTRA properties (in Neo4j but NOT in schema):")
            for prop in sorted(extra_props):
                print(f"       - {prop}")
        
        if missing_props:
            print(f"    ")
            print(f"    🟡 MISSING properties (in schema but NOT in Neo4j):")
            for prop in sorted(missing_props):
                print(f"       - {prop}")
    else:
        print(f"\n✅ {node_type}: Perfect match")

print("\n" + "=" * 120)
if violations_found:
    print("SUMMARY: Schema violations found! See details above.")
else:
    print("SUMMARY: All node types match their schema definitions perfectly!")
print("=" * 120)

#!/usr/bin/env python3

import yaml
import json

def test_improved_formatting():
    """Test the improved audit schema formatting"""
    
    # Load the actual schema file
    schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
    
    try:
        with open(schema_path, 'r') as f:
            schema = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Failed to load schema: {e}")
        return

    # Apply the new formatting logic
    def format_complete_schema_for_audit(schema_dict):
        try:
            # Extract just the nodes and relationships sections for clarity
            audit_schema = {}
            
            if 'nodes' in schema_dict:
                audit_schema['nodes'] = schema_dict['nodes']
            
            if 'relationships' in schema_dict:
                audit_schema['relationships'] = schema_dict['relationships']
                
            # If we don't have the expected structure, pass through the whole schema
            if not audit_schema:
                audit_schema = schema_dict
                
            formatted = yaml.dump(audit_schema, default_flow_style=False, sort_keys=True)
            
            # Add explicit validation comment for the LLM
            header = """# CPG Schema Structure - NODES AND RELATIONSHIPS ONLY
# This schema shows all available node types and their attributes
# Each node under 'nodes:' is a valid node type that can be referenced
#
"""
            return header + formatted
        except Exception as e:
            # Fallback to JSON if YAML fails
            try:
                audit_schema = {'nodes': schema_dict.get('nodes', {}), 'relationships': schema_dict.get('relationships', {})}
                return f"# CPG Schema (JSON fallback)\n{json.dumps(audit_schema, indent=2)}"
            except Exception:
                return json.dumps(schema_dict, indent=2)
    
    formatted = format_complete_schema_for_audit(schema)
    
    print("=== IMPROVED FORMATTED SCHEMA ===")
    print(f"Length: {len(formatted)} characters")
    print("\nFirst 1500 characters:")
    print(formatted[:1500])
    print("\n...")
    
    print("\n=== KEY VALIDATIONS ===")
    # Check that the important nodes are clearly visible
    lines = formatted.split('\n')
    type_found = False
    namespace_found = False
    
    for i, line in enumerate(lines):
        if line.strip() == 'Type:':
            print(f"✅ Found 'Type:' at line {i+1}")
            type_found = True
            # Show the attributes
            for j in range(i+1, min(i+10, len(lines))):
                if 'attributes:' in lines[j]:
                    print(f"  Attributes section found at line {j+1}")
                    # Show first few attributes
                    for k in range(j+1, min(j+5, len(lines))):
                        if lines[k].strip().startswith('- '):
                            print(f"    {lines[k].strip()}")
                    break
            break
    
    for i, line in enumerate(lines):
        if line.strip() == 'Namespace:':
            print(f"✅ Found 'Namespace:' at line {i+1}")
            namespace_found = True
            # Show the attributes  
            for j in range(i+1, min(i+10, len(lines))):
                if 'attributes:' in lines[j]:
                    print(f"  Attributes section found at line {j+1}")
                    # Show first few attributes
                    for k in range(j+1, min(j+5, len(lines))):
                        if lines[k].strip().startswith('- '):
                            print(f"    {lines[k].strip()}")
                    break
            break
    
    if not type_found:
        print("❌ 'Type:' not found clearly in formatted schema")
    if not namespace_found:
        print("❌ 'Namespace:' not found clearly in formatted schema")
        
    print(f"\nTotal node types in formatted schema: {formatted.count(':') - formatted.count('::')}")

if __name__ == "__main__":
    test_improved_formatting()
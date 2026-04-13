#!/usr/bin/env python3

import yaml
import json
import sys
import os

def debug_schema_audit():
    """Debug what the audit system is actually seeing"""
    
    # Load the actual schema file
    schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
    
    print("=== Loading Schema File ===")
    try:
        with open(schema_path, 'r') as f:
            schema = yaml.safe_load(f)
        print("✅ Schema loaded successfully")
        print(f"Schema keys: {list(schema.keys())}")
        
        if 'nodes' in schema:
            print(f"Node types found: {list(schema['nodes'].keys())}")
            # Check if Type and Namespace are in the schema
            if 'Type' in schema['nodes']:
                print("✅ 'Type' node found in schema")
                print(f"Type attributes: {schema['nodes']['Type'].get('attributes', [])}")
            else:
                print("❌ 'Type' node NOT found in schema")
                
            if 'Namespace' in schema['nodes']:
                print("✅ 'Namespace' node found in schema")
                print(f"Namespace attributes: {schema['nodes']['Namespace'].get('attributes', [])}")
            else:
                print("❌ 'Namespace' node NOT found in schema")
        
    except Exception as e:
        print(f"❌ Failed to load schema: {e}")
        return
    
    # Test the format function
    print("\n=== Testing Format Function ===")
    try:
        formatted = yaml.dump(schema, default_flow_style=False, sort_keys=True)
        print("✅ YAML formatting successful")
        print("Formatted schema sample (first 1000 chars):")
        print(formatted[:1000])
        print("...")
        
        # Check if the formatted version contains the nodes we're looking for
        if 'Type:' in formatted and 'Namespace:' in formatted:
            print("✅ Type and Namespace found in formatted schema")
        else:
            print("❌ Type and/or Namespace NOT found in formatted schema")
            
    except Exception as e:
        print(f"❌ YAML formatting failed: {e}")
        try:
            formatted = json.dumps(schema, indent=2)
            print("✅ JSON formatting fallback successful")
            print("JSON schema sample (first 1000 chars):")
            print(formatted[:1000])
            print("...")
        except Exception as e2:
            print(f"❌ JSON formatting also failed: {e2}")

if __name__ == "__main__":
    debug_schema_audit()
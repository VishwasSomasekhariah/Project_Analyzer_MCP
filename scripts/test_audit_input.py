#!/usr/bin/env python3

import yaml
import json
import sys
import os

def test_audit_prompt():
    """Create a minimal version of what the audit LLM sees"""
    
    # Load the actual schema file
    schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
    
    try:
        with open(schema_path, 'r') as f:
            schema = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Failed to load schema: {e}")
        return

    # Format the schema the same way the audit function does
    def format_complete_schema_for_audit(schema_data):
        try:
            return yaml.dump(schema_data, default_flow_style=False, sort_keys=True)
        except Exception:
            return json.dumps(schema_data, indent=2)
    
    formatted_schema = format_complete_schema_for_audit(schema)
    
    # Create a minimal test case similar to what was failing
    test_schema_analysis = {
        "relevant_node_types": ["Type", "Namespace"], 
        "node_attribute_mapping": {
            "Type": ["name", "type_kind", "body"],
            "Namespace": ["name", "path", "body"]
        },
        "relationships_to_explore": ["CONTAINS", "DEFINED_IN"]
    }
    
    # Create the prompt exactly as the audit function does
    audit_prompt = f"""
AUDIT TASK: Validate methodological approaches against the ACTUAL CPG schema for correctness.

User Query: Test query about comments

**COMPLETE ACTUAL CPG SCHEMA** (GROUND TRUTH):
```yaml
{formatted_schema}
```

**PHASE 1 SCHEMA ANALYSIS (to validate)**:
- Identified Node Types: {test_schema_analysis['relevant_node_types']}
- Node Attribute Mapping: {json.dumps(test_schema_analysis['node_attribute_mapping'], indent=2)}
- Relationships: {test_schema_analysis['relationships_to_explore']}

**STRICT AUDIT REQUIREMENTS**:
1. Validate Phase 1 Schema Analysis:
   - Check that identified node types exist in actual schema
   - Verify node attribute mappings are correct (all mapped attributes exist)
   - Ensure appropriate node types are selected for the query type

CRITICAL: The schema above should show 'Type' and 'Namespace' nodes clearly.
Check if the COMPLETE ACTUAL CPG SCHEMA contains:
- A section with 'Type:' 
- A section with 'Namespace:'
- Attributes listed for each

Please identify if 'Type' and 'Namespace' exist in the schema and list their attributes.
"""
    
    print("=== AUDIT PROMPT SAMPLE ===")
    print("Full prompt length:", len(audit_prompt))
    print("\n=== SCHEMA SECTION ===")
    # Show just the nodes part of the formatted schema
    lines = formatted_schema.split('\n')
    in_nodes_section = False
    nodes_lines = []
    
    for line in lines:
        if line.strip().startswith('nodes:'):
            in_nodes_section = True
            nodes_lines.append(line)
        elif in_nodes_section:
            if line and not line.startswith(' ') and not line.startswith('\t'):
                # We've reached the end of the nodes section
                break
            nodes_lines.append(line)
    
    print("Nodes section from formatted schema:")
    print('\n'.join(nodes_lines[:50]))  # First 50 lines of nodes section
    print("...")
    
    print("\n=== CHECKING FOR TARGET NODES ===")
    formatted_lower = formatted_schema.lower()
    if 'type:' in formatted_lower:
        print("✅ 'type:' found in formatted schema")
    else:
        print("❌ 'type:' NOT found in formatted schema")
        
    if 'namespace:' in formatted_lower:
        print("✅ 'namespace:' found in formatted schema")  
    else:
        print("❌ 'namespace:' NOT found in formatted schema")

if __name__ == "__main__":
    test_audit_prompt()
#!/usr/bin/env python3

import yaml
import json
from src.core.workflow.research_engine import ResearchEngine

async def debug_audit_issue():
    """Debug why the audit is giving false negatives"""
    
    # Load the actual schema
    schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
    with open(schema_path, 'r') as f:
        schema = yaml.safe_load(f)
    
    # Create a dummy research engine to test the formatting
    class MockLLMService:
        pass
    
    research_engine = ResearchEngine(MockLLMService())
    
    # Test the format function
    formatted_schema = research_engine._format_complete_schema_for_audit(schema)
    
    print("=== FORMATTED SCHEMA FOR AUDIT ===")
    print("Length:", len(formatted_schema))
    
    # Check if the key attributes are present
    print("\n=== CHECKING KEY ATTRIBUTES ===")
    
    # Look for Type node and its attributes
    lines = formatted_schema.split('\n')
    type_section = []
    in_type_section = False
    type_found = False
    
    for i, line in enumerate(lines):
        if line.strip() == 'Type:':
            type_found = True
            in_type_section = True
            type_section.append(f"Line {i+1}: {line}")
            print(f"✅ Found Type: at line {i+1}")
            
            # Get the attributes section
            for j in range(i+1, min(i+20, len(lines))):
                type_section.append(f"Line {j+1}: {lines[j]}")
                if 'attributes:' in lines[j]:
                    print(f"✅ Found attributes section at line {j+1}")
                    # List the attributes
                    for k in range(j+1, min(j+20, len(lines))):
                        if lines[k].strip().startswith('- '):
                            attr = lines[k].strip()[2:]
                            type_section.append(f"Line {k+1}: {lines[k]}")
                            if attr == 'documentation':
                                print(f"✅ Found 'documentation' attribute at line {k+1}")
                        elif lines[k].strip() and not lines[k].startswith(' '):
                            # End of attributes
                            break
                    break
            break
    
    if not type_found:
        print("❌ Type: section not found in formatted schema!")
        return
        
    print(f"\n=== TYPE SECTION ({len(type_section)} lines) ===")
    for line in type_section:
        print(line)
    
    # Test specific attribute checks
    print(f"\n=== ATTRIBUTE VERIFICATION ===")
    if 'documentation' in formatted_schema:
        print("✅ 'documentation' found in formatted schema")
    else:
        print("❌ 'documentation' NOT found in formatted schema")
    
    if 'value' in formatted_schema:
        print("✅ 'value' found in formatted schema") 
    else:
        print("❌ 'value' NOT found in formatted schema")
        
    # Test the exact prompt that would be sent
    print(f"\n=== AUDIT PROMPT TEST ===")
    test_schema_analysis = {
        "relevant_node_types": ["Type"],
        "node_attribute_mapping": {"Type": ["documentation", "file_path"]},
        "relationships_to_explore": ["CONTAINS"]
    }
    
    # This is what gets sent to the audit LLM
    audit_prompt_schema_section = f"""
**COMPLETE ACTUAL CPG SCHEMA** (GROUND TRUTH):
```yaml
{formatted_schema}
```

**PHASE 1 SCHEMA ANALYSIS (to validate)**:
- Identified Node Types: {test_schema_analysis['relevant_node_types']}
- Node Attribute Mapping: {json.dumps(test_schema_analysis['node_attribute_mapping'], indent=2)}
"""
    
    print("Audit prompt schema section length:", len(audit_prompt_schema_section))
    print("First 2000 characters:")
    print(audit_prompt_schema_section[:2000])
    print("...")

if __name__ == "__main__":
    import asyncio
    asyncio.run(debug_audit_issue())
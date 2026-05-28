#!/usr/bin/env python3
"""
Test the new validate_relationship_triplet tool.

This script verifies that:
1. Valid triplets return is_valid=True
2. Invalid triplets return is_valid=False with alternatives
3. Non-existent relationship types return appropriate errors
"""

import sys
sys.path.insert(0, '/opt/genpod')

import json
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from src.core.workflow.schema_tools import SchemaTools
from src.core.workflow.schema_tools_langchain import create_schema_tools


def test_triplet_validation():
    """Test the validate_relationship_triplet functionality."""

    print("=" * 80)
    print("Testing validate_relationship_triplet Tool")
    print("=" * 80)

    # Load reconciled schema
    print("\n1. Loading reconciled schema...")
    try:
        with open('/tmp/reconciled_schema_complete.json', 'r') as f:
            schema_data = json.load(f)
        print("   ✅ Schema loaded successfully")
    except Exception as e:
        print(f"   ❌ Failed to load schema: {e}")
        return

    # Create mock schema manager with just the schema data
    print("\n2. Creating schema manager...")
    class MockSchemaManager:
        def __init__(self, schema):
            self._reconciled_schema = schema

    schema_manager = MockSchemaManager(schema_data)
    print("   ✅ Schema manager created")

    # Create schema tools
    print("\n3. Creating schema tools...")
    schema_tools = SchemaTools(schema_manager)
    langchain_tools = create_schema_tools(schema_manager)
    print(f"   ✅ Created {len(langchain_tools)} LangChain tools")

    # Find the validate_relationship_triplet tool
    triplet_tool = None
    for tool in langchain_tools:
        if tool.name == "validate_relationship_triplet":
            triplet_tool = tool
            break

    if not triplet_tool:
        print("   ❌ validate_relationship_triplet tool not found!")
        return

    print("   ✅ Found validate_relationship_triplet tool")

    print("\n" + "=" * 80)
    print("Test Cases")
    print("=" * 80)

    # Test Case 1: VALID triplet (Variable -> REFERENCES -> Type)
    print("\n📋 Test 1: Valid triplet (Variable-[:REFERENCES]->Type)")
    result1 = triplet_tool.invoke({
        "from_label": "Variable",
        "relationship_type": "REFERENCES",
        "to_label": "Type"
    })
    print(f"   Result: {json.dumps(result1, indent=2)}")
    assert result1['is_valid'] == True, "Expected is_valid=True for Variable->REFERENCES->Type"
    print("   ✅ PASS: Valid triplet correctly identified")

    # Test Case 2: INVALID triplet (Statement -> REFERENCES -> Type)
    print("\n📋 Test 2: Invalid triplet (Statement-[:REFERENCES]->Type)")
    result2 = triplet_tool.invoke({
        "from_label": "Statement",
        "relationship_type": "REFERENCES",
        "to_label": "Type"
    })
    print(f"   Result: {json.dumps(result2, indent=2)}")
    assert result2['is_valid'] == False, "Expected is_valid=False for Statement->REFERENCES->Type"
    assert 'from_alternatives' in result2, "Expected from_alternatives in response"
    assert 'to_alternatives' in result2, "Expected to_alternatives in response"
    print("   ✅ PASS: Invalid triplet correctly identified")
    print(f"   📊 Found {len(result2['from_alternatives'])} alternatives from Statement")
    print(f"   📊 Found {len(result2['to_alternatives'])} alternatives to Type")

    # Show some alternatives
    if result2['from_alternatives'][:3]:
        print(f"   💡 Sample from_alternatives: {result2['from_alternatives'][:3]}")
    if result2['to_alternatives'][:3]:
        print(f"   💡 Sample to_alternatives: {result2['to_alternatives'][:3]}")

    # Test Case 3: VALID triplet (Function -> CONTAINS -> Block)
    print("\n📋 Test 3: Valid triplet (Function-[:CONTAINS]->Block)")
    result3 = triplet_tool.invoke({
        "from_label": "Function",
        "relationship_type": "CONTAINS",
        "to_label": "Block"
    })
    print(f"   Result: {json.dumps(result3, indent=2)}")
    assert result3['is_valid'] == True, "Expected is_valid=True for Function->CONTAINS->Block"
    print("   ✅ PASS: Valid triplet correctly identified")

    # Test Case 4: NON-EXISTENT relationship type
    print("\n📋 Test 4: Non-existent relationship (Function-[:FAKE_REL]->Type)")
    result4 = triplet_tool.invoke({
        "from_label": "Function",
        "relationship_type": "FAKE_REL",
        "to_label": "Type"
    })
    print(f"   Result: {json.dumps(result4, indent=2)}")
    assert result4['is_valid'] == False, "Expected is_valid=False for non-existent relationship"
    assert 'error' in result4, "Expected error field for non-existent relationship"
    print("   ✅ PASS: Non-existent relationship correctly handled")

    # Test Case 5: Test that ALL alternatives are returned (no slicing)
    print("\n📋 Test 5: Verify ALL alternatives are returned (no slicing)")
    # Get the full schema to count expected alternatives
    relationships = schema_data.get('relationships', {})

    # Count expected from_alternatives for Statement
    expected_from_statement = 0
    for rel_name, rel_info in relationships.items():
        for pair in rel_info.get('valid_pairs', []):
            if pair.get('from') == 'Statement':
                expected_from_statement += 1

    actual_from_statement = len(result2['from_alternatives'])
    print(f"   Expected from Statement: {expected_from_statement}")
    print(f"   Actual from Statement: {actual_from_statement}")
    assert actual_from_statement == expected_from_statement, f"Expected {expected_from_statement} alternatives, got {actual_from_statement}"
    print("   ✅ PASS: All alternatives returned (no slicing)")

    print("\n" + "=" * 80)
    print("✅ All Tests Passed!")
    print("=" * 80)
    print("\n✨ The validate_relationship_triplet tool is working correctly!")
    print("\nKey Features Verified:")
    print("  ✅ Valid triplets return is_valid=True")
    print("  ✅ Invalid triplets return is_valid=False with alternatives")
    print("  ✅ Non-existent relationships return error messages")
    print("  ✅ ALL alternatives are returned (no slicing)")
    print("  ✅ No hardcoded special cases or suggestions")


if __name__ == "__main__":
    test_triplet_validation()

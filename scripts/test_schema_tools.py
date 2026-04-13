#!/usr/bin/env python3
"""
Test script for Schema Tools

Demonstrates how the 8 schema discovery tools work with actual reconciled schema.
"""

import asyncio
import json
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from src.core.workflow.schema_tools import SchemaTools


async def main():
    print("=" * 80)
    print("SCHEMA TOOLS DEMONSTRATION")
    print("=" * 80)

    print("\n📊 Loading existing reconciled schema from benchmark results...")

    # Load a reconciled schema from previous run
    with open('/tmp/reconciled_schema_complete.json', 'r') as f:
        reconciled_schema = json.load(f)

    # Create a mock DynamicSchemaManager with the reconciled schema
    class MockSchemaManager:
        def __init__(self, reconciled_schema):
            self._reconciled_schema = reconciled_schema

    schema_manager = MockSchemaManager(reconciled_schema)

    # Create SchemaTools instance
    tools = SchemaTools(schema_manager)

    print("✅ Schema tools ready!\n")
    print(f"   Loaded schema with {len(reconciled_schema.get('nodes', {}))} node types")
    print(f"   and {len(reconciled_schema.get('relationships', {}))} relationship types\n")

    # Test each tool
    print("=" * 80)
    print("TOOL 1: get_node_labels()")
    print("=" * 80)
    result = tools.get_node_labels()
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 2: get_valid_pairs('REFERENCES')")
    print("=" * 80)
    result = tools.get_valid_pairs("REFERENCES")
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 3: get_outgoing_relationships('Function')")
    print("=" * 80)
    result = tools.get_outgoing_relationships("Function")
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 4: get_node_properties('Statement')")
    print("=" * 80)
    result = tools.get_node_properties("Statement")
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 5: get_children_types('Block')")
    print("=" * 80)
    result = tools.get_children_types("Block")
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 7: get_incoming_relationships('Type')")
    print("=" * 80)
    result = tools.get_incoming_relationships("Type")
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("TOOL 8: get_leaf_nodes()")
    print("=" * 80)
    result = tools.get_leaf_nodes()
    print(json.dumps(result, indent=2))

    print("\n" + "=" * 80)
    print("EXAMPLE WORKFLOW: Building a query step-by-step")
    print("=" * 80)

    print("\n🎯 Goal: Find Type nodes instantiated in CreateWorkers function")

    print("\n📍 Step 1: Check if Function node exists")
    result = tools.get_node_properties("Function")
    print(f"   Function exists: {result['exists']}")
    print(f"   Properties: {result['properties'][:5]}...")  # Show first 5

    print("\n📍 Step 2: Find relationships from Function to Block")
    result = tools.get_outgoing_relationships("Function")
    has_contains = "CONTAINS" in result.get('outgoing', {})
    targets = result.get('outgoing', {}).get('CONTAINS', [])
    print(f"   Function has CONTAINS: {has_contains}")
    print(f"   Can contain: {targets}")

    print("\n📍 Step 3: Check if Block can contain Statement")
    result = tools.get_outgoing_relationships("Block")
    has_statement = "Statement" in result.get('outgoing', {}).get('CONTAINS', [])
    print(f"   Block can contain Statement: {has_statement}")

    print("\n📍 Step 4: Find path from Statement to Type")
    result = tools.get_outgoing_relationships("Statement")
    rels_to_type = []
    for rel, targets in result.get('outgoing', {}).items():
        if 'Type' in targets:
            rels_to_type.append(rel)
    print(f"   Statement -> Type via: {rels_to_type}")

    print("\n📍 Step 5: Verify REFERENCES relationship")
    result = tools.get_valid_pairs("REFERENCES")
    pairs = result.get('valid_pairs', [])
    statement_to_type = any(
        p['from'] == 'Statement' and p['to'] == 'Type'
        for p in pairs
    )
    print(f"   Statement-[:REFERENCES]->Type is valid: {statement_to_type}")

    print("\n✅ Built query path:")
    print("   Function-[:CONTAINS]->Block-[:CONTAINS]->Statement-[:REFERENCES]->Type")

    print("\n📝 Generated Cypher:")
    query = """MATCH (f:Function {name: 'CreateWorkers'})
      -[:CONTAINS]->(b:Block)
      -[:CONTAINS]->(s:Statement)
      -[:REFERENCES]->(t:Type)
RETURN t"""
    print(query)

    print("\n" + "=" * 80)
    print("✅ DEMONSTRATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

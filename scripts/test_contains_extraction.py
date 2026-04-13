#!/usr/bin/env python3
"""
Validation test to verify CONTAINS relationship extraction after fix.
Tests that embedding-based extraction properly identifies CONTAINS from
semantic queries about containment.
"""
import asyncio
import json
import sys
import yaml
sys.path.insert(0, '/opt/genpod')

from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def test_contains_extraction():
    """Test that CONTAINS relationship is extracted from containment queries"""

    print("=" * 80)
    print("VALIDATION TEST: CONTAINS Relationship Extraction")
    print("=" * 80)
    print()

    # Load YAML schema
    print("1️⃣  Loading YAML schema...")
    with open("/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)
    print(f"✅ Loaded YAML schema with {len(yaml_schema.get('NodeDefinitions', {}))} node types\n")

    # Initialize schema manager
    print("2️⃣  Initializing DynamicSchemaManager...")
    manager = DynamicSchemaManager(
        yaml_schema=yaml_schema,
        cache_file="/tmp/test_contains_cache.json"
    )

    # Mock cypher server for this test
    class MockCypherServer:
        async def execute_query(self, query: str):
            # Return minimal APOC schema in the expected format
            apoc_schema = {
                "Function": {
                    "type": "node",
                    "properties": {
                        "name": {"type": "STRING", "indexed": False},
                        "body": {"type": "STRING", "indexed": False}
                    },
                    "count": 10
                },
                "Type": {
                    "type": "node",
                    "properties": {
                        "name": {"type": "STRING", "indexed": False}
                    },
                    "count": 5
                },
                "Namespace": {
                    "type": "node",
                    "properties": {
                        "name": {"type": "STRING", "indexed": False}
                    },
                    "count": 3
                },
                "CONTAINS": {
                    "type": "relationship",
                    "properties": {},
                    "relationships": {
                        "Type": {
                            "Function": {
                                "direction": "out",
                                "count": 10
                            }
                        },
                        "Namespace": {
                            "Function": {
                                "direction": "out",
                                "count": 5
                            }
                        }
                    },
                    "count": 15
                }
            }

            return {
                'success': True,
                'results': [{'value': apoc_schema}]
            }

    manager.cypher_server = MockCypherServer()

    # Initialize (reconcile schemas and build embeddings)
    await manager.initialize_background()
    print("✅ Initialization complete\n")

    # Test Case 1: Query mentioning "contained in"
    print("3️⃣  Test Case 1: 'locate Function F where F is contained in Type T'")
    print("-" * 80)

    test_text_1 = """
    Premises:
    - T: Type node
    - F: Function node

    Subquery:
    locate Function node F where F.name='MyMethod' and F is contained in Type node T where T.name='MyClass'
    """

    extracted_1 = manager.extract_types_from_query(test_text_1)
    print(f"Extracted node types: {extracted_1['node_types']}")
    print(f"Extracted relationship types: {extracted_1['relationship_types']}")

    if 'CONTAINS' in extracted_1['relationship_types']:
        print("✅ CONTAINS successfully extracted from 'is contained in'")
    else:
        print("❌ CONTAINS NOT extracted (this should not happen!)")
    print()

    # Test Case 2: Query mentioning "contains"
    print("4️⃣  Test Case 2: 'Type T contains Function F'")
    print("-" * 80)

    test_text_2 = """
    Premises:
    - T: Type node representing a class
    - F: Function node representing a method

    Subquery:
    locate all Function nodes F where Type node T contains F and T.name='WorkerFactory'
    """

    extracted_2 = manager.extract_types_from_query(test_text_2)
    print(f"Extracted node types: {extracted_2['node_types']}")
    print(f"Extracted relationship types: {extracted_2['relationship_types']}")

    if 'CONTAINS' in extracted_2['relationship_types']:
        print("✅ CONTAINS successfully extracted from 'contains'")
    else:
        print("❌ CONTAINS NOT extracted (this should not happen!)")
    print()

    # Test Case 3: Query mentioning hierarchical nesting
    print("5️⃣  Test Case 3: 'Namespace nesting Functions'")
    print("-" * 80)

    test_text_3 = """
    Premises:
    - NS: Namespace node
    - F: Function node

    Subquery:
    locate Namespace NS that nests Function F, modeling hierarchical structure of source code
    """

    extracted_3 = manager.extract_types_from_query(test_text_3)
    print(f"Extracted node types: {extracted_3['node_types']}")
    print(f"Extracted relationship types: {extracted_3['relationship_types']}")

    if 'CONTAINS' in extracted_3['relationship_types']:
        print("✅ CONTAINS successfully extracted from 'nesting/hierarchical'")
    else:
        print("❌ CONTAINS NOT extracted (this should not happen!)")
    print()

    # Verify rich description is being used
    print("6️⃣  Verifying CONTAINS description from EdgeDefinitions")
    print("-" * 80)

    contains_data = manager._reconciled_schema['relationships'].get('CONTAINS', {})
    contains_desc = contains_data.get('description', 'NOT FOUND')

    print(f"CONTAINS description length: {len(contains_desc)} characters")
    print(f"Description preview: {contains_desc[:150]}...")
    print()

    if len(contains_desc) > 200:
        print("✅ Rich semantic description from EdgeDefinitions is being used")
    else:
        print("❌ Description seems too short - might be using fallback")
    print()

    # Summary
    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    all_passed = (
        'CONTAINS' in extracted_1['relationship_types'] and
        'CONTAINS' in extracted_2['relationship_types'] and
        'CONTAINS' in extracted_3['relationship_types'] and
        len(contains_desc) > 200
    )

    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("✅ CONTAINS relationship is properly extracted from semantic queries")
        print("✅ EdgeDefinitions descriptions are being used for embeddings")
    else:
        print("❌ SOME TESTS FAILED")
        print("❌ Review the output above to identify issues")
    print()


if __name__ == "__main__":
    asyncio.run(test_contains_extraction())

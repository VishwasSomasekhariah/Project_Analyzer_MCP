#!/usr/bin/env python3
"""
Test what suggestions the validator actually returns for Statement→Type
"""
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.workflow.cypher_query_validator import CypherQueryValidator
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
import asyncio

async def test_validator_suggestions():
    # Initialize schema manager
    manager = DynamicSchemaManager(
        neo4j_config_path='neo4j_config.json',
        cpg_yaml_path='src/integrations/cpg/cpg_schema.yaml'
    )

    # Wait for initialization
    await manager.initialize()

    # Get reconciled schema
    schema = manager._reconciled_schema

    print("=" * 80)
    print("TESTING VALIDATOR SUGGESTIONS")
    print("=" * 80)

    # Test Query 1: Statement-[:CONTAINS]->Type
    query1 = """
    MATCH (stmt:Statement)-[:CONTAINS]->(t:Type)
    WHERE stmt.type = 'assignment'
    RETURN t.name
    """

    print("\n### TEST 1: (Statement)-[:CONTAINS]->(Type)")
    print(f"Query: {query1.strip()}")

    validator = CypherQueryValidator(schema)
    result = validator.validate(query1)

    print(f"\nValid: {result.is_valid}")
    print(f"Errors: {len(result.errors)}")

    for issue in result.get_errors():
        print(f"\n❌ {issue.location}")
        print(f"   Message: {issue.message}")
        print(f"   Suggestion: {issue.suggestion if issue.suggestion else '(NONE)'}")

    # Test Query 2: Statement-[:REFERENCES]->Type
    query2 = """
    MATCH (stmt:Statement)-[:REFERENCES]->(t:Type)
    RETURN t.name
    """

    print("\n" + "=" * 80)
    print("### TEST 2: (Statement)-[:REFERENCES]->(Type)")
    print(f"Query: {query2.strip()}")

    result2 = validator.validate(query2)

    print(f"\nValid: {result2.is_valid}")
    print(f"Errors: {len(result2.errors)}")

    for issue in result2.get_errors():
        print(f"\n❌ {issue.location}")
        print(f"   Message: {issue.message}")
        print(f"   Suggestion: {issue.suggestion if issue.suggestion else '(NONE)'}")

    # Show what CONTAINS relationships actually exist
    print("\n" + "=" * 80)
    print("### VALID CONTAINS RELATIONSHIPS IN SCHEMA")
    print("=" * 80)

    contains_pairs = validator.valid_pairs.get('CONTAINS', set())
    print(f"\nTotal CONTAINS pairs: {len(contains_pairs)}")

    for source, target in sorted(contains_pairs):
        print(f"  ({source})-[:CONTAINS]->({target})")

    # Check if Statement appears anywhere
    print("\n### STATEMENT RELATIONSHIPS")
    has_statement = False
    for rel_type, pairs in validator.valid_pairs.items():
        for source, target in pairs:
            if 'Statement' in (source, target):
                print(f"  ({source})-[:{rel_type}]->({target})")
                has_statement = True

    if not has_statement:
        print("  ⚠️  Statement nodes have NO relationships in the schema!")

# Run the test
asyncio.run(test_validator_suggestions())

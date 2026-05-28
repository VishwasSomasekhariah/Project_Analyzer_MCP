#!/usr/bin/env python3
"""
Test Cypher Query Validator Integration in CoT Generate Step

This script tests that the validator catches invalid queries and provides
helpful feedback for the LLM to fix them.
"""
import asyncio
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.workflow.cypher_query_validator import CypherQueryValidator, create_default_validator

async def main():
    print("=" * 80)
    print("Testing Cypher Query Validator Integration")
    print("=" * 80)

    # Create validator with reconciled schema
    validator = create_default_validator()

    # Test 1: Invalid relationship (Statement-IMPLEMENTS->Type)
    print("\n" + "=" * 80)
    print("Test 1: Invalid Relationship (Statement-IMPLEMENTS->Type)")
    print("=" * 80)

    invalid_query_1 = """
    MATCH (p:Project {name: 'HelloWorldApp'})-[:CONTAINS]->(:File)
          -[:CONTAINS]->(:Namespace)-[:CONTAINS]->(t:Type {name: 'WorkerFactory'})
          -[:CONTAINS]->(f:Function {name: 'CreateWorkers'})
          -[:CONTAINS]->(:Block)-[:CONTAINS]->(s:Statement)
          -[:IMPLEMENTS]->(type:Type)
    RETURN s.text, type.name
    """

    result1 = validator.validate(invalid_query_1)

    print(f"Result: {'✅ VALID' if result1.is_valid else '❌ INVALID'}")

    if not result1.is_valid:
        print("\nErrors found:")
        for issue in result1.get_errors():
            print(f"  ❌ {issue.location}: {issue.message}")
            if issue.suggestion:
                print(f"     💡 {issue.suggestion}")

    # Test 2: Invalid property (Function.invalid_property)
    print("\n" + "=" * 80)
    print("Test 2: Invalid Property (Function.invalid_property)")
    print("=" * 80)

    invalid_query_2 = """
    MATCH (f:Function)
    WHERE f.invalid_property = 'test'
    RETURN f.name
    """

    result2 = validator.validate(invalid_query_2)

    print(f"Result: {'✅ VALID' if result2.is_valid else '❌ INVALID'}")

    if not result2.is_valid:
        print("\nErrors found:")
        for issue in result2.get_errors():
            print(f"  ❌ {issue.location}: {issue.message}")
            if issue.suggestion:
                print(f"     💡 Suggestion: {issue.suggestion[:100]}...")

    # Test 3: Valid query (should pass)
    print("\n" + "=" * 80)
    print("Test 3: Valid Query (File->Type->Function)")
    print("=" * 80)

    valid_query = """
    MATCH (p:Project {name: 'HelloWorldApp'})-[:CONTAINS]->(f:File)
          -[:CONTAINS]->(t:Type)-[:CONTAINS]->(func:Function)
    WHERE func.name = 'CreateWorkers'
    RETURN f.name, t.name, func.name
    """

    result3 = validator.validate(valid_query)

    print(f"Result: {'✅ VALID' if result3.is_valid else '❌ INVALID'}")

    if not result3.is_valid:
        print("\nUnexpected errors:")
        for issue in result3.get_errors():
            print(f"  ❌ {issue.location}: {issue.message}")

    # Test 4: Show how feedback would be formatted for LLM
    print("\n" + "=" * 80)
    print("Test 4: Example Feedback for LLM (from Test 1)")
    print("=" * 80)

    if not result1.is_valid:
        error_messages = []
        for issue in result1.get_errors():
            error_messages.append(f"  ❌ {issue.location}: {issue.message}")
            if issue.suggestion:
                error_messages.append(f"     💡 {issue.suggestion}")

        feedback = f"""Your generated Cypher query has schema validation errors:

{chr(10).join(error_messages)}

Please regenerate the query fixing these issues. Ensure:
1. All node labels exist in the schema
2. All relationship types are valid between the specified node types
3. All properties exist on the correct node types
4. Follow the relationship cardinality rules from the schema

Review the suggestions above and generate a corrected query."""

        print(feedback)

    print("\n" + "=" * 80)
    print("✅ Integration test complete!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())

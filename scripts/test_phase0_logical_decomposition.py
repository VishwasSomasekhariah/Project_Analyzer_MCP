"""
Test Phase 0: Logical Query Decomposition

Tests the new logical reasoning-based query decomposition that uses
modal logic and formal reasoning to interpret user queries.
"""
import asyncio
import yaml
import json
from pathlib import Path

from src.core.llm_service import LLMService
from src.core.workflow.research_engine import ResearchEngine


async def test_phase0_decomposition():
    """Test Phase 0 logical query decomposition"""

    # Initialize services
    llm_service = LLMService()
    research_engine = ResearchEngine(llm_service)

    # Load schema
    schema_path = Path("src/schemas/project_knowledgebase_graph_schema.yaml")
    with open(schema_path, 'r') as f:
        schema = yaml.safe_load(f)

    print("=" * 80)
    print("TESTING PHASE 0: LOGICAL QUERY DECOMPOSITION")
    print("=" * 80)

    # Test Case 1: Specific lookup query
    print("\n" + "=" * 80)
    print("TEST CASE 1: Specific Lookup Query")
    print("=" * 80)

    user_query_1 = "How many method calls are in Manager.Run()?"
    intent_1 = {
        "intent_type": "lookup",
        "confidence": 0.9,
        "reasoning": "Query asks 'how many' which indicates counting/lookup intent",
        "expected_result_type": "Numeric count of method calls"
    }

    state_1 = {
        'user_query': user_query_1,
        'intent': intent_1,
        'schema': schema
    }

    print(f"\nUser Query: {user_query_1}")
    print(f"Intent Type: {intent_1['intent_type']}")
    print(f"Confidence: {intent_1['confidence']}")

    result_1 = await research_engine._decompose_user_query(state_1)

    print("\n--- DECOMPOSITION RESULT ---")
    print(f"Intent: {result_1['intent']}")
    print(f"Logical Form: {result_1['logical_form']}")
    print(f"\nPremises:")
    for premise in result_1['premises']:
        print(f"  - {premise}")
    print(f"\nSubqueries:")
    for i, subquery in enumerate(result_1['subqueries'], 1):
        print(f"  [{i}] {subquery}")

    # Save result to /tmp
    output_path_1 = '/tmp/phase0_test_case1_result.json'
    with open(output_path_1, 'w') as f:
        json.dump(result_1, f, indent=2)
    print(f"\n✅ Result saved to {output_path_1}")

    # Test Case 2: Exploratory query
    print("\n" + "=" * 80)
    print("TEST CASE 2: Exploratory Query")
    print("=" * 80)

    user_query_2 = "What is the HelloWorldApp project about?"
    intent_2 = {
        "intent_type": "exploratory",
        "confidence": 0.8,
        "reasoning": "Broad 'what is' question indicates exploratory intent",
        "expected_result_type": "Summary description"
    }

    state_2 = {
        'user_query': user_query_2,
        'intent': intent_2,
        'schema': schema
    }

    print(f"\nUser Query: {user_query_2}")
    print(f"Intent Type: {intent_2['intent_type']}")
    print(f"Confidence: {intent_2['confidence']}")

    result_2 = await research_engine._decompose_user_query(state_2)

    print("\n--- DECOMPOSITION RESULT ---")
    print(f"Intent: {result_2['intent']}")
    print(f"Logical Form: {result_2['logical_form']}")
    print(f"\nPremises:")
    for premise in result_2['premises']:
        print(f"  - {premise}")
    print(f"\nSubqueries:")
    for i, subquery in enumerate(result_2['subqueries'], 1):
        print(f"  [{i}] {subquery}")

    # Save result to /tmp
    output_path_2 = '/tmp/phase0_test_case2_result.json'
    with open(output_path_2, 'w') as f:
        json.dump(result_2, f, indent=2)
    print(f"\n✅ Result saved to {output_path_2}")

    # Test Case 3: Ambiguous query
    print("\n" + "=" * 80)
    print("TEST CASE 3: Ambiguous Query")
    print("=" * 80)

    user_query_3 = "How many method calls are in run?"
    intent_3 = {
        "intent_type": "lookup",
        "confidence": 0.6,
        "reasoning": "Counting query but ambiguous target (multiple 'run' functions may exist)",
        "expected_result_type": "Numeric count (after disambiguation)"
    }

    state_3 = {
        'user_query': user_query_3,
        'intent': intent_3,
        'schema': schema
    }

    print(f"\nUser Query: {user_query_3}")
    print(f"Intent Type: {intent_3['intent_type']}")
    print(f"Confidence: {intent_3['confidence']}")

    result_3 = await research_engine._decompose_user_query(state_3)

    print("\n--- DECOMPOSITION RESULT ---")
    print(f"Intent: {result_3['intent']}")
    print(f"Logical Form: {result_3['logical_form']}")
    print(f"\nPremises:")
    for premise in result_3['premises']:
        print(f"  - {premise}")
    print(f"\nSubqueries:")
    for i, subquery in enumerate(result_3['subqueries'], 1):
        print(f"  [{i}] {subquery}")

    # Save result to /tmp
    output_path_3 = '/tmp/phase0_test_case3_result.json'
    with open(output_path_3, 'w') as f:
        json.dump(result_3, f, indent=2)
    print(f"\n✅ Result saved to {output_path_3}")

    print("\n" + "=" * 80)
    print("ALL TEST CASES COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_phase0_decomposition())

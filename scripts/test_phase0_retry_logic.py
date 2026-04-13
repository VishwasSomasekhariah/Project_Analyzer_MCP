"""
Test Phase 0 Retry Logic

Tests the new retry mechanism for Phase 0 decomposition, especially for queries
that previously failed (like T039).
"""
import asyncio
import yaml
from pathlib import Path

from src.core.llm_service import LLMService
from src.core.workflow.research_engine import ResearchEngine


async def test_retry_logic():
    """Test Phase 0 retry logic on previously failed queries"""

    # Initialize services
    llm_service = LLMService()
    research_engine = ResearchEngine(llm_service)

    # Load schema
    schema_path = Path("src/schemas/project_knowledgebase_graph_schema.yaml")
    with open(schema_path, 'r') as f:
        schema = yaml.safe_load(f)

    # Test queries - including T039 which previously scored 1.36/10
    test_cases = [
        {
            "id": "T039",
            "query": "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?",
            "intent": {
                "intent_type": "lookup",
                "confidence": 0.95,
                "reasoning": "Query asks for specific classes created by factory method",
                "expected_result_type": "List of class names"
            }
        },
        {
            "id": "T055",
            "query": "How many .cs files are in the main directory (excluding subdirectories)?",
            "intent": {
                "intent_type": "lookup",
                "confidence": 0.85,
                "reasoning": "Query asks for count of specific file type in directory",
                "expected_result_type": "Integer count"
            }
        },
        {
            "id": "SUCCESS_CASE",
            "query": "How many method calls are in Manager.Run()?",
            "intent": {
                "intent_type": "lookup",
                "confidence": 0.9,
                "reasoning": "Specific method call count query",
                "expected_result_type": "Integer count"
            }
        }
    ]

    print("=" * 80)
    print("TESTING PHASE 0 RETRY LOGIC")
    print("=" * 80)
    print()

    results = []

    for i, test in enumerate(test_cases, 1):
        print(f"\n[{i}/{len(test_cases)}] Testing: {test['id']}")
        print(f"Query: {test['query']}")
        print()

        try:
            # Prepare state
            state = {
                'user_query': test['query'],
                'intent': test['intent'],
                'schema': schema
            }

            # Call decompose with retry logic
            print("  → Running Phase 0 decomposition with retry logic...")
            decomposition = await research_engine._decompose_user_query(state)

            print("  ✅ Success!")
            print(f"     Intent: {decomposition['intent']}")
            print(f"     Logical Form: {decomposition['logical_form'][:80]}...")
            print(f"     Premises: {len(decomposition['premises'])}")
            print(f"     Subqueries: {len(decomposition['subqueries'])}")

            # Check for pass-through indicators
            is_passthrough = (
                "ANSWER(" in decomposition['logical_form'] or
                any("cannot be decomposed" in p.lower() for p in decomposition['premises']) or
                any("retrieve answer to:" in sq.lower() for sq in decomposition['subqueries'])
            )

            if is_passthrough:
                print("  ⚠️  WARNING: Possible pass-through detected!")
                result = "PASS_THROUGH"
            else:
                print("  ✅ Valid decomposition (not pass-through)")
                result = "SUCCESS"

            results.append({
                "test_id": test['id'],
                "status": result,
                "decomposition": decomposition
            })

        except ValueError as e:
            print(f"  ❌ Failed: {e}")
            results.append({
                "test_id": test['id'],
                "status": "FAILED",
                "error": str(e)
            })

        except Exception as e:
            print(f"  ❌ Unexpected error: {e}")
            results.append({
                "test_id": test['id'],
                "status": "ERROR",
                "error": str(e)
            })

    # Summary
    print("\n" + "=" * 80)
    print("RETRY LOGIC TEST SUMMARY")
    print("=" * 80)
    print(f"Total tests: {len(test_cases)}")
    print(f"Successful: {len([r for r in results if r['status'] == 'SUCCESS'])}")
    print(f"Pass-through: {len([r for r in results if r['status'] == 'PASS_THROUGH'])}")
    print(f"Failed: {len([r for r in results if r['status'] in ['FAILED', 'ERROR']])}")
    print()

    # Key findings
    print("KEY FINDINGS:")
    for result in results:
        status_emoji = {
            "SUCCESS": "✅",
            "PASS_THROUGH": "⚠️",
            "FAILED": "❌",
            "ERROR": "❌"
        }.get(result['status'], "❓")

        print(f"  {status_emoji} {result['test_id']}: {result['status']}")

    print()
    print("=" * 80)

    # Specifically check T039
    t039_result = next((r for r in results if r['test_id'] == 'T039'), None)
    if t039_result:
        print("\nT039 ANALYSIS (Previously scored 1.36/10):")
        print("-" * 80)
        if t039_result['status'] == 'SUCCESS':
            print("✅ T039 now successfully decomposes without fallback!")
            print("\nDecomposition:")
            decomp = t039_result['decomposition']
            print(f"  Logical Form: {decomp['logical_form']}")
            print(f"  Premises: {len(decomp['premises'])}")
            print(f"  Subqueries: {len(decomp['subqueries'])}")
        elif t039_result['status'] == 'PASS_THROUGH':
            print("⚠️  T039 still using pass-through (needs prompt improvement)")
        else:
            print(f"❌ T039 failed: {t039_result.get('error', 'Unknown error')}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_retry_logic())

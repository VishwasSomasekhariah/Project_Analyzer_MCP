"""
Comprehensive Phase 0 Test with Dynamic Intent Analysis

Tests Phase 0 logical decomposition on all 61 test queries from the comparative
analysis benchmark, using the same intent analysis that the workflow uses.
"""
import asyncio
import yaml
import json
from pathlib import Path
from typing import Dict, Any

from src.core.llm_service import LLMService
from src.core.workflow.research_engine import ResearchEngine
from src.core.workflow.prompts import get_intent_analysis_prompt
from src.core.workflow.models import IntentAnalysis


async def analyze_intent_dynamic(llm_service: LLMService, user_query: str, max_attempts: int = 3) -> Dict[str, Any]:
    """
    Dynamically analyze intent using the same workflow method.

    Args:
        llm_service: LLM service instance
        user_query: User query to analyze
        max_attempts: Max retry attempts

    Returns:
        Intent analysis dict
    """
    for attempt in range(max_attempts):
        try:
            # Get prompt from workflow
            intent_prompt = get_intent_analysis_prompt(user_query)

            result = await llm_service.generate_response(intent_prompt, json_mode=True)

            if result and not result.error:
                intent_data = json.loads(result.content.strip())

                # Validate with Pydantic
                intent_analysis = IntentAnalysis(**intent_data)

                return intent_analysis.model_dump()
            else:
                raise Exception(f"Intent analysis failed: {result.error if result else 'No result'}")

        except Exception as e:
            if attempt == max_attempts - 1:
                # Fallback intent
                return {
                    "intent_type": "lookup",
                    "confidence": 0.5,
                    "reasoning": f"Fallback due to analysis failure: {e}",
                    "expected_result_type": "Unknown"
                }
            continue


async def test_comprehensive_phase0():
    """Run comprehensive Phase 0 test on all benchmark queries"""

    # Load all test scenarios from extracted file
    with open('/tmp/test_scenarios_raw.txt', 'r') as f:
        scenario_lines = f.readlines()

    test_scenarios = []
    for line in scenario_lines:
        line = line.strip().rstrip(',')
        if line:
            try:
                scenario = eval(line)  # Safe here as we control the input
                test_scenarios.append(scenario)
            except:
                continue

    # Initialize services
    llm_service = LLMService()
    research_engine = ResearchEngine(llm_service)

    # Load schema
    schema_path = Path("src/schemas/project_knowledgebase_graph_schema.yaml")
    with open(schema_path, 'r') as f:
        schema = yaml.safe_load(f)

    print("=" * 80)
    print("COMPREHENSIVE PHASE 0 TEST - ALL BENCHMARK QUERIES")
    print("=" * 80)
    print(f"Total test scenarios: {len(test_scenarios)}")
    print()

    all_results = []

    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n[{i}/{len(test_scenarios)}] Testing: {scenario['id']} - {scenario['subcategory']}")
        print(f"Query: {scenario['query'][:80]}...")

        try:
            # Step 1: Dynamic intent analysis
            print("  → Analyzing intent...")
            intent = await analyze_intent_dynamic(llm_service, scenario['query'])
            print(f"     Intent: {intent['intent_type']} (confidence: {intent['confidence']})")

            # Step 2: Phase 0 decomposition
            print("  → Running Phase 0 decomposition...")
            state = {
                'user_query': scenario['query'],
                'intent': intent,
                'schema': schema
            }

            decomposition = await research_engine._decompose_user_query(state)
            print(f"     Subqueries: {len(decomposition['subqueries'])}")

            # Collect result
            result = {
                "test_id": scenario['id'],
                "category": scenario['category'],
                "subcategory": scenario['subcategory'],
                "scenario_type": scenario['scenario_type'],
                "query": scenario['query'],
                "intent": intent,
                "decomposition": decomposition
            }

            all_results.append(result)
            print("  ✅ Success")

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            all_results.append({
                "test_id": scenario['id'],
                "category": scenario['category'],
                "subcategory": scenario['subcategory'],
                "scenario_type": scenario['scenario_type'],
                "query": scenario['query'],
                "error": str(e)
            })

    # Save comprehensive results
    output_path = '/tmp/phase0_comprehensive_results.json'
    with open(output_path, 'w') as f:
        json.dump({
            "total_tests": len(test_scenarios),
            "successful": len([r for r in all_results if 'error' not in r]),
            "failed": len([r for r in all_results if 'error' in r]),
            "results": all_results
        }, f, indent=2)

    print("\n" + "=" * 80)
    print("COMPREHENSIVE TEST COMPLETED")
    print("=" * 80)
    print(f"Total tests: {len(test_scenarios)}")
    print(f"Successful: {len([r for r in all_results if 'error' not in r])}")
    print(f"Failed: {len([r for r in all_results if 'error' in r])}")
    print(f"\n✅ Results saved to {output_path}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_comprehensive_phase0())

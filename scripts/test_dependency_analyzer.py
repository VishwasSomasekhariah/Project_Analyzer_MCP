"""
Test Dependency Analyzer

Tests the LLM-based dependency analyzer on Phase 0 decomposition outputs.
Validates that it correctly extracts premise-to-subquery mappings,
subquery dependencies, and execution groups.
"""
import asyncio
import yaml
import json
from pathlib import Path

from src.core.llm_service import LLMService
from src.core.workflow.research_engine import ResearchEngine


async def test_dependency_analyzer():
    """Test dependency analyzer on sample decompositions"""

    # Initialize services
    llm_service = LLMService()
    research_engine = ResearchEngine(llm_service)

    # Load schema
    schema_path = Path("src/schemas/project_knowledgebase_graph_schema.yaml")
    with open(schema_path, 'r') as f:
        schema = yaml.safe_load(f)

    # Test queries
    test_cases = [
        {
            "id": "T003",
            "query": "What are the dependencies between classes in HelloWorldApp?",
            "intent": {
                "intent_type": "lookup",
                "confidence": 0.9,
                "reasoning": "Query asks for specific class dependencies",
                "expected_result_type": "Dependency relationships"
            }
        },
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
            "id": "SIMPLE",
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
    print("TESTING DEPENDENCY ANALYZER")
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

            # Phase 0: Decompose query
            print("  🔍 Phase 0: Decomposing query...")
            decomposition = await research_engine._decompose_user_query(state)

            print(f"  ✅ Decomposition complete:")
            print(f"     Premises: {len(decomposition['premises'])}")
            print(f"     Subqueries: {len(decomposition['subqueries'])}")
            print()

            # Post-processing: Analyze dependencies
            print("  🔍 Post-Processing: Analyzing dependencies...")
            dependency_analysis = await research_engine._analyze_dependencies(decomposition)

            print(f"  ✅ Dependency analysis complete:")
            print()

            # Display results
            print("  " + "=" * 76)
            print("  DEPENDENCY ANALYSIS RESULTS")
            print("  " + "=" * 76)
            print()

            # Premises
            print("  PREMISES (with validations):")
            print("  " + "-" * 76)
            for premise in dependency_analysis['premises']:
                print(f"  {premise['id']}: {premise['text'][:70]}...")
                print(f"       Validates: {premise['validates']}")
                print()

            # Subqueries
            print("  SUBQUERIES (with dependencies):")
            print("  " + "-" * 76)
            for subquery in dependency_analysis['subqueries']:
                print(f"  {subquery['id']}: {subquery['text'][:70]}...")
                print(f"       Needs premises: {subquery['depends_on_premises']}")
                print(f"       Needs subqueries: {subquery['depends_on_subqueries']}")
                print()

            # Execution groups
            print("  EXECUTION GROUPS (parallel execution plan):")
            print("  " + "-" * 76)
            for i, group in enumerate(dependency_analysis['execution_groups'], 1):
                print(f"  Group {i}: {', '.join(group)} (can run in parallel)")
            print()

            # Reasoning
            print("  REASONING:")
            print("  " + "-" * 76)
            reasoning = dependency_analysis['reasoning']
            # Word wrap reasoning at 76 chars
            words = reasoning.split()
            line = "  "
            for word in words:
                if len(line) + len(word) + 1 > 76:
                    print(line)
                    line = "  " + word
                else:
                    line += (" " if line != "  " else "") + word
            if line.strip():
                print(line)
            print()

            results.append({
                "test_id": test['id'],
                "status": "SUCCESS",
                "decomposition": decomposition,
                "dependency_analysis": dependency_analysis
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
    print("DEPENDENCY ANALYZER TEST SUMMARY")
    print("=" * 80)
    print(f"Total tests: {len(test_cases)}")
    print(f"Successful: {len([r for r in results if r['status'] == 'SUCCESS'])}")
    print(f"Failed: {len([r for r in results if r['status'] in ['FAILED', 'ERROR']])}")
    print()

    # Key findings
    print("KEY FINDINGS:")
    for result in results:
        status_emoji = {
            "SUCCESS": "✅",
            "FAILED": "❌",
            "ERROR": "❌"
        }.get(result['status'], "❓")

        print(f"  {status_emoji} {result['test_id']}: {result['status']}")

    print()
    print("=" * 80)

    # Save results to file
    output_file = "/tmp/dependency_analyzer_test.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(test_dependency_analyzer())

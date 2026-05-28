#!/usr/bin/env python3
"""
Test parallel execution with token tracking.

Tests:
1. Parallel execution (default batch_size=4)
2. Token tracking across all LLM calls
3. Per-approach token tracking
4. Multiple queries from different categories
5. JSON output for manual validation
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from datetime import datetime
import pickle

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Test queries from different categories
TEST_QUERIES = [
    # Original queries (commented out for now)
    # {
    #     "id": "T001",
    #     "category": "Technical",
    #     "subcategory": "Architecture",
    #     "query": "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?"
    # },
    # {
    #     "id": "F001",
    #     "category": "Functional",
    #     "subcategory": "Business Logic",
    #     "query": "What is the core business logic of the HelloWorldApp? How do the workers coordinate?"
    # },
    # {
    #     "id": "T038",
    #     "category": "Technical",
    #     "subcategory": "Method Signatures",
    #     "query": "What is the exact method signature of the CreateWorkers method in the WorkerFactory class?"
    # },

    # Using Statements & Dependencies (T066-T070) - factual/lookup tests
    # {
    #     "id": "T066",
    #     "category": "Technical",
    #     "subcategory": "Using Statements",
    #     "query": "What using statements are present in Program.cs?"
    # },
    # {
    #     "id": "T067",
    #     "category": "Technical",
    #     "subcategory": "Import Dependencies",
    #     "query": "Which files contain System.Collections.Generic using statements?"
    # },
    # {
    #     "id": "T068",
    #     "category": "Technical",
    #     "subcategory": "Import Order",
    #     "query": "What is the first using statement in Manager.cs?"
    # },
    # {
    #     "id": "T069",
    #     "category": "Technical",
    #     "subcategory": "Import Count",
    #     "query": "How many using statements are in WorkerFactory.cs?"
    # },
    # {
    #     "id": "T070",
    #     "category": "Technical",
    #     "subcategory": "System Imports",
    #     "query": "Which class files import the System namespace explicitly?"
    # },

    # Code Patterns & Structure (T076, T080)
    # {
    #     "id": "T076",
    #     "category": "Technical",
    #     "subcategory": "Static Classes",
    #     "query": "How many classes are declared as public static?"
    # },
    # {
    #     "id": "T080",
    #     "category": "Technical",
    #     "subcategory": "Naming Patterns",
    #     "query": "What variable naming pattern is used for private fields?"
    # },

    # Project File Details (T081-T084)
    # {
    #     "id": "T081",
    #     "category": "Technical",
    #     "subcategory": "Project SDK",
    #     "query": "What SDK is specified in the project file?"
    # },
    # {
    #     "id": "T082",
    #     "category": "Technical",
    #     "subcategory": "Project Settings",
    #     "query": "Is ImplicitUsings enabled in the project configuration?"
    # },
    # {
    #     "id": "T083",
    #     "category": "Technical",
    #     "subcategory": "Root Namespace",
    #     "query": "What is the exact RootNamespace value in the project file?"
    # },
    {
        "id": "T084",
        "category": "Technical",
        "subcategory": "Project Structure",
        "query": "How many project properties are defined in the HelloWorldApp.csproj file?"
    },

    # Method Implementation Details (T089)
    {
        "id": "T089",
        "category": "Functional",
        "subcategory": "Method Calls",
        "query": "How many method calls are in Manager.Run()?"
    }
]


async def run_single_query(client, config, test_query_obj):
    """Run a single query and return results."""
    query_id = test_query_obj["id"]
    query_text = test_query_obj["query"]
    category = test_query_obj["category"]

    logger.info("")
    logger.info("=" * 80)
    logger.info(f"🔍 Running Query {query_id} ({category})")
    logger.info("=" * 80)
    logger.info(f"Query: {query_text}")
    logger.info("")

    start_time = time.time()

    try:
        session = await client.create_session("mcp-analysis-server")

        # Call CPG RAG tool
        logger.info("🔄 Calling query_cpg_rag...")
        result = await session.call_tool(
            "query_cpg_rag",
            {
                "user_query": query_text,
                "project_name": "HelloWorldApp",
                "config_path": config["neo4j_config"],
                "project_path": config["project_path"],
                "mappings_path": config["mappings_path"],
                "queries_path": config["queries_path"],
                "max_results": 100,
                "max_agent_iterations": 5
            }
        )

        # Save raw result
        pickle_dir = Path("/opt/genpod/mcp_debug_dumps")
        pickle_dir.mkdir(exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        pickle_file = pickle_dir / f"token_test_{query_id}_{timestamp_str}.pkl"

        with open(pickle_file, 'wb') as f:
            pickle.dump(result, f)
        logger.info(f"💾 Raw result saved to: {pickle_file}")

        # Extract content
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)

        response_time = time.time() - start_time

        # Parse result
        result_data = json.loads(content_text)

        # Extract basic info
        status = result_data.get("status")
        response_obj = result_data.get("response", {})
        answer = response_obj.get("answer", "") if isinstance(response_obj, dict) else str(response_obj)

        # Extract token metrics
        total_tokens = result_data.get('total_tokens_used', 0)
        total_input = result_data.get('total_input_tokens', 0)
        total_output = result_data.get('total_output_tokens', 0)
        total_cost = result_data.get('total_estimated_cost_usd', 0.0)

        # Extract per-step breakdown
        think_tokens = result_data.get('think_tokens', 0)
        generate_tokens = result_data.get('generate_tokens', 0)
        rethink_tokens = result_data.get('rethink_tokens', 0)
        diagnostics_tokens = result_data.get('diagnostics_tokens', 0)
        refinement_tokens = result_data.get('refinement_tokens', 0)
        sufficiency_tokens = result_data.get('sufficiency_check_tokens', 0)
        synthesis_tokens = result_data.get('synthesis_tokens', 0)

        # Extract per-approach tracking
        tokens_per_approach = result_data.get('tokens_per_approach', {})
        cost_per_approach = result_data.get('cost_per_approach', {})
        approach_statuses = result_data.get('approach_statuses', {})

        # Extract model tracking
        models_used = result_data.get('models_used', [])
        llm_call_history = result_data.get('llm_call_history', [])

        logger.info("")
        logger.info("📊 QUERY RESULTS")
        logger.info("=" * 80)
        logger.info(f"Status: {status}")
        logger.info(f"Response time: {response_time:.2f}s")
        logger.info(f"Raw results (filtered data): {len(result_data.get('raw_results', []))}")
        logger.info(f"Approaches: {len(approach_statuses)}")
        logger.info("")

        logger.info("🤖 ANSWER (first 200 chars):")
        logger.info(answer[:200] + "..." if len(answer) > 200 else answer)
        logger.info("")

        logger.info("🔢 TOKEN TRACKING")
        logger.info("=" * 80)
        logger.info(f"Total tokens: {total_tokens:,}")
        logger.info(f"  - Input: {total_input:,}")
        logger.info(f"  - Output: {total_output:,}")
        logger.info(f"  - Cost: ${total_cost:.6f}")
        logger.info("")

        logger.info("Per-step breakdown:")
        logger.info(f"  - Think: {think_tokens:,}")
        logger.info(f"  - Generate: {generate_tokens:,}")
        logger.info(f"  - Rethink: {rethink_tokens:,}")
        logger.info(f"  - Diagnostics: {diagnostics_tokens:,}")
        logger.info(f"  - Refinement: {refinement_tokens:,}")
        logger.info(f"  - Sufficiency: {sufficiency_tokens:,}")
        logger.info(f"  - Synthesis: {synthesis_tokens:,}")
        logger.info("")

        if tokens_per_approach:
            logger.info("Per-approach tracking:")
            for approach_idx in sorted(map(int, tokens_per_approach.keys())):
                tokens = tokens_per_approach.get(str(approach_idx), 0)
                cost = cost_per_approach.get(str(approach_idx), 0.0)
                logger.info(f"  - Approach {approach_idx}: {tokens:,} tokens, ${cost:.6f}")
            logger.info("")

        if models_used:
            unique_models = list(set(models_used))
            logger.info(f"Models used: {', '.join(unique_models)}")
            logger.info("")

        if llm_call_history:
            logger.info(f"Total LLM calls: {len(llm_call_history)}")
            call_types = {}
            for call in llm_call_history:
                call_type = call.get('call_type', 'unknown')
                call_types[call_type] = call_types.get(call_type, 0) + 1
            logger.info("  Breakdown by type:")
            for call_type, count in sorted(call_types.items()):
                logger.info(f"    - {call_type}: {count}")
            logger.info("")

        # Validation checks
        checks_passed = 0
        checks_total = 0

        logger.info("✅ VALIDATION CHECKS")
        logger.info("=" * 80)

        # Check 1: Total tokens > 0
        checks_total += 1
        if total_tokens > 0:
            logger.info("✅ PASS: Total tokens tracked (> 0)")
            checks_passed += 1
        else:
            logger.info("❌ FAIL: No tokens tracked")

        # Check 2: Input + Output = Total
        checks_total += 1
        if total_input + total_output == total_tokens:
            logger.info("✅ PASS: Token sum validation (input + output = total)")
            checks_passed += 1
        else:
            logger.info(f"❌ FAIL: Token sum mismatch ({total_input} + {total_output} != {total_tokens})")

        # Check 3: LLM call history exists
        checks_total += 1
        if len(llm_call_history) > 0:
            logger.info(f"✅ PASS: LLM call history tracked ({len(llm_call_history)} calls)")
            checks_passed += 1
        else:
            logger.info("❌ FAIL: No LLM call history")

        # Check 4: Per-approach tracking exists
        checks_total += 1
        if len(tokens_per_approach) > 0:
            logger.info(f"✅ PASS: Per-approach tracking ({len(tokens_per_approach)} approaches)")
            checks_passed += 1
        else:
            logger.info("❌ FAIL: No per-approach tracking")

        # Check 5: Cost estimated
        checks_total += 1
        if total_cost > 0:
            logger.info(f"✅ PASS: Cost estimated (${total_cost:.6f})")
            checks_passed += 1
        else:
            logger.info("❌ FAIL: No cost estimate")

        # Check 6: Parallel execution
        checks_total += 1
        if len(approach_statuses) > 1:
            logger.info(f"✅ PASS: Parallel execution (multiple approaches: {len(approach_statuses)})")
            checks_passed += 1
        else:
            logger.info("❌ FAIL: Only one approach (not parallel?)")

        logger.info("")
        logger.info(f"Overall: {checks_passed}/{checks_total} checks passed")

        # Build result summary
        result_summary = {
            "query_id": query_id,
            "query_text": query_text,
            "category": category,
            "subcategory": test_query_obj["subcategory"],
            "timestamp": timestamp_str,
            "status": status,
            "response_time_seconds": response_time,
            "raw_results_count": len(result_data.get('raw_results', [])),
            "approaches_count": len(approach_statuses),
            "answer": answer,
            "raw_results": result_data.get('raw_results', []),  # Filtered discovered data
            "token_tracking": {
                "total_tokens_used": total_tokens,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_estimated_cost_usd": total_cost,
                "per_step": {
                    "think_tokens": think_tokens,
                    "generate_tokens": generate_tokens,
                    "rethink_tokens": rethink_tokens,
                    "diagnostics_tokens": diagnostics_tokens,
                    "refinement_tokens": refinement_tokens,
                    "sufficiency_check_tokens": sufficiency_tokens,
                    "synthesis_tokens": synthesis_tokens
                },
                "per_approach": {str(k): {"tokens": v, "cost": cost_per_approach.get(str(k), 0.0)}
                                for k, v in tokens_per_approach.items()},
                "models_used": list(set(models_used)),
                "llm_call_count": len(llm_call_history),
                "llm_call_breakdown": call_types if llm_call_history else {}
            },
            "validation": {
                "checks_passed": checks_passed,
                "checks_total": checks_total,
                "success_rate": checks_passed / checks_total if checks_total > 0 else 0.0
            },
            "full_result": result_data
        }

        return result_summary, checks_passed, checks_total

    except Exception as e:
        logger.error(f"❌ Query {query_id} failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "query_id": query_id,
            "query_text": query_text,
            "category": category,
            "status": "error",
            "error": str(e),
            "validation": {"checks_passed": 0, "checks_total": 6, "success_rate": 0.0}
        }, 0, 6


async def test_parallel_with_token_tracking():
    """Test parallel execution with token tracking on multiple queries."""

    # Configuration
    config = {
        "config_file": "/opt/genpod/file_watcher_mcp_config.json",
        "neo4j_config": "/opt/genpod/neo4j_config.json",
        "project_path": "/opt/HelloWorldApp",
        "mappings_path": "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml",
        "queries_path": "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries"
    }

    logger.info("=" * 80)
    logger.info("🧪 PARALLEL EXECUTION + TOKEN TRACKING TEST")
    logger.info("=" * 80)
    logger.info(f"Number of test queries: {len(TEST_QUERIES)}")
    logger.info("Batch size: 4 (default, parallel mode)")
    logger.info("Features tested:")
    logger.info("  - Token tracking across all LLM calls")
    logger.info("  - Per-approach token tracking")
    logger.info("  - Multiple query categories")
    logger.info("  - JSON output for manual validation")
    logger.info("=" * 80)

    overall_start_time = time.time()

    # Create MCP client
    client = MCPClient.from_config_file(config["config_file"])

    # Run all test queries
    all_results = []
    total_checks_passed = 0
    total_checks = 0

    for test_query in TEST_QUERIES:
        result_summary, checks_passed, checks_total = await run_single_query(client, config, test_query)
        all_results.append(result_summary)
        total_checks_passed += checks_passed
        total_checks += checks_total

    overall_time = time.time() - overall_start_time

    # Save results to JSON
    output_dir = Path("/opt/genpod/TEST_OUTPUT_LOGS")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_file = output_dir / f"token_tracking_test_{timestamp}.json"

    output_data = {
        "test_suite": "parallel_execution_token_tracking",
        "timestamp": timestamp,
        "total_execution_time_seconds": overall_time,
        "queries_tested": len(TEST_QUERIES),
        "overall_validation": {
            "total_checks_passed": total_checks_passed,
            "total_checks": total_checks,
            "success_rate": total_checks_passed / total_checks if total_checks > 0 else 0.0
        },
        "results": all_results
    }

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Print summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("📊 TEST SUITE SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total execution time: {overall_time:.2f}s")
    logger.info(f"Queries tested: {len(TEST_QUERIES)}")
    logger.info(f"Overall validation: {total_checks_passed}/{total_checks} checks passed ({total_checks_passed/total_checks*100:.1f}%)")
    logger.info("")

    for result in all_results:
        status_icon = "✅" if result.get("status") == "success" else "❌"
        validation = result.get("validation", {})
        logger.info(f"{status_icon} {result['query_id']} ({result['category']}): {validation.get('checks_passed', 0)}/{validation.get('checks_total', 0)} checks")

    logger.info("")
    logger.info(f"📁 Results saved to: {json_file}")
    logger.info("")

    if total_checks_passed == total_checks:
        logger.info("🎉 ALL TESTS PASSED!")
        return 0
    else:
        logger.info(f"⚠️  {total_checks - total_checks_passed} checks failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_parallel_with_token_tracking())
    import sys
    sys.exit(exit_code)

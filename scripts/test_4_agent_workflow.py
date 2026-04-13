"""
Test script for the 4-Agent Team LangGraph workflow.

This tests the new architecture:
- Thinker → ThinkingValidator → CypherValidator → ExecutorVerifier
"""

import asyncio
import json
import logging
import sys
from datetime import datetime

# Generate timestamp for this test run
TEST_RUN_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
LOG_FILE = f"test_results_4agent_{TEST_RUN_TIMESTAMP}.log"
JSON_FILE = f"test_results_4agent_{TEST_RUN_TIMESTAMP}.json"

# Setup logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

from src.core.graph_rag.core.config import SystemConfig
from src.core.graph_rag.orchestrators.multi_agent_cot import MultiAgentCoT


async def test_4_agent_workflow():
    """Test the 4-agent team workflow with multiple queries and collect results to JSON."""

    # Test queries - CONFLICT CASES from cross_validation_conflicts
    # These are queries where Vector and CPG RAG gave conflicting answers
    test_queries = [
        # T004: CPG states no class references another, conflicts with interface usage
        "Analyze the class hierarchy and inheritance structure in the HelloWorldApp.",
        # T005: HelloWorldApp class not directly found in vector response
        "What are the key methods in the HelloWorldApp and their cyclomatic complexity?",
        # F003: Vector suggests callback mechanism, CPG finds no such communication
        "How do the workers communicate with the Manager in the HelloWorldApp?",
        # T039: Vector suggests instantiation of specific classes; CPG does not support
        "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?",
        # T041: Vector suggests Helper class exists, CPG does not
        "What is the exact method signature of the FormatMessage method in the Helper class?",
        # T044: Vector suggests specific message, CPG does not confirm
        "What exact message does WorkerA send when calling the Notify method?",
        # T045: CPG indicates no call to Helper.FormatMessage, vector indicates there is
        "What are the exact two parameters passed to Helper.FormatMessage by WorkerB?",
        # T046: Vector claims text is passed, CPG shows no such calls
        "What exact text does WorkerC pass as the second parameter to Helper.FormatMessage?",
        # T049: Vector claims 'void Process()' method, CPG claims no methods in IWorker
        "How many methods does the IWorker interface define and what are their exact signatures?",
    ]

    print("\n" + "="*80)
    print("4-AGENT TEAM WORKFLOW TEST - BATCH MODE")
    print("="*80)
    print(f"\nRunning {len(test_queries)} queries...")
    print(f"Log file: {LOG_FILE}")
    print(f"JSON file: {JSON_FILE}")

    # Collect all results
    all_results = {
        "test_run_timestamp": datetime.now().isoformat(),
        "configuration": {
            "use_4_agent_team": True,
            "four_agent_max_iterations": 3,
            "max_cot_iterations": 15,
            "llm_model": "gpt-4o"
        },
        "queries": []
    }

    # Create config with 4-agent team ENABLED
    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="src/schemas/project_knowledgebase_graph_schema.yaml",
        use_4_agent_team=True,  # Enable 4-agent team
        four_agent_max_iterations=3,
        max_cot_iterations=15,  # Increased for thorough schema discovery
        verification_enabled=True,
        entity_resolution_enabled=True,
        llm_model="gpt-4o",
    )

    for i, test_query in enumerate(test_queries, 1):
        print(f"\n{'='*80}")
        print(f"QUERY {i}/{len(test_queries)}")
        print(f"{'='*80}")
        print(f"Query: {test_query}")
        print("-"*80)

        # Create fresh agent for each query to avoid state issues
        agent = MultiAgentCoT(config=config, enable_observer=False)

        query_result = {
            "query_number": i,
            "query": test_query,
            "status": "success",
            "answer": None,
            "confidence": None,
            "citations": [],
            "execution_time_ms": None,
            "sub_queries_count": None,
            "llm_calls_count": None,
            "token_usage": None,
            "error": None,
            "execution_traces": []  # Trace data for debugging/analysis
        }

        try:
            # Run the query
            result = await agent.run(test_query)

            # Collect results
            query_result["answer"] = result.answer
            query_result["confidence"] = result.confidence.value
            query_result["execution_time_ms"] = result.execution_time_ms
            query_result["sub_queries_count"] = result.sub_queries_count
            query_result["llm_calls_count"] = result.llm_calls_count

            if result.token_usage:
                query_result["token_usage"] = {
                    "total_tokens": result.token_usage.total_tokens,
                    "prompt_tokens": result.token_usage.total_prompt_tokens,
                    "completion_tokens": result.token_usage.total_completion_tokens,
                    "call_count": result.token_usage.call_count
                }

            # Collect citations
            if result.citations:
                for citation in result.citations:
                    citation_data = {
                        "claim": citation.claim,
                        "verified": citation.verification_status.value == "verified",
                        "verification_status": citation.verification_status.value,
                        "entity_name": citation.entity_name,
                        "entity_type": citation.entity_type,
                        "source_file": citation.source_file,
                        "source_location": citation.source_location,
                        "discovery_query": citation.discovery_query,
                        "verification_query": citation.verification_query,
                        "confidence": citation.confidence.value if citation.confidence else None
                    }
                    query_result["citations"].append(citation_data)

            query_result["verified_count"] = result.verified_count
            query_result["unverified_count"] = result.unverified_count

            # Capture execution traces (4-agent workflow only)
            if agent.last_execution_traces:
                query_result["execution_traces"] = agent.last_execution_traces
                print(f"Captured {len(agent.last_execution_traces)} execution traces")

            # Print summary
            print(f"\nAnswer: {result.answer[:200]}..." if len(result.answer) > 200 else f"\nAnswer: {result.answer}")
            print(f"Confidence: {result.confidence.value}")
            print(f"Citations: {len(result.citations)} ({result.verified_count} verified)")
            print(f"Time: {result.execution_time_ms}ms")

        except Exception as e:
            query_result["status"] = "error"
            query_result["error"] = str(e)
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await agent.shutdown()

        all_results["queries"].append(query_result)

    # Calculate summary statistics
    successful_queries = [q for q in all_results["queries"] if q["status"] == "success"]
    all_results["summary"] = {
        "total_queries": len(test_queries),
        "successful_queries": len(successful_queries),
        "failed_queries": len(test_queries) - len(successful_queries),
        "total_citations": sum(len(q["citations"]) for q in successful_queries),
        "total_verified_citations": sum(q.get("verified_count", 0) for q in successful_queries),
        "total_execution_time_ms": sum(q["execution_time_ms"] or 0 for q in successful_queries),
        "total_tokens": sum((q["token_usage"]["total_tokens"] if q["token_usage"] else 0) for q in successful_queries),
        "total_llm_calls": sum(q["llm_calls_count"] or 0 for q in successful_queries)
    }

    # Save to JSON file
    with open(JSON_FILE, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*80}")
    print("BATCH TEST COMPLETE")
    print(f"{'='*80}")
    print(f"Results saved to: {JSON_FILE}")
    print(f"Logs saved to: {LOG_FILE}")
    print(f"\nSummary:")
    print(f"  Queries: {all_results['summary']['successful_queries']}/{all_results['summary']['total_queries']} successful")
    print(f"  Total citations: {all_results['summary']['total_citations']} ({all_results['summary']['total_verified_citations']} verified)")
    print(f"  Total time: {all_results['summary']['total_execution_time_ms']}ms")
    print(f"  Total tokens: {all_results['summary']['total_tokens']}")
    print(f"  Total LLM calls: {all_results['summary']['total_llm_calls']}")

    return len(successful_queries) == len(test_queries)


async def compare_workflows():
    """Compare legacy CoT+Verifier vs 4-Agent Team."""

    test_query = "What are the key methods in the HelloWorldApp and their cyclomatic complexity?"

    print("\n" + "="*80)
    print("WORKFLOW COMPARISON TEST")
    print("="*80)
    print(f"Query: {test_query}")

    results = {}

    for use_4_agent in [False, True]:
        workflow_name = "4-Agent Team" if use_4_agent else "Legacy CoT+Verifier"
        print(f"\n{'='*40}")
        print(f"Testing: {workflow_name}")
        print(f"{'='*40}")

        config = SystemConfig(
            mcp_config_path="neo4j_config.json",
            yaml_schema_path="src/schemas/project_knowledgebase_graph_schema.yaml",
            use_4_agent_team=use_4_agent,
            four_agent_max_iterations=3,
            max_cot_iterations=8,
            verification_enabled=True,
            entity_resolution_enabled=True,
            llm_model="gpt-4o",
        )

        agent = MultiAgentCoT(config=config, enable_observer=False)

        try:
            result = await agent.run(test_query)
            results[workflow_name] = {
                'answer': result.answer,
                'citations': len(result.citations),
                'verified': result.verified_count,
                'time_ms': result.execution_time_ms,
                'llm_calls': result.llm_calls_count,
                'tokens': result.token_usage.total_tokens if result.token_usage else 0
            }
        except Exception as e:
            results[workflow_name] = {'error': str(e)}
        finally:
            await agent.shutdown()

    # Print comparison
    print("\n" + "="*80)
    print("COMPARISON RESULTS")
    print("="*80)

    for name, data in results.items():
        print(f"\n{name}:")
        if 'error' in data:
            print(f"  ERROR: {data['error']}")
        else:
            print(f"  Citations: {data['citations']} ({data['verified']} verified)")
            print(f"  Time: {data['time_ms']}ms")
            print(f"  LLM calls: {data['llm_calls']}")
            print(f"  Tokens: {data['tokens']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--compare":
        asyncio.run(compare_workflows())
    else:
        success = asyncio.run(test_4_agent_workflow())
        sys.exit(0 if success else 1)

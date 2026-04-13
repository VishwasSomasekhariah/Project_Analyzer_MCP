#!/usr/bin/env python3
"""
Simple hybrid workflow test to observe parallel execution behavior.
"""

import asyncio
import json
import logging
import time
import traceback
from datetime import datetime

from mcp_use import MCPClient, MCPSession
from mcp_use.connectors.http import HttpConnector

# Enable DEBUG logging to see full MCP client behavior
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

async def test_hybrid_workflow():
    """Test hybrid workflow and observe Vector + CPG parallel execution"""

    config_file = "/opt/genpod/file_watcher_mcp_config.json"

    print("="*80)
    print("🔍 Testing Hybrid Workflow (Vector + CPG in parallel)")
    print("="*80)
    print(f"📁 Config: {config_file}")

    try:
        # Load config to get server URL
        with open(config_file) as f:
            config = json.load(f)

        server_config = config['mcpServers']['mcp-analysis-server']

        # Create connector with custom timeouts
        # Default: timeout=5, sse_read_timeout=300 (5 minutes)
        # Custom: timeout=10, sse_read_timeout=3600 (1 hour)
        connector = HttpConnector(
            base_url=server_config['url'],
            headers=server_config.get('headers'),
            auth_token=server_config.get('auth_token'),
            timeout=10,  # HTTP operation timeout
            sse_read_timeout=3600,  # SSE read timeout: 1 hour (for long workflows)
        )

        print(f"📡 Custom SSE timeout: 3600s (1 hour)")

        # Create session with custom connector
        session = MCPSession(connector)
        await session.initialize()

        # Test queries - Functional category
        test_queries = [
            {"id": "F001", "query": "What is the core business logic of the HelloWorldApp? How do the workers coordinate?"},
            {"id": "F002", "query": "Trace the data flow through the HelloWorldApp from Manager to Workers."},
            {"id": "F003", "query": "How do the workers communicate with the Manager in the HelloWorldApp?"},
            {"id": "F004", "query": "How is the WorkerFactory used in the HelloWorldApp and what does it create?"},
            {"id": "F005", "query": "How does the notification system work in the HelloWorldApp?"},
        ]

        all_results = []

        for idx, test in enumerate(test_queries, 1):
            print(f"\n{'='*80}")
            print(f"🧪 TEST {idx}/{len(test_queries)}: {test['id']}")
            print(f"{'='*80}")
            print(f"📝 Query: {test['query']}")
            print(f"🕐 Start time: {datetime.now().strftime('%H:%M:%S')}")
            print("-" * 80)

            start_time = time.time()

            try:
                # Call the query_hybrid_rag tool
                result = await session.call_tool(
                    "query_hybrid_rag",
                    {
                        "user_query": test['query'],
                        "project_name": "HelloWorldApp",
                        # Vector config
                        "collection_name": "HelloWorldApp_qdrant_v2",
                        "vector_config_path": "/opt/genpod/qdrant_config.json",
                        "top_k": 5,
                        # CPG config
                        "max_agent_iterations": 100,
                        "parallel_agents": False,
                        # Note: max_parallel_workers not used - 4-agent team runs all sub-queries in parallel without worker limits
                        "use_4_agent_team": True,
                        "four_agent_max_iterations": 3
                    }
                )

                execution_time = time.time() - start_time

                print("-" * 80)
                print(f"✅ Query completed in {execution_time:.2f}s")
                print(f"🕐 End time: {datetime.now().strftime('%H:%M:%S')}")

                all_results.append({
                    "test_id": test['id'],
                    "query": test['query'],
                    "execution_time": execution_time,
                    "result": result
                })

            except Exception as e:
                execution_time = time.time() - start_time
                print(f"❌ Query failed after {execution_time:.2f}s: {e}")
                all_results.append({
                    "test_id": test['id'],
                    "query": test['query'],
                    "execution_time": execution_time,
                    "error": str(e)
                })
                continue

        print(f"\n{'='*80}")
        print(f"📊 ALL TESTS SUMMARY ({len(test_queries)} queries)")
        print(f"{'='*80}")

        total_time = sum(r.get('execution_time', 0) for r in all_results)
        successful = sum(1 for r in all_results if 'result' in r)
        failed = len(all_results) - successful

        print(f"Total execution time: {total_time:.2f}s")
        print(f"Successful: {successful}/{len(test_queries)}")
        print(f"Failed: {failed}/{len(test_queries)}")

        # Pick first successful result to display details
        result = None
        for r in all_results:
            if 'result' in r:
                result = r['result']
                execution_time = r['execution_time']
                break

        # Parse and display results
        if result and result.content:
            try:
                response = json.loads(result.content[0].text)

                print("\n" + "="*80)
                print("📊 RESULTS SUMMARY")
                print("="*80)

                # Status
                print(f"Status: {response.get('status', 'unknown')}")

                # Retrieval results
                retrieval_results = response.get('retrieval_results', {})
                vector_result = retrieval_results.get('vector', {})
                cpg_result = retrieval_results.get('cpg', {})

                print(f"\nVector: {vector_result.get('status')} - {vector_result.get('results_count')} results in {vector_result.get('execution_time', 0):.2f}s")
                print(f"CPG: {cpg_result.get('status')} - {cpg_result.get('results_count')} results in {cpg_result.get('execution_time', 0):.2f}s")

                # Synthesis
                synthesis = response.get('synthesis', {})
                print(f"\nSynthesis Status: {synthesis.get('status', 'unknown')}")
                print(f"Confidence: {synthesis.get('confidence', 0):.2f}")

                # Answer
                answer = synthesis.get('answer', '')
                if answer:
                    print(f"\n{'='*80}")
                    print("📝 ANSWER")
                    print('='*80)
                    print(answer)

                # Save full output
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = f"query_hybrid_rag_mcp_test_{timestamp}.json"
                with open(output_file, 'w') as f:
                    json.dump(response, f, indent=2)
                print(f"\n💾 Full output saved to: {output_file}")

            except json.JSONDecodeError as e:
                print(f"❌ Failed to parse JSON response: {e}")
                print(f"Raw response: {result.content}")
        else:
            print("❌ No response received")

        print("\n" + "="*80)
        print("🔍 CHECK SERVER LOGS FOR PARALLEL EXECUTION DETAILS:")
        print("="*80)
        print("tail -100 /opt/genpod/logs/workflow.log | grep -E 'Node: (vector|cpg)_retrieval'")
        print("="*80)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_hybrid_workflow())

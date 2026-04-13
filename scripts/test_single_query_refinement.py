#!/usr/bin/env python3
u"""
Single Query Refinement Test

Quick test of the query refinement feature with one query.
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


async def test_single_query():
    """Test a single query with the refinement feature."""

    # Configuration
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    neo4j_config = "/opt/genpod/neo4j_config.json"
    project_path = "/opt/HelloWorldApp"
    mappings_path = "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml"
    queries_path = "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries"

    # Test query - likely to trigger refinement due to ambiguous "workers"
    test_query = "How many workers are there in the HelloWorldApp?"

    logger.info("="*80)
    logger.info("🧪 QUERY REFINEMENT TEST")
    logger.info("="*80)
    logger.info(f"Query: {test_query}")
    logger.info("Expected: Should find WorkerA, WorkerB, WorkerC")
    logger.info("Testing: Refinement logic if initial queries fail")
    logger.info("="*80 + "\n")

    start_time = time.time()

    try:
        # Create MCP client
        client = MCPClient.from_config_file(config_file)
        session = await client.create_session("mcp-analysis-server")

        # Call CPG RAG tool
        logger.info("🔄 Calling query_cpg_rag...")
        result = await session.call_tool(
            "query_cpg_rag",
            {
                "user_query": test_query,
                "project_name": "HelloWorldApp",
                "config_path": neo4j_config,
                "project_path": project_path,
                "mappings_path": mappings_path,
                "queries_path": queries_path,
                "max_results": 100,
                "max_agent_iterations": 5
            }
        )

        # Save raw result
        pickle_dir = Path("/opt/genpod/mcp_debug_dumps")
        pickle_dir.mkdir(exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        pickle_file = pickle_dir / f"single_test_{timestamp_str}.pkl"

        with open(pickle_file, 'wb') as f:
            pickle.dump(result, f)
        logger.info(f"💾 Raw result saved to: {pickle_file}\n")

        # Extract content
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)

        response_time = time.time() - start_time

        # Parse result
        result_data = json.loads(content_text)

        # Extract key info
        status = result_data.get("status")
        response_obj = result_data.get("response", {})
        answer = response_obj.get("answer", "") if isinstance(response_obj, dict) else str(response_obj)
        raw_results = result_data.get("raw_results", [])
        approach_statuses = result_data.get("approach_statuses", {})
        failed_approaches = result_data.get("failed_approaches", [])

        # Print results
        logger.info("="*80)
        logger.info("📊 RESULTS")
        logger.info("="*80)
        logger.info(f"Status: {status}")
        logger.info(f"Response time: {response_time:.2f}s")
        logger.info(f"Raw results count: {len(raw_results)}")
        logger.info(f"\nApproach statuses: {json.dumps(approach_statuses, indent=2)}")
        logger.info(f"Failed approaches: {failed_approaches}")

        logger.info(f"\n{'='*80}")
        logger.info("🤖 ANSWER")
        logger.info("="*80)
        logger.info(answer)

        # Check for clean citations
        has_diagnostics = any('diagnostic' in str(r).lower() for r in raw_results if isinstance(r, dict))
        logger.info(f"\n{'='*80}")
        logger.info("✅ VALIDATION")
        logger.info("="*80)
        logger.info(f"Clean citations (no diagnostics in results): {'✅ PASS' if not has_diagnostics else '❌ FAIL'}")
        logger.info(f"Failed approaches tracked: {'✅ PASS' if failed_approaches is not None else '❌ FAIL'}")
        logger.info(f"Approach statuses tracked: {'✅ PASS' if approach_statuses else '❌ FAIL'}")

        logger.info(f"\n{'='*80}")
        logger.info("✅ TEST COMPLETE")
        logger.info("="*80)

        return result_data

    except Exception as e:
        logger.error(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    asyncio.run(test_single_query())

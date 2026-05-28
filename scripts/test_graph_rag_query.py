#!/usr/bin/env python3
"""
Test script for Graph RAG query_cpg_rag tool.
Based on properly_fixed_comparative_analysis.py pattern but uses the current
query_cpg_rag tool parameters.

Usage:
    python test_graph_rag_query.py
    python test_graph_rag_query.py --query "your query here"
    python test_graph_rag_query.py --json  # Output raw JSON
"""

import asyncio
import json
import logging
import time
import argparse
import pickle
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class GraphRAGQueryTester:
    """Test runner for Graph RAG CPG queries - based on ProperlyFixedComparativeAnalyzer pattern."""

    def __init__(self):
        """Initialize the tester with same config as benchmark script."""
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.neo4j_config = "/opt/genpod/neo4j_config.json"
        self.schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"

    async def run_cpg_query(self, query: str) -> Dict[str, Any]:
        """
        Run query using Multi-Agent CPG RAG.
        Uses the CURRENT query_cpg_rag tool parameters.
        """
        start_time = time.time()

        try:
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("mcp-analysis-server")

            # Call with CURRENT query_cpg_rag parameters (from tools.py)
            result = await session.call_tool(
                "query_cpg_rag",
                {
                    "user_query": query,
                    "project_name": "HelloWorldApp",
                    "config_path": self.neo4j_config,
                    "schema_path": self.schema_path,
                    "llm_model": "gpt-4o",
                    "max_cot_iterations": 10,
                    "max_verifier_iterations": 10,
                    # Note: max_parallel_workers not used - 4-agent team runs all sub-queries in parallel without worker limits
                    "parallel_agents": True,
                    "enable_verification": True,
                    "enable_entity_resolution": True,
                    "enable_observer": False
                }
            )

            # PICKLE DUMP: Save raw MCP result for debugging
            pickle_dir = Path("/opt/genpod/mcp_debug_dumps")
            pickle_dir.mkdir(exist_ok=True)

            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            pickle_file = pickle_dir / f"test_query_raw_response_{timestamp_str}.pkl"

            with open(pickle_file, 'wb') as f:
                pickle.dump(result, f)
            print(f"   SAVED RAW MCP RESULT: {pickle_file}")

            # Parse result - extract content text first
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)

            response_time_ms = int((time.time() - start_time) * 1000)

            try:
                result_data = json.loads(content_text)

                # Extract key components based on ProductionResponse structure
                response_data = result_data.get("response", {})

                return {
                    "status": result_data.get("status", "success"),
                    "answer": response_data.get("answer", "") if isinstance(response_data, dict) else str(response_data),
                    "confidence": response_data.get("confidence", "N/A") if isinstance(response_data, dict) else "N/A",
                    # Citations are at top level, not nested in response
                    "citations": result_data.get("citations", []),
                    # verified/unverified counts are at top level, not nested in response
                    "verified_count": result_data.get("verified_count", 0),
                    "unverified_count": result_data.get("unverified_count", 0),
                    "response_time_ms": response_time_ms,
                    "error": "",
                    "full_response": result_data,
                }

            except json.JSONDecodeError as e:
                return {
                    "status": "error",
                    "answer": content_text,
                    "response_time_ms": response_time_ms,
                    "error": f"JSON parsing failed: {e}",
                    "full_response": content_text
                }

        except Exception as e:
            logger.error(f"CPG query failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "answer": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }

    async def test_query(self, query: str, output_json: bool = False) -> Dict[str, Any]:
        """Run a test query and display results."""
        print("=" * 80)
        print("GRAPH RAG QUERY TEST")
        print("=" * 80)
        print(f"Query: {query}")
        print("-" * 80)

        result = await self.run_cpg_query(query)

        print(f"\n[Completed in {result.get('response_time_ms', 0)/1000:.1f}s]")

        if result.get('status') == 'success':
            print("\n" + "=" * 80)
            print("ANSWER:")
            print("=" * 80)
            print(result.get('answer', 'No answer found'))

            # Print confidence and verification stats
            print(f"\nConfidence: {result.get('confidence', 'N/A')}")
            print(f"Verified: {result.get('verified_count', 0)} / Unverified: {result.get('unverified_count', 0)}")

            # Print citations summary if available
            citations = result.get('citations', [])
            if citations:
                print(f"\nCitations ({len(citations)}):")
                for i, citation in enumerate(citations[:5]):
                    claim = citation.get('claim', 'N/A') if isinstance(citation, dict) else str(citation)
                    print(f"  {i+1}. {claim[:80]}...")
        else:
            print("\n" + "=" * 80)
            print("ERROR:")
            print("=" * 80)
            print(result.get('error', 'Unknown error'))

        if output_json:
            print("\n" + "=" * 80)
            print("RAW JSON RESPONSE:")
            print("=" * 80)
            print(json.dumps(result.get('full_response', result), indent=2))

        return result


def main():
    """Main function to run the Graph RAG query test."""
    parser = argparse.ArgumentParser(description="Test Graph RAG CPG query")
    parser.add_argument("--query", "-q", type=str,
                        default="What are the key methods in the HelloWorldApp and their cyclomatic complexity?",
                        help="The query to test")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output raw JSON response")

    args = parser.parse_args()

    async def run_test():
        tester = GraphRAGQueryTester()
        return await tester.test_query(args.query, output_json=args.json)

    return asyncio.run(run_test())


if __name__ == "__main__":
    main()

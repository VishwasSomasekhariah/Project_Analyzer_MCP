"""
Quick test to verify the V2 hybrid workflow fallback path (vector + CPG).
Uses a query that PageIndex cannot answer confidently to trigger the fallback.
"""
import asyncio
import json
import logging
from mcp_use import MCPSession
from mcp_use.connectors.http import HttpConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MCP_CONFIG = "/opt/genpod/file_watcher_mcp_config.json"

# This query asks about something that does NOT exist in HelloWorldApp
# (no REST API / authentication layer), so PageIndex should return low confidence
# and trigger the vector + CPG fallback path.
FALLBACK_QUERY = (
    "What REST API endpoints does HelloWorldApp expose and how is JWT authentication "
    "handled between the client and the worker services?"
)


async def run():
    with open(MCP_CONFIG) as f:
        config = json.load(f)
    server_config = config["mcpServers"]["mcp-analysis-server"]
    connector = HttpConnector(
        base_url=server_config["url"],
        headers=server_config.get("headers"),
        auth_token=server_config.get("auth_token"),
        timeout=10,
        sse_read_timeout=3600,
    )
    session = MCPSession(connector)
    await session.initialize()

    logger.info(f"Running query: {FALLBACK_QUERY}")
    result = await session.call_tool(
        "query_hybrid_rag",
        {
            "user_query": FALLBACK_QUERY,
            "project_name": "HelloWorldApp",
            "project_path": "/opt/HelloWorldApp",
            "mcts_iterations": 20,
            "collection_name": "HelloWorldApp_pageindex_test",
            "vector_config_path": "/opt/genpod/qdrant_config.json",
            "config_path": "/opt/genpod/neo4j_config.json",
            "vector_db": "qdrant",
            "enable_reasoning": True,
            "max_branches": 2,
            "max_results": 5,
            "batch_size": 5,
            "max_context_limit": 100000,
            "use_4_agent_team": True,
            "four_agent_max_iterations": 3,
        },
    )

    content = result.content[0] if isinstance(result.content, list) else result.content
    text = content.text if hasattr(content, "text") else str(content)
    data = json.loads(text)

    print("\n" + "=" * 70)
    print("V2 HYBRID WORKFLOW - FALLBACK PATH TEST")
    print("=" * 70)
    print(f"analysis_type   : {data.get('analysis_type')}")
    print(f"used_fallback   : {data.get('used_fallback')}")

    retrieval = data.get("retrieval_results", {})
    pi  = retrieval.get("pageindex", {})
    vec = retrieval.get("vector", {})
    cpg = retrieval.get("cpg", {})
    print(f"\nPageIndex : status={pi.get('status')}, results={pi.get('results_count')}, sufficient={pi.get('was_sufficient')}")
    print(f"Vector    : status={vec.get('status')}, results={vec.get('results_count')}")
    print(f"CPG       : status={cpg.get('status')}, results={cpg.get('results_count')}")

    synthesis = data.get("synthesis", {})
    print(f"\nStrategy  : {synthesis.get('strategy_used')}")
    print(f"Confidence: {synthesis.get('confidence')}")
    print(f"Status    : {synthesis.get('status')}")
    print(f"\nAnswer:\n{synthesis.get('answer', '')}")
    print("=" * 70)

    with open("test_hybrid_v2_fallback_result.json", "w") as f:
        json.dump(data, f, indent=2)
    print("\nFull result saved to test_hybrid_v2_fallback_result.json")


if __name__ == "__main__":
    asyncio.run(run())

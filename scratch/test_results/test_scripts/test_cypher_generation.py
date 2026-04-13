#!/usr/bin/env python3
"""
Test if Cypher generation now works with the comprehensive analysis
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_cypher_generation():
    """Test if Cypher generation works now."""
    logger.info("Testing Cypher generation with comprehensive analysis...")
    
    # Connect to main MCP server (port 9000)
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("project-analyzer-server")
    
    logger.info("✓ Connected to main MCP server")
    
    try:
        # Test the fixed comprehensive analysis
        logger.info("=== Testing Comprehensive Analysis ===")
        
        result = await session.call_tool(
            "comprehensive_code_analysis",
            {
                "user_query": "Find all functions that handle errors or exceptions in the codebase",
                "project_path": "/opt/HelloWorldApp",
                "collection_name": "helloworldapp-fresh-test",
                "max_vector_results": 10,
                "max_cpg_results": 15,
                "use_llm_filtering": True,
                "neo4j_config": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("✅ Comprehensive analysis completed")
        
        # Parse the result to check Cypher generation
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        
        if hasattr(result_content, 'text'):
            content_text = result_content.text
        else:
            content_text = str(result_content)
        
        try:
            result_data = json.loads(content_text)
        except json.JSONDecodeError:
            result_data = {"raw_content": content_text}
        
        # Check the steps
        steps = result_data.get("steps", {})
        cypher_generation = steps.get("3_cypher_generation", {})
        cpg_queries = steps.get("4_cpg_queries", {})
        
        logger.info("=== Cypher Generation Results ===")
        logger.info(f"Cypher generation status: {cypher_generation.get('status', 'Unknown')}")
        
        if "queries" in cypher_generation:
            queries = cypher_generation["queries"]
            logger.info(f"✅ Generated {len(queries)} Cypher queries")
            
            for i, query in enumerate(queries):
                logger.info(f"Query {i+1}: {query.get('query', 'No query')[:100]}...")
        else:
            logger.warning("❌ No Cypher queries found in generation step")
        
        logger.info("=== CPG Query Execution Results ===")
        if "results" in cpg_queries:
            cpg_results = cpg_queries["results"]
            successful_queries = [q for q in cpg_results if q.get("status") == "success"]
            
            logger.info(f"✅ CPG queries executed: {len(successful_queries)}/{len(cpg_results)} successful")
            
            for i, query_result in enumerate(cpg_results):
                status = query_result.get("status", "unknown")
                result_count = len(query_result.get("result", []))
                logger.info(f"  Query {i+1}: {status} ({result_count} results)")
                
                if status == "success" and result_count > 0:
                    logger.info(f"    Sample result: {str(query_result.get('result', [])[:1])}")
        else:
            logger.warning("❌ No CPG query results found")
        
        # Check overall success
        if cypher_generation.get("status") == "success" and cpg_queries.get("successful_queries", 0) > 0:
            logger.info("🎉 SUCCESS: Cypher generation and execution working!")
        else:
            logger.warning("⚠️ Issues detected in Cypher generation/execution")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await client.close_session("project-analyzer-server")
        logger.info("✓ MCP session closed")


if __name__ == "__main__":
    asyncio.run(test_cypher_generation())
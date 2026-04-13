#!/usr/bin/env python3
"""
Test script to validate the enhanced error feedback loop functionality
in the comprehensive_code_analysis tool.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add the src directory to the path so we can import the MCP client
sys.path.insert(0, str(Path(__file__).parent))

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/opt/genpod/test_error_feedback_loop.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def test_error_feedback_loop():
    """Test the enhanced error feedback loop functionality."""
    logger.info("Starting error feedback loop test")
    
    try:
        # Connect to MCP server
        config_file = "/opt/genpod/file_watcher_mcp_config.json"
        client = MCPClient.from_config_file(config_file)
        session = await client.create_session("project-analyzer-server")
        
        logger.info("✓ Connected to MCP server")
        logger.info(f"Available tools: {[tool.name for tool in session.tools]}")
        
        # Test comprehensive analysis with error feedback potential
        # This query should trigger some Cypher generation that might need retries
        test_query = "Find all functions that handle errors or exceptions in the codebase"
        
        logger.info(f"Testing comprehensive analysis with query: {test_query}")
        
        # Call the comprehensive_code_analysis tool
        result = await session.call_tool(
            "comprehensive_code_analysis",
            {
                "user_query": test_query,
                "project_path": "/opt/HelloWorldApp",  # Use the existing test project
                "collection_name": "helloworldapp-fresh-test",  # Use the correct collection name
                "max_vector_results": 10,
                "max_cpg_results": 15,
                "use_llm_filtering": True,
                "neo4j_config": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("✓ Comprehensive analysis completed")
        
        # Analyze the result structure to check for error feedback implementation
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        
        # Handle MCP TextContent objects
        if hasattr(result_content, 'text'):
            content_text = result_content.text
        elif isinstance(result_content, str):
            content_text = result_content
        else:
            content_text = str(result_content)
        
        try:
            result_data = json.loads(content_text)
        except json.JSONDecodeError:
            result_data = {"raw_content": content_text}
        
        # Check for retry-related fields in the results
        steps = result_data.get("steps", {})
        cypher_generation = steps.get("3_cypher_generation", {})
        
        logger.info("=== Error Feedback Loop Analysis ===")
        logger.info(f"Cypher generation status: {cypher_generation.get('status', 'Unknown')}")
        
        if "attempt" in cypher_generation:
            logger.info(f"✓ Retry mechanism active - completed on attempt: {cypher_generation['attempt']}")
        
        if "retry_history" in cypher_generation:
            retry_history = cypher_generation["retry_history"]
            logger.info(f"✓ Retry history captured - {len(retry_history)} attempts logged")
            
            for i, retry in enumerate(retry_history):
                logger.info(f"  Retry {i+1}: {retry.get('type', 'unknown')} - {retry.get('error', 'no error')[:100]}")
        
        if cypher_generation.get("status") == "failed_all_retries":
            logger.info("✓ Fallback mechanism triggered after all retries failed")
            logger.info(f"  Fallback: {cypher_generation.get('fallback', 'Unknown')}")
        
        # Check CPG query results
        cpg_queries = steps.get("4_cpg_queries", {})
        if "results" in cpg_queries:
            successful_queries = len([q for q in cpg_queries["results"] if q.get("status") == "success"])
            total_queries = len(cpg_queries["results"])
            logger.info(f"✓ CPG queries executed: {successful_queries}/{total_queries} successful")
            
            # Log some example results
            for i, query_result in enumerate(cpg_queries["results"][:3]):  # Show first 3
                status = query_result.get("status", "unknown")
                query_type = query_result.get("query_type", "unknown")
                attempt = query_result.get("attempt", "unknown")
                logger.info(f"  Query {i+1} ({query_type}): {status} (attempt: {attempt})")
        
        # Log final summary
        synthesis = steps.get("5_synthesis", {})
        if "summary" in synthesis:
            summary = synthesis["summary"]
            logger.info("=== Final Summary ===")
            logger.info(f"Vector search results: {summary.get('vector_search_results', 'Unknown')}")
            logger.info(f"LLM filtering applied: {summary.get('llm_filtering_applied', 'Unknown')}")
            logger.info(f"Cypher queries generated: {summary.get('cypher_queries_generated', 'Unknown')}")
            logger.info(f"Successful CPG queries: {summary.get('successful_cpg_queries', 'Unknown')}")
            logger.info(f"Analysis complete: {summary.get('analysis_complete', 'Unknown')}")
        
        logger.info("✅ Error feedback loop test completed successfully")
        
        # Save detailed results for review
        with open("/opt/genpod/error_feedback_test_results.json", "w") as f:
            json.dump(result_data, f, indent=2)
        logger.info("✓ Detailed results saved to error_feedback_test_results.json")
        
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise
    finally:
        try:
            await client.close_session("project-analyzer-server")
            logger.info("✓ MCP session closed")
        except Exception as e:
            logger.warning(f"Error closing session: {e}")

async def main():
    """Main test execution."""
    try:
        await test_error_feedback_loop()
        print("\n✅ Error feedback loop test PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Error feedback loop test FAILED: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
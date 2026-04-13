#!/usr/bin/env python3
"""
Save the full comprehensive analysis response to a file for inspection
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


async def save_full_response():
    """Save the full comprehensive analysis response."""
    logger.info("Saving full comprehensive analysis response...")
    
    # Connect to main MCP server (port 9000)
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("project-analyzer-server")
    
    logger.info("✓ Connected to main MCP server")
    
    try:
        # Test the comprehensive analysis
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
        
        # Extract the full response text
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        
        if hasattr(result_content, 'text'):
            content_text = result_content.text
        else:
            content_text = str(result_content)
        
        # Save to file
        with open("/opt/genpod/full_comprehensive_response.json", "w") as f:
            f.write(content_text)
        
        logger.info("✅ Full response saved to full_comprehensive_response.json")
        
        # Also try to parse and save pretty-printed JSON
        try:
            result_data = json.loads(content_text)
            
            with open("/opt/genpod/full_comprehensive_response_pretty.json", "w") as f:
                json.dump(result_data, f, indent=2)
            
            logger.info("✅ Pretty-printed JSON saved to full_comprehensive_response_pretty.json")
            
            # Show structure
            logger.info("=== Response Structure ===")
            if isinstance(result_data, dict):
                logger.info(f"Top-level keys: {list(result_data.keys())}")
                
                if "results" in result_data and "steps" in result_data["results"]:
                    steps = result_data["results"]["steps"]
                    logger.info(f"Steps available: {list(steps.keys())}")
                    
                    for step_name, step_data in steps.items():
                        logger.info(f"Step {step_name}: {list(step_data.keys()) if isinstance(step_data, dict) else type(step_data)}")
                        
                        if isinstance(step_data, dict) and "status" in step_data:
                            logger.info(f"  Status: {step_data['status']}")
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse as JSON: {e}")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await client.close_session("project-analyzer-server")
        logger.info("✓ MCP session closed")


if __name__ == "__main__":
    asyncio.run(save_full_response())
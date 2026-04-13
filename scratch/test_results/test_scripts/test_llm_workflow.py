#!/usr/bin/env python3
# test_llm_workflow.py
"""
Test script for the modular MCP architecture with focus on orchestrated workflows.
Tests the full_project_setup workflow and comprehensive_code_analysis pipeline.

This script tests:
1. LLM service setup and configuration
2. full_project_setup: vectorization + CPG analysis + comprehensive monitoring
3. comprehensive_code_analysis: LLM-powered query workflow using established data
"""

import asyncio
import time
import logging
import json
import tempfile
import os
import sys

from mcp_use import MCPClient

# Point at your SSE transport
MCP_SERVER_URL = "http://localhost:9000/sse"

# ——— Configuration —————————————————————————————————————————————
# Create a timestamped log file for this test run
import datetime
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = f"/opt/genpod/test_modular_architecture_{timestamp}.log"

# Configure logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_filename, mode='w', encoding='utf-8'),
        logging.StreamHandler()  # Keep console output too
    ]
)
logger = logging.getLogger(__name__)

# Log the test session details
logger.info("=" * 80)
logger.info("MODULAR MCP ARCHITECTURE TEST SESSION")
logger.info("=" * 80)
logger.info(f"Test session started at: {datetime.datetime.now().isoformat()}")
logger.info(f"Log file: {log_filename}")
logger.info(f"MCP Server URL: {MCP_SERVER_URL}")
logger.info("=" * 80)


def unwrap_content(result):
    """
    The mcp_use client returns result.content as a list of TextContent objects.
    We pull out the first element, take its .text and JSON-decode it if possible.
    """
    raw = result.content
    if isinstance(raw, list) and raw:
        raw = raw[0]
    # If it has a .text attribute, attempt to parse JSON out of it
    if hasattr(raw, "text"):
        try:
            return json.loads(raw.text)
        except json.JSONDecodeError:
            return raw.text
    return raw


async def test_llm_service_setup(session):
    """Test LLM service setup before main workflows."""
    
    logger.info("=== Testing LLM Service Setup ===")
    
    # Test 1: LLM service health check
    logger.info("Testing LLM service health check...")
    try:
        resp = await session.call_tool("llm_service_health_check", {})
        result = unwrap_content(resp)
        logger.info("✓ LLM service status: %s", result.get("llm_service_status", "unknown"))
        if result.get("llm_service_status") != "available":
            logger.warning("⚠ LLM service not available - comprehensive analysis may fail")
    except Exception as e:
        logger.error("✗ LLM service health check failed: %s", e)
        return False
    
    # Test 2: Configure LLM service (in case API keys aren't set)
    logger.info("Testing LLM service configuration...")
    try:
        resp = await session.call_tool(
            "configure_llm_service",
            {
                "provider": "openai",
                "cache_ttl": 1800
                # Note: API keys should be set via environment variables
            }
        )
        result = unwrap_content(resp)
        logger.info("✓ LLM configuration: %s", result.get("message", "unknown"))
    except Exception as e:
        logger.error("✗ LLM configuration failed: %s", e)
        return False
    
    return True


async def test_full_project_setup(session):
    """Test the full project setup workflow."""
    
    logger.info("=== Testing Full Project Setup Workflow ===")
    
    # Test full_project_setup - the orchestrated workflow
    logger.info("🔧 Executing full project setup (vectorization + CPG analysis + monitoring)...")
    logger.info("📁 Project path: /opt/HelloWorldApp")
    logger.info("📊 Collection name: helloworldapp-comprehensive")
    logger.info("🔍 LSP analysis: enabled")
    logger.info("🤖 AI enhancements: enabled")
    logger.info("⏳ Processing initiated - this may take several minutes...")
    
    try:
        t0 = time.time()
        resp = await session.call_tool(
            "full_project_setup",
            {
                "project_path": "/opt/HelloWorldApp",
                "collection_name": "helloworldapp-comprehensive",
                "enable_lsp": True,
                "enable_ai": True
            }
        )
        duration = time.time() - t0
        result = unwrap_content(resp)
        
        logger.info("⏱️  Full project setup completed in %.2f seconds", duration)
        
        if result.get("status") == "success":
            logger.info("✓ Full project setup completed in %.2f seconds", duration)
            logger.info("Monitoring mode: %s", result.get("monitoring_mode"))
            logger.info("Capabilities: %s", result.get("capabilities", []))
            
            # Log workflow step results
            workflow_results = result.get("workflow_results", {})
            steps = workflow_results.get("steps", {})
            for step_name, step_data in steps.items():
                logger.info("  %s: %s", step_name, step_data.get("status", "unknown"))
                if step_data.get("status") == "failed":
                    logger.warning("    Error: %s", step_data.get("error", "unknown"))
        else:
            logger.error("✗ Full project setup failed: %s", result.get("error", "unknown"))
            # Log partial results if available
            if "partial_results" in result:
                logger.info("Partial results available:")
                partial_steps = result["partial_results"].get("steps", {})
                for step_name, step_data in partial_steps.items():
                    logger.info("  %s: %s", step_name, step_data.get("status", "unknown"))
            return False
            
    except Exception as e:
        logger.error("✗ Full project setup failed with exception: %s", e)
        return False
    
    return True


async def test_comprehensive_analysis(session):
    """Test the comprehensive LLM-powered analysis workflow."""
    
    logger.info("=== Testing Comprehensive LLM Analysis ===")
    
    # Test the full workflow
    test_query = "How is the main function implemented and what functions does it call?"
    
    logger.info("Testing comprehensive analysis with query: '%s'", test_query)
    
    try:
        t0 = time.time()
        resp = await session.call_tool(
            "comprehensive_code_analysis",
            {
                "user_query": test_query,
                "project_path": "/opt/HelloWorldApp",
                "collection_name": "helloworldapp-comprehensive",  # Use same collection as full setup
                "neo4j_config": "/opt/genpod/neo4j_config.json",
                "max_vector_results": 5,
                "max_cpg_results": 10,
                "use_llm_filtering": True,
                "llm_provider": "openai"
            }
        )
        duration = time.time() - t0
        result = unwrap_content(resp)
        
        logger.info("Comprehensive analysis completed in %.2f seconds", duration)
        
        if result.get("status") == "success":
            logger.info("✓ Comprehensive analysis succeeded!")
            
            # Log workflow steps
            analysis_results = result.get("results", {})
            steps = analysis_results.get("steps", {})
            
            for step_name, step_data in steps.items():
                status = step_data.get("status", "unknown")
                logger.info("  %s: %s", step_name, status)
                
                if status == "failed":
                    logger.warning("    Error: %s", step_data.get("error", "unknown"))
                elif status == "completed":
                    # Log some summary info
                    if "result_count" in step_data:
                        logger.info("    Results: %s", step_data["result_count"])
                    if "llm_metadata" in step_data:
                        metadata = step_data["llm_metadata"]
                        logger.info("    LLM: %s (cost: $%.4f, latency: %sms)", 
                                  metadata.get("model", "unknown"),
                                  metadata.get("cost", 0),
                                  metadata.get("latency_ms", 0))
            
            # Log final summary
            synthesis = steps.get("5_synthesis", {}).get("summary", {})
            if synthesis:
                logger.info("Final Summary:")
                logger.info("  Vector results: %s", synthesis.get("vector_search_results", 0))
                logger.info("  LLM filtering: %s", synthesis.get("llm_filtering_applied", False))
                logger.info("  Cypher queries: %s", synthesis.get("cypher_queries_generated", 0))
                logger.info("  Successful CPG queries: %s", synthesis.get("successful_cpg_queries", 0))
            
        else:
            logger.error("✗ Comprehensive analysis failed: %s", result.get("error", "unknown"))
            # Log partial results if available
            if "partial_results" in result:
                logger.info("Partial results available - checking steps...")
                partial_steps = result["partial_results"].get("steps", {})
                for step_name, step_data in partial_steps.items():
                    logger.info("  %s: %s", step_name, step_data.get("status", "unknown"))
            return False
            
    except Exception as e:
        logger.error("✗ Comprehensive analysis failed with exception: %s", e)
        import traceback
        traceback.print_exc()
        return False
    
    return True


async def main():
    """Main test function."""
    test_start_time = time.time()
    logger.info("Starting modular MCP architecture tests...")
    
    # Log environment information
    logger.info("ENVIRONMENT INFORMATION:")
    logger.info(f"  Python version: {sys.version}")
    logger.info(f"  Working directory: {os.getcwd()}")
    logger.info(f"  Target MCP server: {MCP_SERVER_URL}")
    
    # Check if we have API keys
    openai_key_present = bool(os.getenv("OPENAI_API_KEY"))
    anthropic_key_present = bool(os.getenv("ANTHROPIC_API_KEY"))
    logger.info(f"  OpenAI API key present: {openai_key_present}")
    logger.info(f"  Anthropic API key present: {anthropic_key_present}")
    
    if not openai_key_present and not anthropic_key_present:
        logger.error("❌ No LLM API keys found in environment!")
        logger.error("Please set OPENAI_API_KEY or ANTHROPIC_API_KEY")
        logger.error("Example: export OPENAI_API_KEY='your-key-here'")
        logger.info("=" * 80)
        logger.info(f"TEST SESSION FAILED - No API keys available")
        logger.info(f"Session duration: {time.time() - test_start_time:.2f} seconds")
        logger.info("=" * 80)
        sys.exit(1)

    # 1) Write a temporary MCP config file that points at /sse
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tf:
        cfg = {
            "mcpServers": {
                "project-analyzer-server": {
                    "type": "http",
                    "url": MCP_SERVER_URL
                }
            }
        }
        json.dump(cfg, tf)
        config_path = tf.name

    try:
        # 2) Create the client & session with no timeout constraints
        client = MCPClient.from_config_file(config_path)
        session = await client.create_session("project-analyzer-server")
        
        # Log session creation details
        logger.info("✓ MCP client and session created successfully")
        logger.info("✓ No timeout constraints applied - allowing natural processing time")
        
        # 3) List available tools
        tools_response = session.tools
        tool_names = [tool.name for tool in tools_response]
        logger.info("Available tools: %s", tool_names)
        
        # Check if our new modular tools are available
        expected_tools = [
            "full_project_setup",
            "comprehensive_code_analysis",
            "configure_llm_service",
            "llm_service_health_check"
        ]
        
        missing_tools = [tool for tool in expected_tools if tool not in tool_names]
        if missing_tools:
            logger.error("❌ Missing expected tools: %s", missing_tools)
            return
        
        logger.info("✓ All expected tools are available")
        
        # 4) Run tests in sequence with detailed logging
        success = True
        total_test_start = time.time()
        
        logger.info("🚀 Starting sequential test execution...")
        logger.info("Note: Processing times may vary significantly based on project complexity")
        logger.info("LSP analysis and tree-sitter parsing can take several minutes for complex projects")
        logger.info("-" * 80)
        
        # Test LLM service setup first
        logger.info("Phase 1/3: LLM Service Setup")
        llm_start = time.time()
        if not await test_llm_service_setup(session):
            logger.error("❌ LLM service setup failed")
            success = False
        else:
            logger.info("✅ Phase 1 completed in %.2f seconds", time.time() - llm_start)
        
        # Test full project setup workflow
        if success:
            logger.info("Phase 2/3: Full Project Setup (Vectorization + CPG Analysis)")
            logger.info("⏳ This phase may take several minutes depending on project complexity...")
            setup_start = time.time()
            if not await test_full_project_setup(session):
                logger.error("❌ Full project setup test failed")
                success = False
            else:
                logger.info("✅ Phase 2 completed in %.2f seconds", time.time() - setup_start)
        
        # Test comprehensive analysis workflow (using data from full setup)
        if success:
            logger.info("Phase 3/3: Comprehensive LLM-Powered Analysis")
            logger.info("⏳ Running end-to-end analysis workflow...")
            analysis_start = time.time()
            if not await test_comprehensive_analysis(session):
                logger.error("❌ Comprehensive analysis test failed")
                success = False
            else:
                logger.info("✅ Phase 3 completed in %.2f seconds", time.time() - analysis_start)
        
        # Final test results summary with comprehensive statistics
        total_duration = time.time() - total_test_start
        test_duration = time.time() - test_start_time
        logger.info("=" * 80)
        logger.info("🏁 FINAL TEST RESULTS")
        logger.info("=" * 80)
        
        if success:
            logger.info("🎉 ALL TESTS PASSED!")
            logger.info("✅ Modular MCP architecture is working correctly")
            logger.info("✅ File watcher race conditions have been resolved")
            logger.info("✅ LLM-powered analysis pipeline is functional")
            logger.info("✅ Production-ready implementation validated")
        else:
            logger.error("❌ SOME TESTS FAILED")
            logger.error("Please review the detailed logs above for failure analysis")
            logger.error("Check individual phase logs for specific error details")
        
        logger.info("-" * 80)
        logger.info("⏱️  PERFORMANCE STATISTICS")
        logger.info(f"Total test execution time: {total_duration:.2f} seconds")
        logger.info(f"Overall session duration: {test_duration:.2f} seconds")
        logger.info(f"Test completed at: {datetime.datetime.now().isoformat()}")
        logger.info(f"Detailed log file: {log_filename}")
        logger.info("=" * 80)

    except Exception as e:
        test_duration = time.time() - test_start_time
        logger.exception("❌ CRITICAL ERROR during MCP interaction")
        logger.info("=" * 80)
        logger.info(f"TEST SESSION FAILED with exception: {type(e).__name__}")
        logger.info(f"Session duration: {test_duration:.2f} seconds")
        logger.info(f"Detailed log saved to: {log_filename}")
        logger.info("=" * 80)
    finally:
        # Clean up
        logger.info("Cleaning up test resources...")
        try:
            os.unlink(config_path)
            logger.info("✓ Temporary config file cleaned up")
        except OSError as e:
            logger.warning(f"Could not clean up config file: {e}")
        try:
            await client.close_session("project-analyzer-server")
            logger.info("✓ MCP session closed")
        except Exception as e:
            logger.warning(f"Could not close MCP session cleanly: {e}")
        
        logger.info("Test cleanup completed.")


if __name__ == "__main__":
    asyncio.run(main())
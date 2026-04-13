#!/usr/bin/env python3
"""
Single Query Old vs New CPG Retriever Test

Tests the specific query: "What are the dependencies and relationships between different classes in the HelloWorldApp?"

Compares:
- OLD: query_cpg_only 
- NEW: query_cpg_adaptive

Uses proper MCP client approach like properly_fixed_comparative_analysis.py
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class SingleQueryComparison:
    def __init__(self):
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.test_query = "What are the dependencies and relationships between different classes in the HelloWorldApp?"
        
    async def test_old_implementation(self) -> dict:
        """Test the OLD query_cpg_only implementation"""
        logger.info("🔵 Testing OLD implementation (query_cpg_only)")
        
        try:
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("mcp-analysis-server")
            
            start_time = time.time()
            
            result = await session.call_tool(
                "query_cpg_only",
                {
                    "user_query": self.test_query,
                    "config_path": "/opt/genpod/neo4j_config.json",
                    "max_results": 100,
                    "enable_synthesis": True,
                    "enable_advanced_rag": True
                }
            )
            
            execution_time = time.time() - start_time
            
            # Session cleanup handled automatically
            
            # Save raw MCP result to pickle file for interactive analysis
            import pickle
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pkl_filename = f"old_query_cpg_only_result_{timestamp}.pkl"
            
            with open(pkl_filename, 'wb') as f:
                pickle.dump({
                    "raw_mcp_result": result,
                    "execution_time": execution_time,
                    "test_query": self.test_query,
                    "timestamp": timestamp,
                    "implementation": "query_cpg_only"
                }, f)
            logger.info(f"💾 Saved raw OLD result to: {pkl_filename}")
            
            # Extract result content from MCP response
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            result_data = json.loads(content_text) if isinstance(content_text, str) else content_text
            
            # Extract result details
            status = result_data.get("status", "unknown")
            result_count = 0
            
            if status == "success":
                # Count results from various possible keys
                for key in ["raw_results", "results", "cpg_results", "combined_results"]:
                    if key in result_data and isinstance(result_data[key], list):
                        result_count = max(result_count, len(result_data[key]))
            
            logger.info(f"✅ OLD completed - Status: {status}, Results: {result_count}, Time: {execution_time:.2f}s")
            
            return {
                "implementation": "OLD",
                "status": status,
                "execution_time": execution_time,
                "result_count": result_count,
                "has_synthesis": "synthesis" in result_data or "answer" in result_data,
                "context_size": len(json.dumps(result_data, default=str)),
                "error": result_data.get("error"),
                "analysis_type": result_data.get("analysis_type", "unknown"),
                "discovery_metadata": result_data.get("discovery_metadata", {}),
                "executed_queries": result_data.get("executed_queries", []),
                "full_result": result_data
            }
            
        except Exception as e:
            logger.error(f"❌ OLD implementation failed: {e}")
            return {
                "implementation": "OLD",
                "status": "error",
                "execution_time": 0,
                "result_count": 0,
                "has_synthesis": False,
                "context_size": 0,
                "error": str(e),
                "analysis_type": "error",
                "discovery_metadata": {},
                "executed_queries": [],
                "full_result": {"error": str(e)}
            }
    
    async def test_new_implementation(self) -> dict:
        """Test the NEW query_cpg_rag implementation"""
        logger.info("🟢 Testing NEW implementation (query_cpg_rag)")
        
        try:
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("mcp-analysis-server")
            
            start_time = time.time()
            
            result = await session.call_tool(
                "query_cpg_rag",
                {
                    "user_query": self.test_query,
                    "project_name": "HelloWorldApp",
                    "config_path": "/opt/genpod/neo4j_config.json",
                    "max_results": 100,
                    "max_agent_iterations": 10
                }
            )
            
            execution_time = time.time() - start_time
            
            # Session cleanup handled automatically
            
            # Save raw MCP result to pickle file for interactive analysis
            import pickle
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pkl_filename = f"new_query_cpg_rag_result_{timestamp}.pkl"
            
            with open(pkl_filename, 'wb') as f:
                pickle.dump({
                    "raw_mcp_result": result,
                    "execution_time": execution_time,
                    "test_query": self.test_query,
                    "timestamp": timestamp,
                    "implementation": "query_cpg_rag"
                }, f)
            logger.info(f"💾 Saved raw NEW result to: {pkl_filename}")
            
            # Extract result content from MCP response
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            result_data = json.loads(content_text) if isinstance(content_text, str) else content_text
            
            # Extract result details
            status = result_data.get("status", "unknown")
            result_count = 0
            
            if status == "success":
                # Count results from various possible keys (query_cpg_rag format)
                for key in ["discovered_data", "final_results", "query_history", "raw_results", "results"]:
                    if key in result_data and isinstance(result_data[key], list):
                        result_count = max(result_count, len(result_data[key]))
            
            # Extract agent metadata (query_cpg_rag format)  
            agent_metadata = result_data.get("agent_metadata", {})
            iterations_used = result_data.get("iterations_used", 0)
            
            logger.info(f"✅ NEW completed - Status: {status}, Results: {result_count}, Time: {execution_time:.2f}s")
            
            if iterations_used > 0:
                logger.info(f"🤖 Agent Workflow: {iterations_used} iterations used")
            if agent_metadata:
                workflow_type = result_data.get("workflow_type", "unknown")
                logger.info(f"🔄 Workflow Type: {workflow_type}")
            
            return {
                "implementation": "NEW",
                "status": status,
                "execution_time": execution_time,
                "result_count": result_count,
                "has_synthesis": "response" in result_data and bool(result_data.get("response")),
                "context_size": len(json.dumps(result_data, default=str)),
                "error": result_data.get("error"),
                "analysis_type": result_data.get("tool_name", "query_cpg_rag"),
                "workflow": result_data.get("workflow_type", "unknown"),
                "agent_metadata": agent_metadata,
                "iterations_used": iterations_used,
                "executed_queries": result_data.get("query_history", []),
                "full_result": result_data
            }
            
        except Exception as e:
            logger.error(f"❌ NEW implementation failed: {e}")
            return {
                "implementation": "NEW",
                "status": "error",
                "execution_time": 0,
                "result_count": 0,
                "has_synthesis": False,
                "context_size": 0,
                "error": str(e),
                "analysis_type": "error",
                "workflow": "error",
                "agent_metadata": {},
                "iterations_used": 0,
                "executed_queries": [],
                "full_result": {"error": str(e)}
            }
    
    def analyze_comparison(self, old_result: dict, new_result: dict) -> dict:
        """Analyze and compare the results"""
        
        comparison = {
            "test_query": self.test_query,
            "timestamp": datetime.now().isoformat(),
            
            "performance": {
                "old_time": old_result["execution_time"],
                "new_time": new_result["execution_time"],
                "speedup": old_result["execution_time"] / new_result["execution_time"] if new_result["execution_time"] > 0 else "N/A",
                "faster": "NEW" if new_result["execution_time"] < old_result["execution_time"] else "OLD"
            },
            
            "result_quality": {
                "old_count": old_result["result_count"],
                "new_count": new_result["result_count"],
                "count_change": new_result["result_count"] - old_result["result_count"],
                "both_successful": old_result["status"] == "success" and new_result["status"] == "success"
            },
            
            "context_efficiency": {
                "old_size": old_result["context_size"],
                "new_size": new_result["context_size"],
                "reduction": old_result["context_size"] - new_result["context_size"],
                "reduction_pct": ((old_result["context_size"] - new_result["context_size"]) / old_result["context_size"] * 100) if old_result["context_size"] > 0 else 0
            },
            
            "feature_analysis": {
                "old_synthesis": old_result["has_synthesis"],
                "new_synthesis": new_result["has_synthesis"],
                "synthesis_parity": old_result["has_synthesis"] == new_result["has_synthesis"],
                "agent_workflow": bool(new_result.get("agent_metadata")),
                "iterations_used": new_result.get("iterations_used", 0)
            },
            
            "error_status": {
                "old_status": old_result["status"],
                "new_status": new_result["status"],
                "old_error": old_result.get("error"),
                "new_error": new_result.get("error"),
                "improvement": old_result["status"] != "success" and new_result["status"] == "success",
                "regression": old_result["status"] == "success" and new_result["status"] != "success"
            },
            
            "query_analysis": {
                "old_queries": len(old_result.get("executed_queries", [])),
                "new_queries": len(new_result.get("executed_queries", [])),
                "old_analysis_type": old_result.get("analysis_type"),
                "new_analysis_type": new_result.get("analysis_type"),
                "new_workflow": new_result.get("workflow", "unknown")
            }
        }
        
        # Generate overall assessment
        if comparison["error_status"]["improvement"]:
            comparison["assessment"] = "🚀 NEW implementation fixes critical error in OLD"
        elif comparison["error_status"]["regression"]:
            comparison["assessment"] = "❌ NEW implementation introduces error"
        elif comparison["context_efficiency"]["reduction_pct"] > 20:
            comparison["assessment"] = "📊 Significant context reduction achieved"
        elif comparison["performance"]["faster"] == "NEW" and comparison["result_quality"]["both_successful"]:
            comparison["assessment"] = "⚡ Performance improvement with maintained quality"
        elif comparison["result_quality"]["both_successful"]:
            comparison["assessment"] = "✅ Functional parity maintained"
        else:
            comparison["assessment"] = "⚠️ Mixed results"
        
        return comparison
    
    async def run_single_test(self) -> dict:
        """Run the single query test"""
        logger.info("🧪 Starting Single Query Comparison Test")
        logger.info(f"🔍 Query: {self.test_query}")
        logger.info("=" * 80)
        
        # Test both implementations
        old_result = await self.test_old_implementation()
        logger.info("-" * 40)
        new_result = await self.test_new_implementation()
        
        # Compare results
        comparison = self.analyze_comparison(old_result, new_result)
        
        # Display results
        logger.info("=" * 80)
        logger.info("📊 COMPARISON RESULTS:")
        logger.info(f"📈 Assessment: {comparison['assessment']}")
        logger.info(f"⏱️  Performance: OLD={comparison['performance']['old_time']:.2f}s, NEW={comparison['performance']['new_time']:.2f}s")
        logger.info(f"📋 Result Count: OLD={comparison['result_quality']['old_count']}, NEW={comparison['result_quality']['new_count']}")
        logger.info(f"💾 Context Size: OLD={comparison['context_efficiency']['old_size']:,} chars, NEW={comparison['context_efficiency']['new_size']:,} chars")
        
        if comparison["context_efficiency"]["reduction_pct"] > 0:
            logger.info(f"🎯 Context Reduction: {comparison['context_efficiency']['reduction_pct']:.1f}%")
        
        if comparison["feature_analysis"]["agent_workflow"]:
            iterations = comparison["feature_analysis"]["iterations_used"]
            logger.info(f"🤖 Agent Workflow (NEW): {iterations} iterations used")
        
        logger.info(f"🔧 Query Count: OLD={comparison['query_analysis']['old_queries']}, NEW={comparison['query_analysis']['new_queries']}")
        logger.info("=" * 80)
        
        # Create comprehensive report
        report = {
            "test_metadata": {
                "timestamp": datetime.now().isoformat(),
                "query": self.test_query,
                "config_file": self.config_file
            },
            "old_result": old_result,
            "new_result": new_result,
            "comparison": comparison
        }
        
        # Save report
        filename = f"single_query_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"💾 Detailed report saved to: {filename}")
        
        return report

async def main():
    """Main execution"""
    try:
        tester = SingleQueryComparison()
        report = await tester.run_single_test()
        
        logger.info("🎉 Single Query Test Completed Successfully!")
        print(f"\n📊 Final Assessment: {report['comparison']['assessment']}")
        return report
        
    except Exception as e:
        logger.error(f"💥 Test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

if __name__ == "__main__":
    report = asyncio.run(main())
    
    if report and report["comparison"]["error_status"]["new_status"] == "success":
        print("✅ Test completed successfully!")
    else:
        print("❌ Test encountered issues!")
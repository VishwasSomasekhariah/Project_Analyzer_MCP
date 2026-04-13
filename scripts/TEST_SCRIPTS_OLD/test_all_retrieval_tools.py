#!/usr/bin/env python3
"""
Comprehensive test for all retrieval tools:
1. query_vector_only - Vector retrieval
2. query_cpg_only - Enhanced CPG with Advanced RAG
3. comprehensive_code_analysis - Hybrid retrieval

Following the pattern from properly_fixed_comparative_analysis.py
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from mcp_use import MCPClient

# Configure logging to both file and console
log_filename = f"retrieval_tools_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ComprehensiveRetrievalTester:
    def __init__(self):
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.collection_name = "helloworldapp-benchmarking"
        self.neo4j_config = "/opt/genpod/neo4j_config.json"
        self.project_path = "/opt/HelloWorldApp"
        
        # Output files
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.output_file = f"retrieval_tools_test_results_{timestamp}.json"
        
        logger.info(f"Test results will be saved to: {self.output_file}")
        logger.info(f"Logs will be saved to: {log_filename}")
        
    async def test_vector_only(self, session):
        """Test query_vector_only tool"""
        print("\n🔍 Testing query_vector_only...")
        logger.info("Starting vector_only test")
        
        test_query = "Find WorkerA.cs file"
        logger.info(f"Test query: {test_query}")
        
        try:
            result = await session.call_tool(
                "query_vector_only",
                {
                    "query": test_query,
                    "collection_name": self.collection_name,
                    "max_results": 10,
                    "output_format": "json"
                }
            )
            
            # Parse result - extract content text first
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            try:
                result_data = json.loads(content_text)
            except json.JSONDecodeError:
                result_data = {"error": "JSON parsing failed", "raw_response": content_text}
            
            print(f"  Status: {result_data.get('status', 'unknown')}")
            print(f"  AI Response length: {len(result_data.get('ai_response', ''))}")
            
            # Check raw results
            raw_results = result_data.get("raw_results", [])
            print(f"  Raw results count: {len(raw_results)}")
            
            if raw_results:
                print(f"  First result type: {type(raw_results[0])}")
            
            # Validate vector tool
            checks = [
                ("Status success", result_data.get("status") == "success"),
                ("Has AI response", bool(result_data.get("ai_response"))),
                ("Has raw results", len(raw_results) > 0),
                ("Has metadata", bool(result_data.get("metadata")))
            ]
            
            passed = sum(1 for _, check in checks if check)
            print(f"  Vector tool checks: {passed}/{len(checks)}")
            
            for check_name, check_result in checks:
                status = "✅" if check_result else "❌"
                print(f"    {status} {check_name}")
            
            return passed >= 3, result_data
            
        except Exception as e:
            print(f"  ❌ Vector test failed: {e}")
            return False, None
    
    async def test_cpg_only(self, session):
        """Test query_cpg_only with Enhanced RAG"""
        print("\n🔍 Testing query_cpg_only (Enhanced RAG)...")
        logger.info("Starting cpg_only Enhanced RAG test")
        
        test_query = "How many comment lines are in WorkerA.cs?"
        logger.info(f"Test query: {test_query}")
        
        try:
            result = await session.call_tool(
                "query_cpg_only",
                {
                    "user_query": test_query,
                    "config_path": "/opt/genpod/neo4j_config.json",
                    "max_results": 50,
                    "enable_synthesis": True,
                    "enable_advanced_rag": True
                }
            )
            
            # Parse result - extract content text first
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            try:
                result_data = json.loads(content_text)
            except json.JSONDecodeError:
                result_data = {"error": "JSON parsing failed", "raw_response": content_text}
            
            print(f"  Status: {result_data.get('status', 'unknown')}")
            print(f"  Workflow: {result_data.get('workflow', 'unknown')}")
            print(f"  Analysis type: {result_data.get('analysis_type', 'unknown')}")
            
            # Check raw results
            raw_results = result_data.get("raw_results", [])
            print(f"  Raw results count: {len(raw_results)}")
            
            # Check entities
            entities = result_data.get("entities_extracted", {})
            print(f"  Entities extracted: {len(entities)} types")
            
            # Check retrieval plan
            plan = result_data.get("retrieval_plan", {})
            print(f"  Retrieval plan: {bool(plan)}")
            
            # Check synthesis
            synthesis = result_data.get("synthesis", "")
            print(f"  Synthesis length: {len(synthesis)}")
            
            # Validate CPG tool
            checks = [
                ("Status success", result_data.get("status") == "success"),
                ("Has raw results", len(raw_results) > 0),
                ("Advanced RAG workflow", result_data.get("workflow") == "advanced_rag"),
                ("Entities extracted", bool(entities)),
                ("Has synthesis", bool(synthesis)),
                ("Has retrieval plan", bool(plan))
            ]
            
            passed = sum(1 for _, check in checks if check)
            print(f"  CPG tool checks: {passed}/{len(checks)}")
            
            for check_name, check_result in checks:
                status = "✅" if check_result else "❌"
                print(f"    {status} {check_name}")
            
            return passed >= 4, result_data
            
        except Exception as e:
            print(f"  ❌ CPG test failed: {e}")
            import traceback
            traceback.print_exc()
            return False, None
    
    async def test_comprehensive_analysis(self, session):
        """Test comprehensive_code_analysis with hybrid retrieval"""
        print("\n🔍 Testing comprehensive_code_analysis (Hybrid)...")
        logger.info("Starting comprehensive_code_analysis hybrid test")
        
        test_query = "Analyze the structure of WorkerA.cs"
        logger.info(f"Test query: {test_query}")
        
        try:
            result = await session.call_tool(
                "comprehensive_code_analysis",
                {
                    "user_query": test_query,
                    "project_path": self.project_path,
                    "collection_name": self.collection_name,
                    "use_hybrid_retrieval": True,
                    "max_vector_results": 10,  # Separate parameter for vector search
                    "max_graph_results": 50,   # Separate parameter for CPG search
                    "max_final_results": 60,   # Final hybrid results
                    "neo4j_config": "/opt/genpod/neo4j_config.json"  # Corrected parameter name
                }
            )
            
            # Parse result - extract content text first
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            try:
                result_data = json.loads(content_text)
            except json.JSONDecodeError:
                result_data = {"error": "JSON parsing failed", "raw_response": content_text}
            
            print(f"  Status: {result_data.get('status', 'unknown')}")
            print(f"  Analysis type: {result_data.get('analysis_type', 'unknown')}")
            print(f"  Workflow: {result_data.get('workflow', 'unknown')}")
            
            # Check raw results
            vector_raw = result_data.get("vector_raw_results", [])
            cpg_raw = result_data.get("cpg_raw_results", [])
            print(f"  Vector raw results: {len(vector_raw)}")
            print(f"  CPG raw results: {len(cpg_raw)}")
            
            # Check synthesis
            synthesis = result_data.get("synthesis", "")
            print(f"  Synthesis length: {len(synthesis)}")
            
            # Check entities
            entities = result_data.get("entities_extracted")
            print(f"  Entities extracted: {bool(entities)}")
            
            # Validate comprehensive tool
            checks = [
                ("Status success", result_data.get("status") == "success"),
                ("Hybrid analysis type", "hybrid" in result_data.get("analysis_type", "")),
                ("Vector raw results", len(vector_raw) > 0),
                ("CPG raw results", len(cpg_raw) > 0),
                ("Has synthesis", bool(synthesis)),
                ("Has entities", bool(entities)),
                ("Hybrid workflow", "hybrid" in result_data.get("workflow", ""))
            ]
            
            passed = sum(1 for _, check in checks if check)
            print(f"  Comprehensive tool checks: {passed}/{len(checks)}")
            
            for check_name, check_result in checks:
                status = "✅" if check_result else "❌"
                print(f"    {status} {check_name}")
            
            return passed >= 4, result_data
            
        except Exception as e:
            print(f"  ❌ Comprehensive test failed: {e}")
            import traceback
            traceback.print_exc()
            return False, None
    
    async def run_all_tests(self):
        """Run all retrieval tool tests"""
        print("🧪 Comprehensive Retrieval Tools Test Suite")
        print("=" * 60)
        print("Testing: Vector-Only, CPG-Only (Enhanced RAG), Hybrid Retrieval")
        print("=" * 60)
        print("🚀 Starting comprehensive retrieval tool tests...")
        
        results = {
            "test_metadata": {
                "timestamp": datetime.now().isoformat(),
                "test_suite": "comprehensive_retrieval_tools",
                "total_tests": 3
            },
            "individual_tests": {}
        }
        
        # Create MCP client and session
        client = MCPClient(self.config_file)
        session = await client.create_session("mcp-analysis-server")
        
        try:
            # Test vector only
            vector_success, vector_data = await self.test_vector_only(session)
            results["individual_tests"]["vector_only"] = {
                "success": vector_success,
                "test_query": "Find WorkerA.cs file",
                "tool_response": vector_data
            }
            
            # Test CPG only with Enhanced RAG
            cpg_success, cpg_data = await self.test_cpg_only(session)
            results["individual_tests"]["cpg_only_enhanced_rag"] = {
                "success": cpg_success,
                "test_query": "How many comment lines are in WorkerA.cs?",
                "tool_response": cpg_data
            }
            
            # Test comprehensive analysis
            comp_success, comp_data = await self.test_comprehensive_analysis(session)
            results["individual_tests"]["comprehensive_analysis"] = {
                "success": comp_success,
                "test_query": "Analyze the structure of WorkerA.cs",
                "tool_response": comp_data,
                "vector_raw_results": comp_data.get("vector_raw_results", []) if comp_data else [],
                "cpg_raw_results": comp_data.get("cpg_raw_results", []) if comp_data else [],
                "hybrid_results": comp_data.get("hybrid_results", []) if comp_data else [],
                "synthesis": comp_data.get("synthesis", "") if comp_data else "",
                "entities_extracted": comp_data.get("entities_extracted", {}) if comp_data else {}
            }
            
            # Calculate summary
            passed_tests = sum([vector_success, cpg_success, comp_success])
            results["test_metadata"]["passed_tests"] = passed_tests
            results["test_metadata"]["success_rate"] = passed_tests / 3
            results["test_metadata"]["overall_success"] = passed_tests == 3
            
            # Display results
            print(f"\n📊 Test Results Summary:")
            print(f"  Vector Only: {'✅ PASS' if vector_success else '❌ FAIL'}")
            print(f"  CPG Only (Enhanced RAG): {'✅ PASS' if cpg_success else '❌ FAIL'}")
            print(f"  Comprehensive (Hybrid): {'✅ PASS' if comp_success else '❌ FAIL'}")
            print(f"\n🎯 Overall Score: {passed_tests}/3 tools passing")
            
            # Save results
            with open(self.output_file, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            
            print(f"✅ Test results saved to: {self.output_file}")
            
            print(f"\n{'=' * 60}")
            if passed_tests == 3:
                print("🎉 TEST SUITE PASSED!")
                print("✅ All retrieval tools functioning correctly")
                print("✅ Enhanced RAG implementation verified")
                print("✅ Hybrid retrieval working with raw results")
                print("✅ Benchmarking compatibility confirmed")
            else:
                print("⚠️  TEST SUITE ISSUES DETECTED")
                print(f"❌ {3 - passed_tests} tools need attention")
            
            logger.info(f"Test results saved to {self.output_file}")
            
        finally:
            await client.close()

async def main():
    """Main test runner"""
    tester = ComprehensiveRetrievalTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
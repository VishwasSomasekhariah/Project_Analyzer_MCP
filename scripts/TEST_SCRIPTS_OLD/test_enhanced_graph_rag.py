#!/usr/bin/env python3
"""
Enhanced Graph RAG Test Suite

This script validates the enhanced query_cpg_only tool with advanced RAG capabilities.
Tests both traditional Cypher queries and natural language queries.
"""

import asyncio
import json
import logging
import time
import os
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('enhanced_rag_test.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class EnhancedRAGTester:
    """Test suite for Enhanced Graph RAG system"""
    
    def __init__(self):
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.results = []
        
    async def run_all_tests(self):
        """Run comprehensive test suite"""
        logger.info("🚀 Starting Enhanced Graph RAG Test Suite")
        
        # Test categories
        test_suites = [
            ("Basic Cypher Queries", self.test_basic_cypher_queries),
            ("Natural Language Queries", self.test_natural_language_queries),
            ("Advanced RAG Features", self.test_advanced_rag_features),
            ("Error Handling", self.test_error_handling),
            ("Performance", self.test_performance)
        ]
        
        for suite_name, test_func in test_suites:
            logger.info(f"\n📋 Running {suite_name}...")
            try:
                suite_results = await test_func()
                self.results.append({
                    "suite": suite_name,
                    "results": suite_results,
                    "status": "completed"
                })
            except Exception as e:
                logger.error(f"❌ {suite_name} failed: {e}")
                self.results.append({
                    "suite": suite_name,
                    "error": str(e),
                    "status": "failed"
                })
        
        # Generate final report
        await self.generate_report()
    
    async def test_basic_cypher_queries(self) -> List[Dict]:
        """Test traditional Cypher query functionality"""
        results = []
        
        test_cases = [
            {
                "name": "Simple Type Query",
                "cypher_query": 'MATCH (n:Type) WHERE n.name = "WorkerA" RETURN n.name, n.type_kind, n.file_path LIMIT 1',
                "expected_fields": ["name", "type_kind", "file_path"]
            },
            {
                "name": "File Contents Query", 
                "cypher_query": 'MATCH (f:File)-[:CONTAINS]->(t:Type) WHERE f.name = "WorkerA.cs" RETURN t.name, t.body LIMIT 2',
                "expected_fields": ["name", "body"]
            },
            {
                "name": "Complex Relationship Query",
                "cypher_query": 'MATCH (t:Type)-[:INHERITS_FROM|IMPLEMENTS]->(base:Type) RETURN t.name, base.name LIMIT 3',
                "expected_fields": ["t.name", "base.name"]
            }
        ]
        
        client = MCPClient.from_config_file(self.config_file)
        session = await client.create_session("mcp-analysis-server")
        
        for test_case in test_cases:
            logger.info(f"  Testing: {test_case['name']}")
            start_time = time.time()
            
            try:
                response = await session.call_tool(
                    "query_cpg_only",
                    {
                        "cypher_query": test_case["cypher_query"],
                        "enable_synthesis": False,
                        "enable_advanced_rag": False
                    }
                )
                
                execution_time = time.time() - start_time
                
                # Extract content from CallToolResult
                response_data = response.content[0].text if hasattr(response, 'content') and response.content else str(response)
                try:
                    response_dict = json.loads(response_data) if isinstance(response_data, str) else response_data
                except:
                    response_dict = {"status": "error", "results": None}
                
                # Validate response
                is_valid = self.validate_cypher_response(response_dict, test_case["expected_fields"])
                
                results.append({
                    "test": test_case["name"],
                    "status": "✅ PASS" if is_valid else "❌ FAIL",
                    "execution_time": round(execution_time, 3),
                    "response_status": response_dict.get("status", "unknown"),
                    "has_results": bool(response_dict.get("results")),
                    "response": response_dict
                })
                
                logger.info(f"    Result: {'✅ PASS' if is_valid else '❌ FAIL'} ({execution_time:.3f}s)")
                
            except Exception as e:
                results.append({
                    "test": test_case["name"],
                    "status": "❌ ERROR",
                    "error": str(e),
                    "execution_time": time.time() - start_time
                })
                logger.error(f"    Result: ❌ ERROR - {e}")
        
        return results
    
    async def test_natural_language_queries(self) -> List[Dict]:
        """Test natural language query processing with advanced RAG"""
        results = []
        
        test_cases = [
            {
                "name": "Comment Counting Query",
                "user_query": "How many comment lines are in WorkerA.cs?",
                "expected_intent": "quantitative",
                "expected_workflow": "advanced_rag"
            },
            {
                "name": "Method Listing Query",
                "user_query": "What methods does WorkerA implement?",
                "expected_intent": "structural",
                "expected_workflow": "advanced_rag"
            },
            {
                "name": "Relationship Query",
                "user_query": "Which classes implement IWorker interface?",
                "expected_intent": "relational",
                "expected_workflow": "advanced_rag"
            },
            {
                "name": "Location Query",
                "user_query": "Where is the Manager class defined?",
                "expected_intent": "locational",
                "expected_workflow": "advanced_rag"
            }
        ]
        
        client = MCPClient.from_config_file(self.config_file)
        session = await client.create_session("mcp-analysis-server")
        
        for test_case in test_cases:
            logger.info(f"  Testing: {test_case['name']}")
            start_time = time.time()
            
            try:
                response = await session.call_tool(
                    "query_cpg_only",
                    {
                        "user_query": test_case["user_query"],
                        "enable_synthesis": True,
                        "enable_advanced_rag": True
                    }
                )
                
                execution_time = time.time() - start_time
                
                # Validate advanced RAG response
                is_valid = self.validate_rag_response(response, test_case)
                
                results.append({
                    "test": test_case["name"],
                    "status": "✅ PASS" if is_valid else "❌ FAIL",
                    "execution_time": round(execution_time, 3),
                    "workflow_used": response.get("workflow", "unknown"),
                    "intent_detected": response.get("intent_detected", {}).get("type", "unknown"),
                    "entities_extracted": response.get("entities_extracted", {}),
                    "synthesis_quality": len(response.get("synthesis", "")) > 10,
                    "response": response
                })
                
                logger.info(f"    Result: {'✅ PASS' if is_valid else '❌ FAIL'} ({execution_time:.3f}s)")
                logger.info(f"    Intent: {response.get('intent_detected', {}).get('type', 'unknown')}")
                logger.info(f"    Workflow: {response.get('workflow', 'unknown')}")
                
            except Exception as e:
                results.append({
                    "test": test_case["name"],
                    "status": "❌ ERROR", 
                    "error": str(e),
                    "execution_time": time.time() - start_time
                })
                logger.error(f"    Result: ❌ ERROR - {e}")
        
        return results
    
    async def test_advanced_rag_features(self) -> List[Dict]:
        """Test specific advanced RAG features"""
        results = []
        
        client = MCPClient.from_config_file(self.config_file)
        session = await client.create_session("mcp-analysis-server")
        
        # Test entity extraction
        logger.info("  Testing: Entity Extraction")
        try:
            response = await session.call_tool(
                "query_cpg_only",
                {
                    "user_query": "How many foreach loops are in Manager.cs file?",
                    "enable_synthesis": False,
                    "enable_advanced_rag": True
                }
            )
            
            entities = response.get("entities_extracted", {})
            has_files = bool(entities.get("files"))
            has_concepts = bool(entities.get("concepts"))
            has_intent = bool(entities.get("intent"))
            
            results.append({
                "test": "Entity Extraction",
                "status": "✅ PASS" if (has_files and has_concepts and has_intent) else "❌ FAIL",
                "entities_found": entities,
                "files_extracted": entities.get("files", []),
                "concepts_extracted": entities.get("concepts", []),
                "intent_classified": entities.get("intent", "unknown")
            })
            
        except Exception as e:
            results.append({
                "test": "Entity Extraction",
                "status": "❌ ERROR",
                "error": str(e)
            })
        
        # Test reranking metadata
        logger.info("  Testing: Content Reranking")
        try:
            response = await session.call_tool(
                "query_cpg_only",
                {
                    "user_query": "Show me the WorkerA class implementation",
                    "enable_synthesis": True,
                    "enable_advanced_rag": True
                }
            )
            
            metadata = response.get("metadata", {})
            ranking_meta = metadata.get("ranking_metadata", {})
            has_ranking = bool(ranking_meta.get("total_candidates"))
            has_scores = bool(ranking_meta.get("top_scores"))
            
            results.append({
                "test": "Content Reranking",
                "status": "✅ PASS" if (has_ranking and has_scores) else "❌ FAIL",
                "ranking_metadata": ranking_meta,
                "nodes_processed": ranking_meta.get("total_candidates", 0),
                "top_k_selected": ranking_meta.get("top_k_selected", 0)
            })
            
        except Exception as e:
            results.append({
                "test": "Content Reranking", 
                "status": "❌ ERROR",
                "error": str(e)
            })
        
        return results
    
    async def test_error_handling(self) -> List[Dict]:
        """Test error handling and fallback mechanisms"""
        results = []
        
        test_cases = [
            {
                "name": "Invalid Cypher Query",
                "cypher_query": "INVALID CYPHER SYNTAX",
                "expect_error": True
            },
            {
                "name": "Empty User Query",
                "user_query": "",
                "expect_error": True
            },
            {
                "name": "No Query Provided",
                "expect_error": True
            }
        ]
        
        client = MCPClient.from_config_file(self.config_file)
        session = await client.create_session("mcp-analysis-server")
        
        for test_case in test_cases:
            logger.info(f"  Testing: {test_case['name']}")
            
            try:
                kwargs = {}
                if "cypher_query" in test_case:
                    kwargs["cypher_query"] = test_case["cypher_query"]
                if "user_query" in test_case:
                    kwargs["user_query"] = test_case["user_query"]
                
                response = await session.call_tool("query_cpg_only", kwargs)
                
                has_error = response.get("status") == "error"
                expected_result = test_case.get("expect_error", False)
                is_correct = has_error == expected_result
                
                results.append({
                    "test": test_case["name"],
                    "status": "✅ PASS" if is_correct else "❌ FAIL",
                    "expected_error": expected_result,
                    "got_error": has_error,
                    "error_message": response.get("error", ""),
                    "response": response
                })
                
            except Exception as e:
                results.append({
                    "test": test_case["name"],
                    "status": "❌ EXCEPTION",
                    "error": str(e)
                })
        
        return results
    
    async def test_performance(self) -> List[Dict]:
        """Test performance characteristics"""
        results = []
        
        performance_tests = [
            {
                "name": "Simple Query Performance",
                "query_type": "cypher",
                "cypher_query": 'MATCH (n:Type) RETURN n.name LIMIT 5'
            },
            {
                "name": "Advanced RAG Performance", 
                "query_type": "natural_language",
                "user_query": "What classes are in the project?"
            }
        ]
        
        client = MCPClient.from_config_file(self.config_file)
        session = await client.create_session("mcp-analysis-server")
        
        for test in performance_tests:
            logger.info(f"  Testing: {test['name']}")
            
            # Run multiple times for average
            times = []
            for i in range(3):
                start_time = time.time()
                
                try:
                    if test["query_type"] == "cypher":
                        response = await session.call_tool(
                            "query_cpg_only",
                            {
                                "cypher_query": test["cypher_query"],
                                "enable_advanced_rag": False
                            }
                        )
                    else:
                        response = await session.call_tool(
                            "query_cpg_only",
                            {
                                "user_query": test["user_query"],
                                "enable_advanced_rag": True
                            }
                        )
                    
                    execution_time = time.time() - start_time
                    times.append(execution_time)
                    
                except Exception as e:
                    logger.error(f"    Performance test failed: {e}")
                    break
            
            if times:
                avg_time = sum(times) / len(times)
                results.append({
                    "test": test["name"],
                    "status": "✅ COMPLETE",
                    "average_time": round(avg_time, 3),
                    "min_time": round(min(times), 3),
                    "max_time": round(max(times), 3),
                    "runs": len(times)
                })
                logger.info(f"    Average time: {avg_time:.3f}s")
        
        return results
    
    def validate_cypher_response(self, response: Dict, expected_fields: List[str]) -> bool:
        """Validate basic Cypher query response"""
        if response.get("status") != "success":
            return False
        
        results = response.get("results")
        if not results:
            return False
        
        # Check if expected fields are present
        if isinstance(results, list) and results:
            first_result = results[0]
            return all(field in first_result for field in expected_fields)
        
        return False
    
    def validate_rag_response(self, response: Dict, test_case: Dict) -> bool:
        """Validate advanced RAG response"""
        # Check workflow
        if response.get("workflow") != test_case.get("expected_workflow"):
            return False
        
        # Check intent detection
        intent_detected = response.get("intent_detected", {})
        if intent_detected.get("type") != test_case.get("expected_intent"):
            return False
        
        # Check entities extraction
        entities = response.get("entities_extracted", {})
        if not entities:
            return False
        
        # Check synthesis
        synthesis = response.get("synthesis", "")
        if len(synthesis) < 10:  # Should have meaningful response
            return False
        
        return True
    
    async def generate_report(self):
        """Generate comprehensive test report"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"enhanced_rag_test_report_{timestamp}.json"
        
        # Calculate summary statistics
        total_tests = sum(len(suite["results"]) for suite in self.results if "results" in suite)
        passed_tests = 0
        failed_tests = 0
        error_tests = 0
        
        for suite in self.results:
            if "results" in suite:
                for test in suite["results"]:
                    status = test.get("status", "")
                    if "PASS" in status:
                        passed_tests += 1
                    elif "FAIL" in status:
                        failed_tests += 1
                    elif "ERROR" in status:
                        error_tests += 1
        
        summary = {
            "test_run": {
                "timestamp": timestamp,
                "total_tests": total_tests,
                "passed": passed_tests,
                "failed": failed_tests,
                "errors": error_tests,
                "success_rate": round((passed_tests / total_tests) * 100, 2) if total_tests > 0 else 0
            },
            "test_suites": self.results
        }
        
        # Save detailed report
        with open(report_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        # Print summary
        logger.info(f"\n🎯 TEST SUMMARY")
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"✅ Passed: {passed_tests}")
        logger.info(f"❌ Failed: {failed_tests}")
        logger.info(f"🚫 Errors: {error_tests}")
        logger.info(f"Success Rate: {summary['test_run']['success_rate']}%")
        logger.info(f"📄 Detailed report saved: {report_file}")

async def main():
    """Main test runner"""
    tester = EnhancedRAGTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
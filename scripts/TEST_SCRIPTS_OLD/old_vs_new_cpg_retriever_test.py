#!/usr/bin/env python3
"""
Comprehensive test script comparing old query_cpg_only vs new query_cpg_adaptive implementations.

This script tests:
1. Backward compatibility with identical parameters
2. Performance differences (execution time, result quality)
3. Limit detection capabilities (new feature)
4. Context explosion mitigation (old: 402 rows -> new: ~68 rows)
5. Discovery quality and fault tolerance
6. Debug output comparison

Usage:
    python old_vs_new_cpg_retriever_test.py
"""

import asyncio
import json
import time
import logging
from typing import Dict, Any, List
from datetime import datetime
import sys
import os

# Add src to path for imports
sys.path.append('/opt/genpod/src')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'/opt/genpod/old_vs_new_cpg_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class CPGRetrieverComparison:
    def __init__(self):
        self.test_scenarios = [
            {
                "name": "Architecture Query",
                "user_query": "What is the overall architecture of this project? Show me the main classes and their relationships.",
                "test_type": "structural_discovery"
            },
            {
                "name": "Function Discovery", 
                "user_query": "What functions are defined in this project and what do they do?",
                "test_type": "semantic_discovery"
            },
            {
                "name": "Direct Cypher - Backward Compatibility",
                "cypher_query": "MATCH (n:Type) RETURN n.name, n.file_path, n.type_kind LIMIT 20",
                "user_query": None,
                "test_type": "backward_compatibility"
            },
            {
                "name": "Large Result Set - Context Test",
                "user_query": "Give me a comprehensive overview of all code elements in this project",
                "test_type": "context_explosion_test"
            },
            {
                "name": "Entity Extraction Test",
                "user_query": "Find all classes that inherit from or implement other classes",
                "test_type": "relationship_discovery"
            }
        ]
        
        self.config_path = "configs/neo4j_mcp_config.yaml"
        self.project_name = "HelloWorldApp"
        
    async def test_old_implementation(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Test the old query_cpg_only implementation"""
        logger.info(f"🔵 Testing OLD implementation - {scenario['name']}")
        
        try:
            # Import the MCP server tools
            from project_analyzer_tool.tools import ProjectAnalyzerTools
            
            tools = ProjectAnalyzerTools()
            
            start_time = time.time()
            
            # Call old implementation
            if scenario.get("cypher_query"):
                result = await tools.query_cpg_only(
                    cypher_query=scenario["cypher_query"],
                    config_path=self.config_path,
                    max_results=100,
                    user_query=scenario.get("user_query"),
                    enable_synthesis=True,
                    enable_advanced_rag=True
                )
            else:
                result = await tools.query_cpg_only(
                    user_query=scenario["user_query"],
                    config_path=self.config_path,
                    max_results=100,
                    enable_synthesis=True,
                    enable_advanced_rag=True
                )
            
            execution_time = time.time() - start_time
            
            # Extract metrics
            result_count = 0
            if result.get("status") == "success":
                if "raw_results" in result:
                    result_count = len(result["raw_results"])
                elif "results" in result:
                    result_count = len(result["results"])
                elif "cpg_results" in result:
                    result_count = len(result["cpg_results"])
                    
            return {
                "implementation": "OLD",
                "scenario": scenario["name"],
                "status": result.get("status", "unknown"),
                "execution_time": execution_time,
                "result_count": result_count,
                "has_synthesis": "synthesis" in result or "answer" in result,
                "context_size": self._estimate_context_size(result),
                "error": result.get("error"),
                "raw_result": result,
                "debug_info": {
                    "queries_executed": result.get("executed_queries", []),
                    "discovery_metadata": result.get("discovery_metadata", {}),
                    "analysis_type": result.get("analysis_type", "unknown")
                }
            }
            
        except Exception as e:
            logger.error(f"❌ OLD implementation failed: {e}")
            return {
                "implementation": "OLD",
                "scenario": scenario["name"],
                "status": "error",
                "execution_time": 0,
                "result_count": 0,
                "has_synthesis": False,
                "context_size": 0,
                "error": str(e),
                "raw_result": {},
                "debug_info": {}
            }
    
    async def test_new_implementation(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Test the new query_cpg_adaptive implementation"""
        logger.info(f"🟢 Testing NEW implementation - {scenario['name']}")
        
        try:
            # Import the MCP server tools  
            from project_analyzer_tool.tools import ProjectAnalyzerTools
            
            tools = ProjectAnalyzerTools()
            
            start_time = time.time()
            
            # Call new implementation
            if scenario.get("cypher_query"):
                result = await tools.query_cpg_adaptive(
                    cypher_query=scenario["cypher_query"],
                    user_query=scenario.get("user_query"),
                    project_name=self.project_name,
                    config_path=self.config_path,
                    max_results=100,
                    enable_discovery=True,
                    enable_synthesis=True,
                    enable_advanced_rag=True
                )
            else:
                result = await tools.query_cpg_adaptive(
                    user_query=scenario["user_query"],
                    project_name=self.project_name,
                    config_path=self.config_path,
                    max_results=100,
                    enable_discovery=True,
                    enable_synthesis=True,
                    enable_advanced_rag=True
                )
            
            execution_time = time.time() - start_time
            
            # Extract metrics
            result_count = 0
            if result.get("status") == "success":
                if "raw_results" in result:
                    result_count = len(result["raw_results"])
                elif "results" in result:
                    result_count = len(result["results"])
                elif "cpg_results" in result:
                    result_count = len(result["cpg_results"])
                elif "targeted_expansion_results" in result:
                    result_count = len(result["targeted_expansion_results"])
                    
            # NEW: Extract limit detection info
            limit_detection = result.get("discovery_metadata", {}).get("limit_detection", {})
            
            return {
                "implementation": "NEW", 
                "scenario": scenario["name"],
                "status": result.get("status", "unknown"),
                "execution_time": execution_time,
                "result_count": result_count,
                "has_synthesis": "synthesis" in result or "answer" in result,
                "context_size": self._estimate_context_size(result),
                "error": result.get("error"),
                "raw_result": result,
                "debug_info": {
                    "queries_executed": result.get("executed_queries", []),
                    "discovery_metadata": result.get("discovery_metadata", {}),
                    "analysis_type": result.get("analysis_type", "unknown"),
                    "workflow": result.get("workflow", "unknown")
                },
                # NEW: Limit detection metrics
                "limit_detection": limit_detection
            }
            
        except Exception as e:
            logger.error(f"❌ NEW implementation failed: {e}")
            return {
                "implementation": "NEW",
                "scenario": scenario["name"],
                "status": "error", 
                "execution_time": 0,
                "result_count": 0,
                "has_synthesis": False,
                "context_size": 0,
                "error": str(e),
                "raw_result": {},
                "debug_info": {},
                "limit_detection": {}
            }
    
    def _estimate_context_size(self, result: Dict[str, Any]) -> int:
        """Estimate the context size (character count) of the result"""
        try:
            return len(json.dumps(result, default=str))
        except:
            return len(str(result))
    
    def _compare_results(self, old_result: Dict[str, Any], new_result: Dict[str, Any]) -> Dict[str, Any]:
        """Compare old vs new results and generate insights"""
        
        comparison = {
            "scenario": old_result["scenario"],
            "performance": {
                "old_execution_time": old_result["execution_time"],
                "new_execution_time": new_result["execution_time"],
                "speedup_factor": (old_result["execution_time"] / new_result["execution_time"]) if new_result["execution_time"] > 0 else "N/A",
                "performance_improvement": old_result["execution_time"] > new_result["execution_time"]
            },
            "result_quality": {
                "old_result_count": old_result["result_count"],
                "new_result_count": new_result["result_count"],
                "result_count_change": new_result["result_count"] - old_result["result_count"],
                "both_successful": old_result["status"] == "success" and new_result["status"] == "success"
            },
            "context_efficiency": {
                "old_context_size": old_result["context_size"],
                "new_context_size": new_result["context_size"],
                "context_reduction": old_result["context_size"] - new_result["context_size"],
                "context_reduction_pct": ((old_result["context_size"] - new_result["context_size"]) / old_result["context_size"] * 100) if old_result["context_size"] > 0 else 0
            },
            "feature_comparison": {
                "old_has_synthesis": old_result["has_synthesis"],
                "new_has_synthesis": new_result["has_synthesis"],
                "synthesis_parity": old_result["has_synthesis"] == new_result["has_synthesis"],
                "new_has_limit_detection": bool(new_result.get("limit_detection")),
                "limit_detection_info": new_result.get("limit_detection", {})
            },
            "error_analysis": {
                "old_error": old_result.get("error"),
                "new_error": new_result.get("error"),
                "error_status_change": (old_result["status"], new_result["status"]),
                "reliability_improvement": old_result["status"] != "success" and new_result["status"] == "success"
            }
        }
        
        # Determine overall assessment
        if new_result["status"] == "success" and old_result["status"] != "success":
            comparison["overall_assessment"] = "✅ NEW implementation fixes error in OLD"
        elif old_result["status"] == "success" and new_result["status"] != "success":
            comparison["overall_assessment"] = "❌ NEW implementation introduces error"
        elif comparison["context_efficiency"]["context_reduction_pct"] > 20:
            comparison["overall_assessment"] = "🚀 Significant context efficiency improvement"
        elif comparison["performance"]["performance_improvement"] and comparison["result_quality"]["both_successful"]:
            comparison["overall_assessment"] = "⚡ Performance improvement with maintained quality"
        elif comparison["result_quality"]["both_successful"]:
            comparison["overall_assessment"] = "✅ Functional parity maintained"
        else:
            comparison["overall_assessment"] = "⚠️  Mixed results - requires analysis"
            
        return comparison
    
    async def run_comprehensive_test(self) -> Dict[str, Any]:
        """Run the complete test suite"""
        logger.info("🧪 Starting Comprehensive CPG Retriever Comparison Test")
        logger.info(f"📊 Testing {len(self.test_scenarios)} scenarios")
        
        test_results = []
        comparisons = []
        
        for i, scenario in enumerate(self.test_scenarios):
            logger.info(f"📝 Scenario {i+1}/{len(self.test_scenarios)}: {scenario['name']}")
            logger.info(f"🎯 Test Type: {scenario['test_type']}")
            
            # Test both implementations
            old_result = await self.test_old_implementation(scenario)
            new_result = await self.test_new_implementation(scenario)
            
            # Compare results
            comparison = self._compare_results(old_result, new_result)
            
            test_results.extend([old_result, new_result])
            comparisons.append(comparison)
            
            # Log immediate comparison results
            logger.info(f"📈 {comparison['overall_assessment']}")
            logger.info(f"⏱️  Performance: OLD={old_result['execution_time']:.2f}s, NEW={new_result['execution_time']:.2f}s")
            logger.info(f"📊 Results: OLD={old_result['result_count']}, NEW={new_result['result_count']}")
            if new_result.get("limit_detection"):
                limit_info = new_result["limit_detection"]
                logger.info(f"🔍 Limit Detection: {limit_info.get('completeness_assessment', 'unknown')} completeness")
            logger.info("-" * 80)
        
        # Generate summary statistics
        summary = self._generate_summary_statistics(comparisons)
        
        # Final comprehensive report
        report = {
            "test_metadata": {
                "timestamp": datetime.now().isoformat(),
                "config_path": self.config_path,
                "project_name": self.project_name,
                "total_scenarios": len(self.test_scenarios)
            },
            "individual_results": test_results,
            "comparisons": comparisons,
            "summary_statistics": summary
        }
        
        # Save detailed report
        report_filename = f'/opt/genpod/cpg_retriever_comparison_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(report_filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
            
        logger.info(f"💾 Detailed report saved to: {report_filename}")
        
        return report
    
    def _generate_summary_statistics(self, comparisons: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate summary statistics across all test scenarios"""
        
        successful_old = sum(1 for c in comparisons if c["error_analysis"]["old_error"] is None)
        successful_new = sum(1 for c in comparisons if c["error_analysis"]["new_error"] is None)
        
        performance_improvements = sum(1 for c in comparisons if c["performance"]["performance_improvement"])
        
        context_reductions = [c["context_efficiency"]["context_reduction_pct"] for c in comparisons 
                            if isinstance(c["context_efficiency"]["context_reduction_pct"], (int, float))]
        
        avg_context_reduction = sum(context_reductions) / len(context_reductions) if context_reductions else 0
        
        limit_detection_scenarios = sum(1 for c in comparisons 
                                      if c["feature_comparison"]["new_has_limit_detection"])
        
        return {
            "success_rates": {
                "old_success_rate": successful_old / len(comparisons) * 100,
                "new_success_rate": successful_new / len(comparisons) * 100,
                "success_rate_improvement": (successful_new - successful_old) / len(comparisons) * 100
            },
            "performance": {
                "scenarios_with_performance_improvement": performance_improvements,
                "performance_improvement_rate": performance_improvements / len(comparisons) * 100
            },
            "context_efficiency": {
                "avg_context_reduction_pct": avg_context_reduction,
                "scenarios_with_context_reduction": len([r for r in context_reductions if r > 0]),
                "max_context_reduction_pct": max(context_reductions) if context_reductions else 0
            },
            "new_features": {
                "scenarios_with_limit_detection": limit_detection_scenarios,
                "limit_detection_coverage": limit_detection_scenarios / len(comparisons) * 100
            },
            "overall_recommendation": self._get_overall_recommendation(comparisons)
        }
    
    def _get_overall_recommendation(self, comparisons: List[Dict[str, Any]]) -> str:
        """Generate overall recommendation based on test results"""
        
        success_improvements = sum(1 for c in comparisons if c["error_analysis"]["reliability_improvement"])
        performance_improvements = sum(1 for c in comparisons if c["performance"]["performance_improvement"])
        context_improvements = sum(1 for c in comparisons 
                                 if isinstance(c["context_efficiency"]["context_reduction_pct"], (int, float))
                                 and c["context_efficiency"]["context_reduction_pct"] > 10)
        
        total_scenarios = len(comparisons)
        
        if success_improvements > total_scenarios * 0.3:
            return "🚀 STRONG RECOMMENDATION: NEW implementation significantly improves reliability"
        elif performance_improvements > total_scenarios * 0.6 and context_improvements > total_scenarios * 0.5:
            return "✅ RECOMMENDED: NEW implementation offers better performance and efficiency"
        elif context_improvements > total_scenarios * 0.7:
            return "📈 RECOMMENDED: NEW implementation significantly reduces context explosion"
        elif success_improvements == 0 and performance_improvements > total_scenarios * 0.4:
            return "⚡ CONSIDER: NEW implementation offers performance benefits with maintained reliability"
        else:
            return "⚠️  MIXED RESULTS: Further analysis needed before replacement"

async def main():
    """Main test execution"""
    try:
        logger.info("🎬 Starting CPG Retriever Comparison Test Suite")
        
        tester = CPGRetrieverComparison()
        report = await tester.run_comprehensive_test()
        
        logger.info("📋 FINAL TEST SUMMARY")
        logger.info("=" * 80)
        
        summary = report["summary_statistics"]
        
        logger.info(f"✅ Success Rates: OLD={summary['success_rates']['old_success_rate']:.1f}%, NEW={summary['success_rates']['new_success_rate']:.1f}%")
        logger.info(f"⚡ Performance Improvements: {summary['performance']['scenarios_with_performance_improvement']}/{len(report['comparisons'])} scenarios")
        logger.info(f"📊 Context Efficiency: {summary['context_efficiency']['avg_context_reduction_pct']:.1f}% average reduction")
        logger.info(f"🔍 Limit Detection: {summary['new_features']['scenarios_with_limit_detection']}/{len(report['comparisons'])} scenarios")
        
        logger.info("🏆 OVERALL RECOMMENDATION:")
        logger.info(f"   {summary['overall_recommendation']}")
        
        logger.info("=" * 80)
        logger.info("🎉 Test Suite Completed Successfully!")
        
        return report
        
    except Exception as e:
        logger.error(f"💥 Test suite failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

if __name__ == "__main__":
    # Ensure we're in the right directory
    os.chdir('/opt/genpod')
    
    # Run the test
    report = asyncio.run(main())
    
    if report:
        print(f"\n✅ Test completed successfully!")
        print(f"📊 Report summary: {report['summary_statistics']['overall_recommendation']}")
        sys.exit(0)
    else:
        print("\n❌ Test failed!")
        sys.exit(1)
#!/usr/bin/env python3
"""
Validate Enhanced Graph RAG Against Real Test Scenarios

Test our enhanced system against actual scenarios from properly_fixed_comparative_analysis.py
to determine if issues are with our system or test design.
"""

import asyncio
import json
import logging
from typing import Dict, Any, List
from datetime import datetime

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RealScenarioValidator:
    """Validate against real test scenarios"""
    
    def __init__(self):
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        
    def extract_response_data(self, response) -> Dict[str, Any]:
        """Extract JSON data from MCP CallToolResult"""
        if hasattr(response, 'content') and response.content:
            content_text = response.content[0].text
            try:
                return json.loads(content_text)
            except Exception as e:
                logger.error(f"Failed to parse response JSON: {e}")
                return {"status": "error", "error": f"JSON parse error: {e}"}
        else:
            return {"status": "error", "error": "No content in response"}
    
    async def test_real_scenarios(self):
        """Test against actual scenarios from properly_fixed_comparative_analysis.py"""
        
        # Select representative scenarios from different categories
        test_scenarios = [
            # Comment Count (T072) - Our main test case
            {
                "id": "T072",
                "category": "Technical", 
                "query": "How many comment lines are in WorkerA.cs?",
                "expected_type": "quantitative",
                "scenario_type": "factual"
            },
            # Method Implementation (T088) - Control Flow
            {
                "id": "T088",
                "category": "Functional",
                "query": "Which methods contain foreach loops?", 
                "expected_type": "structural",
                "scenario_type": "factual"
            },
            # Code Comments (T071) - Specific content
            {
                "id": "T071", 
                "category": "Technical",
                "query": "What is the exact text of the first WATCHER TEST comment in WorkerA.cs?",
                "expected_type": "locational",
                "scenario_type": "factual"
            },
            # Using Statements (T069) - Import analysis
            {
                "id": "T069",
                "category": "Technical", 
                "query": "How many using statements are in WorkerFactory.cs?",
                "expected_type": "quantitative",
                "scenario_type": "factual"
            },
            # Method Signatures (T038) - Class structure
            {
                "id": "T038",
                "category": "Technical",
                "query": "What is the exact method signature of the CreateWorkers method in the WorkerFactory class?",
                "expected_type": "structural", 
                "scenario_type": "factual"
            },
            # Interface Implementation (T042) - Relationships
            {
                "id": "T042",
                "category": "Technical",
                "query": "What interface does the Manager class implement?",
                "expected_type": "relational",
                "scenario_type": "factual"
            }
        ]
        
        logger.info("🚀 Testing Enhanced Graph RAG Against Real Scenarios")
        logger.info(f"Testing {len(test_scenarios)} representative scenarios...")
        
        results = []
        client = MCPClient.from_config_file(self.config_file)
        session = await client.create_session("mcp-analysis-server")
        
        for i, scenario in enumerate(test_scenarios, 1):
            logger.info(f"\n{i}️⃣ Testing {scenario['id']}: {scenario['query'][:60]}...")
            
            try:
                # Test with enhanced Graph RAG
                start_time = asyncio.get_event_loop().time()
                
                response = await session.call_tool(
                    "query_cpg_only",
                    {
                        "user_query": scenario["query"],
                        "enable_synthesis": True,
                        "enable_advanced_rag": True
                    }
                )
                
                end_time = asyncio.get_event_loop().time()
                execution_time = round((end_time - start_time) * 1000, 2)  # ms
                
                response_data = self.extract_response_data(response)
                
                # Analyze response quality
                analysis = self.analyze_response_quality(scenario, response_data)
                
                result = {
                    "scenario_id": scenario["id"],
                    "category": scenario["category"], 
                    "query": scenario["query"],
                    "expected_type": scenario["expected_type"],
                    "execution_time_ms": execution_time,
                    "response_status": response_data.get("status"),
                    "workflow_used": response_data.get("workflow"),
                    "intent_detected": response_data.get("intent_detected", {}).get("type"),
                    "entities_extracted": bool(response_data.get("entities_extracted", {}).get("files") or 
                                             response_data.get("entities_extracted", {}).get("types")),
                    "synthesis_length": len(response_data.get("synthesis", "")),
                    "analysis": analysis,
                    "raw_response": response_data
                }
                
                results.append(result)
                
                # Log key metrics
                logger.info(f"   Status: {response_data.get('status')}")
                logger.info(f"   Workflow: {response_data.get('workflow', 'N/A')}")
                logger.info(f"   Intent: {response_data.get('intent_detected', {}).get('type', 'N/A')}")
                logger.info(f"   Answer Length: {len(response_data.get('synthesis', ''))} chars")
                logger.info(f"   Execution: {execution_time}ms")
                logger.info(f"   Quality: {analysis.get('overall_quality', 'N/A')}")
                
            except Exception as e:
                logger.error(f"   ❌ Error testing {scenario['id']}: {e}")
                results.append({
                    "scenario_id": scenario["id"],
                    "query": scenario["query"],
                    "error": str(e),
                    "analysis": {"overall_quality": "ERROR"}
                })
        
        # Generate comprehensive analysis
        await self.generate_scenario_analysis(results)
        return results
    
    def analyze_response_quality(self, scenario: Dict, response_data: Dict) -> Dict[str, Any]:
        """Analyze the quality of the response for a given scenario"""
        
        analysis = {
            "workflow_correct": response_data.get("workflow") == "advanced_rag",
            "intent_classified": response_data.get("intent_detected", {}).get("type") != "error",
            "synthesis_meaningful": len(response_data.get("synthesis", "")) > 20,
            "entities_found": bool(response_data.get("entities_extracted", {})),
            "provides_answer": True,  # Will analyze content
            "response_relevance": "unknown"
        }
        
        synthesis = response_data.get("synthesis", "").lower()
        query = scenario["query"].lower()
        
        # Check if response is relevant to query
        if "error" in synthesis:
            analysis["provides_answer"] = False
            analysis["response_relevance"] = "error"
        elif any(word in synthesis for word in ["comment", "method", "using", "interface", "class"] 
                if word in query):
            analysis["response_relevance"] = "high"
        elif len(synthesis) > 10:
            analysis["response_relevance"] = "medium"
        else:
            analysis["response_relevance"] = "low"
        
        # Overall quality assessment
        quality_score = sum([
            analysis["workflow_correct"],
            analysis["intent_classified"], 
            analysis["synthesis_meaningful"],
            analysis["entities_found"],
            analysis["provides_answer"],
            analysis["response_relevance"] in ["high", "medium"]
        ])
        
        if quality_score >= 5:
            analysis["overall_quality"] = "EXCELLENT"
        elif quality_score >= 4:
            analysis["overall_quality"] = "GOOD"
        elif quality_score >= 3:
            analysis["overall_quality"] = "FAIR"
        elif quality_score >= 2:
            analysis["overall_quality"] = "POOR"
        else:
            analysis["overall_quality"] = "FAILED"
        
        analysis["quality_score"] = f"{quality_score}/6"
        
        return analysis
    
    async def generate_scenario_analysis(self, results: List[Dict]):
        """Generate comprehensive analysis of results"""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"real_scenario_validation_{timestamp}.json"
        
        # Calculate metrics
        total_scenarios = len(results)
        successful_responses = sum(1 for r in results if r.get("response_status") == "success")
        advanced_rag_used = sum(1 for r in results if r.get("workflow_used") == "advanced_rag")
        intent_classified = sum(1 for r in results if r.get("intent_detected") and r.get("intent_detected") != "error")
        entities_extracted = sum(1 for r in results if r.get("entities_extracted"))
        
        # Quality distribution
        quality_counts = {}
        for result in results:
            quality = result.get("analysis", {}).get("overall_quality", "UNKNOWN")
            quality_counts[quality] = quality_counts.get(quality, 0) + 1
        
        # Average execution time
        exec_times = [r.get("execution_time_ms", 0) for r in results if "execution_time_ms" in r]
        avg_execution_time = sum(exec_times) / len(exec_times) if exec_times else 0
        
        summary = {
            "validation_summary": {
                "timestamp": timestamp,
                "total_scenarios_tested": total_scenarios,
                "successful_responses": successful_responses,
                "success_rate": round((successful_responses / total_scenarios) * 100, 1) if total_scenarios > 0 else 0,
                "advanced_rag_usage": advanced_rag_used,
                "advanced_rag_rate": round((advanced_rag_used / total_scenarios) * 100, 1) if total_scenarios > 0 else 0,
                "intent_classification_success": intent_classified,
                "intent_success_rate": round((intent_classified / total_scenarios) * 100, 1) if total_scenarios > 0 else 0,
                "entity_extraction_success": entities_extracted,
                "entity_success_rate": round((entities_extracted / total_scenarios) * 100, 1) if total_scenarios > 0 else 0,
                "average_execution_time_ms": round(avg_execution_time, 2),
                "quality_distribution": quality_counts
            },
            "detailed_results": results
        }
        
        # Save report
        with open(report_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        # Print summary
        logger.info(f"\n🎯 REAL SCENARIO VALIDATION RESULTS")
        logger.info(f"📊 Overall Metrics:")
        logger.info(f"   Total Scenarios: {total_scenarios}")
        logger.info(f"   Successful Responses: {successful_responses}/{total_scenarios} ({summary['validation_summary']['success_rate']}%)")
        logger.info(f"   Advanced RAG Usage: {advanced_rag_used}/{total_scenarios} ({summary['validation_summary']['advanced_rag_rate']}%)")
        logger.info(f"   Intent Classification: {intent_classified}/{total_scenarios} ({summary['validation_summary']['intent_success_rate']}%)")
        logger.info(f"   Entity Extraction: {entities_extracted}/{total_scenarios} ({summary['validation_summary']['entity_success_rate']}%)")
        logger.info(f"   Average Response Time: {round(avg_execution_time, 2)}ms")
        
        logger.info(f"\n📈 Quality Distribution:")
        for quality, count in sorted(quality_counts.items()):
            percentage = round((count / total_scenarios) * 100, 1)
            logger.info(f"   {quality}: {count}/{total_scenarios} ({percentage}%)")
        
        logger.info(f"\n📄 Detailed report saved: {report_file}")
        
        # Assessment
        if summary['validation_summary']['success_rate'] >= 90:
            logger.info(f"\n🎉 SYSTEM ASSESSMENT: EXCELLENT - System performing very well on real scenarios")
        elif summary['validation_summary']['success_rate'] >= 75:
            logger.info(f"\n✅ SYSTEM ASSESSMENT: GOOD - System working well with minor issues")
        elif summary['validation_summary']['success_rate'] >= 60:
            logger.info(f"\n⚠️ SYSTEM ASSESSMENT: FAIR - System functional but needs improvement")
        else:
            logger.info(f"\n❌ SYSTEM ASSESSMENT: POOR - System has significant issues")
        
        return summary

async def main():
    """Main validation runner"""
    validator = RealScenarioValidator()
    results = await validator.test_real_scenarios()
    return results

if __name__ == "__main__":
    asyncio.run(main())
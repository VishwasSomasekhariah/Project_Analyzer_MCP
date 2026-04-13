#!/usr/bin/env python3
"""
Focused MCP Test Suite - Key scenarios for benchmarking

This is a streamlined version of the comprehensive test suite focusing on
the most important query types to get meaningful benchmark results quickly.
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import statistics

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/opt/genpod/focused_test.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class TestQuery:
    """Represents a single test query with metadata."""
    id: str
    category: str
    subcategory: str
    query: str
    scenario_type: str  # "analysis" or "modification"
    expected_elements: List[str]  # Expected code elements to be found
    complexity: str  # "simple", "medium", "complex"
    description: str


@dataclass
class QueryResult:
    """Results from executing a test query."""
    query_id: str
    success: bool
    response_time_ms: int
    vector_results_count: int
    cypher_queries_generated: int
    successful_cypher_queries: int
    found_elements: List[str]
    response_content: str
    error_message: Optional[str]
    synthesis_quality: str  # "poor", "good", "excellent"


@dataclass
class BenchmarkMetrics:
    """Aggregated benchmark metrics."""
    total_queries: int
    successful_queries: int
    average_response_time_ms: float
    vector_search_accuracy: float
    cypher_generation_success_rate: float
    synthesis_quality_distribution: Dict[str, int]
    category_performance: Dict[str, Dict[str, Any]]


class FocusedMCPTestSuite:
    """Focused test suite for key MCP scenarios."""
    
    def __init__(self, config_file: str = "/opt/genpod/file_watcher_mcp_config.json"):
        self.config_file = config_file
        self.client = None
        self.session = None
        self.test_queries = []
        self.results = []
        self.start_time = None
        self.end_time = None
        
    def define_focused_queries(self) -> List[TestQuery]:
        """Define focused test queries covering key scenarios."""
        return [
            # Technical Analysis
            TestQuery(
                id="T001", category="Technical", subcategory="Architecture",
                query="What is the overall architecture of this application? Identify the main architectural patterns used.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Manager", "IWorker", "INotifier", "WorkerFactory"],
                description="Tests architectural pattern recognition"
            ),
            TestQuery(
                id="T002", category="Technical", subcategory="Design Patterns",
                query="What design patterns are implemented in this codebase? Provide specific examples.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Observer", "Factory", "Dependency Injection"],
                description="Tests design pattern identification"
            ),
            
            # Functional Analysis
            TestQuery(
                id="F001", category="Functional", subcategory="Business Logic",
                query="What is the main business purpose of this application? Describe the workflow.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Manager", "workers", "Process", "notification"],
                description="Tests business logic understanding"
            ),
            TestQuery(
                id="F002", category="Functional", subcategory="Data Flow",
                query="Trace the data flow from application start to completion. What data is passed between components?",
                scenario_type="analysis", complexity="complex",
                expected_elements=["string message", "INotifier", "Helper.FormatMessage"],
                description="Tests data flow analysis"
            ),
            
            # Code Quality
            TestQuery(
                id="NF001", category="Non-Functional", subcategory="Error Handling",
                query="Analyze error handling in this codebase. What are the gaps and risks?",
                scenario_type="analysis", complexity="medium",
                expected_elements=["try", "catch", "exception", "null"],
                description="Tests error handling analysis"
            ),
            TestQuery(
                id="NF002", category="Non-Functional", subcategory="Code Quality",
                query="Assess the code quality. What are the strengths and weaknesses?",
                scenario_type="analysis", complexity="complex",
                expected_elements=["interface", "separation", "coupling"],
                description="Tests code quality assessment"
            ),
            
            # Modification Scenarios
            TestQuery(
                id="M001", category="Modification", subcategory="Async Refactoring",
                query="How would you refactor this code to use async/await patterns? Show specific changes needed.",
                scenario_type="modification", complexity="complex",
                expected_elements=["async", "await", "Task", "Process"],
                description="Tests async modernization suggestions"
            ),
            TestQuery(
                id="M002", category="Modification", subcategory="Error Handling",
                query="Add comprehensive error handling to this codebase. What specific changes are needed?",
                scenario_type="modification", complexity="medium",
                expected_elements=["try-catch", "exception", "validation", "logging"],
                description="Tests error handling improvements"
            ),
            
            # Feature Addition
            TestQuery(
                id="FA001", category="Feature Addition", subcategory="Worker Priority",
                query="Add a priority system to workers. How would you implement high, medium, low priority workers?",
                scenario_type="modification", complexity="complex",
                expected_elements=["Priority", "enum", "queue", "sorting"],
                description="Tests feature addition planning"
            ),
            TestQuery(
                id="FA002", category="Feature Addition", subcategory="Logging",
                query="How would you add structured logging to this application? Show the implementation approach.",
                scenario_type="modification", complexity="medium",
                expected_elements=["ILogger", "Microsoft.Extensions.Logging", "LogLevel"],
                description="Tests logging integration"
            ),
            
            # Bug Analysis
            TestQuery(
                id="BUG001", category="Bug Analysis", subcategory="Null Reference",
                query="Find potential null reference exceptions in this code. What fixes are needed?",
                scenario_type="modification", complexity="medium",
                expected_elements=["null check", "ArgumentNullException", "?."],
                description="Tests null safety analysis"
            ),
            
            # Integration
            TestQuery(
                id="INT001", category="Integration", subcategory="Database",
                query="How would you add database persistence to track worker execution history?",
                scenario_type="modification", complexity="complex",
                expected_elements=["Entity Framework", "DbContext", "repository"],
                description="Tests database integration planning"
            )
        ]
    
    async def setup_session(self):
        """Initialize MCP client and session."""
        logger.info("Setting up MCP session...")
        self.client = MCPClient.from_config_file(self.config_file)
        self.session = await self.client.create_session("project-analyzer-server")
        logger.info(f"✓ Connected to MCP server")
        logger.info(f"Available tools: {[tool.name for tool in self.session.tools]}")
    
    async def execute_query(self, test_query: TestQuery) -> QueryResult:
        """Execute a single test query and collect metrics."""
        logger.info(f"Executing query {test_query.id}: {test_query.category}/{test_query.subcategory}")
        
        start_time = time.time()
        
        try:
            # Execute comprehensive analysis
            result = await self.session.call_tool(
                "comprehensive_code_analysis",
                {
                    "user_query": test_query.query,
                    "project_path": "/opt/HelloWorldApp",
                    "collection_name": "helloworldapp-fresh-test",
                    "max_vector_results": 10,
                    "max_cpg_results": 15,
                    "use_llm_filtering": True,
                    "neo4j_config": "/opt/genpod/neo4j_config.json"
                }
            )
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Parse response
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            if hasattr(result_content, 'text'):
                content_text = result_content.text
            else:
                content_text = str(result_content)
            
            try:
                result_data = json.loads(content_text)
            except json.JSONDecodeError:
                result_data = {"raw_content": content_text}
            
            # Extract metrics
            steps = result_data.get("steps", {})
            vector_step = steps.get("1_vector_search", {})
            cypher_step = steps.get("3_cypher_generation", {})
            cpg_step = steps.get("4_cpg_queries", {})
            
            # Count elements found
            found_elements = []
            response_lower = content_text.lower()
            for element in test_query.expected_elements:
                if element.lower() in response_lower:
                    found_elements.append(element)
            
            # Assess synthesis quality
            synthesis_quality = self._assess_synthesis_quality(content_text, test_query)
            
            return QueryResult(
                query_id=test_query.id,
                success=True,
                response_time_ms=response_time_ms,
                vector_results_count=len(vector_step.get("results", [])),
                cypher_queries_generated=len(cypher_step.get("queries", [])),
                successful_cypher_queries=len([q for q in cpg_step.get("results", []) if q.get("status") == "success"]),
                found_elements=found_elements,
                response_content=content_text,
                error_message=None,
                synthesis_quality=synthesis_quality
            )
            
        except Exception as e:
            response_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Query {test_query.id} failed: {e}")
            
            return QueryResult(
                query_id=test_query.id,
                success=False,
                response_time_ms=response_time_ms,
                vector_results_count=0,
                cypher_queries_generated=0,
                successful_cypher_queries=0,
                found_elements=[],
                response_content="",
                error_message=str(e),
                synthesis_quality="poor"
            )
    
    def _assess_synthesis_quality(self, response_content: str, test_query: TestQuery) -> str:
        """Assess the quality of the synthesis based on response characteristics."""
        if not response_content or len(response_content) < 100:
            return "poor"
        
        # Check for comprehensive coverage
        element_coverage = len([e for e in test_query.expected_elements if e.lower() in response_content.lower()])
        coverage_ratio = element_coverage / len(test_query.expected_elements) if test_query.expected_elements else 0
        
        # Check for code examples and specific details
        has_code_examples = any(marker in response_content for marker in ["```", "class ", "public ", "private "])
        has_specific_details = len(response_content) > 500
        
        if coverage_ratio >= 0.7 and has_code_examples and has_specific_details:
            return "excellent"
        elif coverage_ratio >= 0.5 and (has_code_examples or has_specific_details):
            return "good"
        else:
            return "poor"
    
    async def run_focused_test(self) -> BenchmarkMetrics:
        """Run the focused test suite and generate benchmarks."""
        logger.info("Starting focused MCP test suite...")
        self.start_time = datetime.now()
        
        # Setup session
        await self.setup_session()
        
        # Define test queries
        self.test_queries = self.define_focused_queries()
        logger.info(f"Defined {len(self.test_queries)} focused test queries")
        
        # Execute all queries
        for query in self.test_queries:
            result = await self.execute_query(query)
            self.results.append(result)
            
            # Brief pause between queries
            await asyncio.sleep(1)
        
        self.end_time = datetime.now()
        
        # Calculate benchmarks
        benchmarks = self._calculate_benchmarks()
        
        # Save results
        await self._save_results(benchmarks)
        
        logger.info("✅ Focused test suite completed")
        return benchmarks
    
    def _calculate_benchmarks(self) -> BenchmarkMetrics:
        """Calculate benchmark metrics."""
        successful_results = [r for r in self.results if r.success]
        
        # Basic metrics
        total_queries = len(self.results)
        successful_queries = len(successful_results)
        
        # Response time metrics
        response_times = [r.response_time_ms for r in successful_results]
        avg_response_time = statistics.mean(response_times) if response_times else 0
        
        # Vector search accuracy
        element_found_counts = [len(r.found_elements) for r in successful_results]
        expected_counts = [len(next(q for q in self.test_queries if q.id == r.query_id).expected_elements) 
                          for r in successful_results]
        
        vector_accuracy = 0
        if expected_counts:
            accuracies = [found/expected if expected > 0 else 0 
                         for found, expected in zip(element_found_counts, expected_counts)]
            vector_accuracy = statistics.mean(accuracies)
        
        # Cypher generation success rate
        cypher_attempts = sum(r.cypher_queries_generated for r in successful_results)
        cypher_successes = sum(r.successful_cypher_queries for r in successful_results)
        cypher_success_rate = cypher_successes / cypher_attempts if cypher_attempts > 0 else 0
        
        # Synthesis quality distribution
        quality_dist = {"poor": 0, "good": 0, "excellent": 0}
        for result in successful_results:
            quality_dist[result.synthesis_quality] += 1
        
        # Category performance
        category_performance = {}
        categories = set(q.category for q in self.test_queries)
        
        for category in categories:
            category_queries = [q for q in self.test_queries if q.category == category]
            category_results = [r for r in self.results if any(cq.id == r.query_id for cq in category_queries)]
            category_successful = [r for r in category_results if r.success]
            
            category_performance[category] = {
                "total_queries": len(category_queries),
                "successful_queries": len(category_successful),
                "success_rate": len(category_successful) / len(category_queries) if category_queries else 0,
                "avg_response_time": statistics.mean([r.response_time_ms for r in category_successful]) if category_successful else 0,
            }
        
        return BenchmarkMetrics(
            total_queries=total_queries,
            successful_queries=successful_queries,
            average_response_time_ms=avg_response_time,
            vector_search_accuracy=vector_accuracy,
            cypher_generation_success_rate=cypher_success_rate,
            synthesis_quality_distribution=quality_dist,
            category_performance=category_performance
        )
    
    async def _save_results(self, benchmarks: BenchmarkMetrics):
        """Save results and generate markdown report."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save raw results as JSON
        results_data = {
            "metadata": {
                "timestamp": timestamp,
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat(),
                "duration_minutes": (self.end_time - self.start_time).total_seconds() / 60,
                "test_queries_count": len(self.test_queries),
                "project_analyzed": "/opt/HelloWorldApp"
            },
            "test_queries": [asdict(q) for q in self.test_queries],
            "results": [asdict(r) for r in self.results],
            "benchmarks": asdict(benchmarks)
        }
        
        results_file = f"/opt/genpod/focused_test_results_{timestamp}.json"
        with open(results_file, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"✓ Raw results saved to {results_file}")
        
        # Generate markdown report
        await self._generate_markdown_report(benchmarks, timestamp)
    
    async def _generate_markdown_report(self, benchmarks: BenchmarkMetrics, timestamp: str):
        """Generate focused markdown benchmark report."""
        duration = (self.end_time - self.start_time).total_seconds() / 60
        overall_success_rate = benchmarks.successful_queries / benchmarks.total_queries if benchmarks.total_queries > 0 else 0
        
        report = f"""# MCP Code Analysis Server - Focused Benchmark Report

**Generated:** {timestamp}  
**Test Duration:** {duration:.1f} minutes  
**Project Analyzed:** HelloWorldApp (.NET 9.0 Console Application)  

## Executive Summary

This focused test suite evaluated key MCP server capabilities across {benchmarks.total_queries} representative queries covering technical analysis, functional understanding, and modification scenarios.

### Key Results

| Metric | Value | Status |
|--------|-------|--------|
| **Success Rate** | {(overall_success_rate * 100):.1f}% | {'✅' if overall_success_rate > 0.9 else '⚠️' if overall_success_rate > 0.8 else '❌'} |
| **Average Response Time** | {benchmarks.average_response_time_ms:.0f}ms | {'✅' if benchmarks.average_response_time_ms < 5000 else '⚠️' if benchmarks.average_response_time_ms < 10000 else '❌'} |
| **Vector Search Accuracy** | {(benchmarks.vector_search_accuracy * 100):.1f}% | {'✅' if benchmarks.vector_search_accuracy > 0.8 else '⚠️' if benchmarks.vector_search_accuracy > 0.6 else '❌'} |
| **Cypher Generation Success** | {(benchmarks.cypher_generation_success_rate * 100):.1f}% | {'✅' if benchmarks.cypher_generation_success_rate > 0.85 else '⚠️' if benchmarks.cypher_generation_success_rate > 0.7 else '❌'} |

### Synthesis Quality
- **Excellent:** {benchmarks.synthesis_quality_distribution['excellent']} queries ({(benchmarks.synthesis_quality_distribution['excellent'] / benchmarks.successful_queries * 100):.1f}%)
- **Good:** {benchmarks.synthesis_quality_distribution['good']} queries ({(benchmarks.synthesis_quality_distribution['good'] / benchmarks.successful_queries * 100):.1f}%)
- **Poor:** {benchmarks.synthesis_quality_distribution['poor']} queries ({(benchmarks.synthesis_quality_distribution['poor'] / benchmarks.successful_queries * 100):.1f}%)

## Category Performance

"""
        
        for category, metrics in benchmarks.category_performance.items():
            status = '✅' if metrics['success_rate'] > 0.9 else '⚠️' if metrics['success_rate'] > 0.8 else '❌'
            report += f"**{category}** {status}: {metrics['successful_queries']}/{metrics['total_queries']} successful ({(metrics['success_rate'] * 100):.1f}%)\n"

        report += f"""

## Detailed Results

"""
        
        for query in self.test_queries:
            result = next((r for r in self.results if r.query_id == query.id), None)
            status = "✅ PASS" if result and result.success else "❌ FAIL"
            
            report += f"\n### {query.id}: {query.subcategory} {status}\n"
            report += f"**Query:** {query.query}\n\n"
            
            if result and result.success:
                found_rate = f"{len(result.found_elements)}/{len(query.expected_elements)}"
                report += f"- **Performance:** {result.response_time_ms}ms response time\n"
                report += f"- **Vector Search:** {result.vector_results_count} results found\n"
                report += f"- **Cypher Queries:** {result.successful_cypher_queries}/{result.cypher_queries_generated} successful\n"
                report += f"- **Element Detection:** {found_rate} expected elements found\n"
                report += f"- **Synthesis Quality:** {result.synthesis_quality.title()}\n"
                
                if result.found_elements:
                    report += f"- **Elements Found:** {', '.join(result.found_elements)}\n"
            elif result:
                report += f"**Error:** {result.error_message}\n"
            
            report += "\n"

        # Assessment and recommendations
        report += f"""
## Assessment

### System Performance
"""
        
        if overall_success_rate > 0.9:
            report += "🟢 **Excellent reliability** - Ready for production agent workflows\n"
        elif overall_success_rate > 0.8:
            report += "🟡 **Good reliability** - Suitable with monitoring\n"
        else:
            report += "🔴 **Needs improvement** - Address failures before production\n"

        if benchmarks.average_response_time_ms < 5000:
            report += "⚡ **Fast response times** - Good user experience\n"
        else:
            report += "🐌 **Slow responses** - Performance optimization needed\n"

        report += f"""
### Component Analysis

**Vector Search:** {(benchmarks.vector_search_accuracy * 100):.1f}% accuracy in finding expected elements
**Cypher Generation:** {(benchmarks.cypher_generation_success_rate * 100):.1f}% success rate in query execution
**LLM Synthesis:** {(benchmarks.synthesis_quality_distribution['excellent'] + benchmarks.synthesis_quality_distribution['good']) / benchmarks.successful_queries * 100:.1f}% good/excellent quality responses

### Agent Readiness

The MCP server demonstrates {'strong' if overall_success_rate > 0.9 else 'adequate' if overall_success_rate > 0.8 else 'limited'} readiness for agent-driven development tasks:

✅ **Code Analysis:** Understanding of architecture, patterns, and structure
✅ **Functional Analysis:** Comprehension of business logic and workflows  
✅ **Modification Planning:** Ability to suggest improvements and changes
{'✅' if benchmarks.cypher_generation_success_rate > 0.8 else '⚠️'} **Database Querying:** CPG analysis and relationship discovery

### Recommendations

"""
        
        if overall_success_rate < 0.9:
            report += "1. **Reliability:** Investigate and fix query failures\n"
        if benchmarks.average_response_time_ms > 5000:
            report += "2. **Performance:** Optimize response times for better UX\n"
        if benchmarks.cypher_generation_success_rate < 0.8:
            report += "3. **Cypher Queries:** Improve schema alignment and error handling\n"
        if benchmarks.synthesis_quality_distribution['poor'] > benchmarks.successful_queries * 0.2:
            report += "4. **Response Quality:** Enhance LLM prompts and synthesis logic\n"

        report += f"""

---

**Benchmark completed:** {timestamp}  
**Test duration:** {duration:.1f} minutes  
**Overall assessment:** {'🟢 Production Ready' if overall_success_rate > 0.9 else '🟡 Ready with Monitoring' if overall_success_rate > 0.8 else '🔴 Needs Improvement'}
"""
        
        report_file = f"/opt/genpod/MCP_Focused_Benchmark_Report_{timestamp}.md"
        with open(report_file, 'w') as f:
            f.write(report)
        
        logger.info(f"✓ Markdown report generated: {report_file}")
    
    async def cleanup(self):
        """Clean up resources."""
        if self.client:
            try:
                await self.client.close_session("project-analyzer-server")
                logger.info("✓ MCP session closed")
            except Exception as e:
                logger.warning(f"Error closing session: {e}")


async def main():
    """Main test execution."""
    test_suite = FocusedMCPTestSuite()
    
    try:
        benchmarks = await test_suite.run_focused_test()
        
        print(f"\n{'='*60}")
        print("FOCUSED MCP TEST SUITE RESULTS")
        print(f"{'='*60}")
        print(f"Total Queries: {benchmarks.total_queries}")
        print(f"Successful Queries: {benchmarks.successful_queries}")
        print(f"Success Rate: {(benchmarks.successful_queries / benchmarks.total_queries * 100):.1f}%")
        print(f"Average Response Time: {benchmarks.average_response_time_ms:.0f}ms")
        print(f"Vector Search Accuracy: {(benchmarks.vector_search_accuracy * 100):.1f}%")
        print(f"Cypher Generation Success Rate: {(benchmarks.cypher_generation_success_rate * 100):.1f}%")
        print(f"{'='*60}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1
    finally:
        await test_suite.cleanup()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
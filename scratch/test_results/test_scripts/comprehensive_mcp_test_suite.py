#!/usr/bin/env python3
"""
Comprehensive Test Suite for MCP Code Analysis Server

This test suite validates the MCP server's ability to analyze and suggest modifications
for the HelloWorldApp codebase across multiple dimensions:
- Technical analysis (architecture, patterns, dependencies)
- Functional analysis (business logic, workflows)
- Non-functional analysis (performance, security, maintainability)
- Modification scenarios (refactoring, features, modernization)

The test generates detailed benchmarking data and a comprehensive markdown report.
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
        logging.FileHandler("/opt/genpod/comprehensive_test.log"),
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
    token_usage: Optional[Dict[str, int]]
    cost_estimate: float
    vector_results_count: int
    cypher_queries_generated: int
    successful_cypher_queries: int
    found_elements: List[str]
    response_content: str
    error_message: Optional[str]
    llm_filtering_applied: bool
    synthesis_quality: str  # "poor", "good", "excellent"


@dataclass
class BenchmarkMetrics:
    """Aggregated benchmark metrics."""
    total_queries: int
    successful_queries: int
    average_response_time_ms: float
    total_cost: float
    vector_search_accuracy: float
    cypher_generation_success_rate: float
    element_detection_accuracy: float
    synthesis_quality_distribution: Dict[str, int]
    category_performance: Dict[str, Dict[str, Any]]


class ComprehensiveMCPTestSuite:
    """Comprehensive test suite for MCP code analysis server."""
    
    def __init__(self, config_file: str = "/opt/genpod/file_watcher_mcp_config.json"):
        self.config_file = config_file
        self.client = None
        self.session = None
        self.test_queries = []
        self.results = []
        self.start_time = None
        self.end_time = None
        
    def define_test_queries(self) -> List[TestQuery]:
        """Define comprehensive test queries covering all scenarios."""
        queries = []
        
        # For faster execution, let's use a focused subset of key queries
        # 1. TECHNICAL ANALYSIS - Architecture & Design Patterns
        queries.extend([
            TestQuery(
                id="T001", category="Technical", subcategory="Architecture",
                query="What is the overall architecture of this application? Identify the main architectural patterns used.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Manager", "IWorker", "INotifier", "WorkerFactory"],
                description="Tests ability to identify architectural patterns and component relationships"
            ),
            TestQuery(
                id="T002", category="Technical", subcategory="Design Patterns",
                query="What design patterns are implemented in this codebase? Provide specific examples.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Observer", "Factory", "Dependency Injection"],
                description="Tests pattern recognition capabilities"
            ),
            TestQuery(
                id="T003", category="Technical", subcategory="Dependencies",
                query="Analyze the dependency graph. Which classes depend on which interfaces?",
                scenario_type="analysis", complexity="simple",
                expected_elements=["WorkerA", "WorkerB", "WorkerC", "INotifier"],
                description="Tests dependency analysis and interface usage tracking"
            ),
            TestQuery(
                id="T004", category="Technical", subcategory="Class Hierarchy",
                query="Show me the inheritance and interface implementation hierarchy.",
                scenario_type="analysis", complexity="simple",
                expected_elements=["IWorker", "INotifier", "implements"],
                description="Tests class relationship analysis"
            ),
            TestQuery(
                id="T005", category="Technical", subcategory="Method Analysis",
                query="Find all public methods and their signatures across the codebase.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Process", "Notify", "CreateWorkers", "FormatMessage"],
                description="Tests method discovery and signature analysis"
            )
        ])
        
        # 2. FUNCTIONAL ANALYSIS - Business Logic & Workflows
        queries.extend([
            TestQuery(
                id="F001", category="Functional", subcategory="Business Logic",
                query="What is the main business purpose of this application? Describe the workflow.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Manager", "workers", "Process", "notification"],
                description="Tests business logic comprehension"
            ),
            TestQuery(
                id="F002", category="Functional", subcategory="Data Flow",
                query="Trace the data flow from application start to completion. What data is passed between components?",
                scenario_type="analysis", complexity="complex",
                expected_elements=["string message", "INotifier", "Helper.FormatMessage"],
                description="Tests data flow analysis capabilities"
            ),
            TestQuery(
                id="F003", category="Functional", subcategory="Worker Coordination",
                query="How does the Manager coordinate work across multiple workers? What is the coordination pattern?",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Manager.Run", "workers.Process", "callback"],
                description="Tests understanding of coordination mechanisms"
            ),
            TestQuery(
                id="F004", category="Functional", subcategory="Factory Usage",
                query="How are workers created and initialized? What role does the factory play?",
                scenario_type="analysis", complexity="simple",
                expected_elements=["WorkerFactory", "CreateWorkers", "new WorkerA"],
                description="Tests factory pattern analysis"
            ),
            TestQuery(
                id="F005", category="Functional", subcategory="Notification System",
                query="How does the notification system work? Trace all notification flows.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["INotifier.Notify", "Manager.Notify", "message"],
                description="Tests callback mechanism analysis"
            )
        ])
        
        # 3. NON-FUNCTIONAL ANALYSIS - Quality, Performance, Security
        queries.extend([
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
                expected_elements=["interface", "separation", "coupling", "cohesion"],
                description="Tests code quality assessment"
            ),
            TestQuery(
                id="NF003", category="Non-Functional", subcategory="Performance",
                query="Identify potential performance bottlenecks and areas for optimization.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["Console.WriteLine", "foreach", "synchronous"],
                description="Tests performance analysis capabilities"
            ),
            TestQuery(
                id="NF004", category="Non-Functional", subcategory="Security",
                query="Are there any security vulnerabilities or concerns in this code?",
                scenario_type="analysis", complexity="medium",
                expected_elements=["input validation", "string", "console"],
                description="Tests security analysis"
            ),
            TestQuery(
                id="NF005", category="Non-Functional", subcategory="Maintainability",
                query="How maintainable is this codebase? What makes it easy or hard to maintain?",
                scenario_type="analysis", complexity="complex",
                expected_elements=["interfaces", "separation", "naming", "structure"],
                description="Tests maintainability assessment"
            ),
            TestQuery(
                id="NF006", category="Non-Functional", subcategory="Testing",
                query="What testing strategy would be appropriate for this codebase? Identify testable components.",
                scenario_type="analysis", complexity="medium",
                expected_elements=["IWorker", "INotifier", "WorkerFactory", "unit test"],
                description="Tests testability analysis"
            )
        ])
        
        # 4. MODIFICATION SCENARIOS - Refactoring
        queries.extend([
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
                description="Tests error handling improvement suggestions"
            ),
            TestQuery(
                id="M003", category="Modification", subcategory="Logging Integration",
                query="How would you add structured logging to this application? Show the implementation approach.",
                scenario_type="modification", complexity="medium",
                expected_elements=["ILogger", "Microsoft.Extensions.Logging", "LogLevel"],
                description="Tests logging integration suggestions"
            ),
            TestQuery(
                id="M004", category="Modification", subcategory="Configuration",
                query="How would you make this application configurable? What configuration options should be added?",
                scenario_type="modification", complexity="medium",
                expected_elements=["IConfiguration", "appsettings.json", "options"],
                description="Tests configuration enhancement suggestions"
            ),
            TestQuery(
                id="M005", category="Modification", subcategory="Dependency Injection",
                query="Refactor this code to use a proper DI container. What changes are needed?",
                scenario_type="modification", complexity="complex",
                expected_elements=["IServiceCollection", "ServiceProvider", "AddTransient"],
                description="Tests DI container integration suggestions"
            )
        ])
        
        # 5. FEATURE ADDITION SCENARIOS
        queries.extend([
            TestQuery(
                id="FA001", category="Feature Addition", subcategory="Worker Priority",
                query="Add a priority system to workers. How would you implement high, medium, low priority workers?",
                scenario_type="modification", complexity="complex",
                expected_elements=["Priority", "enum", "queue", "sorting"],
                description="Tests feature addition planning"
            ),
            TestQuery(
                id="FA002", category="Feature Addition", subcategory="Worker Status",
                query="Add worker status tracking (idle, running, completed, failed). Show the implementation.",
                scenario_type="modification", complexity="medium",
                expected_elements=["WorkerStatus", "enum", "Status property"],
                description="Tests status tracking feature design"
            ),
            TestQuery(
                id="FA003", category="Feature Addition", subcategory="Result Collection",
                query="Modify workers to return results instead of just notifications. How would you implement this?",
                scenario_type="modification", complexity="medium",
                expected_elements=["WorkerResult", "generic", "return type"],
                description="Tests result handling enhancement"
            ),
            TestQuery(
                id="FA004", category="Feature Addition", subcategory="Parallel Processing",
                query="Add parallel execution of workers. What changes are needed for thread-safe operation?",
                scenario_type="modification", complexity="complex",
                expected_elements=["Parallel", "Task", "thread-safe", "ConcurrentCollection"],
                description="Tests parallelization suggestions"
            ),
            TestQuery(
                id="FA005", category="Feature Addition", subcategory="Worker Lifecycle",
                query="Add worker lifecycle management (start, pause, resume, stop). Show the implementation approach.",
                scenario_type="modification", complexity="complex",
                expected_elements=["IDisposable", "CancellationToken", "lifecycle"],
                description="Tests lifecycle management design"
            )
        ])
        
        # 6. MODERNIZATION SCENARIOS
        queries.extend([
            TestQuery(
                id="MOD001", category="Modernization", subcategory="NET 9 Features",
                query="What .NET 9 features could improve this codebase? Show specific examples.",
                scenario_type="modification", complexity="medium",
                expected_elements=["record", "init", "nullable", "global using"],
                description="Tests modern .NET feature suggestions"
            ),
            TestQuery(
                id="MOD002", category="Modernization", subcategory="Design Patterns",
                query="Modernize this code using current design pattern best practices. What would you change?",
                scenario_type="modification", complexity="complex",
                expected_elements=["mediator", "command", "strategy", "builder"],
                description="Tests modern pattern application"
            ),
            TestQuery(
                id="MOD003", category="Modernization", subcategory="API Design",
                query="Convert this to a REST API. What would the API design look like?",
                scenario_type="modification", complexity="complex",
                expected_elements=["Controller", "POST", "GET", "endpoint"],
                description="Tests API conversion suggestions"
            ),
            TestQuery(
                id="MOD004", category="Modernization", subcategory="Cloud Native",
                query="How would you make this application cloud-native and containerizable?",
                scenario_type="modification", complexity="complex",
                expected_elements=["Docker", "health check", "configuration", "stateless"],
                description="Tests cloud-native transformation"
            ),
            TestQuery(
                id="MOD005", category="Modernization", subcategory="Reactive Patterns",
                query="Implement reactive programming patterns. How would you use observables and streams?",
                scenario_type="modification", complexity="complex",
                expected_elements=["IObservable", "reactive", "stream", "subscribe"],
                description="Tests reactive programming suggestions"
            )
        ])
        
        # 7. BUG ANALYSIS AND FIXES
        queries.extend([
            TestQuery(
                id="BUG001", category="Bug Analysis", subcategory="Null Reference",
                query="Find potential null reference exceptions in this code. What fixes are needed?",
                scenario_type="modification", complexity="medium",
                expected_elements=["null check", "ArgumentNullException", "?.", "!"],
                description="Tests null safety analysis"
            ),
            TestQuery(
                id="BUG002", category="Bug Analysis", subcategory="Resource Leaks",
                query="Identify potential resource leaks and memory issues. How would you fix them?",
                scenario_type="modification", complexity="medium",
                expected_elements=["IDisposable", "using", "GC", "memory"],
                description="Tests resource management analysis"
            ),
            TestQuery(
                id="BUG003", category="Bug Analysis", subcategory="Concurrency Issues",
                query="What concurrency issues could occur if this code runs in a multi-threaded environment?",
                scenario_type="modification", complexity="complex",
                expected_elements=["thread-safe", "lock", "concurrent", "race condition"],
                description="Tests concurrency analysis"
            )
        ])
        
        # 8. INTEGRATION SCENARIOS
        queries.extend([
            TestQuery(
                id="INT001", category="Integration", subcategory="Database Integration",
                query="How would you add database persistence to track worker execution history?",
                scenario_type="modification", complexity="complex",
                expected_elements=["Entity Framework", "DbContext", "repository", "database"],
                description="Tests database integration planning"
            ),
            TestQuery(
                id="INT002", category="Integration", subcategory="Message Queue",
                query="Integrate a message queue for worker communication. What would the implementation look like?",
                scenario_type="modification", complexity="complex",
                expected_elements=["message queue", "publisher", "subscriber", "broker"],
                description="Tests messaging system integration"
            ),
            TestQuery(
                id="INT003", category="Integration", subcategory="External API",
                query="How would you integrate external APIs for worker data sources?",
                scenario_type="modification", complexity="medium",
                expected_elements=["HttpClient", "API", "endpoint", "serialization"],
                description="Tests external API integration"
            )
        ])
        
        return queries
    
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
                    "max_vector_results": 15,
                    "max_cpg_results": 20,
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
            
            # Extract metrics - handle nested structure
            # Steps are nested under "results"
            results = result_data.get("results", {})
            steps = results.get("steps", {})
            vector_step = steps.get("1_vector_search", {})
            cypher_step = steps.get("3_cypher_generation", {})
            cpg_step = steps.get("4_cpg_queries", {})
            synthesis_step = steps.get("5_synthesis", {})
            
            # Count elements found
            found_elements = []
            response_lower = content_text.lower()
            for element in test_query.expected_elements:
                if element.lower() in response_lower:
                    found_elements.append(element)
            
            # Assess synthesis quality based on response completeness and relevance
            synthesis_quality = self._assess_synthesis_quality(content_text, test_query)
            
            return QueryResult(
                query_id=test_query.id,
                success=True,
                response_time_ms=response_time_ms,
                token_usage=None,  # Would need to extract from LLM metadata
                cost_estimate=0.0,  # Would need to extract from LLM metadata
                vector_results_count=len(vector_step.get("results", [])),
                cypher_queries_generated=len(cypher_step.get("queries", [])),
                successful_cypher_queries=len([q for q in cpg_step.get("results", []) if q.get("status") == "success"]),
                found_elements=found_elements,
                response_content=content_text,
                error_message=None,
                llm_filtering_applied=bool(steps.get("2_llm_filtering")),
                synthesis_quality=synthesis_quality
            )
            
        except Exception as e:
            response_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Query {test_query.id} failed: {e}")
            
            return QueryResult(
                query_id=test_query.id,
                success=False,
                response_time_ms=response_time_ms,
                token_usage=None,
                cost_estimate=0.0,
                vector_results_count=0,
                cypher_queries_generated=0,
                successful_cypher_queries=0,
                found_elements=[],
                response_content="",
                error_message=str(e),
                llm_filtering_applied=False,
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
    
    async def run_comprehensive_test(self) -> BenchmarkMetrics:
        """Run the complete test suite and generate benchmarks."""
        logger.info("Starting comprehensive MCP test suite...")
        self.start_time = datetime.now()
        
        # Setup session
        await self.setup_session()
        
        # Define test queries
        self.test_queries = self.define_test_queries()
        logger.info(f"Defined {len(self.test_queries)} test queries")
        
        # Execute all queries
        for query in self.test_queries:
            result = await self.execute_query(query)
            self.results.append(result)
            
            # Brief pause between queries to avoid overwhelming the server
            await asyncio.sleep(1)
        
        self.end_time = datetime.now()
        
        # Calculate benchmarks
        benchmarks = self._calculate_benchmarks()
        
        # Save results
        await self._save_results(benchmarks)
        
        logger.info("✅ Comprehensive test suite completed")
        return benchmarks
    
    def _calculate_benchmarks(self) -> BenchmarkMetrics:
        """Calculate comprehensive benchmark metrics."""
        successful_results = [r for r in self.results if r.success]
        
        # Basic metrics
        total_queries = len(self.results)
        successful_queries = len(successful_results)
        success_rate = successful_queries / total_queries if total_queries > 0 else 0
        
        # Response time metrics
        response_times = [r.response_time_ms for r in successful_results]
        avg_response_time = statistics.mean(response_times) if response_times else 0
        
        # Vector search accuracy (percentage of queries that found expected elements)
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
                "element_detection_rate": statistics.mean([
                    len(r.found_elements) / len(next(q for q in category_queries if q.id == r.query_id).expected_elements)
                    for r in category_successful
                    if next(q for q in category_queries if q.id == r.query_id).expected_elements
                ]) if category_successful else 0
            }
        
        return BenchmarkMetrics(
            total_queries=total_queries,
            successful_queries=successful_queries,
            average_response_time_ms=avg_response_time,
            total_cost=sum(r.cost_estimate for r in successful_results),
            vector_search_accuracy=vector_accuracy,
            cypher_generation_success_rate=cypher_success_rate,
            element_detection_accuracy=vector_accuracy,
            synthesis_quality_distribution=quality_dist,
            category_performance=category_performance
        )
    
    async def _save_results(self, benchmarks: BenchmarkMetrics):
        """Save detailed results and generate markdown report."""
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
        
        results_file = f"/opt/genpod/comprehensive_test_results_{timestamp}.json"
        with open(results_file, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"✓ Raw results saved to {results_file}")
        
        # Generate markdown report
        await self._generate_markdown_report(benchmarks, timestamp)
    
    async def _generate_markdown_report(self, benchmarks: BenchmarkMetrics, timestamp: str):
        """Generate detailed markdown benchmark report."""
        report_file = f"/opt/genpod/MCP_Comprehensive_Benchmark_Report_{timestamp}.md"
        
        # Generate the report content (will be implemented in the next step)
        report_content = self._create_markdown_content(benchmarks, timestamp)
        
        with open(report_file, 'w') as f:
            f.write(report_content)
        
        logger.info(f"✓ Markdown report generated: {report_file}")
    
    def _create_markdown_content(self, benchmarks: BenchmarkMetrics, timestamp: str) -> str:
        """Create the detailed markdown report content based on actual test results."""
        duration = (self.end_time - self.start_time).total_seconds() / 60
        
        # Calculate actual success rates and metrics from results
        overall_success_rate = benchmarks.successful_queries / benchmarks.total_queries if benchmarks.total_queries > 0 else 0
        
        report = f"""# Comprehensive MCP Code Analysis Server Benchmark Report

**Generated:** {timestamp}  
**Test Duration:** {duration:.1f} minutes  
**Project Analyzed:** HelloWorldApp (.NET 9.0 Console Application)  
**MCP Server:** Project Analyzer with Vector Search + CPG Integration  

## Executive Summary

This comprehensive test suite evaluated the MCP server's ability to analyze and suggest modifications for the HelloWorldApp codebase across {len(set(q.category for q in self.test_queries))} categories with {benchmarks.total_queries} total test queries.

### Key Metrics

| Metric | Value | Status |
|--------|-------|--------|
| **Total Test Queries** | {benchmarks.total_queries} | ✅ |
| **Successful Queries** | {benchmarks.successful_queries} | {'✅' if overall_success_rate > 0.9 else '⚠️' if overall_success_rate > 0.8 else '❌'} |
| **Success Rate** | {(overall_success_rate * 100):.1f}% | {'✅' if overall_success_rate > 0.9 else '⚠️' if overall_success_rate > 0.8 else '❌'} |
| **Average Response Time** | {benchmarks.average_response_time_ms:.0f}ms | {'✅' if benchmarks.average_response_time_ms < 5000 else '⚠️' if benchmarks.average_response_time_ms < 10000 else '❌'} |
| **Vector Search Accuracy** | {(benchmarks.vector_search_accuracy * 100):.1f}% | {'✅' if benchmarks.vector_search_accuracy > 0.8 else '⚠️' if benchmarks.vector_search_accuracy > 0.6 else '❌'} |
| **Cypher Generation Success** | {(benchmarks.cypher_generation_success_rate * 100):.1f}% | {'✅' if benchmarks.cypher_generation_success_rate > 0.85 else '⚠️' if benchmarks.cypher_generation_success_rate > 0.7 else '❌'} |
| **Total Estimated Cost** | ${benchmarks.total_cost:.3f} | {'✅' if benchmarks.total_cost < 2.0 else '⚠️' if benchmarks.total_cost < 5.0 else '❌'} |

### Synthesis Quality Distribution

| Quality Level | Count | Percentage |
|---------------|-------|------------|
| **Excellent** | {benchmarks.synthesis_quality_distribution['excellent']} | {(benchmarks.synthesis_quality_distribution['excellent'] / benchmarks.successful_queries * 100):.1f}% |
| **Good** | {benchmarks.synthesis_quality_distribution['good']} | {(benchmarks.synthesis_quality_distribution['good'] / benchmarks.successful_queries * 100):.1f}% |
| **Poor** | {benchmarks.synthesis_quality_distribution['poor']} | {(benchmarks.synthesis_quality_distribution['poor'] / benchmarks.successful_queries * 100):.1f}% |

## Category Performance Analysis

"""

        # Add category performance based on actual results
        for category, metrics in benchmarks.category_performance.items():
            status_icon = '✅' if metrics['success_rate'] > 0.9 else '⚠️' if metrics['success_rate'] > 0.8 else '❌'
            report += f"""
### {category} {status_icon}

| Metric | Value |
|--------|-------|
| **Queries Tested** | {metrics['total_queries']} |
| **Successful Queries** | {metrics['successful_queries']} |
| **Success Rate** | {(metrics['success_rate'] * 100):.1f}% |
| **Avg Response Time** | {metrics['avg_response_time']:.0f}ms |
| **Element Detection Rate** | {(metrics['element_detection_rate'] * 100):.1f}% |

"""

        # Add detailed results section
        report += "\n## Detailed Test Results\n\n"
        
        # Group results by category
        category_results = {}
        for query in self.test_queries:
            if query.category not in category_results:
                category_results[query.category] = []
            result = next((r for r in self.results if r.query_id == query.id), None)
            category_results[query.category].append((query, result))

        for category, query_results in category_results.items():
            successful_in_category = sum(1 for _, result in query_results if result and result.success)
            report += f"\n### {category} Results ({successful_in_category}/{len(query_results)} successful)\n\n"
            
            for query, result in query_results:
                status = "✅ PASS" if result and result.success else "❌ FAIL"
                
                report += f"**{query.id}:** {query.subcategory} {status}\n"
                report += f"*{query.scenario_type.title()} | {query.complexity.title()} complexity*\n\n"
                
                if result and result.success:
                    found_rate = f"{len(result.found_elements)}/{len(query.expected_elements)}" if query.expected_elements else "N/A"
                    report += f"- Response: {result.response_time_ms}ms | Elements found: {found_rate} | Quality: {result.synthesis_quality}\n"
                elif result:
                    report += f"- **Error:** {result.error_message}\n"
                else:
                    report += f"- **Error:** No result recorded\n"
                
                report += "\n"

        # Generate insights based on actual performance
        report += f"""
## Performance Analysis

### Component Performance Assessment

"""
        
        # Assess vector search performance
        if benchmarks.vector_search_accuracy > 0.8:
            report += "✅ **Vector Search:** Strong performance with {:.1f}% accuracy in finding expected code elements.\n".format(benchmarks.vector_search_accuracy * 100)
        elif benchmarks.vector_search_accuracy > 0.6:
            report += "⚠️ **Vector Search:** Moderate performance with {:.1f}% accuracy. Room for improvement.\n".format(benchmarks.vector_search_accuracy * 100)
        else:
            report += "❌ **Vector Search:** Low accuracy at {:.1f}%. Needs significant improvement.\n".format(benchmarks.vector_search_accuracy * 100)

        # Assess Cypher generation
        if benchmarks.cypher_generation_success_rate > 0.85:
            report += "✅ **Cypher Generation:** Excellent success rate of {:.1f}%.\n".format(benchmarks.cypher_generation_success_rate * 100)
        elif benchmarks.cypher_generation_success_rate > 0.7:
            report += "⚠️ **Cypher Generation:** Good success rate of {:.1f}% but could be improved.\n".format(benchmarks.cypher_generation_success_rate * 100)
        else:
            report += "❌ **Cypher Generation:** Low success rate of {:.1f}%. Schema alignment issues likely.\n".format(benchmarks.cypher_generation_success_rate * 100)

        # Assess response times
        if benchmarks.average_response_time_ms < 5000:
            report += "✅ **Response Time:** Fast responses averaging {:.0f}ms.\n".format(benchmarks.average_response_time_ms)
        elif benchmarks.average_response_time_ms < 10000:
            report += "⚠️ **Response Time:** Acceptable but could be faster at {:.0f}ms average.\n".format(benchmarks.average_response_time_ms)
        else:
            report += "❌ **Response Time:** Slow responses averaging {:.0f}ms. Optimization needed.\n".format(benchmarks.average_response_time_ms)

        # Category-specific insights
        report += "\n### Category-Specific Insights\n\n"
        
        best_category = max(benchmarks.category_performance.items(), key=lambda x: x[1]['success_rate'])
        worst_category = min(benchmarks.category_performance.items(), key=lambda x: x[1]['success_rate'])
        
        report += f"**Strongest Performance:** {best_category[0]} ({(best_category[1]['success_rate'] * 100):.1f}% success)\n"
        report += f"**Needs Improvement:** {worst_category[0]} ({(worst_category[1]['success_rate'] * 100):.1f}% success)\n\n"

        # Generate data-driven recommendations
        report += "## Recommendations\n\n"
        
        if overall_success_rate < 0.9:
            report += "### Immediate Actions Needed\n"
            report += f"- **Overall Success Rate ({(overall_success_rate * 100):.1f}%)** is below optimal. Focus on error handling and query reliability.\n"
        
        if benchmarks.cypher_generation_success_rate < 0.8:
            report += "- **Cypher Query Reliability:** Review schema alignment and query generation logic.\n"
        
        if benchmarks.average_response_time_ms > 5000:
            report += f"- **Performance Optimization:** Response times averaging {benchmarks.average_response_time_ms:.0f}ms need improvement.\n"

        if benchmarks.synthesis_quality_distribution['poor'] > benchmarks.successful_queries * 0.3:
            report += "- **Synthesis Quality:** Too many poor-quality responses. Enhance LLM prompts and filtering.\n"

        # Agent readiness assessment based on actual results
        report += f"""
## Agent Readiness Assessment

Based on the test results with {(overall_success_rate * 100):.1f}% success rate:

"""
        
        if overall_success_rate > 0.9:
            report += "🟢 **READY FOR PRODUCTION**: High reliability across all test scenarios.\n"
        elif overall_success_rate > 0.8:
            report += "🟡 **READY WITH MONITORING**: Good performance but requires monitoring in production.\n"
        else:
            report += "🔴 **NEEDS IMPROVEMENT**: Reliability issues must be addressed before production use.\n"

        # Add specific agent task recommendations based on category performance
        report += "\n### Recommended Agent Task Priorities\n\n"
        
        sorted_categories = sorted(benchmarks.category_performance.items(), key=lambda x: x[1]['success_rate'], reverse=True)
        
        for i, (category, metrics) in enumerate(sorted_categories[:3]):
            priority = ["High", "Medium", "Low"][i] if i < 3 else "Low"
            report += f"**{priority} Priority:** {category} tasks ({(metrics['success_rate'] * 100):.1f}% reliability)\n"

        report += f"""

---

**Test Completion:** {timestamp}  
**Total Execution Time:** {duration:.1f} minutes  
**System Status:** {'🟢 Operational' if overall_success_rate > 0.8 else '🟡 Monitoring Required' if overall_success_rate > 0.6 else '🔴 Needs Attention'}
"""

        return report
    
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
    test_suite = ComprehensiveMCPTestSuite()
    
    try:
        benchmarks = await test_suite.run_comprehensive_test()
        
        print(f"\n{'='*60}")
        print("COMPREHENSIVE MCP TEST SUITE RESULTS")
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
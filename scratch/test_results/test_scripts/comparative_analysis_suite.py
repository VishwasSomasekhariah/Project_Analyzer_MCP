#!/usr/bin/env python3
"""
Comparative Analysis Test Suite

This test suite runs ALL 37 test queries from the comprehensive test suite against three different approaches:
1. Vector-only search (codebase-vector-rag query)
2. CPG-only search (project-analyzer query)  
3. Comprehensive analysis (comprehensive_code_analysis)

Results are saved to CSV/Excel for detailed comparative analysis.
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
import os
import pandas as pd
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add the test scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent / "test_results" / "test_scripts"))

from mcp_use import MCPClient

# Import OpenAI for direct LLM calls
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@dataclass
class ComparativeResult:
    """Results from comparative analysis across all three approaches."""
    # Query metadata
    query_id: str
    user_query: str
    query_category: str
    query_subcategory: str
    scenario_type: str
    timestamp: str
    
    # Vector-only results
    vector_status: str
    vector_response: str
    vector_response_time_ms: int
    vector_error: str
    
    # CPG-only results
    cpg_status: str
    cpg_response: str
    cpg_response_time_ms: int
    cpg_error: str
    
    # Comprehensive results
    comprehensive_status: str
    comprehensive_response: str
    comprehensive_response_time_ms: int
    comprehensive_error: str

class ComparativeAnalyzer:
    def __init__(self, test_scenario_filter=None):
        """
        Initialize the comparative analyzer.
        
        Args:
            test_scenario_filter: Can be:
                - None: Run all 37 scenarios
                - int: Run first N scenarios (e.g., 5)
                - list: Run specific scenario IDs (e.g., ['T001', 'T002', 'F001'])
                - str: Run scenarios matching category (e.g., 'Technical')
        """
        self.results = []
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.project_path = "/opt/HelloWorldApp"
        self.collection_name = "helloworldapp-fresh-test"
        self.neo4j_config = "/opt/genpod/neo4j_config.json"
        self.test_scenario_filter = test_scenario_filter
        
        # Use the comprehensive schema from the actual schema file
        self.graph_schema_prompt = self.get_comprehensive_schema_prompt()
        
    def define_all_test_queries(self) -> List[Dict]:
        """Define ALL 37 test queries from the comprehensive test suite."""
        return [
            # Technical Analysis (5 queries)
            {
                "id": "T001",
                "category": "Technical",
                "subcategory": "Architecture",
                "query": "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?",
                "scenario_type": "analysis"
            },
            {
                "id": "T002",
                "category": "Technical",
                "subcategory": "Design Patterns",
                "query": "Find all classes in the HelloWorldApp that implement specific design patterns like Factory, Observer, or Strategy patterns.",
                "scenario_type": "analysis"
            },
            {
                "id": "T003",
                "category": "Technical",
                "subcategory": "Dependencies",
                "query": "What are the dependencies and relationships between different classes in the HelloWorldApp?",
                "scenario_type": "analysis"
            },
            {
                "id": "T004",
                "category": "Technical",
                "subcategory": "Class Hierarchy",
                "query": "Show me the class hierarchy and inheritance relationships in the HelloWorldApp.",
                "scenario_type": "analysis"
            },
            {
                "id": "T005",
                "category": "Technical",
                "subcategory": "Method Analysis",
                "query": "Analyze the methods in the HelloWorldApp. Which methods are most complex or important?",
                "scenario_type": "analysis"
            },
            
            # Functional Analysis (5 queries)
            {
                "id": "F001",
                "category": "Functional",
                "subcategory": "Business Logic",
                "query": "Identify the core business logic in the HelloWorldApp. What does the application actually do?",
                "scenario_type": "analysis"
            },
            {
                "id": "F002",
                "category": "Functional",
                "subcategory": "Data Flow",
                "query": "Trace the data flow through the HelloWorldApp. How does data move between components?",
                "scenario_type": "analysis"
            },
            {
                "id": "F003",
                "category": "Functional",
                "subcategory": "Worker Coordination",
                "query": "How do the different workers in the HelloWorldApp coordinate and communicate with each other?",
                "scenario_type": "analysis"
            },
            {
                "id": "F004",
                "category": "Functional",
                "subcategory": "Factory Usage",
                "query": "How is the factory pattern used in the HelloWorldApp? Show me the factory implementations.",
                "scenario_type": "analysis"
            },
            {
                "id": "F005",
                "category": "Functional",
                "subcategory": "Notification System",
                "query": "Analyze the notification system in the HelloWorldApp. How do components notify each other?",
                "scenario_type": "analysis"
            },
            
            # Non-Functional Analysis (6 queries)
            {
                "id": "NF001",
                "category": "Non-Functional",
                "subcategory": "Error Handling",
                "query": "Analyze the error handling patterns in the HelloWorldApp. Are there any potential issues or improvements?",
                "scenario_type": "analysis"
            },
            {
                "id": "NF002",
                "category": "Non-Functional",
                "subcategory": "Code Quality",
                "query": "Assess the code quality of the HelloWorldApp. Are there any code smells or areas for improvement?",
                "scenario_type": "analysis"
            },
            {
                "id": "NF003",
                "category": "Non-Functional",
                "subcategory": "Performance",
                "query": "Identify potential performance bottlenecks in the HelloWorldApp. What could be optimized?",
                "scenario_type": "analysis"
            },
            {
                "id": "NF004",
                "category": "Non-Functional",
                "subcategory": "Security",
                "query": "Are there any security concerns or vulnerabilities in the HelloWorldApp code?",
                "scenario_type": "analysis"
            },
            {
                "id": "NF005",
                "category": "Non-Functional",
                "subcategory": "Maintainability",
                "query": "How maintainable is the HelloWorldApp code? What would make it easier to maintain?",
                "scenario_type": "analysis"
            },
            {
                "id": "NF006",
                "category": "Non-Functional",
                "subcategory": "Testing",
                "query": "What testing strategies would be appropriate for the HelloWorldApp? Where should tests be added?",
                "scenario_type": "analysis"
            },
            
            # Modification Scenarios (5 queries)
            {
                "id": "M001",
                "category": "Modification",
                "subcategory": "Async Refactoring",
                "query": "How would you refactor the HelloWorldApp to use async/await patterns for better performance?",
                "scenario_type": "modification"
            },
            {
                "id": "M002",
                "category": "Modification",
                "subcategory": "Error Handling",
                "query": "How would you improve error handling in the HelloWorldApp with try-catch blocks and logging?",
                "scenario_type": "modification"
            },
            {
                "id": "M003",
                "category": "Modification",
                "subcategory": "Logging Integration",
                "query": "How would you integrate comprehensive logging throughout the HelloWorldApp?",
                "scenario_type": "modification"
            },
            {
                "id": "M004",
                "category": "Modification",
                "subcategory": "Configuration",
                "query": "How would you add configuration management to the HelloWorldApp?",
                "scenario_type": "modification"
            },
            {
                "id": "M005",
                "category": "Modification",
                "subcategory": "Dependency Injection",
                "query": "How would you implement dependency injection in the HelloWorldApp?",
                "scenario_type": "modification"
            },
            
            # Feature Addition (5 queries)
            {
                "id": "FA001",
                "category": "Feature Addition",
                "subcategory": "Worker Priority",
                "query": "How would you add priority levels to workers in the HelloWorldApp?",
                "scenario_type": "modification"
            },
            {
                "id": "FA002",
                "category": "Feature Addition",
                "subcategory": "Worker Status",
                "query": "How would you add status tracking for workers in the HelloWorldApp?",
                "scenario_type": "modification"
            },
            {
                "id": "FA003",
                "category": "Feature Addition",
                "subcategory": "Result Collection",
                "query": "How would you implement result collection and aggregation in the HelloWorldApp?",
                "scenario_type": "modification"
            },
            {
                "id": "FA004",
                "category": "Feature Addition",
                "subcategory": "Parallel Processing",
                "query": "How would you add parallel processing capabilities to the HelloWorldApp?",
                "scenario_type": "modification"
            },
            {
                "id": "FA005",
                "category": "Feature Addition",
                "subcategory": "Worker Lifecycle",
                "query": "How would you implement worker lifecycle management in the HelloWorldApp?",
                "scenario_type": "modification"
            },
            
            # Modernization (5 queries)
            {
                "id": "MOD001",
                "category": "Modernization",
                "subcategory": "NET 9 Features",
                "query": "How would you modernize the HelloWorldApp to use .NET 9 features and improvements?",
                "scenario_type": "modification"
            },
            {
                "id": "MOD002",
                "category": "Modernization",
                "subcategory": "Design Patterns",
                "query": "How would you refactor the HelloWorldApp to use modern design patterns like CQRS or mediator?",
                "scenario_type": "modification"
            },
            {
                "id": "MOD003",
                "category": "Modernization",
                "subcategory": "API Design",
                "query": "How would you convert the HelloWorldApp into a modern REST API or GraphQL service?",
                "scenario_type": "modification"
            },
            {
                "id": "MOD004",
                "category": "Modernization",
                "subcategory": "Cloud Native",
                "query": "How would you make the HelloWorldApp cloud-native with containerization and microservices?",
                "scenario_type": "modification"
            },
            {
                "id": "MOD005",
                "category": "Modernization",
                "subcategory": "Reactive Patterns",
                "query": "How would you implement reactive programming patterns in the HelloWorldApp?",
                "scenario_type": "modification"
            },
            
            # Bug Analysis (3 queries)
            {
                "id": "BUG001",
                "category": "Bug Analysis",
                "subcategory": "Null Reference",
                "query": "Find potential null reference exceptions in the HelloWorldApp code.",
                "scenario_type": "modification"
            },
            {
                "id": "BUG002",
                "category": "Bug Analysis",
                "subcategory": "Resource Leaks",
                "query": "Identify potential resource leaks or disposal issues in the HelloWorldApp.",
                "scenario_type": "modification"
            },
            {
                "id": "BUG003",
                "category": "Bug Analysis",
                "subcategory": "Concurrency Issues",
                "query": "Find potential concurrency issues or race conditions in the HelloWorldApp.",
                "scenario_type": "modification"
            },
            
            # Integration (3 queries)
            {
                "id": "INT001",
                "category": "Integration",
                "subcategory": "Database Integration",
                "query": "How would you integrate a database into the HelloWorldApp?",
                "scenario_type": "modification"
            },
            {
                "id": "INT002",
                "category": "Integration",
                "subcategory": "Message Queue",
                "query": "How would you integrate message queuing into the HelloWorldApp?",
                "scenario_type": "modification"
            },
            {
                "id": "INT003",
                "category": "Integration",
                "subcategory": "External API",
                "query": "How would you integrate external API calls into the HelloWorldApp?",
                "scenario_type": "modification"
            }
        ]
    
    def get_filtered_test_queries(self) -> List[Dict]:
        """Get test queries based on the filter criteria."""
        all_queries = self.define_all_test_queries()
        
        if self.test_scenario_filter is None:
            return all_queries
        
        if isinstance(self.test_scenario_filter, int):
            return all_queries[:self.test_scenario_filter]
        
        if isinstance(self.test_scenario_filter, list):
            return [q for q in all_queries if q["id"] in self.test_scenario_filter]
        
        if isinstance(self.test_scenario_filter, str):
            return [q for q in all_queries if q["category"] == self.test_scenario_filter]
        
        return all_queries
    
    async def run_vector_only_query(self, query: str) -> Dict[str, Any]:
        """Run query using codebase-vector-rag only."""
        start_time = time.time()
        
        try:
            cmd = [
                "codebase-vector-rag", "query", query,
                "--collection-name", self.collection_name,
                "--max-results", "15"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            return {
                "status": "success" if result.returncode == 0 else "error",
                "response": result.stdout if result.returncode == 0 else result.stderr,
                "response_time_ms": response_time_ms,
                "error": result.stderr if result.returncode != 0 else ""
            }
                
        except Exception as e:
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
    
    def get_comprehensive_schema_prompt(self) -> str:
        """Return comprehensive schema prompt using NodeDefinitions and EdgeDefinitions."""
        return """
Neo4j Code Property Graph Schema for HelloWorldApp (.NET):

NODE DEFINITIONS:
Type: Classes, interfaces, structs, enums - name, type_kind, access_modifier, file_path, fields, base_list, body
Function: Methods, functions, constructors - name, body, parameters, return_type, file_path, modifier
Variable: Local variables, fields, parameters - name, type_kind, initial_value, access_modifier, file_path
File: Source files - name, file_path, version
Namespace: Code organization - name, path, file_path, body

EDGE DEFINITIONS:
DEFINED_IN: (Type|Function|Variable)-[:DEFINED_IN]->(File|Namespace)
CONTAINS: (Type|File|Namespace)-[:CONTAINS]->(Function|Variable|Type)
IMPLEMENTS: (Type)-[:IMPLEMENTS]->(Type) // class implements interface
INHERITS_FROM: (Type)-[:INHERITS_FROM]->(Type) // class extends base
CALLS: (Function)-[:CALLS]->(Function)
HAS_PARAMETER: (Function)-[:HAS_PARAMETER]->(Variable)
DECLARED_IN: (Variable)-[:DECLARED_IN]->(Function|Type|Namespace)

HELLOWORLDAPP CONTEXT:
.NET console app with design patterns:
- Factory: WorkerFactory.CreateWorkers() creates IWorker implementations
- Observer: Manager implements INotifier, workers call back via Notify()
- Strategy: WorkerA, WorkerB, WorkerC implement IWorker.Process() differently
- Key Types: Manager, WorkerFactory, WorkerA, WorkerB, WorkerC, IWorker, INotifier
"""

    async def generate_cypher_queries_with_llm(self, user_query: str) -> list:
        """Generate Cypher queries using GPT-4o directly (mimicking LLM service)."""
        if not OpenAI:
            return [{"query": "MATCH (t:Type)-[:DEFINED_IN]->(f:File) WHERE t.name CONTAINS 'Factory' RETURN t.name, f.file_path LIMIT 20", "purpose": "Find Factory classes"}]
        
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        system_prompt = f"""You are an expert Neo4j Cypher query generator for code analysis.

{self.graph_schema_prompt}

Generate 1-3 Cypher queries that:
1. Are syntactically correct Neo4j Cypher
2. Return meaningful results for the user's question
3. Include appropriate LIMIT clauses (10-20 results)
4. Use relevant WHERE clauses for filtering
5. Focus on the HelloWorldApp codebase

Return ONLY a JSON array: [{{"query": "MATCH...", "purpose": "description"}}]"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-2024-08-06",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"User Query: {user_query}"}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            response_text = response.choices[0].message.content.strip()
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                return [{"query": "MATCH (t:Type)-[:DEFINED_IN]->(f:File) WHERE t.name CONTAINS 'Factory' RETURN t.name, f.file_path LIMIT 20", "purpose": "Find Factory classes"}]
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return [{"query": "MATCH (t:Type)-[:DEFINED_IN]->(f:File) WHERE t.name CONTAINS 'Factory' RETURN t.name, f.file_path LIMIT 20", "purpose": "Find Factory classes"}]

    async def run_cpg_only_query(self, query: str) -> Dict[str, Any]:
        """Run query using CPG-only approach with dynamic Cypher generation."""
        start_time = time.time()
        
        try:
            # Generate Cypher queries using LLM
            cypher_queries = await self.generate_cypher_queries_with_llm(query)
            
            # Execute generated Cypher queries
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("project-analyzer-server")
            
            cpg_results = []
            for query_obj in cypher_queries:
                result = await session.call_tool(
                    "query_cpg_only",
                    {
                        "cypher_query": query_obj["query"],
                        "config_path": self.neo4j_config,
                        "max_results": 20
                    }
                )
                
                result_content = result.content[0] if isinstance(result.content, list) else result.content
                content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
                
                cpg_results.append({
                    "cypher_query": query_obj["query"],
                    "purpose": query_obj.get("purpose", "Generated query"),
                    "result": content_text
                })
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            combined_response = {
                "status": "success",
                "approach": "cpg_only_with_dynamic_cypher",
                "user_query": query,
                "queries_generated": len(cypher_queries),
                "results": cpg_results
            }
            
            return {
                "status": "success",
                "response": json.dumps(combined_response, indent=2),
                "response_time_ms": response_time_ms,
                "error": ""
            }
                
        except Exception as e:
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
    
    async def run_comprehensive_query(self, query: str) -> Dict[str, Any]:
        """Run query using comprehensive_code_analysis."""
        start_time = time.time()
        
        try:
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("project-analyzer-server")
            
            result = await session.call_tool(
                "comprehensive_code_analysis",
                {
                    "user_query": query,
                    "project_path": self.project_path,
                    "collection_name": self.collection_name,
                    "max_vector_results": 15,
                    "max_cpg_results": 20,
                    "use_llm_filtering": True,
                    "neo4j_config": self.neo4j_config
                }
            )
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Parse response
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            if hasattr(result_content, 'text'):
                content_text = result_content.text
            else:
                content_text = str(result_content)
            
            return {
                "status": "success",
                "response": content_text,
                "response_time_ms": response_time_ms,
                "error": ""
            }
                
        except Exception as e:
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
    
    async def run_comparative_analysis(self):
        """Run the complete comparative analysis."""
        queries = self.get_filtered_test_queries()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logger.info(f"Starting comparative analysis with {len(queries)} queries...")
        if self.test_scenario_filter is not None:
            logger.info(f"Filter applied: {self.test_scenario_filter}")
        
        for i, query_def in enumerate(queries, 1):
            logger.info(f"Processing query {i}/{len(queries)}: {query_def['id']}")
            
            # Run all three approaches
            logger.info(f"  - Running vector-only query...")
            vector_result = await self.run_vector_only_query(query_def["query"])
            
            logger.info(f"  - Running CPG-only query...")
            cpg_result = await self.run_cpg_only_query(query_def["query"])
            
            logger.info(f"  - Running comprehensive query...")
            comprehensive_result = await self.run_comprehensive_query(query_def["query"])
            
            # Create comparative result
            result = ComparativeResult(
                query_id=query_def["id"],
                user_query=query_def["query"],
                query_category=query_def["category"],
                query_subcategory=query_def["subcategory"],
                scenario_type=query_def["scenario_type"],
                timestamp=timestamp,
                
                # Vector results
                vector_status=vector_result["status"],
                vector_response=vector_result["response"],
                vector_response_time_ms=vector_result["response_time_ms"],
                vector_error=vector_result["error"],
                
                # CPG results
                cpg_status=cpg_result["status"],
                cpg_response=cpg_result["response"],
                cpg_response_time_ms=cpg_result["response_time_ms"],
                cpg_error=cpg_result["error"],
                
                # Comprehensive results
                comprehensive_status=comprehensive_result["status"],
                comprehensive_response=comprehensive_result["response"],
                comprehensive_response_time_ms=comprehensive_result["response_time_ms"],
                comprehensive_error=comprehensive_result["error"]
            )
            
            self.results.append(result)
            logger.info(f"✓ Completed {query_def['id']} - V:{vector_result['status']} C:{cpg_result['status']} X:{comprehensive_result['status']}")
        
        # Save results
        self.save_results(timestamp)
        logger.info(f"✅ Comparative analysis completed. Results saved with timestamp {timestamp}")
    
    def save_results(self, timestamp: str):
        """Save results to CSV and Excel files."""
        
        # Convert to DataFrame
        df = pd.DataFrame([asdict(result) for result in self.results])
        
        # Save to CSV
        csv_path = f"/opt/genpod/comparative_analysis_{timestamp}.csv"
        df.to_csv(csv_path, index=False)
        
        # Save to Excel
        excel_path = f"/opt/genpod/comparative_analysis_{timestamp}.xlsx"
        df.to_excel(excel_path, index=False)
        
        logger.info(f"✓ Results saved to {csv_path} and {excel_path}")

async def main():
    analyzer = ComparativeAnalyzer()
    await analyzer.run_comparative_analysis()

if __name__ == "__main__":
    asyncio.run(main())
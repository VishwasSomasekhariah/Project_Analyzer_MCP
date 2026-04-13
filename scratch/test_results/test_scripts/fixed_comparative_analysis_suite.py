#!/usr/bin/env python3
"""
Fixed Comparative Analysis Suite

This fixed version addresses the CPG query generation issues:
1. Uses proper database schema based on actual data
2. Implements category-specific fallback queries
3. Fixes LLM query generation with better prompts
4. Handles JSON parsing errors gracefully
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
import os
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

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

class FixedComparativeAnalyzer:
    def __init__(self, test_scenario_filter=None):
        """
        Initialize the fixed comparative analyzer.
        
        Args:
            test_scenario_filter: Can be:
                - None: Run all 37 scenarios
                - int: Run first N scenarios (e.g., 5)
                - list: Run specific scenario IDs (e.g., ['T001', 'T002', 'F001'])
                - str: Run scenarios matching category (e.g., 'Technical')
        """
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.project_path = "/opt/HelloWorldApp"
        self.collection_name = "helloworldapp-fresh-test"
        self.neo4j_config = "/opt/genpod/neo4j_config.json"
        self.test_scenario_filter = test_scenario_filter
        
        # Use the comprehensive schema based on actual database structure
        self.graph_schema_prompt = self.get_comprehensive_schema_prompt()
        
        # Define category-specific fallback queries
        self.fallback_queries = {
            "Technical": [
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 15",
                    "purpose": "Find all classes and interfaces for technical analysis"
                },
                {
                    "query": "MATCH (t1:Type)-[r:IMPLEMENTS]->(t2:Type) RETURN t1.name, t2.name, t1.file_path LIMIT 10",
                    "purpose": "Find implementation relationships"
                }
            ],
            "Functional": [
                {
                    "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
                    "purpose": "Find all functions for functional analysis"
                },
                {
                    "query": "MATCH (f1:Function)-[r:CALLS]->(f2:Function) RETURN f1.name, f2.name, f1.file_path LIMIT 10",
                    "purpose": "Find function call relationships"
                }
            ],
            "Non-Functional": [
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind = 'class' RETURN t.name, t.file_path LIMIT 15",
                    "purpose": "Find all classes for quality analysis"
                },
                {
                    "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
                    "purpose": "Find all functions for performance analysis"
                }
            ],
            "Modification": [
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind = 'class' RETURN t.name, t.file_path LIMIT 15",
                    "purpose": "Find classes for modification analysis"
                },
                {
                    "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
                    "purpose": "Find functions for modification analysis"
                }
            ],
            "Feature Addition": [
                {
                    "query": "MATCH (t:Type) WHERE t.name CONTAINS 'Factory' OR t.name CONTAINS 'Worker' RETURN t.name, t.file_path LIMIT 15",
                    "purpose": "Find worker-related types for feature addition"
                },
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind = 'interface' RETURN t.name, t.file_path LIMIT 10",
                    "purpose": "Find interfaces for extension"
                }
            ],
            "Modernization": [
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind = 'class' RETURN t.name, t.file_path LIMIT 15",
                    "purpose": "Find classes for modernization"
                },
                {
                    "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
                    "purpose": "Find functions for async conversion"
                }
            ],
            "Bug Analysis": [
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind = 'class' RETURN t.name, t.file_path LIMIT 15",
                    "purpose": "Find classes for bug analysis"
                },
                {
                    "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
                    "purpose": "Find functions for bug detection"
                }
            ],
            "Integration": [
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 15",
                    "purpose": "Find types for integration analysis"
                },
                {
                    "query": "MATCH (t1:Type)-[r:REFERENCES]->(t2:Type) RETURN t1.name, t2.name, t1.file_path LIMIT 10",
                    "purpose": "Find type dependencies"
                }
            ]
        }
        
        # Test scenarios
        self.test_scenarios = [
            # Technical Category
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
                "query": "Analyze the class hierarchy and inheritance structure in the HelloWorldApp.",
                "scenario_type": "analysis"
            },
            {
                "id": "T005",
                "category": "Technical",
                "subcategory": "Method Analysis",
                "query": "What are the key methods in the HelloWorldApp and their cyclomatic complexity?",
                "scenario_type": "analysis"
            },
            
            # Functional Category
            {
                "id": "F001",
                "category": "Functional",
                "subcategory": "Business Logic",
                "query": "What is the core business logic of the HelloWorldApp? How do the workers coordinate?",
                "scenario_type": "analysis"
            },
            {
                "id": "F002",
                "category": "Functional",
                "subcategory": "Data Flow",
                "query": "Trace the data flow through the HelloWorldApp from Manager to Workers.",
                "scenario_type": "analysis"
            },
            {
                "id": "F003",
                "category": "Functional",
                "subcategory": "Worker Coordination",
                "query": "How do the workers communicate with the Manager in the HelloWorldApp?",
                "scenario_type": "analysis"
            },
            {
                "id": "F004",
                "category": "Functional",
                "subcategory": "Factory Usage",
                "query": "How is the WorkerFactory used in the HelloWorldApp and what does it create?",
                "scenario_type": "analysis"
            },
            {
                "id": "F005",
                "category": "Functional",
                "subcategory": "Notification System",
                "query": "How does the notification system work in the HelloWorldApp?",
                "scenario_type": "analysis"
            },
            
            # Non-Functional Category
            {
                "id": "NF001",
                "category": "Non-Functional",
                "subcategory": "Error Handling",
                "query": "What error handling mechanisms are present in the HelloWorldApp?",
                "scenario_type": "analysis"
            },
            {
                "id": "NF002",
                "category": "Non-Functional",
                "subcategory": "Code Quality",
                "query": "Assess the code quality of the HelloWorldApp. What are the main issues?",
                "scenario_type": "analysis"
            },
            {
                "id": "NF003",
                "category": "Non-Functional",
                "subcategory": "Performance",
                "query": "What are the performance characteristics and potential bottlenecks in the HelloWorldApp?",
                "scenario_type": "analysis"
            },
            {
                "id": "NF004",
                "category": "Non-Functional",
                "subcategory": "Security",
                "query": "What security vulnerabilities or concerns exist in the HelloWorldApp?",
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
            
            # Modification Scenarios
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
            
            # Feature Addition Scenarios
            {
                "id": "FA001",
                "category": "Feature Addition",
                "subcategory": "Worker Priority",
                "query": "How would you add a priority system to the workers in the HelloWorldApp?",
                "scenario_type": "feature_addition"
            },
            {
                "id": "FA002",
                "category": "Feature Addition",
                "subcategory": "Worker Status",
                "query": "How would you add worker status tracking to the HelloWorldApp?",
                "scenario_type": "feature_addition"
            },
            {
                "id": "FA003",
                "category": "Feature Addition",
                "subcategory": "Result Collection",
                "query": "How would you add result collection and aggregation to the HelloWorldApp?",
                "scenario_type": "feature_addition"
            },
            {
                "id": "FA004",
                "category": "Feature Addition",
                "subcategory": "Parallel Processing",
                "query": "How would you add parallel processing capabilities to the HelloWorldApp?",
                "scenario_type": "feature_addition"
            },
            {
                "id": "FA005",
                "category": "Feature Addition",
                "subcategory": "Worker Lifecycle",
                "query": "How would you add worker lifecycle management to the HelloWorldApp?",
                "scenario_type": "feature_addition"
            },
            
            # Modernization Scenarios
            {
                "id": "MOD001",
                "category": "Modernization",
                "subcategory": "NET 9 Features",
                "query": "How would you modernize the HelloWorldApp to use .NET 9 features?",
                "scenario_type": "modernization"
            },
            {
                "id": "MOD002",
                "category": "Modernization",
                "subcategory": "Modern Patterns",
                "query": "How would you update the HelloWorldApp to use modern design patterns?",
                "scenario_type": "modernization"
            },
            {
                "id": "MOD003",
                "category": "Modernization",
                "subcategory": "API Conversion",
                "query": "How would you convert the HelloWorldApp to a web API?",
                "scenario_type": "modernization"
            },
            {
                "id": "MOD004",
                "category": "Modernization",
                "subcategory": "Cloud Native",
                "query": "How would you make the HelloWorldApp cloud-native?",
                "scenario_type": "modernization"
            },
            {
                "id": "MOD005",
                "category": "Modernization",
                "subcategory": "Reactive Patterns",
                "query": "How would you implement reactive programming patterns in the HelloWorldApp?",
                "scenario_type": "modernization"
            },
            
            # Bug Analysis Scenarios
            {
                "id": "BUG001",
                "category": "Bug Analysis",
                "subcategory": "Null Reference",
                "query": "What potential null reference issues exist in the HelloWorldApp?",
                "scenario_type": "bug_analysis"
            },
            {
                "id": "BUG002",
                "category": "Bug Analysis",
                "subcategory": "Resource Leaks",
                "query": "Are there any resource leaks or disposal issues in the HelloWorldApp?",
                "scenario_type": "bug_analysis"
            },
            {
                "id": "BUG003",
                "category": "Bug Analysis",
                "subcategory": "Concurrency Issues",
                "query": "What potential concurrency issues exist in the HelloWorldApp?",
                "scenario_type": "bug_analysis"
            },
            
            # Integration Scenarios
            {
                "id": "INT001",
                "category": "Integration",
                "subcategory": "Database Integration",
                "query": "How would you integrate the HelloWorldApp with a database?",
                "scenario_type": "integration"
            },
            {
                "id": "INT002",
                "category": "Integration",
                "subcategory": "Message Queue",
                "query": "How would you integrate the HelloWorldApp with a message queue system?",
                "scenario_type": "integration"
            },
            {
                "id": "INT003",
                "category": "Integration",
                "subcategory": "External API",
                "query": "How would you integrate the HelloWorldApp with external APIs?",
                "scenario_type": "integration"
            }
        ]
        
        # Filter test scenarios based on the filter
        self.filtered_scenarios = self.filter_test_scenarios()
        
    def filter_test_scenarios(self) -> List[Dict]:
        """Filter test scenarios based on the filter criteria."""
        if self.test_scenario_filter is None:
            return self.test_scenarios
        
        if isinstance(self.test_scenario_filter, int):
            return self.test_scenarios[:self.test_scenario_filter]
        
        if isinstance(self.test_scenario_filter, list):
            return [s for s in self.test_scenarios if s["id"] in self.test_scenario_filter]
        
        if isinstance(self.test_scenario_filter, str):
            return [s for s in self.test_scenarios if s["category"] == self.test_scenario_filter]
        
        return self.test_scenarios
    
    def get_comprehensive_schema_prompt(self) -> str:
        """Return comprehensive schema prompt based on actual database structure."""
        return """
Neo4j Code Property Graph Schema for HelloWorldApp (.NET):

ACTUAL NODE TYPES (verified):
- Project: Root project node
- File: Source files (name, file_path)
- Type: Classes, interfaces (name, type_kind, file_path)
- Variable: Local variables, fields (name, type_kind, file_path)
- Function: Methods, constructors (name, file_path)
- Namespace: Code organization (name, file_path)

ACTUAL RELATIONSHIPS (verified):
- CONTAINS: (Project|File|Type|Namespace)-[:CONTAINS]->(File|Type|Function|Variable)
- IMPLEMENTS: (Type)-[:IMPLEMENTS]->(Type) // class implements interface
- REFERENCES: (Type)-[:REFERENCES]->(Type) // type references
- CALLS: (Function)-[:CALLS]->(Function) // method calls

ACTUAL HELLOWORLDAPP DATA (verified):
Classes: Manager, Program, WorkerA, WorkerB, WorkerC, WorkerFactory
Interfaces: INotifier, IWorker
Functions: Run, Notify, Main, Process, CreateWorkers
Files: Manager.cs, Program.cs, WorkerA.cs, WorkerB.cs, WorkerC.cs, WorkerFactory.cs, INotifier.cs, IWorker.cs, Helper.cs
"""

    async def generate_cypher_queries_with_llm(self, user_query: str, category: str = "Technical") -> list:
        """Generate Cypher queries using GPT-4o with proper fallbacks."""
        
        # Try LLM generation first
        if OpenAI:
            try:
                client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                
                system_prompt = f"""You are an expert Neo4j Cypher query generator for code analysis.

{self.graph_schema_prompt}

Generate 1-2 Cypher queries that:
1. Are syntactically correct Neo4j Cypher
2. Use the ACTUAL node types and relationships listed above
3. Return meaningful results for the user's question
4. Include appropriate LIMIT clauses (10-15 results)
5. Use relevant WHERE clauses for filtering
6. Focus on the HelloWorldApp codebase

Return ONLY a JSON array: [{{"query": "MATCH...", "purpose": "description"}}]"""

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
                
                # Clean up response to extract JSON
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                
                try:
                    queries = json.loads(response_text)
                    if isinstance(queries, list) and len(queries) > 0:
                        logger.info(f"✅ LLM generated {len(queries)} queries for category: {category}")
                        return queries
                except json.JSONDecodeError:
                    logger.warning(f"❌ LLM response not valid JSON: {response_text[:200]}...")
                    
            except Exception as e:
                logger.error(f"❌ LLM call failed: {e}")
        
        # Fall back to category-specific queries
        if category in self.fallback_queries:
            fallback = self.fallback_queries[category]
            logger.info(f"🔄 Using fallback queries for category: {category}")
            return fallback
        else:
            # Default fallback
            logger.warning(f"⚠️  Using default fallback for unknown category: {category}")
            return [
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 15",
                    "purpose": "Find all classes and interfaces"
                }
            ]

    async def run_vector_only_query(self, query: str) -> Dict[str, Any]:
        """Run query using codebase-vector-rag only."""
        start_time = time.time()
        
        try:
            cmd = [
                "codebase-vector-rag", "query",
                query,
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

    async def run_cpg_only_query(self, query: str, category: str = "Technical") -> Dict[str, Any]:
        """Run query using fixed CPG-only approach with dynamic Cypher generation."""
        start_time = time.time()
        
        try:
            # Generate Cypher queries using improved LLM
            cypher_queries = await self.generate_cypher_queries_with_llm(query, category)
            
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
            logger.error(f"CPG query failed: {e}")
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }

    async def run_comprehensive_query(self, query: str, category: str = "Technical") -> Dict[str, Any]:
        """Run comprehensive query using both vector and CPG approaches."""
        start_time = time.time()
        
        try:
            # Run both approaches concurrently
            vector_task = asyncio.create_task(self.run_vector_only_query(query))
            cpg_task = asyncio.create_task(self.run_cpg_only_query(query, category))
            
            vector_result, cpg_result = await asyncio.gather(vector_task, cpg_task)
            
            # Use comprehensive_code_analysis MCP tool
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("project-analyzer-server")
            
            result = await session.call_tool(
                "comprehensive_code_analysis",
                {
                    "user_query": query,
                    "collection_name": self.collection_name,
                    "max_results": 15,
                    "project_path": self.project_path
                }
            )
            
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            return {
                "status": "success",
                "response": content_text,
                "response_time_ms": response_time_ms,
                "error": ""
            }
                
        except Exception as e:
            logger.error(f"Comprehensive query failed: {e}")
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }

    async def run_comparative_analysis(self) -> List[Dict[str, Any]]:
        """Run comparative analysis across all filtered scenarios."""
        results = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        print(f"🚀 Starting Fixed Comparative Analysis Suite")
        print(f"📊 Total scenarios to run: {len(self.filtered_scenarios)}")
        print(f"🕐 Timestamp: {timestamp}")
        print("=" * 80)
        
        for i, scenario in enumerate(self.filtered_scenarios, 1):
            print(f"\n[{i}/{len(self.filtered_scenarios)}] Processing: {scenario['id']} - {scenario['category']}")
            print(f"Query: {scenario['query'][:100]}...")
            
            # Run all three approaches
            vector_result = await self.run_vector_only_query(scenario['query'])
            cpg_result = await self.run_cpg_only_query(scenario['query'], scenario['category'])
            comprehensive_result = await self.run_comprehensive_query(scenario['query'], scenario['category'])
            
            # Compile results
            result = {
                "query_id": scenario['id'],
                "user_query": scenario['query'],
                "query_category": scenario['category'],
                "query_subcategory": scenario['subcategory'],
                "scenario_type": scenario['scenario_type'],
                "timestamp": timestamp,
                
                "vector_status": vector_result['status'],
                "vector_response": vector_result['response'],
                "vector_response_time_ms": vector_result['response_time_ms'],
                "vector_error": vector_result['error'],
                
                "cpg_status": cpg_result['status'],
                "cpg_response": cpg_result['response'],
                "cpg_response_time_ms": cpg_result['response_time_ms'],
                "cpg_error": cpg_result['error'],
                
                "comprehensive_status": comprehensive_result['status'],
                "comprehensive_response": comprehensive_result['response'],
                "comprehensive_response_time_ms": comprehensive_result['response_time_ms'],
                "comprehensive_error": comprehensive_result['error']
            }
            
            results.append(result)
            
            # Print progress
            print(f"  ✅ Vector: {vector_result['status']} ({vector_result['response_time_ms']}ms)")
            print(f"  ✅ CPG: {cpg_result['status']} ({cpg_result['response_time_ms']}ms)")
            print(f"  ✅ Comprehensive: {comprehensive_result['status']} ({comprehensive_result['response_time_ms']}ms)")
            
        return results

    def save_results(self, results: List[Dict[str, Any]], timestamp: str):
        """Save results to CSV file."""
        df = pd.DataFrame(results)
        
        # Create output directory
        output_dir = Path("/opt/genpod/test_results")
        output_dir.mkdir(exist_ok=True)
        
        # Save to CSV
        output_file = output_dir / f"fixed_comparative_analysis_{timestamp}.csv"
        df.to_csv(output_file, index=False)
        
        print(f"\n✅ Results saved to: {output_file}")
        print(f"📊 Total scenarios processed: {len(results)}")
        
        # Print summary statistics
        vector_success = len([r for r in results if r['vector_status'] == 'success'])
        cpg_success = len([r for r in results if r['cpg_status'] == 'success'])
        comp_success = len([r for r in results if r['comprehensive_status'] == 'success'])
        
        print(f"\n📈 Success Rates:")
        print(f"  Vector: {vector_success}/{len(results)} ({vector_success/len(results)*100:.1f}%)")
        print(f"  CPG: {cpg_success}/{len(results)} ({cpg_success/len(results)*100:.1f}%)")
        print(f"  Comprehensive: {comp_success}/{len(results)} ({comp_success/len(results)*100:.1f}%)")
        
        return output_file

async def main():
    """Main function to run the fixed comparative analysis."""
    
    # You can change this filter as needed:
    # - None: Run all 37 scenarios
    # - 5: Run first 5 scenarios  
    # - ['T001', 'T002', 'F001']: Run specific scenarios
    # - 'Technical': Run only Technical category
    
    analyzer = FixedComparativeAnalyzer(test_scenario_filter=5)  # Start with 5 scenarios
    
    # Run the analysis
    results = await analyzer.run_comparative_analysis()
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = analyzer.save_results(results, timestamp)
    
    print(f"\n🎉 Fixed Comparative Analysis completed!")
    print(f"📁 Results saved to: {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
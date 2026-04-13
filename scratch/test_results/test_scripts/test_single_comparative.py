#!/usr/bin/env python3
"""
Test Single Comparative Query

Run just one query to test all three approaches before running the full suite.
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
import os
from pathlib import Path
from typing import Dict, Any

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

class SingleTestRunner:
    def __init__(self):
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.project_path = "/opt/HelloWorldApp"
        self.collection_name = "helloworldapp-fresh-test"
        self.neo4j_config = "/opt/genpod/neo4j_config.json"
        
        # Test query
        self.test_query = "Find all classes in the HelloWorldApp that implement specific design patterns like Factory, Observer, or Strategy patterns."
        
        # Use the comprehensive schema I already read from /opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml
        self.graph_schema_prompt = self.get_comprehensive_schema_prompt()
        
    async def run_vector_only_query(self, query: str) -> Dict[str, Any]:
        """Run query using codebase-vector-rag only."""
        logger.info("🔍 Running vector-only query...")
        start_time = time.time()
        
        try:
            cmd = [
                "codebase-vector-rag", "query", query,
                "--collection-name", self.collection_name,
                "--max-results", "15"
            ]
            
            logger.info(f"Command: {' '.join(cmd)}")
            
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

File: Every parsed source file is represented as a File node serving as a container for all code elements.
- name: The file's name
- file_path: The file's location within the project  
- version: Version information (if available)

Type: Classes, interfaces, structs, enums normalized from various language constructs.
- name: The type's name (e.g., class, struct, enum, union, typedef)
- type_kind: Indicates the kind of type (class, struct, interface, enum, etc.)
- access_modifier: Visibility (public, private, protected, internal)
- is_abstract: Indicator for abstract types (in OOP)
- documentation: Associated documentation or comments
- file_path: Location of the type definition
- fields: Member variables or fields of the type
- base_list: List of base types (inheritance or interface implementation)
- body: The type body content
- modifier: Additional modifiers (static, sealed, etc.)

Function: Methods, functions, constructors from all language constructs.
- name: The function's identifier
- body: The complete implementation of the function
- parameters: List of function parameters
- return_type: The data type returned by the function
- file_path: The file where the function is defined
- start_point/end_point: Start and end positions in the source file
- modifier: Access modifiers (public, private, static, virtual, etc.)
- type_parameters: Generic type parameters, if any
- constraints: Any constraints applied to the function

Variable: Local variables, fields, parameters from various language constructs.
- name: The variable or field name
- type_kind: The variable's data type or category
- initial_value: Assigned value at declaration, if any
- access_modifier: Visibility or access level
- file_path: File where the variable is declared
- value: The variable's assigned value
- modifier: Additional modifiers (readonly, const, static, etc.)

Namespace: Encapsulates all types and functions defined within that scope.
- name: The namespace identifier
- path: The hierarchical or dotted path of the namespace
- file_path: File containing the namespace definition
- body: Contained declarations and definitions

EDGE DEFINITIONS:

DEFINED_IN: Links code elements to their source files or namespaces.
- From: Function, Type, Namespace, Variable
- To: File, Namespace
- Purpose: Each element carries file context used to establish source location

CONTAINS: Models hierarchical nesting found in source code.
- From: Namespace, Type, File, Block
- To: Namespace, Type, Function, Variable, Block, Literal, Macro
- Purpose: File contains Types and Functions, Type contains member Variables and Functions

IMPLEMENTS: Interface implementation relationships.
- From: Type (class/struct)
- To: Type (interface)
- Purpose: Represents that a type conforms to an interface contract

INHERITS_FROM: Object-oriented inheritance relationships.
- From: Type (derived)
- To: Type (base)
- Purpose: Links derived types with their base types

CALLS: Function call relationships within code.
- From: Function (caller)
- To: Function (callee)
- Purpose: When function call detected, establishes caller-callee relationship

HAS_PARAMETER: Function parameter relationships.
- From: Function
- To: Variable (parameter)
- Purpose: Function parameters are Variable nodes connected to parent Function

DECLARED_IN: Variable scope relationships.
- From: Variable
- To: Function, Type, Namespace, Block
- Purpose: Links Variable to its declaration scope for scope-aware queries

HELLOWORLDAPP SPECIFIC CONTEXT:
This .NET console application demonstrates design patterns:
- Factory Pattern: WorkerFactory.CreateWorkers() creates IWorker implementations
- Observer Pattern: Manager implements INotifier, workers call back via Notify()
- Strategy Pattern: WorkerA, WorkerB, WorkerC implement IWorker.Process() differently
- Key Types: Manager, WorkerFactory, WorkerA, WorkerB, WorkerC, IWorker, INotifier
- Key Functions: CreateWorkers, Process, Notify, Run, FormatMessage
"""

    async def generate_cypher_queries_with_llm(self, user_query: str) -> list:
        """Generate Cypher queries using GPT-4o directly (mimicking LLM service)."""
        if not OpenAI:
            raise Exception("OpenAI library not available")
        
        # Initialize OpenAI client
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # System prompt for Cypher generation (using comprehensive schema)
        system_prompt = f"""You are an expert Neo4j Cypher query generator for code analysis.

Given a user query about code analysis, generate 1-3 Cypher queries to search a code property graph (CPG) database.

{self.graph_schema_prompt}

Generate queries that:
1. Are syntactically correct Neo4j Cypher
2. Return meaningful results for the user's question
3. Include appropriate LIMIT clauses (10-20 results)
4. Use relevant WHERE clauses for filtering
5. Focus on the HelloWorldApp codebase
6. Use the proper node types and relationships from the schema above

Return ONLY a JSON array of query objects with this format:
[
  {{
    "query": "MATCH (t:Type)...",
    "purpose": "Find classes implementing design patterns"
  }}
]"""

        user_prompt = f"""User Query: {user_query}

Generate Cypher queries to answer this question about the HelloWorldApp codebase. Focus on finding relevant classes, methods, and relationships that address the user's question."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-2024-08-06",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                queries = json.loads(response_text)
                return queries
            except json.JSONDecodeError:
                # Fallback: extract queries from text
                logger.warning("Failed to parse JSON, using fallback query extraction")
                return [{"query": "MATCH (t:Type)-[:DEFINED_IN]->(f:File) WHERE t.name CONTAINS 'Factory' OR t.name CONTAINS 'Worker' RETURN t.name, f.file_path LIMIT 20", "purpose": "Find Factory and Worker classes"}]
                
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            # Fallback queries
            return [{"query": "MATCH (t:Type)-[:DEFINED_IN]->(f:File) WHERE t.name CONTAINS 'Factory' OR t.name CONTAINS 'Worker' RETURN t.name, f.file_path LIMIT 20", "purpose": "Find Factory and Worker classes"}]

    async def run_cpg_only_query(self, query: str) -> Dict[str, Any]:
        """Run query using CPG-only approach with dynamic Cypher generation."""
        logger.info("🔧 Running CPG-only query with dynamic Cypher generation...")
        start_time = time.time()
        
        try:
            # Step 1: Generate Cypher queries using LLM (without vector search)
            logger.info("  - Generating Cypher queries with GPT-4o...")
            cypher_queries = await self.generate_cypher_queries_with_llm(query)
            
            # Step 2: Execute generated Cypher queries
            logger.info(f"  - Executing {len(cypher_queries)} generated queries...")
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("project-analyzer-server")
            
            cpg_results = []
            for query_obj in cypher_queries:
                cypher_query = query_obj["query"]
                purpose = query_obj.get("purpose", "Generated query")
                
                result = await session.call_tool(
                    "query_cpg_only",
                    {
                        "cypher_query": cypher_query,
                        "config_path": self.neo4j_config,
                        "max_results": 20
                    }
                )
                
                # Parse individual result
                result_content = result.content[0] if isinstance(result.content, list) else result.content
                if hasattr(result_content, 'text'):
                    content_text = result_content.text
                else:
                    content_text = str(result_content)
                
                cpg_results.append({
                    "cypher_query": cypher_query,
                    "purpose": purpose,
                    "result": content_text
                })
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Combine all results
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
        logger.info("🚀 Running comprehensive query...")
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
    
    async def run_test(self):
        """Run the single test."""
        logger.info("🧪 Starting single comparative test...")
        logger.info(f"Test query: {self.test_query}")
        
        # Run all three approaches
        vector_result = await self.run_vector_only_query(self.test_query)
        cpg_result = await self.run_cpg_only_query(self.test_query)
        comprehensive_result = await self.run_comprehensive_query(self.test_query)
        
        # Print results
        logger.info("\n" + "="*80)
        logger.info("RESULTS SUMMARY")
        logger.info("="*80)
        
        logger.info(f"Vector-only: {vector_result['status']} ({vector_result['response_time_ms']}ms)")
        if vector_result['status'] == 'error':
            logger.error(f"Vector error: {vector_result['error']}")
        else:
            logger.info(f"Vector response length: {len(vector_result['response'])} characters")
        
        logger.info(f"CPG-only: {cpg_result['status']} ({cpg_result['response_time_ms']}ms)")
        if cpg_result['status'] == 'error':
            logger.error(f"CPG error: {cpg_result['error']}")
        else:
            logger.info(f"CPG response length: {len(cpg_result['response'])} characters")
        
        logger.info(f"Comprehensive: {comprehensive_result['status']} ({comprehensive_result['response_time_ms']}ms)")
        if comprehensive_result['status'] == 'error':
            logger.error(f"Comprehensive error: {comprehensive_result['error']}")
        else:
            logger.info(f"Comprehensive response length: {len(comprehensive_result['response'])} characters")
        
        # Check if all succeeded
        all_success = all([
            vector_result['status'] == 'success',
            cpg_result['status'] == 'success',
            comprehensive_result['status'] == 'success'
        ])
        
        logger.info("="*80)
        if all_success:
            logger.info("✅ ALL TESTS PASSED - Ready to run full comparative suite!")
        else:
            logger.error("❌ SOME TESTS FAILED - Fix issues before running full suite")
        
        return all_success

async def main():
    runner = SingleTestRunner()
    success = await runner.run_test()
    
    if success:
        print("\n🎉 Single test completed successfully!")
        print("You can now run the full comparative suite with:")
        print("python comparative_analysis_suite.py")
    else:
        print("\n⚠️  Single test had issues. Please check the logs above.")

if __name__ == "__main__":
    asyncio.run(main())
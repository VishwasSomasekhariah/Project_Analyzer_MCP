#!/usr/bin/env python3
"""
Test T001 Scenario JSON Debug Script

This script runs the T001 scenario from the comparative analysis and outputs
the results in JSON format while maintaining the same column structure as CSV.
This allows validation of the comprehensive analysis fix before running all scenarios.
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

# Manual extraction function no longer needed - CLI now outputs clean JSON!

from mcp_use import MCPClient

# Import OpenAI for CPG query generation
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

class T001ScenarioTester:
    def __init__(self):
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.project_path = "/opt/HelloWorldApp"
        self.collection_name = "helloworldapp-benchmarking"
        self.neo4j_config = "/opt/genpod/neo4j_config.json"
        
        # T001 scenario from the comparative analysis
        self.test_scenario = {
            "id": "T001", 
            "category": "Technical", 
            "subcategory": "Architecture", 
            "query": "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?", 
            "scenario_type": "analysis"
        }
        
        # Schema for CPG queries
        self.graph_schema_prompt = """
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

        # Fallback queries for Technical category
        self.fallback_queries = [
            {
                "query": "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 15",
                "purpose": "Find all classes and interfaces for technical analysis"
            },
            {
                "query": "MATCH (t1:Type)-[r:IMPLEMENTS]->(t2:Type) RETURN t1.name, t2.name, t1.file_path LIMIT 10",
                "purpose": "Find implementation relationships"
            }
        ]

    async def generate_cypher_queries_with_llm(self, user_query: str) -> list:
        """Generate Cypher queries using GPT-4o with proper fallbacks."""
        
        # Try LLM generation first
        if OpenAI:
            try:
                import os
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
                        print(f"✅ LLM generated {len(queries)} queries")
                        return queries
                except json.JSONDecodeError:
                    print(f"❌ LLM response not valid JSON: {response_text[:200]}...")
                    
            except Exception as e:
                print(f"❌ LLM call failed: {e}")
        
        # Fall back to category-specific queries
        print(f"🔄 Using fallback queries")
        return self.fallback_queries

    async def run_vector_only_query(self, query: str) -> dict:
        """Run query using query_vector_only MCP tool."""
        start_time = time.time()
        
        try:
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("mcp-analysis-server")
            
            result = await session.call_tool(
                "query_vector_only",
                {
                    "query": query,
                    "collection_name": self.collection_name,
                    "max_results": 15,
                    "output_format": "json",
                }
            )
            
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Parse the MCP response structure (now returns clean CLI JSON)
            try:
                parsed_result = json.loads(content_text)
                
                # MCP tool now returns clean CLI JSON directly in ai_response
                if isinstance(parsed_result, dict) and parsed_result.get("status") == "success":
                    # Get the clean CLI JSON from the ai_response field
                    cli_response_str = parsed_result.get("ai_response", "")
                    
                    # Parse the clean CLI JSON directly
                    try:
                        cli_response = json.loads(cli_response_str)
                        
                        # Extract data from the clean CLI JSON structure
                        if isinstance(cli_response, dict) and "results" in cli_response:
                            ai_response = cli_response.get("response", "")
                            raw_results = cli_response.get("results", [])
                            total_results = cli_response.get("total_results", 0)
                            processing_time = cli_response.get("processing_time", 0)
                            confidence_score = cli_response.get("confidence_score")
                            has_diagram = cli_response.get("has_diagram", False)
                        else:
                            # Fallback to MCP structure if CLI JSON is malformed
                            ai_response = cli_response_str
                            raw_results = parsed_result.get("raw_results", [])
                            total_results = len(raw_results)
                            processing_time = 0
                            confidence_score = None
                            has_diagram = False
                            
                    except json.JSONDecodeError:
                        # Fallback to MCP structure if CLI JSON parsing fails
                        ai_response = cli_response_str
                        raw_results = parsed_result.get("raw_results", [])
                        total_results = len(raw_results)
                        processing_time = 0
                        confidence_score = None
                        has_diagram = False
                    
                    return {
                        "status": "success",
                        "ai_response": ai_response,
                        "raw_results": raw_results,
                        "response": ai_response,
                        "response_time_ms": response_time_ms,
                        "error": "",
                        "metadata": {
                            "vector_total_results": total_results,
                            "vector_processing_time": processing_time,
                            "vector_confidence_score": confidence_score,
                            "has_diagram": has_diagram
                        },
                        "full_response": content_text
                    }
                else:
                    return {
                        "status": parsed_result.get("status", "error"),
                        "ai_response": content_text,
                        "raw_results": [],
                        "response": content_text,
                        "response_time_ms": response_time_ms,
                        "error": parsed_result.get("error", "Unknown error"),
                        "metadata": {},
                        "full_response": content_text
                    }
                    
            except json.JSONDecodeError:
                return {
                    "status": "success",
                    "ai_response": content_text,
                    "raw_results": [],
                    "response": content_text,
                    "response_time_ms": response_time_ms,
                    "error": "JSON parsing failed, using raw output",
                    "metadata": {},
                    "full_response": content_text
                }
                
        except Exception as e:
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }

    async def run_cpg_only_query(self, query: str) -> dict:
        """Run query using CPG-only approach with dynamic Cypher generation."""
        start_time = time.time()
        
        try:
            # Generate Cypher queries
            cypher_queries = await self.generate_cypher_queries_with_llm(query)
            
            # Execute generated Cypher queries
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("mcp-analysis-server")
            
            cpg_results = []
            for query_obj in cypher_queries:
                result = await session.call_tool(
                    "query_cpg_only",
                    {
                        "cypher_query": query_obj["query"],
                        "config_path": self.neo4j_config,
                        "max_results": 20,
                        "user_query": query,
                        "enable_synthesis": True
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

    async def run_comprehensive_query(self, query: str) -> dict:
        """Run comprehensive query using both vector and CPG approaches."""
        start_time = time.time()
        
        try:
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("mcp-analysis-server")
            
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
            
            # Try to parse the response to extract metadata and raw results
            metadata = {}
            parsed_response = content_text
            raw_results = []
            
            try:
                parsed_data = json.loads(content_text)
                if isinstance(parsed_data, dict):
                    # Extract synthesis metadata if available
                    if "results" in parsed_data and isinstance(parsed_data["results"], dict):
                        steps = parsed_data["results"].get("steps", {})
                        if "5_synthesis" in steps:
                            synthesis_step = steps["5_synthesis"]
                            metadata.update({
                                "synthesis_metadata": synthesis_step.get("synthesis_metadata", {}),
                                "synthesis_status": synthesis_step.get("summary", {}).get("synthesis_status", "unknown"),
                                "vector_sources": synthesis_step.get("summary", {}).get("vector_search_results", 0),
                                "cpg_queries": synthesis_step.get("summary", {}).get("cypher_queries_generated", 0),
                                "successful_cpg_queries": synthesis_step.get("summary", {}).get("successful_cpg_queries", 0)
                            })
                        
                        # Extract raw results from vector search step
                        if "1_vector_search" in steps:
                            vector_step = steps["1_vector_search"]
                            if "raw_output" in vector_step:
                                if isinstance(vector_step["raw_output"], list):
                                    raw_results.extend(vector_step["raw_output"])
                                elif isinstance(vector_step["raw_output"], dict):
                                    raw_results.append(vector_step["raw_output"])
                        
                        # Extract raw results from CPG queries
                        for step_name, step_data in steps.items():
                            if step_name.startswith("4_cpg_query") and isinstance(step_data, dict):
                                if "raw_results" in step_data:
                                    cpg_raw = step_data["raw_results"]
                                    if isinstance(cpg_raw, list):
                                        raw_results.extend(cpg_raw)
                                    elif isinstance(cpg_raw, dict) and "results" in cpg_raw:
                                        if isinstance(cpg_raw["results"], list):
                                            raw_results.extend(cpg_raw["results"])
                    
                    # Use the comprehensive response from synthesis if available
                    if "results" in parsed_data and "steps" in parsed_data["results"] and "5_synthesis" in parsed_data["results"]["steps"]:
                        synthesis_response = parsed_data["results"]["steps"]["5_synthesis"].get("comprehensive_response", "")
                        if synthesis_response:
                            parsed_response = synthesis_response
            except (json.JSONDecodeError, KeyError, AttributeError):
                # If parsing fails, use original content and empty metadata
                pass
            
            return {
                "status": "success",
                "response": parsed_response,
                "raw_results": raw_results,
                "response_time_ms": response_time_ms,
                "error": "",
                "metadata": metadata
            }
                
        except Exception as e:
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }

    async def run_t001_scenario(self) -> dict:
        """Run the T001 scenario and return results in JSON format matching CSV columns."""
        print("🧪 Testing T001 Scenario with JSON Output Format")
        print("=" * 60)
        print(f"📝 Scenario: {self.test_scenario['id']} - {self.test_scenario['category']}")
        print(f"🎯 Query: {self.test_scenario['query']}")
        print("=" * 60)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Run all three approaches
        print("\n1️⃣ Running Vector-only query...")
        vector_result = await self.run_vector_only_query(self.test_scenario['query'])
        print(f"   ✅ Vector: {vector_result['status']} ({vector_result.get('response_time_ms', 0)}ms)")
        
        print("\n2️⃣ Running CPG-only query...")
        cpg_result = await self.run_cpg_only_query(self.test_scenario['query'])
        print(f"   ✅ CPG: {cpg_result['status']} ({cpg_result.get('response_time_ms', 0)}ms)")
        
        print("\n3️⃣ Running Comprehensive query...")
        comprehensive_result = await self.run_comprehensive_query(self.test_scenario['query'])
        print(f"   ✅ Comprehensive: {comprehensive_result['status']} ({comprehensive_result.get('response_time_ms', 0)}ms)")
        
        # Extract structured data matching CSV format
        vector_metadata = vector_result.get('metadata', {})
        comp_metadata = comprehensive_result.get('metadata', {})
        
        # Parse CPG response to extract synthesis data if available
        cpg_ai_response = ""
        cpg_raw_results = []
        cpg_synthesis_status = "unknown"
        try:
            cpg_response_data = json.loads(cpg_result.get('response', '{}'))
            if isinstance(cpg_response_data, dict):
                # Extract the results array from the CPG response
                if 'results' in cpg_response_data:
                    cpg_raw_results = []
                    for result_obj in cpg_response_data['results']:
                        if isinstance(result_obj, dict) and 'result' in result_obj:
                            # Parse the nested result JSON
                            try:
                                nested_result = json.loads(result_obj['result'])
                                if 'raw_results' in nested_result:
                                    if nested_result['raw_results'] and 'results' in nested_result['raw_results']:
                                        cpg_raw_results.extend(nested_result['raw_results']['results'])
                            except json.JSONDecodeError:
                                pass
                
                # Try to get synthesis response from various places
                synthesis_text = ""
                if 'results' in cpg_response_data:
                    for result_obj in cpg_response_data['results']:
                        if isinstance(result_obj, dict) and 'result' in result_obj:
                            try:
                                nested_result = json.loads(result_obj['result'])
                                if 'synthesis' in nested_result:
                                    synthesis_text += nested_result['synthesis'] + "\n\n"
                                    if nested_result.get('synthesis_status') == 'success':
                                        cpg_synthesis_status = 'success'
                            except json.JSONDecodeError:
                                pass
                
                cpg_ai_response = synthesis_text.strip() if synthesis_text else cpg_result.get('response', '')
                
                # Fallback to original structure
                if not cpg_ai_response:
                    cpg_ai_response = cpg_response_data.get('synthesis', cpg_result.get('response', ''))
                    cpg_raw_results = cpg_response_data.get('cpg_results', [])
                    cpg_synthesis_status = cpg_response_data.get('synthesis_status', 'unknown')
                    
        except (json.JSONDecodeError, KeyError):
            cpg_ai_response = cpg_result.get('response', '')
            cpg_raw_results = []
        
        # Compile results matching the CSV structure exactly
        result = {
            # Query Information
            "query_id": self.test_scenario['id'],
            "user_query": self.test_scenario['query'],
            "query_category": self.test_scenario['category'],
            "query_subcategory": self.test_scenario['subcategory'],
            "scenario_type": self.test_scenario['scenario_type'],
            "timestamp": timestamp,
            
            # VECTOR RETRIEVER - For Reference-based and Reference-free Evaluation
            "vector_status": vector_result['status'],
            "vector_ai_response": vector_result.get('ai_response', vector_result.get('response', '')),
            "vector_raw_results_json": json.dumps(vector_result.get('raw_results', [])),
            "vector_metadata_json": json.dumps(vector_metadata),
            "vector_response_time_ms": vector_result.get('response_time_ms', 0),
            "vector_error": vector_result.get('error', ''),
            
            # CPG RETRIEVER - For Reference-based and Reference-free Evaluation  
            "cpg_status": cpg_result['status'],
            "cpg_ai_response": cpg_ai_response,
            "cpg_raw_results_json": json.dumps(cpg_raw_results),
            "cpg_synthesis_status": cpg_synthesis_status,
            "cpg_response_time_ms": cpg_result.get('response_time_ms', 0),
            "cpg_error": cpg_result.get('error', ''),
            
            # COMPREHENSIVE RETRIEVER - For Reference-based and Reference-free Evaluation
            "comprehensive_status": comprehensive_result['status'],
            "comprehensive_ai_response": comprehensive_result.get('ai_response', comprehensive_result.get('response', '')),
            "comprehensive_raw_results_json": json.dumps(comprehensive_result.get('raw_results', [])),
            "comprehensive_metadata_json": json.dumps(comp_metadata),
            "comprehensive_response_time_ms": comprehensive_result.get('response_time_ms', 0),
            "comprehensive_error": comprehensive_result.get('error', ''),
            
            # SYNTHESIS QUALITY METRICS - For Evaluation Framework Analysis
            "synthesis_status": comp_metadata.get('synthesis_status', 'unknown'),
            "synthesis_vector_sources": comp_metadata.get('vector_sources', 0),
            "synthesis_cpg_queries": comp_metadata.get('cpg_queries', 0),
            "synthesis_successful_cpg_queries": comp_metadata.get('successful_cpg_queries', 0),
            "synthesis_llm_metadata_json": json.dumps(comp_metadata.get('synthesis_metadata', {})) if comp_metadata.get('synthesis_metadata') else ""
        }
        
        # Print synthesis info
        if comp_metadata:
            print(f"\n🔍 Synthesis Analysis:")
            print(f"   Status: {comp_metadata.get('synthesis_status', 'unknown')}")
            print(f"   Vector sources: {comp_metadata.get('vector_sources', 0)}")
            print(f"   CPG queries: {comp_metadata.get('successful_cpg_queries', 0)}/{comp_metadata.get('cpg_queries', 0)}")
        
        return result

    def save_json_results(self, result: dict):
        """Save results to JSON file."""
        output_file = Path("/opt/genpod/t001_scenario_test_result.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Results saved to: {output_file}")
        print(f"📊 Total fields: {len(result)}")
        
        # Print summary
        print(f"\n📈 T001 Test Summary:")
        print(f"   Vector: {result['vector_status']} ({result['vector_response_time_ms']}ms)")
        print(f"   CPG: {result['cpg_status']} ({result['cpg_response_time_ms']}ms)")
        print(f"   Comprehensive: {result['comprehensive_status']} ({result['comprehensive_response_time_ms']}ms)")
        print(f"   Synthesis: {result['synthesis_status']}")
        
        return output_file

async def main():
    """Main function to run T001 scenario test."""
    tester = T001ScenarioTester()
    
    # Run T001 scenario
    result = await tester.run_t001_scenario()
    
    # Save to JSON
    output_file = tester.save_json_results(result)
    
    print(f"\n🎉 T001 Scenario Test completed!")
    print(f"📁 JSON result saved to: {output_file}")
    print(f"✅ Ready to validate comprehensive analysis fix")

if __name__ == "__main__":
    asyncio.run(main())
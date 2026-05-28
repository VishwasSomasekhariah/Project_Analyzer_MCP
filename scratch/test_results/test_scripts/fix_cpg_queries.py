#!/usr/bin/env python3
"""
Fix CPG query generation with proper fallbacks for different categories
"""

import asyncio
import json
import sys
import os
from pathlib import Path

# Add the test scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent / "test_results" / "test_scripts"))

from mcp_use import MCPClient

# Import OpenAI for LLM query generation
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

class FixedCPGQueryGenerator:
    def __init__(self):
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.neo4j_config = "/opt/genpod/neo4j_config.json"
        
        # Define category-specific fallback queries based on actual database structure
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
    
    def get_comprehensive_schema_prompt(self):
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

{self.get_comprehensive_schema_prompt()}

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
                        print(f"✅ LLM generated {len(queries)} queries for category: {category}")
                        return queries
                except json.JSONDecodeError:
                    print(f"❌ LLM response not valid JSON: {response_text[:200]}...")
                    
            except Exception as e:
                print(f"❌ LLM call failed: {e}")
        
        # Fall back to category-specific queries
        if category in self.fallback_queries:
            fallback = self.fallback_queries[category]
            print(f"🔄 Using fallback queries for category: {category}")
            return fallback
        else:
            # Default fallback
            print(f"⚠️  Using default fallback for unknown category: {category}")
            return [
                {
                    "query": "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 15",
                    "purpose": "Find all classes and interfaces"
                }
            ]
    
    async def test_query_generation(self, test_queries):
        """Test query generation for different categories."""
        
        client = MCPClient.from_config_file(self.config_file)
        session = await client.create_session("project-analyzer-server")
        
        print("Testing Fixed CPG Query Generation")
        print("=" * 80)
        
        for test in test_queries:
            print(f"\n🔍 Testing: {test['id']} - {test['category']}")
            print(f"Query: {test['query'][:100]}...")
            
            # Generate queries
            queries = await self.generate_cypher_queries_with_llm(test['query'], test['category'])
            
            # Test each generated query
            for i, query_obj in enumerate(queries):
                print(f"\n  Generated Query {i+1}:")
                print(f"  Purpose: {query_obj['purpose']}")
                print(f"  Cypher: {query_obj['query']}")
                
                try:
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
                    
                    # Parse result to check for data
                    try:
                        parsed_result = json.loads(content_text)
                        if parsed_result.get("results", {}).get("count", 0) > 0:
                            print(f"  ✅ Success: {parsed_result['results']['count']} results")
                        else:
                            print(f"  ⚠️  Empty results")
                    except:
                        print(f"  ❌ Result parsing failed")
                        
                except Exception as e:
                    print(f"  ❌ Query failed: {e}")
            
            print("-" * 40)

async def main():
    """Main function to test fixed CPG query generation."""
    
    generator = FixedCPGQueryGenerator()
    
    # Test queries from different categories
    test_queries = [
        {
            "id": "T001",
            "category": "Technical",
            "query": "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?"
        },
        {
            "id": "F001",
            "category": "Functional", 
            "query": "What is the core business logic of the HelloWorldApp? How do the workers coordinate?"
        },
        {
            "id": "NF001",
            "category": "Non-Functional",
            "query": "What error handling mechanisms are present in the HelloWorldApp?"
        },
        {
            "id": "FA001",
            "category": "Feature Addition",
            "query": "How would you add a new worker type to the HelloWorldApp?"
        },
        {
            "id": "BUG001",
            "category": "Bug Analysis",
            "query": "What potential null reference issues exist in the HelloWorldApp?"
        }
    ]
    
    await generator.test_query_generation(test_queries)

if __name__ == "__main__":
    asyncio.run(main())
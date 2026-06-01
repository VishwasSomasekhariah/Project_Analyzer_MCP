"""
Graph Query Executor for Advanced Graph RAG
Executes planned subgraph queries with rich property retrieval and error handling
"""

import json
import subprocess
import os
import asyncio
from typing import Dict, List, Any, Optional, Tuple
import time

from src.core.paths import NEO4J_CONFIG, SCHEMA_PATH


class GraphQueryExecutor:
    """Execute planned subgraph queries with rich property retrieval"""
    
    def __init__(self, config_path: str = NEO4J_CONFIG):
        self.config_path = config_path
        self.default_timeout = 30000  # 30 seconds
        self.max_retries = 2
        
        # Query execution statistics
        self.execution_stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "total_execution_time": 0.0,
            "average_query_time": 0.0
        }
    
    async def execute_subgraph_retrieval(self, plan: Dict[str, Any], config_path: str = None) -> Dict[str, Any]:
        """
        Execute all planned queries and collect rich graph data
        
        Args:
            plan: Subgraph retrieval plan from SubgraphPlanner
            config_path: Optional override for Neo4j config path
            
        Returns:
            {
                "seed_results": [...],
                "expansion_results": [...],
                "combined_results": [...],
                "total_nodes": int,
                "rich_content_nodes": int,
                "execution_metadata": {...},
                "query_performance": {...}
            }
        """
        config_path = config_path or self.config_path
        start_time = time.time()
        
        # Initialize results structure
        results = {
            "seed_results": [],
            "expansion_results": [],
            "combined_results": [],
            "total_nodes": 0,
            "rich_content_nodes": 0,
            "execution_metadata": {
                "strategy": plan.get("strategy", "unknown"),
                "expected_analysis": plan.get("expected_analysis", "unknown"),
                "query_complexity": plan.get("query_complexity", "unknown"),
                "estimated_nodes": plan.get("estimated_nodes", 0)
            },
            "query_performance": {}
        }
        
        try:
            # Execute seed queries first (high priority)
            seed_queries = plan.get("seed_queries", [])
            if seed_queries:
                results["seed_results"] = await self._execute_query_batch(
                    seed_queries, config_path, "seed"
                )
            
            # Execute expansion queries (depends on seed results)
            expansion_queries = plan.get("expansion_queries", [])
            if expansion_queries:
                results["expansion_results"] = await self._execute_query_batch(
                    expansion_queries, config_path, "expansion"
                )
            
            # Combine and deduplicate results
            results["combined_results"] = self._combine_and_deduplicate_results(
                results["seed_results"], results["expansion_results"]
            )
            
            # Calculate result statistics
            results["total_nodes"] = len(results["combined_results"])
            results["rich_content_nodes"] = self._count_rich_content_nodes(results["combined_results"])
            
            # Performance metrics
            total_time = time.time() - start_time
            results["query_performance"] = {
                "total_execution_time": round(total_time, 3),
                "queries_executed": len(seed_queries) + len(expansion_queries),
                "average_query_time": round(total_time / max(len(seed_queries) + len(expansion_queries), 1), 3),
                "nodes_per_second": round(results["total_nodes"] / max(total_time, 0.001), 2)
            }
            
            # Update global stats
            self._update_execution_stats(results["query_performance"])
            
            return results
            
        except Exception as e:
            # Return error results with partial data
            results["execution_error"] = str(e)
            results["query_performance"] = {
                "total_execution_time": round(time.time() - start_time, 3),
                "error": True
            }
            return results
    
    async def _execute_query_batch(self, queries: List[Dict[str, Any]], config_path: str, batch_type: str) -> List[Dict[str, Any]]:
        """Execute a batch of queries with parallel processing"""
        if not queries:
            return []
        
        # Sort queries by priority (if available)
        sorted_queries = sorted(queries, key=lambda q: q.get("priority", 0.5), reverse=True)
        
        # Execute queries (parallel execution for independent queries)
        batch_results = []
        
        # For now, execute sequentially to avoid overwhelming Neo4j
        # In production, could implement smarter parallel execution
        for i, query_info in enumerate(sorted_queries):
            query_result = await self._execute_single_query(query_info, config_path, f"{batch_type}_{i}")
            batch_results.append(query_result)
        
        return batch_results
    
    async def _execute_single_query(self, query_info: Dict[str, Any], config_path: str, query_id: str) -> Dict[str, Any]:
        """Execute a single Cypher query with error handling and retries"""
        cypher_query = query_info.get("cypher", "").strip()
        query_type = query_info.get("type", "unknown")
        purpose = query_info.get("purpose", "Graph analysis")
        
        # DEBUG: Log the query being executed
        print(f"🔍 DEBUG - Executing Query {query_id}:")
        print(f"  Type: {query_type}")
        print(f"  Purpose: {purpose}")
        print(f"  Cypher: {cypher_query}")
        print()
        
        if not cypher_query:
            print(f"❌ DEBUG - Empty query for {query_id}")
            return {
                "query_id": query_id,
                "query_type": query_type,
                "purpose": purpose,
                "status": "error",
                "error": "Empty query provided",
                "results": [],
                "execution_time": 0.0
            }
        
        start_time = time.time()
        
        for attempt in range(self.max_retries + 1):
            try:
                # Prepare CLI command
                cli_command = [
                    "project-analyzer",
                    "--config-file", config_path,
                    "query",
                    "--cypher", cypher_query,
                    "--limit", "100",  # Reasonable limit for subgraph queries
                    "--output-format", "json"
                ]
                
                # Execute query
                result = subprocess.run(
                    cli_command,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=self.default_timeout / 1000,  # Convert to seconds
                    cwd=os.getcwd()
                )
                
                execution_time = time.time() - start_time
                
                if result.returncode == 0:
                    # DEBUG: Log the exact CLI response
                    print(f"🔍 DEBUG - CLI Response for query {query_id}:")
                    print(f"  stdout: {result.stdout[:500]}...")
                    print(f"  stderr: {result.stderr}")
                    
                    # Parse successful results
                    parsed_results = self._parse_query_results(result.stdout)
                    print(f"  parsed_results type: {type(parsed_results)}")
                    print(f"  parsed_results length: {len(parsed_results) if isinstance(parsed_results, list) else 'not a list'}")
                    
                    # Check if parsing detected a query error that needs repair
                    if (isinstance(parsed_results, dict) and 
                        parsed_results.get("_needs_repair") and 
                        attempt < self.max_retries):
                        
                        # Attempt to repair the query
                        error_msg = parsed_results.get("_query_error", "")
                        repaired_query = await self._attempt_query_repair(cypher_query, error_msg)
                        
                        if repaired_query and repaired_query != cypher_query:
                            # Retry with repaired query
                            cypher_query = repaired_query
                            await asyncio.sleep(0.2)  # Brief pause before retry
                            continue
                    
                    # Filter out repair metadata from results
                    if isinstance(parsed_results, dict) and parsed_results.get("_needs_repair"):
                        parsed_results = []  # Return empty if couldn't repair
                    
                    # DEBUG: Log query results
                    result_count = len(parsed_results) if isinstance(parsed_results, list) else 1
                    print(f"✅ DEBUG - Query {query_id} Results:")
                    print(f"  Status: success")
                    print(f"  Result count: {result_count}")
                    if isinstance(parsed_results, list) and len(parsed_results) > 0:
                        print(f"  First result keys: {list(parsed_results[0].keys()) if isinstance(parsed_results[0], dict) else type(parsed_results[0])}")
                    elif result_count == 0:
                        print(f"  ⚠️  Empty results - query returned no data")
                    print()
                    
                    return {
                        "query_id": query_id,
                        "query_type": query_type,
                        "purpose": purpose,
                        "cypher_query": cypher_query,
                        "status": "success",
                        "results": parsed_results,
                        "result_count": result_count,
                        "execution_time": round(execution_time, 3),
                        "attempt": attempt + 1
                    }
                else:
                    # Handle query errors
                    error_msg = result.stderr or result.stdout or "Unknown execution error"
                    
                    # Check if it's a retryable error
                    if attempt < self.max_retries and self._is_retryable_error(error_msg):
                        await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    
                    return {
                        "query_id": query_id,
                        "query_type": query_type,
                        "purpose": purpose,
                        "cypher_query": cypher_query,
                        "status": "error",
                        "error": error_msg,
                        "returncode": result.returncode,
                        "results": [],
                        "execution_time": round(execution_time, 3),
                        "attempts": attempt + 1
                    }
                    
            except subprocess.TimeoutExpired:
                if attempt < self.max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                
                return {
                    "query_id": query_id,
                    "query_type": query_type,
                    "purpose": purpose,
                    "cypher_query": cypher_query,
                    "status": "timeout",
                    "error": f"Query timeout after {self.default_timeout}ms",
                    "results": [],
                    "execution_time": round(time.time() - start_time, 3),
                    "attempts": attempt + 1
                }
                
            except Exception as e:
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                
                return {
                    "query_id": query_id,
                    "query_type": query_type,
                    "purpose": purpose,
                    "cypher_query": cypher_query,
                    "status": "exception",
                    "error": str(e),
                    "results": [],
                    "execution_time": round(time.time() - start_time, 3),
                    "attempts": attempt + 1
                }
        
        # Should not reach here, but return error if it does
        return {
            "query_id": query_id,
            "status": "error",
            "error": "Max retries exceeded",
            "results": [],
            "execution_time": round(time.time() - start_time, 3)
        }
    
    def _parse_query_results(self, stdout: str) -> List[Dict[str, Any]]:
        """Parse query results from JSON output"""
        if not stdout.strip():
            return []
        
        try:
            # Try to parse as JSON
            parsed = json.loads(stdout)
            
            # Handle different response formats
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                # Check if it's a CLI response with "results" field
                if "results" in parsed and "success" in parsed and parsed["success"]:
                    return parsed["results"] if isinstance(parsed["results"], list) else [parsed["results"]]
                # Handle CLI error responses
                elif "success" in parsed and not parsed["success"]:
                    # Extract error for potential query repair
                    error_msg = parsed.get("error", "Unknown error")
                    # Return empty results with error info for query repair mechanism
                    return {"_query_error": error_msg, "_needs_repair": True}
                # If it's a single result, wrap in list
                return [parsed]
            else:
                # Convert other types to string and wrap
                return [{"raw_result": str(parsed)}]
                
        except json.JSONDecodeError:
            # If not JSON, try to extract structured data
            lines = stdout.strip().split('\n')
            structured_results = []
            
            for line in lines:
                if line.strip():
                    try:
                        # Try parsing each line as JSON
                        line_data = json.loads(line)
                        structured_results.append(line_data)
                    except json.JSONDecodeError:
                        # Store as raw text
                        structured_results.append({"raw_output": line.strip()})
            
            return structured_results if structured_results else [{"raw_output": stdout}]
    
    def _is_retryable_error(self, error_msg: str) -> bool:
        """Determine if an error is retryable"""
        retryable_patterns = [
            "connection",
            "timeout",
            "network",
            "temporary",
            "unavailable",
            "busy"
        ]
        
        error_lower = error_msg.lower()
        return any(pattern in error_lower for pattern in retryable_patterns)
    
    async def _attempt_query_repair(self, original_query: str, error_message: str) -> str:
        """Attempt to repair a Cypher query based on error feedback and graph schema"""
        try:
            # Import LLM service for query repair
            from src.core.llm_service import LLMService
            
            # Initialize LLM service
            llm_service = LLMService({"cache_ttl": 300})  # Short cache for repairs
            
            # Get graph schema context
            schema_context = self._get_graph_schema_context()
            
            # Create repair prompt with schema context
            repair_prompt = f"""Fix this Cypher query based on the Neo4j syntax error and graph schema:

GRAPH SCHEMA:
{schema_context}

ORIGINAL QUERY:
{original_query}

ERROR MESSAGE:
{error_message}

Please provide ONLY the corrected Cypher query without any explanation or formatting.
Use the graph schema above to ensure:
- Correct node labels (File, Type, Function, etc.)
- Valid property names (name, file_path, body, symbols_location, etc.)
- Proper relationship types (CONTAINS, CALLS, REFERENCES, etc.)
- Correct syntax for WHERE clauses and RETURN statements

CORRECTED QUERY:"""

            # Request query repair
            response = await llm_service.generate_response(
                prompt=repair_prompt,
                system_prompt="You are a Cypher query syntax expert. Fix syntax errors precisely.",
                max_tokens=200,
                temperature=0.1
            )
            
            if response and response.content:
                # Clean up the response
                repaired_query = response.content.strip()
                
                # Remove any markdown formatting
                if repaired_query.startswith("```"):
                    lines = repaired_query.split('\n')
                    repaired_query = '\n'.join(lines[1:-1]) if len(lines) > 2 else repaired_query
                
                # Basic validation - must be different from original
                if repaired_query != original_query and "MATCH" in repaired_query:
                    return repaired_query
            
            return None
            
        except Exception as e:
            # If repair fails, return None to skip repair attempt
            return None
    
    def _get_graph_schema_context(self) -> str:
        """Get comprehensive graph schema context from the actual schema file"""
        try:
            import yaml
            schema_path = SCHEMA_PATH

            with open(schema_path, 'r') as f:
                schema = yaml.safe_load(f)

            context = "COMPREHENSIVE GRAPH SCHEMA:\n\n"
            
            # Add detailed node definitions with descriptions
            if 'NodeDefinitions' in schema:
                context += "NODE TYPES WITH DETAILED DEFINITIONS:\n"
                for node_type, node_def in schema['NodeDefinitions'].items():
                    context += f"\n{node_type}:\n"
                    
                    # Add creation description
                    if 'Creation' in node_def and 'Description' in node_def['Creation']:
                        context += f"  Purpose: {node_def['Creation']['Description']}\n"
                    
                    # Add attribute descriptions
                    if 'Contents' in node_def and 'Attributes' in node_def['Contents']:
                        context += f"  Properties:\n"
                        for attr in node_def['Contents']['Attributes']:
                            if isinstance(attr, dict):
                                for attr_name, attr_desc in attr.items():
                                    context += f"    - {attr_name}: {attr_desc}\n"
                            else:
                                context += f"    - {attr}\n"
            
            # Add detailed relationship definitions
            if 'EdgeDefinitions' in schema:
                context += f"\nRELATIONSHIP TYPES WITH DEFINITIONS:\n"
                for rel_type, rel_def in schema['EdgeDefinitions'].items():
                    context += f"\n{rel_type}:\n"
                    
                    if 'Definition' in rel_def:
                        from_desc = rel_def['Definition'].get('From', 'Unknown')
                        to_desc = rel_def['Definition'].get('To', 'Unknown')
                        context += f"  From: {from_desc}\n"
                        context += f"  To: {to_desc}\n"
                    
                    if 'Creation' in rel_def and 'Description' in rel_def['Creation']:
                        context += f"  Usage: {rel_def['Creation']['Description']}\n"
            
            # Add basic node-attribute mapping for quick reference
            if 'nodes' in schema:
                context += f"\nQUICK REFERENCE - NODE ATTRIBUTES:\n"
                for node_type, node_info in schema['nodes'].items():
                    attributes = node_info.get('attributes', [])
                    context += f"- {node_type}: {', '.join(attributes)}\n"
            
            return context
            
        except Exception as e:
            # Fallback to basic schema if file reading fails
            return """
BASIC SCHEMA:
- File: Properties: name, file_path
- Type: Properties: name, type_kind, file_path, body
- Function: Properties: name, type_kind, file_path, body
- CONTAINS, CALLS, REFERENCES relationships available
"""
    
    def _combine_and_deduplicate_results(self, seed_results: List[Dict[str, Any]], expansion_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Combine seed and expansion results, removing duplicates"""
        all_nodes = []
        seen_nodes = set()  # Track (name, file_path) combinations
        
        # Process seed results first (higher priority)
        for seed_result in seed_results:
            if seed_result.get("status") == "success":
                nodes = seed_result.get("results", [])
                if isinstance(nodes, list):
                    for node in nodes:
                        node_key = self._get_node_key(node)
                        if node_key not in seen_nodes:
                            all_nodes.append({
                                **node,
                                "_source": "seed",
                                "_query_type": seed_result.get("query_type", "unknown"),
                                "_purpose": seed_result.get("purpose", "")
                            })
                            seen_nodes.add(node_key)
        
        # Process expansion results
        for expansion_result in expansion_results:
            if expansion_result.get("status") == "success":
                nodes = expansion_result.get("results", [])
                if isinstance(nodes, list):
                    for node in nodes:
                        node_key = self._get_node_key(node)
                        if node_key not in seen_nodes:
                            all_nodes.append({
                                **node,
                                "_source": "expansion",
                                "_query_type": expansion_result.get("query_type", "unknown"),
                                "_purpose": expansion_result.get("purpose", ""),
                                "_hops": expansion_result.get("hops", 1)
                            })
                            seen_nodes.add(node_key)
        
        return all_nodes
    
    def _get_node_key(self, node: Dict[str, Any]) -> Tuple[str, str]:
        """Generate unique key for node deduplication"""
        # Try different name field patterns (file nodes vs contained nodes)
        name = (node.get("name", "") or 
                node.get("f.name", "") or 
                node.get("contained.name", "") or 
                node.get("t.name", "") or
                "unknown")
        
        # Try different file_path field patterns  
        file_path = (node.get("file_path", "") or
                    node.get("f.file_path", "") or
                    node.get("contained.file_path", "") or
                    node.get("t.file_path", "") or
                    "unknown")
        
        return (str(name), str(file_path))
    
    def _count_rich_content_nodes(self, nodes: List[Dict[str, Any]]) -> int:
        """Count nodes with rich content (body, symbols_location, etc.)"""
        rich_count = 0
        
        for node in nodes:
            has_body = bool(node.get("body") or node.get("t.body"))
            has_symbols = bool(node.get("symbols_location") or node.get("t.symbols_location"))
            has_structure = any(node.get(prop) for prop in ["fields", "parameters", "base_list"])
            
            if has_body or has_symbols or has_structure:
                rich_count += 1
        
        return rich_count
    
    def _update_execution_stats(self, performance: Dict[str, Any]) -> None:
        """Update global execution statistics"""
        self.execution_stats["total_queries"] += performance.get("queries_executed", 0)
        self.execution_stats["total_execution_time"] += performance.get("total_execution_time", 0.0)
        
        if not performance.get("error", False):
            self.execution_stats["successful_queries"] += performance.get("queries_executed", 0)
        else:
            self.execution_stats["failed_queries"] += performance.get("queries_executed", 0)
        
        # Update average
        if self.execution_stats["total_queries"] > 0:
            self.execution_stats["average_query_time"] = round(
                self.execution_stats["total_execution_time"] / self.execution_stats["total_queries"], 3
            )
    
    def get_execution_statistics(self) -> Dict[str, Any]:
        """Get current execution statistics"""
        return self.execution_stats.copy()
    
    def reset_statistics(self) -> None:
        """Reset execution statistics"""
        self.execution_stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "total_execution_time": 0.0,
            "average_query_time": 0.0
        }
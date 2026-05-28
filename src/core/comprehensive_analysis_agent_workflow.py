#!/usr/bin/env python3
"""
Adaptive CPG Discovery Agent Workflow using LangGraph

This implements a proper agent workflow with states, transitions, and decision points
for intelligent CPG exploration to answer user queries.

Workflow States:
1. initialize_environment -> 2. initial_discovery -> 3. analyze_intent -> 
4. generate_query -> 5. execute_query -> 6. evaluate_sufficiency ->
7. [loop back to generate_query OR continue to] synthesize_response -> END

Each state is a node, and transitions are edges with conditions.
"""

import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, TypedDict, Annotated
from dataclasses import dataclass, asdict
import operator

# LangGraph imports
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
except ImportError:
    # Fallback if LangGraph not available
    class StateGraph:
        def __init__(self): pass
        def add_node(self, name, func): pass
        def add_edge(self, from_node, to_node): pass
        def add_conditional_edges(self, from_node, condition, mapping): pass
        def set_entry_point(self, node): pass
        def compile(self): return self
        async def ainvoke(self, state): return state
    END = "END"

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    """State maintained throughout the agent workflow"""
    # Input
    user_query: str
    project_name: str
    neo4j_config: str
    collection_name: str  # Vector search collection name
    
    # Environment
    neo4j_version: str
    schema: Dict[str, Any]
    
    # Discovery & Results - DETAILED STORAGE
    discovered_data: List[Dict[str, Any]]           # Processed/combined data
    query_history: List[Dict[str, Any]]             # Query metadata
    raw_query_results: List[Dict[str, Any]]         # RAW results from each query execution
    all_executed_queries: List[Dict[str, Any]]      # Complete query details with results
    
    # Intent & Planning
    intent: Dict[str, Any]
    current_iteration: int
    max_iterations: int
    
    # CLI Metadata (project_path, mappings_path, queries_path)
    metadata: Dict[str, Any]
    
    # Final Results  
    final_results: List[Dict[str, Any]]
    response: str
    
    # Control Flow
    current_node: str
    should_continue: bool
    error: Optional[str]
    
    # Query Generation & Execution
    next_query: str
    
    # Fallback System
    fallback_mode: bool
    remaining_fallback_strategies: List[Dict[str, Any]]
    fallback_strategy_used: Optional[str]
    
    # Vector Search Results
    vector_search_results: List[Dict[str, Any]]       # Raw vector search results
    vector_search_count: int                          # Count of vector results
    vector_ai_response: str                           # AI-validated response from vector RAG
    vector_metadata: Dict[str, Any]                   # Vector search metadata
    vector_search_raw_response: Dict[str, Any]        # Complete raw response from vector CLI
    vector_discovered_entities: List[str]             # Entities extracted from vector results
    vector_search_error: Optional[str]                # Vector search error message
    
    # Sufficiency Evaluation & CPG Error Handling
    data_gaps: Optional[str]                          # Sufficiency evaluation gaps/requirements
    body_exploration_needed: bool                     # Flag for entity body exploration due to CPG errors

class ComprehensiveAnalysisAgentWorkflow:
    """
    LangGraph-based agent workflow for comprehensive code analysis using multiple data sources
    """
    
    def __init__(self):
        self.graph = None
        self.llm_service = None
    
    def _validate_vector_data_in_state(self, state: AgentState, step_name: str) -> dict:
        """Validate vector data presence and integrity at each workflow step"""
        validation_result = {
            "step": step_name,
            "vector_search_results_present": bool(state.get("vector_search_results")),
            "vector_search_results_count": len(state.get("vector_search_results", [])),
            "vector_ai_response_present": bool(state.get("vector_ai_response", "").strip()),
            "vector_ai_response_length": len(state.get("vector_ai_response", "")),
            "vector_metadata_present": bool(state.get("vector_metadata")),
            "vector_discovered_entities_present": bool(state.get("vector_discovered_entities")),
            "vector_discovered_entities_count": len(state.get("vector_discovered_entities", [])),
            "collection_name_present": bool(state.get("collection_name"))
        }
        
        # Log validation results
        logger.info(f"🔍 VECTOR VALIDATION [{step_name}]:")
        logger.info(f"  ✓ Results: {validation_result['vector_search_results_count']} items")
        logger.info(f"  ✓ AI Response: {validation_result['vector_ai_response_length']} chars")
        logger.info(f"  ✓ Entities: {validation_result['vector_discovered_entities_count']} found")
        logger.info(f"  ✓ Collection: {'✅' if validation_result['collection_name_present'] else '❌'}")
        
        # Warn if vector data is missing unexpectedly
        if step_name in ["initial_discovery", "generate_query", "synthesize_response"]:
            if not validation_result["vector_search_results_present"]:
                logger.warning(f"⚠️  [{step_name}] Vector search results missing when expected")
            if not validation_result["vector_ai_response_present"]:
                logger.warning(f"⚠️  [{step_name}] Vector AI response missing when expected")
        
        return validation_result
        
    async def initialize_services(self):
        """Initialize required services"""
        from src.core.llm_service import LLMService
        from src.core.graph_query_executor import GraphQueryExecutor
        
        self.llm_service = LLMService({"cache_ttl": 1800})
        self.graph_executor = GraphQueryExecutor()
    
    def build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow"""
        
        # Create the state graph
        workflow = StateGraph(state_schema=AgentState)
        
        # Add nodes (states)
        workflow.add_node("initialize_environment", self.initialize_environment)
        workflow.add_node("analyze_intent", self.analyze_intent)
        workflow.add_node("vector_search", self.vector_search)
        workflow.add_node("initial_discovery", self.initial_discovery) 
        workflow.add_node("generate_query", self.generate_query)
        workflow.add_node("execute_query", self.execute_query)
        workflow.add_node("evaluate_sufficiency", self.evaluate_sufficiency)
        workflow.add_node("synthesize_response", self.synthesize_response)
        
        # Define the workflow edges
        workflow.add_edge("initialize_environment", "analyze_intent")
        
        # Conditional edge: route based on intent
        workflow.add_conditional_edges(
            "analyze_intent",
            self.should_use_vector_first,
            {
                "vector_search": "vector_search",  # Architectural queries go to vector first
                "initial_discovery": "initial_discovery"  # Other queries go directly to CPG
            }
        )
        
        workflow.add_edge("vector_search", "initial_discovery")
        workflow.add_edge("initial_discovery", "generate_query")
        workflow.add_edge("generate_query", "execute_query")
        workflow.add_edge("execute_query", "evaluate_sufficiency")
        
        # Conditional edge: continue exploring or synthesize
        workflow.add_conditional_edges(
            "evaluate_sufficiency",
            self.should_continue_exploring,
            {
                "continue": "generate_query",  # Loop back for more queries
                "synthesize": "synthesize_response",  # Move to synthesis
                "error": END  # Stop on error
            }
        )
        
        # End after synthesis
        workflow.add_edge("synthesize_response", END)
        
        # Set entry point
        workflow.set_entry_point("initialize_environment")
        
        return workflow
    
    async def run_workflow(self, user_query: str, project_name: str, 
                          neo4j_config: str, collection_name: str,
                          max_iterations: int = 10, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run the complete agent workflow"""
        
        await self.initialize_services()
        
        # Build and compile the workflow
        self.graph = self.build_workflow()
        compiled_graph = self.graph.compile()
        
        # Initial state
        initial_state: AgentState = {
            "user_query": user_query,
            "project_name": project_name,
            "neo4j_config": neo4j_config,
            "collection_name": collection_name,
            "neo4j_version": "",
            "schema": {},
            "discovered_data": [],
            "query_history": [],
            "raw_query_results": [],           # NEW: Store all raw results
            "all_executed_queries": [],       # NEW: Store complete query details
            "intent": {},
            "current_iteration": 0,
            "max_iterations": max_iterations,
            "final_results": [],
            "metadata": metadata or {},        # NEW: Store CLI parameter metadata
            "response": "",
            "current_node": "initialize_environment",
            "should_continue": True,
            "error": None,
            "next_query": "",
            "fallback_mode": False,           # NEW: Track if we're in fallback mode
            "remaining_fallback_strategies": [],  # NEW: Store unused fallback strategies
            "fallback_strategy_used": None,   # NEW: Track which fallback strategy was used
            
            # Vector Search Fields - Initialize with defaults
            "vector_search_results": [],      # Raw vector search results
            "vector_search_count": 0,         # Count of vector results
            "vector_ai_response": "",         # AI-validated response from vector RAG
            "vector_metadata": {},            # Vector search metadata
            "vector_search_raw_response": {}, # Complete raw response from vector CLI
            "vector_discovered_entities": [], # Entities extracted from vector results
            "vector_search_error": None,     # Vector search error message
            
            # Sufficiency Evaluation & CPG Error Handling
            "data_gaps": None,               # Sufficiency evaluation gaps/requirements  
            "body_exploration_needed": False # Flag for entity body exploration due to CPG errors
        }
        
        logger.info(f"🚀 Starting Adaptive CPG Agent Workflow for: {user_query}")
        
        # Execute the workflow
        try:
            final_state = await compiled_graph.ainvoke(initial_state)
            
            # Final validation before returning results
            final_vector_validation = self._validate_vector_data_in_state(final_state, "workflow_completion")
            
            return {
                "status": "success" if not final_state.get("error") else "error",
                "response": final_state.get("response", ""),
                "discovered_data": final_state.get("discovered_data", []),
                "query_history": final_state.get("query_history", []),
                "iterations_used": final_state.get("current_iteration", 0),
                "final_results": final_state.get("final_results", []),
                "intent": final_state.get("intent", {}),
                "workflow": "langgraph_agent",
                # NEW: Include structure-during-discovery results
                "organized_data": final_state.get("organized_data", {}),
                "architectural_summary": final_state.get("architectural_summary", {}),
                "synthesis_context_used": final_state.get("synthesis_context_used", 0),
                # NEW: Include all raw results for MCP compatibility
                "raw_query_results": final_state.get("raw_query_results", []),
                "all_executed_queries": final_state.get("all_executed_queries", []),
                "raw_results": final_state.get("raw_query_results", []),  # MCP compatibility alias
                "executed_queries": final_state.get("all_executed_queries", []),  # MCP compatibility alias
                # Vector search results for comprehensive RAG
                "vector_search_results": final_state.get("vector_search_results", []),
                "vector_ai_response": final_state.get("vector_ai_response", ""),
                "vector_metadata": final_state.get("vector_metadata", {}),
                "vector_discovered_entities": final_state.get("vector_discovered_entities", []),
                "agent_metadata": {
                    "neo4j_version": final_state.get("neo4j_version", ""),
                    "schema_nodes": len(final_state.get("schema", {}).get("nodes", [])),
                    "total_queries_executed": len(final_state.get("query_history", [])),
                    "total_raw_results": len(final_state.get("raw_query_results", [])),
                    "workflow_nodes_executed": 7,
                    "agents_involved": ["environment", "discovery", "intent", "query_generator", "expansion", "synthesis"]
                },
                "error": final_state.get("error")
            }
            
        except Exception as e:
            logger.error(f"❌ Workflow execution failed: {e}")
            return {
                "status": "error", 
                "error": str(e),
                "workflow": "langgraph_agent"
            }
    
    # ========== WORKFLOW NODE IMPLEMENTATIONS ==========
    
    async def initialize_environment(self, state: AgentState) -> AgentState:
        """Node: Initialize Neo4j environment and load schema"""
        logger.info("🔍 Node: initialize_environment")
        
        try:
            # Detect Neo4j version using CLI
            version_query = "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition"
            result = await self._execute_query_with_retry(version_query, "version_detection", state)
            
            neo4j_version = "5.x"  # Default
            if result["status"] == "success" and result.get("results"):
                version_info = result["results"][0]
                if version_info.get("name") == "Neo4j Kernel":
                    versions = version_info.get("versions", [])
                    if versions:
                        neo4j_version = versions[0]
            
            # Load schema
            try:
                import yaml
                schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
                with open(schema_path, 'r') as f:
                    schema = yaml.safe_load(f)
            except Exception as e:
                logger.warning(f"Could not load schema: {e}")
                schema = {"nodes": [], "relationships": []}
            
            state.update({
                "neo4j_version": neo4j_version,
                "schema": schema,
                "current_node": "initialize_environment"
            })
            
            logger.info(f"✅ Environment initialized - Neo4j: {neo4j_version}")
            return state
            
        except Exception as e:
            logger.error(f"❌ Environment initialization failed: {e}")
            state.update({
                "error": f"Environment initialization failed: {e}",
                "should_continue": False
            })
            return state
    
    async def vector_search(self, state: AgentState) -> AgentState:
        """Node: Vector search for architectural/comprehensive queries"""
        logger.info("🔍 Node: vector_search")
        logger.info(f"🔍 DEBUG - State type: {type(state)}")
        logger.info(f"🔍 DEBUG - State keys: {list(state.keys()) if isinstance(state, dict) else 'Not a dict'}")
        
        try:
            user_query = state.get('user_query', '')
            collection_name = state.get('collection_name')
            
            # Debug logging
            logger.info(f"🔍 DEBUG - State keys: {list(state.keys())}")
            logger.info(f"🔍 DEBUG - Collection name from state: '{collection_name}'")
            logger.info(f"🔍 DEBUG - User query: '{user_query}'")
            
            if not collection_name:
                raise ValueError("Collection name not found in state")
            
            # Execute vector search using MCP client
            result = await self._execute_vector_search(user_query, collection_name, state)
            
            if result.get('status') == 'success':
                # Extract from _execute_vector_search wrapper response
                vector_raw_results = result.get('raw_results', [])  # Wrapper transforms 'results' → 'raw_results'
                vector_ai_response = result.get('ai_response', '')  # Wrapper transforms 'response' → 'ai_response'
                vector_metadata = result.get('metadata', {})
                
                # Store COMPLETE vector search response in state 
                state.update({
                    "vector_search_results": vector_raw_results,  # Actual raw results array
                    "vector_search_count": len(vector_raw_results),
                    "vector_ai_response": vector_ai_response,  # The validated final answer
                    "vector_metadata": vector_metadata,
                    "vector_search_raw_response": result,  # Store complete response
                    "current_node": "vector_search"
                })
                
                logger.info(f"✅ Vector search completed: {len(vector_raw_results)} raw results found")
                logger.info(f"✅ Vector AI response length: {len(vector_ai_response)}")
                logger.info(f"✅ Vector metadata: {vector_metadata}")
                
                # Extract entities from raw results to inform CPG discovery
                vector_entities = await self._extract_entities_from_vector_results(vector_raw_results)
                state['vector_discovered_entities'] = vector_entities
                
                logger.info(f"🔍 Vector search discovered entities: {vector_entities}")
                
            else:
                logger.warning(f"⚠️  Vector search failed: {result.get('error', 'Unknown error')}")
                state.update({
                    "vector_search_results": [],
                    "vector_search_count": 0,
                    "vector_search_error": result.get('error', 'Vector search failed')
                })
            
            return state
            
        except Exception as e:
            logger.error(f"❌ Vector search failed: {e}")
            state.update({
                "error": f"Vector search failed: {e}",
                "vector_search_results": [],
                "vector_search_count": 0
            })
            return state
    
    async def initial_discovery(self, state: AgentState) -> AgentState:
        """Node: Perform initial lightweight discovery"""
        logger.info("📋 Node: initial_discovery")
        
        # Validate vector data at start of discovery
        self._validate_vector_data_in_state(state, "initial_discovery_start")
        
        try:
            logger.info(f"🔍 DEBUG - Starting discovery with schema: {state['schema']}")
            
            # Phase 1: Disambiguation & Clarification
            disambiguation_result = await self._disambiguate_query_terms(state)
            state.update(disambiguation_result)
            
            # Generate intent-driven discovery queries
            intent_analysis = state.get('intent_analysis', {})
            query_type = intent_analysis.get('query_type', 'architectural')
            scope = intent_analysis.get('scope', 'component')
            data_needed = intent_analysis.get('data_needed', 'moderate')
            target_elements = intent_analysis.get('target_elements', [])
            
            project_name = state['project_name']
            
            # Build dynamic disambiguation context
            disambiguation_context = ""
            if state.get('disambiguation_status') == 'completed':
                entities_found = state.get('entities_found', {})
                if entities_found:
                    disambiguation_context = f"""
            
            DISAMBIGUATION RESULTS (Phase 1):
            {json.dumps(entities_found, indent=2)}
            
            Key Entity Insights:
            {chr(10).join([f"- {entity}: {data['primary_type']} ({'FOUND' if data['found'] else 'NOT_FOUND'})" for entity, data in entities_found.items()])}
            """
            
            discovery_prompt = f"""
            CRITICAL: UNIVERSAL LANGUAGE-AGNOSTIC CPG DISCLAIMER
            =====================================================
            This is a UNIVERSAL, LANGUAGE-AGNOSTIC Code Property Graph that represents codebases 
            written in ANY programming language (C, C++, C#, Java, JavaScript, Python, COBOL, etc.).
            
            DO NOT make language-specific assumptions about node types:
            - "Function" node ≠ standalone function (could be method, procedure, subroutine)
            - "Type" node ≠ just classes (could be struct, interface, enum, typedef)
            - "Variable" node ≠ just variables (could be field, parameter, constant)
            
            RELY ONLY ON THE SCHEMA RELATIONSHIPS PROVIDED BELOW.
            The schema defines the ONLY valid connections between nodes.
            
            You are a strategic Neo4j Cypher expert. Generate targeted discovery queries based on intent analysis and disambiguation results:
            
            User Query: {state['user_query']}
            Project: {state['project_name']}
            Neo4j Version: {state['neo4j_version']} (use IS NULL syntax, not EXISTS)
            
            Intent Analysis:
            - Query Type: {query_type}
            - Scope: {scope} 
            - Data Needed: {data_needed}
            - Target Elements: {target_elements}
            - Strategy: {intent_analysis.get('strategy', 'general analysis')}
            {disambiguation_context}
            
            VECTOR SEARCH INSIGHTS:
            {self._build_vector_context(state)}
            
            Complete Schema Information:
            
            Node Types: {list(state['schema'].get('nodes', {}).keys())}
            
            Node Attributes (from schema):
            {chr(10).join([f"- {node}: {', '.join(attrs.get('attributes', []))}" for node, attrs in state['schema'].get('nodes', {}).items()])}
            
            Relationship Types: {list(state['schema'].get('relationships', {}).keys())}
            
            Relationship Definitions (from schema):
            {chr(10).join([f"- {rel}: {rel_def.get('from', 'Unknown')} → {rel_def.get('to', 'Unknown')}" for rel, rel_def in state['schema'].get('relationships', {}).items()])}
            
            IMPORTANT: Use ONLY the relationship types listed above in your queries. Do NOT invent relationships like DEPENDS_ON, USES, EXTENDS.
            
            Generate JSON with strategy-specific queries:
            {{
                "primary_query": "Main targeted query based on intent",
                "context_query": "Supporting query for context (if needed)"
            }}
            
            Strategy Guidelines:
            - LOOKUP ({data_needed} data): Direct targeted queries for specific elements
            - ARCHITECTURAL ({scope} scope): Strategic queries for relationships and dependencies  
            - EXPLORATION ({scope} scope): Broad but focused pattern discovery
            
            Dynamic Query Strategy Based on Disambiguation:
            {self._generate_dynamic_strategy_guidance(state)}
            
            Query Limits:
            - Minimal data: LIMIT 10-20
            - Moderate data: LIMIT 50-100  
            - Comprehensive data: Use sampling with LIMIT 100
            
            Project Filter: (n.project_name = '{state['project_name']}' OR n.project_name IS NULL)
            
            PROVEN WORKING QUERY PATTERNS (use these as templates):
            - Find Types: MATCH (p:Project {{name: '{project_name}'}})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t:Type) RETURN t.name, t.type_kind, f.name LIMIT 100
            - Find Functions: MATCH (p:Project {{name: '{project_name}'}})-[:CONTAINS]->(f:File)-[:CONTAINS]->(func:Function) RETURN func.name, f.name LIMIT 100  
            - Find Relationships: MATCH (p:Project {{name: '{project_name}'}})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t1:Type)-[:IMPLEMENTS]->(t2:Type) RETURN t1.name, t2.name LIMIT 100
            
            AVOID these patterns (they return empty results):
            - Type-[:DEFINED_IN]->File (use CONTAINS instead)
            - Direct relationship queries without Project/File path
            """
            
            queries_result = await self.llm_service.generate_response(discovery_prompt, json_mode=True)
            
            discovered_data = []
            query_history = []
            
            queries = {}
            if queries_result and not queries_result.error:
                try:
                    queries = json.loads(queries_result.content)
                    logger.info(f"🔍 DEBUG - Parsed queries: {type(queries)} = {queries}")
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Failed to parse LLM response as JSON: {e}")
                    logger.error(f"Raw content: {queries_result.content[:500]}")
                    queries = {}
            else:
                logger.error(f"❌ LLM queries_result error: {queries_result.error if queries_result else 'None'}")
                logger.error(f"❌ LLM queries_result content: {queries_result.content if queries_result else 'None'}")
                
            # Execute intent-driven discovery queries
            for query_type, query in queries.items():
                if query:
                    logger.info(f"🔍 DEBUG - About to execute {query_type}: {query}")
                    result = await self._execute_query_with_retry(
                        query, f"initial_{query_type}", state
                    )
                    logger.info(f"🔍 DEBUG - Query result type: {type(result)}")
                    logger.info(f"🔍 DEBUG - Query result: {result}")
                    
                    # Check result type for debugging
                    if not isinstance(result, dict):
                        logger.error(f"❌ Query execution returned {type(result)} instead of dict: {result}")
                        continue
                    
                    # Store complete query execution details
                    complete_query_info = {
                        "query": query,
                        "purpose": f"initial_{query_type}",
                        "status": result["status"],
                        "result_count": len(result.get("results", [])),
                        "results": result.get("results", []),        # RAW results included
                        "execution_time": result.get("execution_time", 0),
                        "agent": "discovery",
                        "phase": "initial_discovery",
                        "error": result.get("error"),
                        "cli_output": result.get("cli_output")        # Raw CLI output
                    }
                    state.get("all_executed_queries", []).append(complete_query_info)
                    
                    if result["status"] == "success":
                        query_results = result.get("results", [])
                        discovered_data.extend(query_results)
                        
                        # Store raw results separately for MCP compatibility
                        state.get("raw_query_results", []).extend(query_results)
                        
                        query_history.append({
                            "query": query,
                            "purpose": f"initial_{query_type}",
                            "result_count": len(query_results),
                            "status": "success"
                        })
                    else:
                        # INTELLIGENT FAILURE ANALYSIS: Diagnose why query failed
                        diagnosis = await self._diagnose_query_failure(query, result, state)
                        logger.warning(f"⚠️ Query failed - {diagnosis['reason']}: {diagnosis['details']}")
                        
                        # Store diagnosis for debugging
                        complete_query_info = {
                            "query": query,
                            "purpose": f"initial_{query_type}",
                            "status": result["status"],
                            "result_count": 0,
                            "results": [],
                            "execution_time": result.get("execution_time", 0),
                            "agent": "discovery",
                            "phase": "initial_discovery",
                            "error": result.get("error"),
                            "cli_output": result.get("cli_output"),
                            "failure_diagnosis": diagnosis
                        }
                        state.get("all_executed_queries", []).append(complete_query_info)
            
            # SMART FALLBACK: Use LLM diagnosis to generate corrected queries
            if not discovered_data:
                logger.warning("⚠️ No data discovered with LLM-generated queries. Analyzing failures and generating corrected queries...")
                
                # Collect corrected queries from diagnosis
                corrected_queries = []
                for query_info in state.get("all_executed_queries", []):
                    if query_info.get("failure_diagnosis", {}).get("corrected_query"):
                        corrected_query = query_info["failure_diagnosis"]["corrected_query"]
                        corrected_queries.append({
                            "query": corrected_query,
                            "purpose": f"corrected_{query_info['purpose']}",
                            "confidence": query_info["failure_diagnosis"].get("confidence", "UNKNOWN")
                        })
                
                # Generate intelligent fallback strategies using LLM
                intelligent_fallbacks = await self._generate_intelligent_fallbacks(state)
                fallback_queries = corrected_queries + intelligent_fallbacks
                
                logger.info(f"🔄 Trying {len(corrected_queries)} LLM-corrected queries + {len(intelligent_fallbacks)} intelligent fallbacks")
                
                for fallback in fallback_queries:
                    confidence = fallback.get("confidence", "UNKNOWN")
                    reasoning = fallback.get("reasoning", "")
                    logger.info(f"🔄 Trying {fallback['purpose']} (confidence: {confidence})")
                    if reasoning:
                        logger.info(f"   Reasoning: {reasoning}")
                    result = await self._execute_query_with_retry(
                        fallback["query"], fallback["purpose"], state
                    )
                    
                    if result["status"] == "success" and result.get("results"):
                        logger.info(f"✅ Fallback {fallback['purpose']} found {len(result['results'])} results")
                        discovered_data.extend(result["results"])
                        state.get("raw_query_results", []).extend(result["results"])
                        
                        query_history.append({
                            "query": fallback["query"],
                            "purpose": fallback["purpose"],
                            "result_count": len(result["results"]),
                            "status": "success"
                        })
                        
                        # Store complete query execution details
                        complete_query_info = {
                            "query": fallback["query"],
                            "purpose": fallback["purpose"],
                            "status": result["status"],
                            "result_count": len(result.get("results", [])),
                            "results": result.get("results", []),
                            "execution_time": result.get("execution_time", 0),
                            "agent": "discovery",
                            "phase": "fallback_discovery",
                            "error": result.get("error"),
                            "cli_output": result.get("cli_output")
                        }
                        state.get("all_executed_queries", []).append(complete_query_info)
                        break  # Stop after first successful fallback
                    else:
                        # Diagnose fallback failure too
                        diagnosis = await self._diagnose_query_failure(fallback["query"], result, state)
                        logger.warning(f"⚠️ Fallback {fallback['purpose']} failed - {diagnosis['reason']}: {diagnosis['details']}")
            
            # Organize discovered data hierarchically during discovery
            organized_data = self._organize_discovered_data(discovered_data, state)
            
            # Generate architectural summary from organized data
            architectural_summary = await self._generate_architectural_summary(organized_data, state)
            
            state.update({
                "discovered_data": discovered_data,  # Keep raw data for MCP compatibility
                "organized_data": organized_data,    # NEW: Hierarchical organization
                "architectural_summary": architectural_summary,  # NEW: Architectural insights
                "query_history": query_history,
                "current_node": "initial_discovery"
            })
            
            logger.info(f"✅ Initial discovery complete: {len(discovered_data)} items found, organized into {len(organized_data['classes'])} classes, {len(organized_data['interfaces'])} interfaces")
            return state
            
        except Exception as e:
            logger.error(f"❌ Initial discovery failed: {e}")
            state.update({"error": f"Initial discovery failed: {e}"})
            return state
    
    async def analyze_intent(self, state: AgentState) -> AgentState:
        """Node: Analyze user intent to determine discovery strategy"""
        logger.info("🎯 Node: analyze_intent")
        
        try:
            intent_prompt = f"""
            Analyze the user's query to determine the optimal discovery strategy:
            
            User Query: {state['user_query']}
            Project: {state['project_name']}
            Available Schema: {list(state['schema'].get('nodes', {}).keys())}
            
            Categorize this query and provide strategy guidance as JSON:
            {{
                "query_type": "lookup|architectural|exploration",
                "scope": "specific|component|system-wide", 
                "data_needed": "minimal|moderate|comprehensive",
                "strategy": "description of discovery approach",
                "target_elements": ["list", "of", "specific", "things", "to", "find"],
                "reasoning": "why this categorization"
            }}
            
            Categories:
            - LOOKUP: Finding specific functions, classes, files, definitions
            - ARCHITECTURAL: Understanding relationships, dependencies, design patterns
            - EXPLORATION: Broad analysis like security, APIs, all patterns
            
            Examples:
            - "Where is function calculateTotal defined?" → lookup/specific/minimal
            - "Show class dependencies in auth module" → architectural/component/moderate  
            - "What are all the API endpoints?" → exploration/system-wide/comprehensive
            """
            
            intent_result = await self.llm_service.generate_response(intent_prompt, json_mode=True)
            
            # Default fallback intent
            intent_analysis = {
                "query_type": "architectural",
                "scope": "component", 
                "data_needed": "moderate",
                "strategy": "general architectural analysis",
                "target_elements": [],
                "reasoning": "fallback analysis"
            }
            
            if intent_result and not intent_result.error:
                try:
                    parsed_intent = json.loads(intent_result.content)
                    intent_analysis.update(parsed_intent)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse intent JSON, using fallback")
            
            state.update({
                "intent_analysis": intent_analysis,
                "intent": intent_analysis["query_type"],  # Backward compatibility
                "current_node": "analyze_intent"
            })
            
            logger.info(f"✅ Intent analyzed: {intent_analysis['query_type']} | {intent_analysis['scope']} | {intent_analysis['data_needed']}")
            return state
            
        except Exception as e:
            logger.error(f"❌ Intent analysis failed: {e}")
            state.update({"error": f"Intent analysis failed: {e}"})
            return state
    
    async def generate_query(self, state: AgentState) -> AgentState:
        """Node: Generate next query based on current state"""
        logger.info(f"🔍 Node: generate_query (iteration {state['current_iteration'] + 1})")
        
        # Validate vector data for query generation
        self._validate_vector_data_in_state(state, "generate_query")
        
        # Check if we're in fallback mode and need diverse strategies
        if state.get("fallback_mode", False):
            return await self._generate_diverse_fallback_queries(state)
        
        try:
            state["current_iteration"] += 1
            
            # Check if body exploration is needed
            if state.get("body_exploration_needed", False):
                return await self._generate_body_exploration_query(state)
            
            # Include disambiguation results and schema information
            entities_found = state.get('entities_found', {})
            schema = state.get('schema', {})
            
            disambiguation_info = ""
            if entities_found:
                disambiguation_info = f"""
            
            DISAMBIGUATION RESULTS:
            {chr(10).join([f"- '{entity}' → {data['primary_type']} node ({'FOUND' if data['found'] else 'NOT_FOUND'})" for entity, data in entities_found.items()])}
            """
            
            query_prompt = f"""
            CRITICAL: UNIVERSAL LANGUAGE-AGNOSTIC CPG DISCLAIMER
            =====================================================
            This is a UNIVERSAL, LANGUAGE-AGNOSTIC Code Property Graph that represents codebases 
            written in ANY programming language (C, C++, C#, Java, JavaScript, Python, COBOL, etc.).
            
            DO NOT make language-specific assumptions about node types:
            - "Function" node ≠ standalone function (could be method, procedure, subroutine)
            - "Type" node ≠ just classes (could be struct, interface, enum, typedef)
            - "Variable" node ≠ just variables (could be field, parameter, constant)
            
            RELY ONLY ON THE SCHEMA RELATIONSHIPS PROVIDED BELOW.
            The schema defines the ONLY valid connections between nodes.
            
            Generate the NEXT Cypher query needed to answer the user's question:
            
            User Query: {state['user_query']}
            Intent: {state['intent']}
            Iteration: {state['current_iteration']}/{state['max_iterations']}
            
            Current Data: {len(state['discovered_data'])} items
            Previous Queries: {[q.get('purpose', 'unknown') if isinstance(q, dict) else str(q) for q in state['query_history']]}
            {disambiguation_info}
            
            SCHEMA INFORMATION (USE ONLY THESE):
            Available Node Types: {list(schema.get('nodes', {}).keys())}
            Available Relationships: {list(schema.get('relationships', {}).keys())}
            
            Node Attributes Available:
            {chr(10).join([f"- {node}: {', '.join(attrs.get('attributes', []))}" for node, attrs in schema.get('nodes', {}).items()])}
            
            IMPORTANT GUIDELINES:
            - Use ONLY the node types and relationships listed above
            - Use disambiguation results to know exact entity types found  
            - Follow containment hierarchies: Project → File → Type → Function
            - For finding instantiations, search function body content using: WHERE func.body CONTAINS 'new ClassName'
            - Neo4j Version: {state['neo4j_version']} (use IS NULL, not EXISTS)
            - Project Filter: (n.project_name = '{state['project_name']}' OR n.project_name IS NULL)
            
            
            Generate ONE targeted Cypher query or return "COMPLETE" if no more queries needed.
            Include LIMIT for performance. Return ONLY the Cypher query, no markdown formatting.
            """
            
            query_result = await self.llm_service.generate_response(query_prompt)
            
            next_query = ""
            if query_result and not query_result.error:
                next_query = query_result.content.strip()
                
                # Remove markdown code blocks if present - but be defensive
                original_query = next_query
                if next_query.startswith("```cypher"):
                    next_query = next_query[9:]  # Remove ```cypher
                elif next_query.startswith("```"):
                    next_query = next_query[3:]   # Remove ```
                if next_query.endswith("```"):
                    next_query = next_query[:-3]  # Remove trailing ```
                
                next_query = next_query.strip()
                
                # If we accidentally removed the entire query, restore it
                if not next_query and original_query:
                    next_query = original_query.strip()
                    logger.warning(f"⚠️ Markdown removal emptied query, restored: {next_query[:50]}...")
            
            # Update state directly instead of using .update() for LangGraph compatibility
            state["next_query"] = next_query
            state["current_node"] = "generate_query"
            
            logger.info(f"🔍 DEBUG - Storing next_query: '{next_query}'")
            logger.info(f"🔍 DEBUG - next_query length: {len(next_query)}")
            logger.info(f"🔍 DEBUG - State updated with next_query")
            logger.info(f"🔍 DEBUG - Verifying state before return: next_query = '{state.get('next_query', 'MISSING')}'")
            
            if next_query.upper() in ["COMPLETE", "NULL", "NONE", ""]:
                logger.info("✅ Query generation complete - no more queries needed")
                state["should_continue"] = False
            else:
                logger.info(f"✅ Generated query: {next_query[:100]}...")
            
            return state
            
        except Exception as e:
            logger.error(f"❌ Query generation failed: {e}")
            state.update({"error": f"Query generation failed: {e}"})
            return state
    
    async def _generate_body_exploration_query(self, state: AgentState) -> AgentState:
        """Generate query to explore entity bodies when relationships are missing/unclear"""
        logger.info("🔍 Generating body exploration query for entities with missing relationships")
        
        try:
            # Extract entity names from the sufficiency response
            data_gaps = state.get("data_gaps", "")
            
            # Get discovered entities that exist but might have missing relationships
            discovered_entities = [item.get('name', '') for item in state.get('discovered_data', []) 
                                 if item.get('name') and item.get('name').strip()]
            
            if not discovered_entities:
                logger.warning("No discovered entities found for body exploration")
                state["body_exploration_needed"] = False
                return state
            
            # Focus on first few entities to avoid overwhelming queries
            target_entities = discovered_entities[:5]
            
            # Generate query to get entity bodies/implementations
            body_query = f"""
            MATCH (t:Type)
            WHERE t.name IN {target_entities}
            RETURN t.name, t.type_kind, t.body, t.fields, t.base_list, 
                   t.file_path, t.access_modifier, t.is_abstract
            LIMIT 20
            """
            
            state.update({
                "next_query": body_query.strip(),
                "current_node": "generate_query",
                "body_exploration_needed": False  # Clear flag after generating query
            })
            
            logger.info(f"✅ Generated body exploration query for entities: {target_entities}")
            return state
            
        except Exception as e:
            logger.error(f"❌ Body exploration query generation failed: {e}")
            state.update({
                "error": f"Body exploration query generation failed: {e}",
                "body_exploration_needed": False
            })
            return state
    
    async def _generate_diverse_fallback_queries(self, state: AgentState) -> AgentState:
        """
        Generate diverse query strategies when primary approach has failed
        """
        logger.info("🔄 Generating diverse fallback query strategies")
        
        try:
            state["current_iteration"] += 1
            
            user_query = state['user_query']
            project_name = state['project_name']
            neo4j_version = state['neo4j_version']
            schema = state.get('schema', {})
            entities_found = state.get('entities_found', {})
            query_history = state.get('query_history', [])
            
            # Build context about what we've tried and failed
            failed_attempts = []
            for query_info in query_history[-5:]:  # Last 5 attempts
                if query_info.get('result_count', 0) == 0:
                    failed_attempts.append({
                        "query": query_info.get('query', 'Unknown'),
                        "approach": query_info.get('purpose', 'Unknown')
                    })
            
            diverse_strategy_prompt = f"""
            CRITICAL: UNIVERSAL LANGUAGE-AGNOSTIC CPG DISCLAIMER
            =====================================================
            This is a UNIVERSAL, LANGUAGE-AGNOSTIC Code Property Graph that represents codebases 
            written in ANY programming language (C, C++, C#, Java, JavaScript, Python, COBOL, etc.).
            
            DO NOT make language-specific assumptions about node types:
            - "Function" node ≠ standalone function (could be method, procedure, subroutine)
            - "Type" node ≠ just classes (could be struct, interface, enum, typedef)
            - "Variable" node ≠ just variables (could be field, parameter, constant)
            
            RELY ONLY ON THE SCHEMA RELATIONSHIPS PROVIDED BELOW.
            The schema defines the ONLY valid connections between nodes.
            
            You are generating DIVERSE FALLBACK QUERY STRATEGIES after primary approaches failed.
            
            USER QUERY: {user_query}
            PROJECT: {project_name}
            NEO4J VERSION: {neo4j_version} (use IS NULL syntax, not EXISTS)
            
            AVAILABLE GRAPH SCHEMA:
            Node Types: {list(schema.get('nodes', {}).keys())}
            Node Attributes: {json.dumps({k: v.get('attributes', []) for k, v in schema.get('nodes', {}).items()}, indent=2)}
            Relationships: {list(schema.get('relationships', {}).keys())}
            
            DISAMBIGUATION RESULTS:
            {json.dumps(entities_found, indent=2) if entities_found else "No specific entities found"}
            
            FAILED APPROACHES (avoid these patterns):
            {json.dumps(failed_attempts, indent=2) if failed_attempts else "No previous failures"}
            
            Generate 3-4 DIVERSE search strategies that use DIFFERENT approaches:
            
            1. **Content-Based Search**: Search in body/documentation properties of nodes
            2. **Fuzzy/Pattern Matching**: Use CONTAINS, regex, or partial name matching  
            3. **Broader Context Search**: Search related entities or broader scope
            4. **Alternative Entity Types**: Try different node types than previously attempted
            
            For each strategy, provide:
            - A single Cypher query that explores the codebase differently
            - Focus on finding ANY relevant information, not just exact matches
            - Use node properties like body, documentation, fields, parameters
            - Project filter: (n.project_name = '{project_name}' OR n.project_name IS NULL)
            
            Return JSON format:
            {{
                "strategies": [
                    {{
                        "approach": "content_search",
                        "query": "MATCH (n) WHERE n.body CONTAINS 'search_term' RETURN n.name, n.body LIMIT 10",
                        "reasoning": "Search for mentions in code body content"
                    }},
                    {{
                        "approach": "fuzzy_match", 
                        "query": "MATCH (n) WHERE n.name =~ '.*pattern.*' RETURN n.name, labels(n) LIMIT 10",
                        "reasoning": "Find entities with similar names"
                    }}
                ]
            }}
            
            Generate queries that are FUNDAMENTALLY DIFFERENT from failed approaches.
            """
            
            strategy_result = await self.llm_service.generate_response(diverse_strategy_prompt, json_mode=True)
            
            if strategy_result and not strategy_result.error:
                try:
                    strategies = json.loads(strategy_result.content)
                    
                    if isinstance(strategies, dict) and "strategies" in strategies:
                        fallback_queries = strategies["strategies"]
                        
                        if fallback_queries and len(fallback_queries) > 0:
                            # Select the first diverse strategy for this iteration
                            selected_strategy = fallback_queries[0]
                            
                            logger.info(f"🔄 Selected fallback strategy: {selected_strategy.get('approach', 'unknown')}")
                            logger.info(f"🔄 Reasoning: {selected_strategy.get('reasoning', 'no reasoning')}")
                            
                            # Store remaining strategies for future iterations
                            remaining_strategies = fallback_queries[1:]
                            state["remaining_fallback_strategies"] = remaining_strategies
                            
                            state.update({
                                "next_query": selected_strategy["query"],
                                "current_node": "generate_query",
                                "fallback_strategy_used": selected_strategy["approach"]
                            })
                            
                            return state
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse diverse strategy JSON: {e}")
            
            # Fallback failed, mark as complete
            logger.warning("🔄 Diverse strategy generation failed, marking as complete")
            state.update({
                "next_query": "COMPLETE",
                "current_node": "generate_query",
                "fallback_mode": False,
                "should_continue": False
            })
            
            return state
            
        except Exception as e:
            logger.error(f"❌ Diverse fallback generation failed: {e}")
            return {
                **state,
                "error": str(e),
                "next_query": "COMPLETE",
                "current_node": "generate_query",
                "fallback_mode": False,
                "should_continue": False
            }
    
    async def execute_query(self, state: AgentState) -> AgentState:
        """Node: Execute the generated query"""
        logger.info("⚡ Node: execute_query")
        
        try:
            logger.info(f"🔍 DEBUG - Full state keys: {list(state.keys())}")
            next_query = state.get("next_query", "")
            logger.info(f"🔍 DEBUG - Retrieved next_query: '{next_query}'")
            logger.info(f"🔍 DEBUG - next_query length: {len(next_query)}")
            logger.info(f"🔍 DEBUG - next_query type: {type(next_query)}")
            logger.info(f"🔍 DEBUG - State object ID: {id(state)}")
            
            if not next_query or next_query.upper() in ["COMPLETE", "NULL", "NONE"]:
                logger.info("No query to execute")
                return state
            
            result = await self._execute_query_with_retry(
                next_query, 
                f"iteration_{state['current_iteration']}", 
                state
            )
            
            # Store complete query execution details
            complete_query_info = {
                "query": next_query,
                "purpose": f"iteration_{state['current_iteration']}",
                "status": result["status"],
                "result_count": len(result.get("results", [])),
                "results": result.get("results", []),              # RAW results included
                "execution_time": result.get("execution_time", 0),
                "agent": "expansion",
                "phase": "iterative_expansion", 
                "iteration": state['current_iteration'],
                "error": result.get("error"),
                "cli_output": result.get("cli_output")            # Raw CLI output
            }
            state.get("all_executed_queries", []).append(complete_query_info)
            
            if result["status"] == "success":
                new_results = result.get("results", [])
                state["discovered_data"].extend(new_results)
                
                # Store raw results separately for MCP compatibility
                state.get("raw_query_results", []).extend(new_results)
                
                logger.info(f"✅ Query executed: {len(new_results)} new results")
            else:
                logger.warning(f"Query execution failed: {result.get('error')}")
            
            # Add to query history (metadata only)
            state["query_history"].append({
                "query": next_query,
                "purpose": f"iteration_{state['current_iteration']}",
                "result_count": len(result.get("results", [])),
                "status": result["status"],
                "iteration": state['current_iteration']
            })
            
            state.update({"current_node": "execute_query"})
            return state
            
        except Exception as e:
            logger.error(f"❌ Query execution failed: {e}")
            state.update({"error": f"Query execution failed: {e}"})
            return state
    
    async def evaluate_sufficiency(self, state: AgentState) -> AgentState:
        """Node: Evaluate if we have sufficient information"""
        logger.info("🧠 Node: evaluate_sufficiency")
        
        try:
            # Check iteration limit
            if state["current_iteration"] >= state["max_iterations"]:
                logger.info(f"✅ Reached max iterations ({state['max_iterations']})")
                state["should_continue"] = False
                return state
            
            # FALLBACK DETECTION: Check if we need diverse query strategies
            fallback_activated = await self._check_fallback_needed(state)
            if fallback_activated:
                logger.info("🔄 Activating diverse query fallback system")
                state["fallback_mode"] = True
                state["should_continue"] = True  # Continue with fallback strategies
                return state
            
            # LLM-based completeness evaluation including BOTH vector and CPG data
            vector_ai_response = state.get('vector_ai_response', '')
            vector_results_count = len(state.get('vector_search_results', []))
            
            sufficiency_prompt = f"""
            Analyze the completeness of discovered data for answering the user's query:
            
            User Query: {state['user_query']}
            Intent: {state['intent']}
            
            === VECTOR SEARCH RESULTS ===
            Vector Results Found: {vector_results_count} code chunks
            Vector AI Response ({len(vector_ai_response)} chars):
            {vector_ai_response}
            
            === CPG STRUCTURAL DATA ===
            Discovered Data ({len(state['discovered_data'])} items):
            {json.dumps(state['discovered_data'][:20], indent=2)}
            
            === CPG QUERY EXECUTION HISTORY ===
            Total Queries Executed: {len(state.get('query_history', []))}
            Query Execution Details:
            {chr(10).join([f"Query {i+1}: {query.get('purpose', 'Unknown')} ({'SUCCESS' if query.get('status') == 'success' else 'FAILED'})" + (f" - {len(query.get('results', []))} results" if query.get('status') == 'success' else f" - {query.get('error', 'Unknown error')}") for i, query in enumerate(state.get('query_history', []))])}
            
            Raw Query Results ({len(state.get('raw_query_results', []))} total):
            {json.dumps(state.get('raw_query_results', [])[:10], indent=2) if state.get('raw_query_results') else 'No raw results available'}
            
            Available Graph Schema:
            Node Types: {list(state['schema'].get('nodes', {}).keys())}
            Relationship Types: {list(state['schema'].get('relationships', {}).keys())}
            
            Iteration: {state['current_iteration']}/{state['max_iterations']}
            
            Analyze COMBINED data completeness:
            1. Does the Vector AI Response already provide a good answer to the user's question?
            2. Does the CPG data add structural detail that enhances the vector response?
            3. Are there references to classes/types that we haven't discovered structurally?
            4. For inheritance/interface relationships, do we have both vector context and CPG relationships?
            5. Based on the query execution history, have we adequately explored the CPG structure?
            6. Were there failed queries that indicate missing data or relationships we should investigate?
            7. Do the raw query results show patterns or gaps that require additional targeted queries?
            8. **TOLERANCE FOR CPG ERRORS**: If relationships are missing/unclear due to CPG creation issues, can we drill into entity BODY content to extract implementation details (e.g., class body, method implementations, field declarations)?
            9. **ENTITY BODY EXPLORATION**: Are there key entities where we need to examine their body/implementation to understand relationships that weren't captured in the CPG structure?
            10. Can we provide a comprehensive answer combining both data sources?
            
            Return "SUFFICIENT" if we can adequately answer the user's question with the COMBINED vector + CPG data, or "NEED_MORE" explaining what specific data is missing.
            
            **SPECIAL CASE**: If CPG relationships are corrupted/missing but entities exist, return "NEED_BODY_EXPLORATION" followed by a list of entity names whose bodies should be examined for implementation details.
            """
            
            sufficiency_result = await self.llm_service.generate_response(sufficiency_prompt)
            
            is_sufficient = False
            if sufficiency_result and not sufficiency_result.error:
                answer = sufficiency_result.content.strip().upper()
                is_sufficient = "SUFFICIENT" in answer
                
                # Handle body exploration request
                if "NEED_BODY_EXPLORATION" in answer:
                    # Extract entity names for body exploration
                    state["body_exploration_needed"] = True
                    state["data_gaps"] = sufficiency_result.content
                    # Force continuation for body exploration
                    is_sufficient = False
                    logger.info("🔍 Body exploration requested for entities with missing/unclear relationships")
                
                # Extract what additional data is needed if insufficient
                elif not is_sufficient and "NEED_MORE" in answer:
                    # Store gaps for next iteration's query generation
                    state["data_gaps"] = sufficiency_result.content
            
            state.update({
                "should_continue": not is_sufficient,
                "current_node": "evaluate_sufficiency"
            })
            
            logger.info(f"✅ Sufficiency evaluation: {'Sufficient' if is_sufficient else 'Need more'}")
            logger.info(f"✅ State updated: should_continue = {state['should_continue']}")
            return state
            
        except Exception as e:
            logger.error(f"❌ Sufficiency evaluation failed: {e}")
            state.update({"error": f"Sufficiency evaluation failed: {e}"})
            return state
    
    async def _check_fallback_needed(self, state: AgentState) -> bool:
        """
        Check if we need to activate diverse query fallback strategies
        """
        current_iteration = state.get('current_iteration', 1)
        discovered_data = state.get('discovered_data', [])
        query_history = state.get('query_history', [])
        
        # Activate fallback if:
        # 1. We're past iteration 2
        # 2. We have zero or very minimal results
        # 3. Recent queries are returning empty results
        
        if current_iteration <= 2:
            return False
            
        if len(discovered_data) > 5:  # If we have substantial data, don't need fallback
            return False
            
        # Check if recent queries are consistently failing
        recent_queries = query_history[-3:] if len(query_history) >= 3 else query_history
        recent_failures = [q for q in recent_queries if q.get('result_count', 0) == 0]
        
        if len(recent_failures) >= 2:  # 2+ consecutive failures
            logger.info(f"🔄 Fallback needed: {len(recent_failures)} recent failures, {len(discovered_data)} total results")
            return True
            
        return False
    
    async def synthesize_response(self, state: AgentState) -> AgentState:
        """Node: Synthesize final response with smart context management"""
        logger.info("🧠 Node: synthesize_response")
        
        # Validate vector data before synthesis
        vector_validation = self._validate_vector_data_in_state(state, "synthesize_response")
        
        try:
            # Use smart context management - prioritize organized data over raw data
            context_data = self._prepare_synthesis_context(state)
            
            user_query = state['user_query']
            intent = state.get('intent', 'Unknown')
            
            vector_results = self._format_vector_results_for_synthesis(state)
            
            architectural_summary_json = json.dumps(context_data['architectural_summary'], indent=2)
            organized_data_json = json.dumps(context_data['organized_data'], indent=2)
            sample_raw_data_json = json.dumps(context_data['sample_raw_data'], indent=2)
            
            
            synthesis_prompt = f"""
            Synthesize a comprehensive answer based on BOTH vector search insights and CPG structural data:
            
            User Query: {user_query}
            Intent: {intent}
            
            === VECTOR SEARCH RESULTS ===
            {vector_results}
            
            === CPG ARCHITECTURAL SUMMARY ===
            {architectural_summary_json}
            
            === CPG ORGANIZED STRUCTURE ===
            {organized_data_json}
            
            === CPG COMPLETE RAW DATA ===
            {json.dumps(state.get('discovered_data', []), indent=2)}
            
            === ALL CPG QUERY EXECUTION DETAILS ===
            {json.dumps(state.get('all_executed_queries', []), indent=2)}
            
            === EXECUTION METADATA ===
            Project: {state['project_name']}
            Vector Results: {len(state.get('vector_search_results', []))}
            CPG Iterations: {state['current_iteration']}
            CPG Queries Executed: {len(state['query_history'])}
            Total CPG Raw Results: {len(state['discovered_data'])}
            
            === SYNTHESIS INSTRUCTIONS ===
            **INTENT-AWARE RESPONSE STRATEGY**:
            
            For LOOKUP queries (specific, minimal):
            - Provide a direct, concise answer to the specific question
            - Avoid unnecessary architectural explanations 
            - Skip cross-validation details unless inconsistencies found
            - Format: "The [answer] is [value]." followed by brief context if needed
            
            For ARCHITECTURAL queries (system-wide, comprehensive):
            - Provide comprehensive response combining vector + CPG data
            - Include architectural overview and structural relationships
            - Cross-validate findings between data sources
            - Explain data source reliability and discrepancies
            
            **CURRENT QUERY INTENT: {state.get('intent', 'Unknown')}**
            
            **RESPONSE REQUIREMENTS**:
            1. Match response detail level to query intent
            2. Use actual discovered data only (no fabrication)
            3. For lookup queries: direct answer first, minimal explanation
            4. For architectural queries: comprehensive analysis with cross-validation
            - Provide evidence from both sources for claims made
            """
            
            synthesis_result = await self.llm_service.generate_response(synthesis_prompt)
            
            response = "Unable to generate response"
            if synthesis_result and not synthesis_result.error:
                initial_response = synthesis_result.content
                
                # Validate response against retrieved data to prevent hallucination
                validated_response = await self._validate_response_against_data(
                    initial_response, context_data, state
                )
                response = validated_response
            
            state.update({
                "response": response,
                "final_results": state["discovered_data"],
                "current_node": "synthesize_response",
                "synthesis_context_used": context_data['context_size']
            })
            
            # Final validation - ensure vector data is preserved in state
            final_validation = self._validate_vector_data_in_state(state, "synthesize_response_complete")
            
            logger.info(f"✅ Response synthesized and validated ({len(response)} chars) using {context_data['context_size']} context chars")
            logger.info(f"✅ Final vector data validation: {final_validation['vector_search_results_count']} results, {final_validation['vector_ai_response_length']} chars AI response")
            return state
            
        except Exception as e:
            logger.error(f"❌ Response synthesis failed: {e}")
            state.update({
                "error": f"Response synthesis failed: {e}",
                "response": f"Error generating response: {e}"
            })
            return state
    
    # ========== WORKFLOW CONTROL FUNCTIONS ==========
    
    def should_use_vector_first(self, state: AgentState) -> str:
        """Route based on intent - architectural queries use vector search first"""
        intent = state.get('intent', '').lower()
        
        # Architectural intents that benefit from vector search
        architectural_keywords = [
            'architectural', 'architecture', 'overview', 'structure', 'design',
            'patterns', 'relationships', 'dependencies', 'interactions', 'flow',
            'components', 'modules', 'system', 'overall'
        ]
        
        if any(keyword in intent for keyword in architectural_keywords):
            logger.info(f"🔍 Intent '{intent}' requires vector search first")
            return "vector_search"
        else:
            logger.info(f"🔍 Intent '{intent}' goes directly to CPG discovery")
            return "initial_discovery"
    
    def should_continue_exploring(self, state: AgentState) -> str:
        """Conditional edge: decide whether to continue exploring or synthesize"""
        
        logger.info(f"🔀 should_continue_exploring: Evaluating routing decision")
        logger.info(f"🔀 State keys present: {list(state.keys())}")
        logger.info(f"🔀 should_continue value: {state.get('should_continue', 'MISSING')}")
        logger.info(f"🔀 current_iteration: {state.get('current_iteration', 'MISSING')}")
        logger.info(f"🔀 max_iterations: {state.get('max_iterations', 'MISSING')}")
        logger.info(f"🔀 error: {state.get('error', 'None')}")
        
        if state.get("error"):
            logger.info("🔀 Routing to: error")
            return "error"
        
        # Since should_continue is defined in AgentState TypedDict, it should always be present
        # When evaluate_sufficiency sets should_continue=False (meaning "sufficient"), 
        # we should route to synthesize, not continue
        should_continue = state["should_continue"]  # Direct access since it's guaranteed by TypedDict
        logger.info(f"🔀 should_continue extracted: {should_continue}")
        
        if not should_continue:
            logger.info("🔀 Routing to: synthesize (should_continue=False)")
            return "synthesize"
        
        if state.get("current_iteration", 0) >= state.get("max_iterations", 5):
            logger.info("🔀 Routing to: synthesize (max iterations reached)")
            return "synthesize"
        
        logger.info("🔀 Routing to: continue")
        return "continue"
    
    # ========== HELPER FUNCTIONS ==========
    
    def _organize_discovered_data(self, raw_data: List[Dict], state: AgentState) -> Dict[str, Any]:
        """Structure discovered data hierarchically during discovery"""
        
        organized = {
            "interfaces": {},
            "classes": {},
            "functions": {},
            "relationships": {
                "inheritance": [],
                "implementation": [],
                "contains": [],
                "calls": []
            },
            "architectural_patterns": {
                "entry_points": {},
                "factory_patterns": {},
                "design_patterns": []
            },
            "project_overview": {
                "main_components": set(),
                "dependency_flows": [],
                "missing_dependencies": [],
                "completeness_gaps": []
            }
        }
        
        # Process raw query results and organize by type
        for item in raw_data:
            self._categorize_discovered_item(item, organized)
        
        # Convert sets to lists for JSON serialization
        organized["project_overview"]["main_components"] = list(organized["project_overview"]["main_components"])
        
        return organized
    
    def _categorize_discovered_item(self, item: Dict, organized: Dict):
        """Categorize a single discovered item into hierarchical structure"""
        
        # Handle relationship data (TypeName, Relationship, RelatedTypeName/ParentTypeName format)
        if "TypeName" in item and "Relationship" in item and ("RelatedTypeName" in item or "ParentTypeName" in item or "SuperTypeName" in item):
            type_name = item["TypeName"]
            relationship = item["Relationship"]
            related_type = item.get("RelatedTypeName") or item.get("ParentTypeName") or item.get("SuperTypeName")
            
            # Validate data - skip invalid or self-referencing relationships
            if not type_name or not relationship or not related_type:
                return  # Skip empty/invalid data
            
            if type_name == related_type and relationship in ["IMPLEMENTS", "INHERITS_FROM"]:
                return  # Skip self-referencing relationships (likely query errors)
            
            # Add to main components
            organized["project_overview"]["main_components"].add(type_name)
            organized["project_overview"]["main_components"].add(related_type)
            
            # Categorize by relationship type
            if relationship == "IMPLEMENTS":
                # IMPLEMENTS relationship indicates related_type is likely an interface/contract
                # Don't assume naming conventions - treat all IMPLEMENTS targets as interfaces
                if related_type not in organized["interfaces"]:
                    organized["interfaces"][related_type] = {
                        "name": related_type,
                        "implementers": [],
                        "type": "interface"
                    }
                # Add implementer - avoid duplicates
                if type_name not in organized["interfaces"][related_type]["implementers"]:
                    organized["interfaces"][related_type]["implementers"].append(type_name)
                
                # Add class info
                if type_name not in organized["classes"]:
                    organized["classes"][type_name] = {
                        "name": type_name,
                        "implements": [],
                        "type": "class"
                    }
                
                # Add implements relationship - avoid duplicates
                if related_type not in organized["classes"][type_name]["implements"]:
                    organized["classes"][type_name]["implements"].append(related_type)
                
                # Record relationship - avoid duplicates
                relationship_record = {
                    "from": type_name,
                    "to": related_type,
                    "type": "implements"
                }
                if relationship_record not in organized["relationships"]["implementation"]:
                    organized["relationships"]["implementation"].append(relationship_record)
                
                # Store relationships for later LLM-driven pattern analysis
                        
            elif relationship == "INHERITS_FROM":
                # Class inheritance - avoid duplicates
                relationship_record = {
                    "from": type_name,
                    "to": related_type,
                    "type": "inherits"
                }
                if relationship_record not in organized["relationships"]["inheritance"]:
                    organized["relationships"]["inheritance"].append(relationship_record)
                
        # Handle node data (n format from previous queries)
        elif "n" in item:
            node = item["n"]
            node_type = node.get("type", "")
            node_name = node.get("name", "")
            
            # Validate node data
            if not node_name:
                return  # Skip nodes without names
            
            if node_type == "Type":
                type_kind = node.get("type_kind", "")
                
                if type_kind == "interface" and node_name not in organized["interfaces"]:
                    organized["interfaces"][node_name] = {
                        "name": node_name,
                        "type": "interface",
                        "file_path": node.get("file_path", ""),
                        "body": node.get("body", ""),
                        "implementers": []
                    }
                elif type_kind == "class" and node_name not in organized["classes"]:
                    organized["classes"][node_name] = {
                        "name": node_name,
                        "type": "class", 
                        "file_path": node.get("file_path", ""),
                        "body": node.get("body", ""),
                        "implements": []
                    }
                    
                    # Store class data - no hardcoded pattern detection based on naming or content
                
            elif node_type == "Function":
                func_name = node.get("name", "")
                if func_name and func_name not in organized["functions"]:  # Validate and deduplicate
                    organized["functions"][func_name] = {
                        "name": func_name,
                        "return_type": node.get("return_type", ""),
                        "parameters": node.get("parameters", ""),
                        "file_path": node.get("file_path", "")
                    }
        
        # Handle class-function mappings (Class, Functions format)
        elif "Class" in item and "Functions" in item:
            class_name = item["Class"]
            functions = item["Functions"]
            
            # Validate data
            if not class_name:
                return  # Skip invalid class names
            
            organized["project_overview"]["main_components"].add(class_name)
            
            # Add to classes if not exists
            if class_name not in organized["classes"]:
                organized["classes"][class_name] = {
                    "name": class_name,
                    "type": "class",
                    "functions": [],
                    "implements": []
                }
            
            # Add functions - no pattern detection based on naming
            organized["classes"][class_name]["functions"] = functions
    
    async def _generate_architectural_summary(self, organized_data: Dict[str, Any], state: AgentState) -> Dict[str, Any]:
        """Generate architectural insights using LLM analysis - no hardcoded patterns"""
        
        # Use LLM to analyze architectural patterns instead of hardcoded logic
        
        architectural_analysis_prompt = f"""
        Analyze the following code structure and identify architectural patterns based on relationships and usage, NOT naming conventions.
        This could be any programming language (C#, COBOL, Java, Fortran, etc.) so don't assume naming patterns.
        
        === STRUCTURAL DATA ===
        Interfaces/Contracts: {json.dumps(organized_data.get('interfaces', {}), indent=2)}
        Classes/Components: {json.dumps(organized_data.get('classes', {}), indent=2)}
        Relationships: {json.dumps(organized_data.get('relationships', {}), indent=2)}
        
        === ANALYSIS INSTRUCTIONS ===
        Based on structural relationships only (not naming), identify:
        1. Architectural patterns (Factory, Observer, Strategy, etc.) from component interactions
        2. Component roles based on relationship patterns (entry points, coordinators, implementors)
        3. Dependency flows from relationship chains
        4. Missing information gaps that would help understand the architecture
        
        Return JSON format:
        {{
          "project_overview": {{
            "main_patterns": ["pattern based on structure"],
            "key_components": ["most connected components"],
            "dependency_flows": ["component chains based on relationships"],
            "missing_dependencies": ["gaps in relationship data"],
            "completeness_gaps": ["missing structural information"]
          }},
          "architectural_insights": {{
            "design_patterns": ["patterns identified from structure"],
            "interface_usage": {{"interface_name": {{"implementers": [...], "usage_pattern": "pattern"}}}},
            "component_roles": {{"component": "role based on relationships"}},
            "coupling_analysis": {{"high_coupling": [...], "low_coupling": [...]}}
          }},
          "expansion_suggestions": {{
            "missing_implementations": ["components referenced but not detailed"],
            "incomplete_chains": ["broken dependency chains"],
            "potential_queries": ["suggested queries to fill gaps"]
          }}
        }}
        """
        
        try:
            # Use LLM to analyze patterns without hardcoded assumptions
            analysis_result = await self.llm_service.generate_response(
                architectural_analysis_prompt, 
                json_mode=True
            )
            
            if analysis_result and not analysis_result.error:
                try:
                    summary = json.loads(analysis_result.content)
                    logger.info("✅ Generated architectural summary using LLM analysis")
                    return summary
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse LLM architectural analysis: {e}")
            
        except Exception as e:
            logger.error(f"LLM architectural analysis failed: {e}")
        
        # Fallback: Basic structural summary without pattern assumptions
        return self._generate_basic_structural_summary(organized_data)
    
    def _prepare_structural_context(self, organized_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare structural context for LLM analysis"""
        return {
            "interface_count": len(organized_data.get("interfaces", {})),
            "class_count": len(organized_data.get("classes", {})),
            "relationship_types": list(set(
                rel.get("type", "") for rel in organized_data.get("relationships", {}).get("implementation", [])
            )),
            "component_summary": {
                name: {
                    "implements": data.get("implements", []),
                    "function_count": len(data.get("functions", []))
                } for name, data in organized_data.get("classes", {}).items()
            }
        }
    
    def _generate_basic_structural_summary(self, organized_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate basic structural summary without pattern assumptions"""
        interfaces = organized_data.get("interfaces", {})
        classes = organized_data.get("classes", {})
        relationships = organized_data.get("relationships", {})
        
        return {
            "project_overview": {
                "main_patterns": ["Component-based Architecture" if interfaces else "Procedural Architecture"],
                "key_components": list(classes.keys())[:10],
                "dependency_flows": [f"Found {len(relationships.get('implementation', []))} implementation relationships"],
                "missing_dependencies": [],
                "completeness_gaps": ["Detailed function relationships not analyzed"]
            },
            "architectural_insights": {
                "design_patterns": [],
                "interface_usage": {name: {"implementers": data.get("implementers", []), "usage_pattern": "Contract Definition"} for name, data in interfaces.items()},
                "component_roles": {name: "Component" for name in list(classes.keys())[:5]},
                "coupling_analysis": {}
            },
            "expansion_suggestions": {
                "missing_implementations": [f"Detailed analysis needed for {name}" for name in list(classes.keys())[:3]],
                "incomplete_chains": ["Function call relationships not mapped"],
                "potential_queries": [
                    "MATCH (f1:Function)-[:CALLS]->(f2:Function) RETURN f1.name AS Caller, f2.name AS Callee LIMIT 50"
                ]
            }
        }
    
    def _prepare_synthesis_context(self, state: AgentState) -> Dict[str, Any]:
        """Prepare smart context for synthesis - prioritize organized data and manage context size"""
        
        # Get available data
        organized_data = state.get("organized_data", {})
        architectural_summary = state.get("architectural_summary", {})
        raw_data = state.get("discovered_data", [])
        intent = state.get("intent", "unknown")
        
        # Smart sampling strategy based on intent
        sample_raw_data = self._sample_raw_data(raw_data, intent, max_samples=20)
        
        # Prepare context with size management
        context = {
            "architectural_summary": architectural_summary,
            "organized_data": organized_data,
            "sample_raw_data": sample_raw_data
        }
        
        # Calculate approximate context size
        context_json = json.dumps(context, indent=2)
        context_size = len(context_json)
        
        # If context is too large, apply compression strategies
        if context_size > 15000:  # Target max context size
            context = self._compress_context(context, intent)
            context_json = json.dumps(context, indent=2)
            context_size = len(context_json)
        
        return {
            "architectural_summary": context["architectural_summary"],
            "organized_data": context["organized_data"],
            "sample_raw_data": context["sample_raw_data"],
            "context_size": context_size
        }
    
    def _sample_raw_data(self, raw_data: List[Dict], intent: str, max_samples: int = 20) -> List[Dict]:
        """Smart sampling of raw data based on query intent"""
        
        if not raw_data:
            return []
        
        if len(raw_data) <= max_samples:
            return raw_data
        
        # Intent-based sampling strategies
        if intent == "lookup":
            # For lookup queries, prioritize unique relationships
            unique_relationships = {}
            for item in raw_data:
                if "TypeName" in item and "Relationship" in item:
                    key = f"{item['TypeName']}-{item['Relationship']}"
                    if key not in unique_relationships:
                        unique_relationships[key] = item
            return list(unique_relationships.values())[:max_samples]
        
        elif intent == "architectural":
            # For architectural queries, prioritize diverse patterns
            patterns = {"IMPLEMENTS": [], "INHERITS_FROM": [], "CONTAINS": [], "CALLS": []}
            for item in raw_data:
                relationship = item.get("Relationship", "")
                if relationship in patterns and len(patterns[relationship]) < max_samples // 4:
                    patterns[relationship].append(item)
            
            # Flatten and return diverse sample
            diverse_sample = []
            for pattern_items in patterns.values():
                diverse_sample.extend(pattern_items)
            return diverse_sample[:max_samples]
        
        elif intent == "exploration":
            # For exploration, provide representative samples across all types
            return raw_data[::max(1, len(raw_data) // max_samples)][:max_samples]
        
        else:
            # Default: take first N items
            return raw_data[:max_samples]
    
    def _compress_context(self, context: Dict[str, Any], intent: str) -> Dict[str, Any]:
        """Compress context when it exceeds size limits"""
        
        compressed = context.copy()
        
        # Always keep architectural summary - it's already compressed
        # Compress organized data based on intent
        organized_data = compressed.get("organized_data", {})
        
        if intent == "lookup":
            # For lookup, keep interfaces and classes but limit details
            if "interfaces" in organized_data:
                for interface_name, interface_data in organized_data["interfaces"].items():
                    if len(interface_data.get("implementers", [])) > 5:
                        interface_data["implementers"] = interface_data["implementers"][:5] + ["..."]
            
            if "classes" in organized_data:
                # Limit to top 10 classes
                classes = dict(list(organized_data["classes"].items())[:10])
                organized_data["classes"] = classes
        
        elif intent == "architectural":
            # For architectural, keep pattern info but limit component details
            if "project_overview" in organized_data:
                main_components = organized_data["project_overview"].get("main_components", [])
                if len(main_components) > 15:
                    organized_data["project_overview"]["main_components"] = main_components[:15] + ["..."]
        
        elif intent == "exploration":
            # For exploration, keep diverse samples but reduce depth
            if "classes" in organized_data:
                # Keep only class names and key properties
                simplified_classes = {}
                for class_name, class_data in list(organized_data["classes"].items())[:8]:
                    simplified_classes[class_name] = {
                        "name": class_data.get("name"),
                        "type": class_data.get("type"),
                        "implements": class_data.get("implements", [])[:3]
                    }
                organized_data["classes"] = simplified_classes
        
        # Reduce sample raw data if still too large
        sample_raw_data = compressed.get("sample_raw_data", [])
        if len(sample_raw_data) > 10:
            compressed["sample_raw_data"] = sample_raw_data[:10]
        
        compressed["organized_data"] = organized_data
        
        return compressed
    
    async def _disambiguate_query_terms(self, state: AgentState) -> Dict[str, Any]:
        """
        Phase 1: Dynamically disambiguate ambiguous terms using available schema and data
        """
        logger.info("🔍 Phase 1: Disambiguating query terms")
        
        try:
            user_query = state.get('user_query', '')
            schema = state.get('schema', {})
            available_node_types = list(schema.get('nodes', {}).keys())
            available_attributes = {}
            
            # Build dynamic attribute mapping from schema
            for node_type, node_def in schema.get('nodes', {}).items():
                available_attributes[node_type] = node_def.get('attributes', [])
            
            # Dynamic prompt based on actual schema - FOCUSED ON ENTITY TYPE IDENTIFICATION
            extraction_prompt = f"""
            Analyze this user query to extract specific entity names and determine what types they likely represent:
            
            User Query: "{user_query}"
            
            Available Entity Types in Schema: {available_node_types}
            
            Entity Attributes Available:
            {json.dumps(available_attributes, indent=2)}
            
            Extract entity names from the query and predict their likely types. Return JSON:
            {{
                "entities": [
                    {{
                        "name": "extracted_name",
                        "likely_types": ["TYPE_DECL", "METHOD", "etc"],
                        "context": "how it appears in query",
                        "relationship_intent": "what user wants to know about this entity"
                    }}
                ],
                "query_intent": "what relationships/properties user is asking about",
                "expected_result_type": "classes|methods|variables|relationships"
            }}
            
            Focus on identifying:
            1. Class names (likely TYPE_DECL nodes)
            2. Method/function names (likely METHOD nodes) 
            3. Variable names (likely LOCAL/IDENTIFIER nodes)
            4. What relationships the user wants to explore
            """
            
            extraction_result = await self.llm_service.generate_response(extraction_prompt, json_mode=True)
            
            if extraction_result.error:
                logger.warning(f"Entity extraction failed: {extraction_result.error}")
                return {"disambiguation_status": "failed"}
            
            try:
                extraction_data = json.loads(extraction_result.content)
                entities = extraction_data.get("entities", [])
                query_intent = extraction_data.get("query_intent", "")
                
                if not entities:
                    logger.info("No specific entities identified - proceeding with general discovery")
                    return {"disambiguation_status": "no_entities", "entities_found": {}}
                
                # Test each entity against its predicted types in the actual schema
                disambiguated_entities = {}
                for entity_info in entities:
                    entity_name = entity_info.get("name", "")
                    likely_types = entity_info.get("likely_types", [])
                    context = entity_info.get("context", "")
                    
                    logger.info(f"🔍 Disambiguating: {entity_name} (predicted: {likely_types})")
                    
                    # Test each predicted type to see if entity exists
                    found_matches = []
                    for predicted_type in likely_types:
                        if predicted_type in available_node_types:
                            # Generate targeted query for this specific type
                            disambiguation_query = f"""
                            // UNIVERSAL LANGUAGE-AGNOSTIC CPG QUERY
                            // This works for ANY programming language (C#, Java, Python, COBOL, etc.)
                            // Uses only schema-defined node types and attributes
                            MATCH (n:{predicted_type}) 
                            WHERE n.name = '{entity_name}' OR n.name CONTAINS '{entity_name}'
                            RETURN labels(n) AS node_types, n.name AS name, n.type_kind AS type_kind, 
                                   n.file_path AS file_path, n.id AS node_id
                            LIMIT 5
                            """
                            
                            result = await self._execute_query_with_retry(
                                disambiguation_query, f"disambiguate_{entity_name}_{predicted_type}", state
                            )
                            
                            if result["status"] == "success" and result.get("results"):
                                found_matches.extend(result["results"])
                                logger.info(f"✅ Found {entity_name} as {predicted_type}: {len(result['results'])} matches")
                    
                    if found_matches:
                        disambiguated_entities[entity_name] = {
                            "found": True,
                            "matches": found_matches,
                            "primary_type": found_matches[0].get("node_types", ["Unknown"])[0] if found_matches else "Unknown",
                            "predicted_types": likely_types,
                            "context": context,
                            "relationship_intent": entity_info.get("relationship_intent", "")
                        }
                        logger.info(f"✅ {entity_name} confirmed as: {disambiguated_entities[entity_name]['primary_type']}")
                    else:
                        disambiguated_entities[entity_name] = {
                            "found": False,
                            "matches": [],
                            "primary_type": "Unknown",
                            "predicted_types": likely_types,
                            "context": context,
                            "relationship_intent": entity_info.get("relationship_intent", "")
                        }
                        logger.warning(f"❌ {entity_name} not found in codebase (searched types: {likely_types})")
                
                return {
                    "disambiguation_status": "completed",
                    "entities_found": disambiguated_entities,
                    "query_intent": query_intent,
                    "total_entities": len(entities),
                    "found_entities": len([e for e in disambiguated_entities.values() if e["found"]])
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse entity extraction JSON: {e}")
                return {"disambiguation_status": "parse_error"}
                
        except Exception as e:
            logger.error(f"Disambiguation failed: {e}")
            return {"disambiguation_status": "error", "error": str(e)}
    
    def _generate_dynamic_strategy_guidance(self, state: AgentState) -> str:
        """Generate dynamic query strategy guidance based on disambiguation results and schema"""
        
        entities_found = state.get('entities_found', {})
        schema = state.get('schema', {})
        
        if not entities_found:
            return "No specific entities identified - use general discovery patterns"
        
        guidance_parts = []
        
        for entity, entity_data in entities_found.items():
            if entity_data.get('found'):
                primary_type = entity_data.get('primary_type', 'Unknown')
                available_attributes = schema.get('nodes', {}).get(primary_type, {}).get('attributes', [])
                
                guidance_parts.append(f"- {entity} (confirmed {primary_type}): Available attributes {available_attributes}")
                
                # Check if body attribute is available for content search
                if 'body' in available_attributes:
                    guidance_parts.append(f"  → {entity} has 'body' attribute - use for content-level queries")
                    guidance_parts.append(f"  → Example: MATCH (n:{primary_type} {{name: '{entity}'}}) WHERE n.body IS NOT NULL RETURN n.body")
            else:
                guidance_parts.append(f"- {entity} (NOT FOUND): Consider alternative search approaches")
        
        return '\n'.join(guidance_parts) if guidance_parts else "Entities found but no specific guidance available"
    
    async def _generate_intelligent_fallbacks(self, state: AgentState) -> List[Dict[str, Any]]:
        """
        Generate intelligent fallback queries based on failed queries and available context
        """
        logger.info("🔍 Generating intelligent fallback strategies")
        
        try:
            # Analyze what failed and what information is available
            failed_queries = [q for q in state.get("all_executed_queries", []) if q.get("status") != "success"]
            user_query = state.get('user_query', '')
            intent_analysis = state.get('intent_analysis', {})
            entities_found = state.get('entities_found', {})
            schema = state.get('schema', {})
            project_name = state.get('project_name', '')
            
            # Build comprehensive failure analysis for LLM
            failure_analysis_prompt = f"""
            CRITICAL: UNIVERSAL LANGUAGE-AGNOSTIC CPG DISCLAIMER
            =====================================================
            This is a UNIVERSAL, LANGUAGE-AGNOSTIC Code Property Graph that represents codebases 
            written in ANY programming language (C, C++, C#, Java, JavaScript, Python, COBOL, etc.).
            
            DO NOT make language-specific assumptions about node types:
            - "Function" node ≠ standalone function (could be method, procedure, subroutine)
            - "Type" node ≠ just classes (could be struct, interface, enum, typedef)
            - "Variable" node ≠ just variables (could be field, parameter, constant)
            
            RELY ONLY ON THE SCHEMA RELATIONSHIPS PROVIDED BELOW.
            The schema defines the ONLY valid connections between nodes.
            
            Generate intelligent fallback query strategies based on comprehensive failure analysis.
            
            USER QUERY: {user_query}
            
            INTENT ANALYSIS:
            {json.dumps(intent_analysis, indent=2)}
            
            DISAMBIGUATION RESULTS:
            {json.dumps(entities_found, indent=2)}
            
            FAILED QUERIES ANALYSIS:
            {json.dumps([{{
                'query': q.get('query', ''),
                'purpose': q.get('purpose', ''),
                'status': q.get('status', ''),
                'result_count': q.get('result_count', 0),
                'error': q.get('error'),
                'failure_diagnosis': q.get('failure_diagnosis', {})
            }} for q in failed_queries], indent=2)}
            
            AVAILABLE SCHEMA:
            Node Types: {list(schema.get('nodes', {}).keys())}
            Available Attributes per Node:
            {json.dumps({node: attrs.get('attributes', []) for node, attrs in schema.get('nodes', {}).items()}, indent=2)}
            Available Relationships: {list(schema.get('relationships', {}).keys())}
            
            PROJECT CONTEXT: {project_name}
            
            Based on this analysis, generate progressive fallback strategies that:
            1. Learn from the specific failure patterns
            2. Use available schema information intelligently
            3. Consider the user's actual intent
            4. Provide alternative approaches when entities aren't found structurally
            
            IMPORTANT: Return ONLY a JSON array (not an object) of fallback strategies:
            [
              {{
                "query": "Cypher query based on failure analysis",
                "purpose": "descriptive purpose",  
                "confidence": "HIGH|MEDIUM|LOW",
                "reasoning": "why this approach should work"
              }}
            ]
            
            Start your response with [ and end with ]. Do not wrap in any other JSON structure.
            """
            
            fallback_result = await self.llm_service.generate_response(failure_analysis_prompt, json_mode=True)
            
            if fallback_result.error:
                logger.warning(f"Intelligent fallback generation failed: {fallback_result.error}")
                return []
            
            try:
                fallback_strategies = json.loads(fallback_result.content)
                
                if not isinstance(fallback_strategies, list):
                    logger.warning(f"Fallback strategies not a list: {type(fallback_strategies)}")
                    # Try to extract strategies from object format if it's a dict
                    if isinstance(fallback_strategies, dict) and 'strategies' in fallback_strategies:
                        fallback_strategies = fallback_strategies['strategies']
                        logger.info("Extracted strategies from object wrapper")
                    elif isinstance(fallback_strategies, dict) and 'fallbacks' in fallback_strategies:
                        fallback_strategies = fallback_strategies['fallbacks']
                        logger.info("Extracted fallbacks from object wrapper")
                    else:
                        return []
                
                logger.info(f"✅ Generated {len(fallback_strategies)} intelligent fallback strategies")
                
                # Validate and clean fallback strategies
                valid_fallbacks = []
                for strategy in fallback_strategies:
                    if isinstance(strategy, dict) and strategy.get('query'):
                        valid_fallbacks.append({
                            "query": strategy.get('query', ''),
                            "purpose": strategy.get('purpose', 'intelligent_fallback'),
                            "confidence": strategy.get('confidence', 'MEDIUM'),
                            "reasoning": strategy.get('reasoning', 'LLM-generated fallback')
                        })
                
                return valid_fallbacks
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse intelligent fallback JSON: {e}")
                return []
                
        except Exception as e:
            logger.error(f"Intelligent fallback generation failed: {e}")
            return []
    
    async def _diagnose_query_failure(self, query: str, result: Dict[str, Any], state: AgentState) -> Dict[str, Any]:
        """
        LLM-powered intelligent diagnosis of why a Cypher query failed or returned empty results
        """
        
        schema = state.get('schema', {})
        project_name = state.get('project_name', '')
        
        # Prepare diagnosis prompt for LLM
        diagnosis_prompt = f"""
        CRITICAL: UNIVERSAL LANGUAGE-AGNOSTIC CPG DISCLAIMER
        =====================================================
        This is a UNIVERSAL, LANGUAGE-AGNOSTIC Code Property Graph that represents codebases 
        written in ANY programming language (C, C++, C#, Java, JavaScript, Python, COBOL, etc.).
        
        DO NOT make language-specific assumptions about node types:
        - "Function" node ≠ standalone function (could be method, procedure, subroutine)
        - "Type" node ≠ just classes (could be struct, interface, enum, typedef)
        - "Variable" node ≠ just variables (could be field, parameter, constant)
        
        RELY ONLY ON THE SCHEMA RELATIONSHIPS PROVIDED BELOW.
        The schema defines the ONLY valid connections between nodes.
        
        You are a Neo4j Cypher query diagnostician. A query has failed or returned empty results.
        
        FAILED QUERY:
        ```cypher
        {query}
        ```
        
        EXECUTION RESULT:
        - Status: {result.get('status')}
        - Results Count: {len(result.get('results', []))}
        - Error: {result.get('error', 'None')}
        - Detailed Error: {result.get('detailed_error', 'None')}
        - Error Type: {result.get('error_type', 'None')}
        - CLI Output: {result.get('cli_output', 'None')[:500] if result.get('cli_output') else 'None'}
        
        DATABASE SCHEMA (Available Node Types and Relationships):
        Node Types: {list(schema.get('nodes', {}).keys())}
        Relationship Types: {list(schema.get('relationships', {}).keys())}
        
        Relationship Definitions:
        {chr(10).join([f"- {rel}: {rel_def.get('from', 'Unknown')} → {rel_def.get('to', 'Unknown')}" for rel, rel_def in schema.get('relationships', {}).items()])}
        
        PROJECT CONTEXT:
        - Target Project: {project_name}
        
        ANALYZE THE FAILURE and provide diagnosis in JSON format:
        {{
            "reason": "Primary failure category (SYNTAX_ERROR|SCHEMA_MISMATCH|NO_DATA|CLI_ERROR|RELATIONSHIP_PATTERN_ISSUE)",
            "details": "Detailed technical explanation of what went wrong",
            "root_cause": "The fundamental issue causing the failure",
            "suggestions": ["Specific actionable recommendations", "Alternative query approaches", "Schema-aware fixes"],
            "corrected_query": "Suggested corrected Cypher query (if applicable)",
            "confidence": "HIGH|MEDIUM|LOW - confidence in this diagnosis"
        }}
        
        DIAGNOSIS GUIDELINES:
        1. If CLI output is empty/invalid → CLI_ERROR
        2. If query uses non-existent node types/relationships → SCHEMA_MISMATCH  
        3. If query syntax is invalid → SYNTAX_ERROR
        4. If query is valid but returns no results → NO_DATA or RELATIONSHIP_PATTERN_ISSUE
        5. Focus on Neo4j 5.x compatibility
        6. Suggest working alternatives based on the schema
        """
        
        try:
            diagnosis_result = await self.llm_service.generate_response(diagnosis_prompt, json_mode=True)
            
            if diagnosis_result and not diagnosis_result.error:
                import json
                diagnosis = json.loads(diagnosis_result.content)
                
                # Add metadata for debugging
                diagnosis.update({
                    "query_analyzed": query,
                    "execution_status": result.get('status'),
                    "results_count": len(result.get('results', [])),
                    "schema_nodes": list(schema.get('nodes', {}).keys()),
                    "schema_relationships": list(schema.get('relationships', {}).keys())
                })
                
                return diagnosis
            else:
                # Fallback if LLM fails
                return {
                    "reason": "DIAGNOSIS_FAILED",
                    "details": f"LLM diagnosis failed: {diagnosis_result.error if diagnosis_result else 'No response'}",
                    "root_cause": "Unable to analyze query failure",
                    "suggestions": ["Manually review query syntax", "Check Neo4j logs", "Verify schema"],
                    "corrected_query": None,
                    "confidence": "LOW"
                }
                
        except Exception as e:
            return {
                "reason": "DIAGNOSIS_ERROR", 
                "details": f"Exception during diagnosis: {str(e)}",
                "root_cause": "Diagnosis system failure",
                "suggestions": ["Review query manually", "Check system logs"],
                "corrected_query": None,
                "confidence": "LOW"
            }
    
    async def _validate_response_against_data(self, response: str, context_data: Dict, state: AgentState) -> str:
        """Validate response against ALL retrieved data using LLM analysis to prevent hallucination"""
        logger.info("🔍 Validating response against complete retrieved data")
        
        try:
            # Get ALL raw data - let LLM analyze everything
            all_raw_data = state.get('discovered_data', [])
            
            validation_prompt = f"""
            Validate this response against ALL retrieved raw data to prevent hallucination and assess data quality:
            
            RESPONSE TO VALIDATE:
            {response}
            
            COMPLETE RAW RETRIEVED DATA:
            {json.dumps(all_raw_data, indent=2)}
            
            USER QUERY INTENT: {state.get('intent', 'Unknown')}
            
            VALIDATION TASK:
            1. Analyze ALL the raw data to extract every entity name, relationship, and piece of information
            2. Cross-reference the response against this complete data inventory
            3. Identify any entities or information in the response that are NOT found in the raw data
            4. Detect data quality issues in the raw data (e.g., impossible relationships, duplicates, inconsistencies)
            5. Assess if data corruption contributed to potential hallucination in the response
            6. **INTENT VALIDATION**: Check if response detail level matches query intent:
               - LOOKUP queries: Should be concise, direct answers without architectural details
               - ARCHITECTURAL queries: Should be comprehensive with full analysis
            7. **VERBOSITY CHECK**: Flag responses that are overly verbose for simple lookup questions
            
            Return JSON with:
            {{
                "validated_response": "Corrected response that matches query intent and uses only raw data",
                "hallucination_detected": true/false,
                "fabricated_entities": ["entities mentioned in response but not in raw data"],
                "intent_appropriate": true/false,
                "verbosity_issue": "NONE/EXCESSIVE/INSUFFICIENT - assess if detail level matches query intent",
                "data_quality_assessment": "Analysis of raw data quality issues discovered",
                "data_quality_score": "HIGH/MEDIUM/LOW based on data consistency",
                "next_iteration_recommendation": "Suggested approach for next iteration if data quality is poor"
            }}
            
            CORRECTION RULES:
            - If entities are mentioned that don't exist in raw data, remove them or replace with "Data not available"
            - **INTENT-BASED CORRECTIONS**: For LOOKUP queries, simplify verbose responses to direct answers
            - **VERBOSITY CORRECTIONS**: Remove unnecessary architectural explanations from simple lookup responses
            - If data quality is poor, acknowledge limitations and suggest body content search
            - If relationships seem impossible (class implementing itself), flag as data corruption
            - Be transparent about data quality issues rather than fabricating information
            """
            
            validation_result = await self.llm_service.generate_response(validation_prompt, json_mode=True)
            
            logger.info(f"🔍 LLM validation response received: {validation_result}")

            if validation_result and not validation_result.error:
                # Implement feedback loop for LLM format validation
                max_format_retries = 3
                validation_data = None
                
                for retry_attempt in range(max_format_retries):
                    try:
                        validation_data = json.loads(validation_result.content)
                        break  # Success - exit retry loop
                        
                    except json.JSONDecodeError as e:
                        logger.warning(f"⚠️  LLM returned invalid JSON format (attempt {retry_attempt + 1}/{max_format_retries})")
                        logger.warning(f"Raw LLM response: {validation_result.content[:200]}...")
                        
                        if retry_attempt < max_format_retries - 1:
                            # Create feedback prompt to fix format
                            format_correction_prompt = f"""
You returned an invalid JSON format. Here's what you returned:
{validation_result.content[:500]}

Error details: {str(e)}

Please return your response in EXACTLY this JSON format:
{{
    "hallucination_detected": true/false,
    "fabricated_entities": ["entity1", "entity2", ...],
    "data_quality_score": "HIGH/MEDIUM/LOW",
    "data_quality_assessment": "your assessment text",
    "response_appropriateness": "APPROPRIATE/TOO_VERBOSE/TOO_CONCISE",
    "appropriateness_reason": "explanation of appropriateness",
    "validated_response": "the final validated response text",
    "next_iteration_recommendation": "recommendations for next iteration"
}}

Return ONLY the JSON object, no other text.
"""
                            
                            retry_result = await self.llm_service.generate_response(format_correction_prompt, json_mode=True)
                            if retry_result and not retry_result.error:
                                validation_result = retry_result
                            else:
                                logger.error(f"❌ Format correction attempt {retry_attempt + 1} failed")
                                break
                        else:
                            logger.error("❌ Max format retry attempts reached, using original response")
                            return response
                
                if validation_data:
                    # Log validation results
                    if validation_data.get('hallucination_detected'):
                        logger.warning(f"⚠️  Hallucination detected. Fabricated entities: {validation_data.get('fabricated_entities', [])}")
                    
                    if validation_data.get('data_quality_score') == 'LOW':
                        logger.warning(f"⚠️  Low data quality detected. Assessment: {validation_data.get('data_quality_assessment', 'None')}")
                    
                    # Store validation metadata for potential next iteration
                    state['validation_metadata'] = {
                        'hallucination_detected': validation_data.get('hallucination_detected', False),
                        'data_quality_score': validation_data.get('data_quality_score', 'UNKNOWN'),
                        'data_quality_assessment': validation_data.get('data_quality_assessment', ''),
                        'next_iteration_recommendation': validation_data.get('next_iteration_recommendation', '')
                    }
                    
                    logger.info("✅ Response validated with LLM-driven quality assessment")
                    return validation_data.get('validated_response', response)
                else:
                    logger.error("❌ Failed to get valid JSON format from LLM after retries")
                    return response
            else:
                logger.warning("⚠️  Validation failed, returning original response")
                return response
                
        except Exception as e:
            logger.error(f"❌ Response validation failed: {e}")
            return response
    
    async def _execute_vector_search(self, query: str, collection_name: str, state: AgentState) -> Dict[str, Any]:
        """Execute vector search using direct CLI call matching query_vector_only format"""
        try:
            import subprocess
            import os
            
            # Build CLI command (same as query_vector_only tool)
            cli_command = [
                "genpod-semantic-rag", "query", query,
                "--collection-name", collection_name,
                "--max-results", "25",  # Match the reference implementation
                "--output-format", "json"
            ]
            
            logger.info(f"🔍 Executing Vector CLI: {' '.join(cli_command)}")
            
            result = subprocess.run(
                cli_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )
            
            logger.info(f"🔍 Vector CLI return code: {result.returncode}")
            logger.info(f"🔍 Vector CLI stdout length: {len(result.stdout)}")
            if result.stderr:
                logger.warning(f"🔍 Vector CLI stderr: {result.stderr}")
            
            if result.returncode == 0:
                try:
                    # Parse the enhanced vector response structure (matching reference)
                    parsed_result = json.loads(result.stdout)
                    logger.info(f"🔍 Vector parsed result keys: {list(parsed_result.keys()) if isinstance(parsed_result, dict) else 'Not a dict'}")
                    logger.info(f"🔍 DEBUG - Full vector response structure:")
                    logger.info(f"  - query: {parsed_result.get('query', 'N/A')}")
                    logger.info(f"  - response: {len(str(parsed_result.get('response', '')))} chars")
                    logger.info(f"  - results: {len(parsed_result.get('results', []))} items")
                    logger.info(f"  - total_results: {parsed_result.get('total_results', 'N/A')}")
                    sample_results = parsed_result.get('results', [{}])[:1]
                    logger.info(f"  - first result sample: {str(sample_results)}")
                    
                    if isinstance(parsed_result, dict) and "query" in parsed_result and "results" in parsed_result:
                        # Successful vector RAG response format
                        return {
                            "status": "success",
                            "ai_response": parsed_result.get("response", ""),  # The corrected/validated response
                            "raw_results": parsed_result.get("results", []),
                            "metadata": parsed_result.get("metadata", {}),
                            "query": query,
                            "collection": collection_name,
                            "total_results": parsed_result.get("total_results", 0),
                            "processing_time": parsed_result.get("processing_time", 0),
                            "confidence_score": parsed_result.get("confidence_score"),
                            "full_response": result.stdout
                        }
                    else:
                        # Handle error case - malformed response
                        logger.warning(f"🔍 Vector search returned malformed response: {parsed_result}")
                        return {
                            "status": "error",
                            "error": "Vector search returned malformed response format",
                            "ai_response": "",
                            "raw_results": [],
                            "metadata": {},
                            "cli_output": result.stdout
                        }
                        
                except json.JSONDecodeError as e:
                    logger.error(f"🔍 Failed to parse vector CLI JSON output: {e}")
                    logger.error(f"🔍 Raw stdout: {result.stdout[:500]}...")
                    return {
                        "status": "error",
                        "error": f"Failed to parse vector CLI output: {e}",
                        "ai_response": result.stdout,  # Fallback to raw output
                        "raw_results": [],
                        "metadata": {},
                        "cli_output": result.stdout
                    }
            else:
                logger.error(f"🔍 Vector CLI failed with return code {result.returncode}")
                return {
                    "status": "error",
                    "error": f"Vector CLI failed with return code {result.returncode}",
                    "ai_response": "",
                    "raw_results": [],
                    "metadata": {},
                    "cli_output": result.stdout,
                    "cli_error": result.stderr
                }
                
        except Exception as e:
            logger.error(f"❌ Vector search execution failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "ai_response": "",
                "raw_results": [],
                "metadata": {}
            }
    
    async def _extract_entities_from_vector_results(self, vector_results: List[Dict]) -> List[str]:
        """Use LLM to intelligently extract relevant entities from vector search results"""
        if not vector_results:
            return []
        
        try:
            # Use all vector results for comprehensive entity extraction
            results_json = json.dumps(vector_results, indent=2)
            
            # extraction_prompt = f"""
            # Extract class names, interface names, and method names from these vector search results.
            
            # VECTOR SEARCH RESULTS (all {len(vector_results)} results):
            # """ + results_json + """

            # TASK: Extract code entity names that appear in:
            # 1. File paths (e.g., "/WorkerFactory.cs" → extract "WorkerFactory")
            # 2. Code content (e.g., "public class Manager" → extract "Manager") 
            # 3. Metadata names (e.g., metadata.name field)

            # Return ONLY a direct JSON array of entity names (no wrapper object):
            # ["Entity1", "Entity2", "Entity3"]

            # Do NOT wrap in an object like {"entities": [...]} or {"result": [...]}. 
            # Return the array directly as the root JSON element.

            # Focus on classes, interfaces, and significant methods. Exclude generic terms like "System", "Console", "String".
            # """

            extraction_prompt = f"""
ROLE:
You are an information extractor. Output only JSON.

INPUT:
You are given vector search results from a codebase.

VECTOR SEARCH RESULTS (all {len(vector_results)} results):
{results_json}

TASK:
Extract names of HIGH-LEVEL ENTITIES that appear in:
1) File paths/filenames (e.g., "/WorkerFactory.cs" → "WorkerFactory")
2) Code content
3) Metadata fields (e.g., metadata.name)

HIGH-LEVEL ENTITIES (language-agnostic):
- Types: class, abstract class, interface, struct, enum, record, protocol, trait, type alias
- Modules / namespacing: module, namespace, package
- Architectural roles: component, service, controller, repository, provider, middleware
- Top-level functions/procedures that are public/exported
- Framework artifacts (when explicitly named): React/Vue/Svelte components; Angular modules; Nest providers; Django/Flask/FastAPI apps; Rails controllers/models
- Schemas/contracts: GraphQL types; Protobuf/Thrift messages/services; OpenAPI schema names
- Data/DB artifacts: ORM models/entities; explicit table names when declared; migration target entity names

EXCLUDE:
- Local variables, parameters, fields/properties
- Private methods or helpers (unless explicitly top-level exported)
- Imports/usings, literals, keywords
- Generic/library terms (e.g., System, Console, String, List)

RULES:
- Preserve names exactly as written (do not change casing or add/remove suffixes).
- Deduplicate so each entity appears only once.
- If a fully qualified name appears (e.g., "MyApp.Core.WorkerFactory"), output only the terminal name: "WorkerFactory".
- Do not infer entities that do not explicitly appear in the provided inputs.
- If nothing is found, return [].

OUTPUT:
Return a single JSON array of strings ONLY, for example:
["Entity1", "Entity2"]
Do NOT include markdown/code fences, comments, prose, or any wrapper object.
"""

            extraction_result = await self.llm_service.generate_response(extraction_prompt, json_mode=True)
            
            logger.info(f"EXTRACTED ENTITIES FROM VECTOR RESULTS: {extraction_result}")

            if extraction_result and not extraction_result.error:
                try:
                    logger.info(f"🔍 DEBUG - LLM entity extraction raw response: {extraction_result.content}")
                    entities = json.loads(extraction_result.content)
                    # Handle different response formats
                    entity_list = []
                    if isinstance(entities, list):
                        entity_list = entities
                    elif isinstance(entities, dict):
                        # Try common keys that might contain the entity list
                        if "result" in entities and isinstance(entities["result"], list):
                            entity_list = entities["result"]
                        elif "entities" in entities and isinstance(entities["entities"], list):
                            entity_list = entities["entities"]
                        else:
                            logger.warning(f"LLM returned dict without expected keys. Keys: {list(entities.keys())}")
                            return []
                    else:
                        logger.warning(f"LLM returned unexpected format: {type(entities)}")
                        return []
                    
                    # Clean the entity list
                    clean_entities = []
                    for entity in entity_list:
                        if isinstance(entity, str) and len(entity) > 2:
                            clean_entity = entity.strip()
                            if clean_entity and clean_entity not in clean_entities:
                                clean_entities.append(clean_entity)
                    logger.info(f"✅ Extracted {len(clean_entities)} clean entities: {clean_entities}")
                    return clean_entities
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse LLM entity extraction response: {e}")
                    return []
            else:
                logger.warning(f"LLM entity extraction failed: {extraction_result.error if extraction_result else 'No response'}")
                return []
                
        except Exception as e:
            logger.error(f"❌ Entity extraction from vector results failed: {e}")
            return []
    
    def _build_vector_context(self, state: AgentState) -> str:
        """Build vector search context for enhanced seed query generation"""
        vector_search_results = state.get('vector_search_results', [])
        vector_discovered_entities = state.get('vector_discovered_entities', [])
        
        if not vector_search_results:
            return "No vector search results available (query may have gone directly to CPG discovery)"
        
        context = f"""
        Vector Search Found: {len(vector_search_results)} relevant code sections
        
        Vector Discovered Entities: {json.dumps(vector_discovered_entities)}
        
        Key Vector Insights:
        (Vector result details available for CPG targeting)
        
        CRITICAL INSTRUCTION: Focus CPG queries on vector-discovered entities {vector_discovered_entities} as primary targets.
        Use these entities to build targeted WHERE clauses in your Cypher queries.
        """
        
        return context
    
    def _format_vector_results_for_synthesis(self, state: AgentState) -> str:
        """Format complete vector search results for synthesis prompt"""
        vector_search_results = state.get('vector_search_results', [])
        vector_ai_response = state.get('vector_ai_response', '')
        vector_metadata = state.get('vector_metadata', {})
        vector_discovered_entities = state.get('vector_discovered_entities', [])
        
        # Log what vector data is available for synthesis
        logger.info(f"🔍 VECTOR SYNTHESIS DATA:")
        logger.info(f"  ✓ Raw results: {len(vector_search_results)} items")
        logger.info(f"  ✓ AI response: {len(vector_ai_response)} chars")
        logger.info(f"  ✓ Entities: {len(vector_discovered_entities)} found")
        logger.info(f"  ✓ Metadata keys: {list(vector_metadata.keys()) if isinstance(vector_metadata, dict) else []}")
        
        if not vector_search_results and not vector_ai_response:
            logger.warning("⚠️  No vector data available for synthesis - CPG-only mode")
            return "No vector search results available (query went directly to CPG discovery)"
        
        formatted_results = f"""
Vector Search Query: {state.get('user_query', '')}
Vector Discovered Entities: {json.dumps(vector_discovered_entities)}

VECTOR RAG VALIDATED AI RESPONSE:
{vector_ai_response}

VECTOR METADATA:
{json.dumps(vector_metadata, indent=2)}

COMPLETE VECTOR RAW RESULTS ({len(vector_search_results)} items):
{json.dumps(vector_search_results, indent=2)}

Vector Analysis Summary:
- Vector RAG provides VALIDATED AI response above (this is the clean, processed answer)
- Raw results contain {len(vector_search_results)} code sections with complete context
- Metadata includes confidence scores and processing details
- Key entities discovered for CPG targeting: {', '.join(vector_discovered_entities) if vector_discovered_entities else 'None extracted'}
- Vector data represents semantic understanding of actual code content
"""
        
        return formatted_results
    
    async def _execute_query_with_retry(self, query: str, purpose: str, state: AgentState, max_retries: int = 2) -> Dict[str, Any]:
        """Execute query using project-analyzer CLI tool (same pattern as other MCP tools)"""
        import subprocess
        import json
        
        for attempt in range(max_retries):
            try:
                # Fix Neo4j 5.x syntax issues
                fixed_query = self._fix_neo4j_syntax(query, state["neo4j_version"])
                
                # Use project-analyzer CLI (same pattern as other tools)
                cli_command = [
                    "project-analyzer",
                    "--config-file", state["neo4j_config"],
                    "query",
                    "--cypher", fixed_query,
                    "--limit", "100",  # Default limit
                    "--output-format", "json"
                ]
                
                logger.info(f"Executing CLI: {' '.join(cli_command)}")
                
                result = subprocess.run(
                    cli_command,
                    text=True,
                    capture_output=True
                )
                
                if result.returncode == 0:
                    try:
                        # Parse JSON output
                        output_data = json.loads(result.stdout)
                        
                        # Check if this is an error response formatted as JSON
                        if isinstance(output_data, dict) and not output_data.get("success", True):
                            return {
                                "status": "error",
                                "results": [],
                                "error": output_data.get("error", "Unknown error"),
                                "query": fixed_query,
                                "purpose": purpose,
                                "cli_output": result.stdout,
                                "detailed_error": output_data.get("detailed_message", ""),
                                "error_type": output_data.get("error_type", "Unknown")
                            }
                        
                        return {
                            "status": "success",
                            "results": output_data.get("results", []),
                            "query": fixed_query,
                            "purpose": purpose,
                            "cli_output": result.stdout
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse CLI JSON output: {e}")
                        logger.error(f"Raw stdout: {result.stdout}")
                        logger.error(f"Raw stderr: {result.stderr}")
                        return {
                            "status": "error",
                            "results": [],
                            "error": f"JSON parse error: {e}",
                            "raw_output": result.stdout,
                            "cli_output": None
                        }
                else:
                    logger.warning(f"CLI command failed (attempt {attempt + 1}): {result.stderr}")
                    
                    # Try to parse stderr as JSON for detailed error info
                    detailed_error = None
                    try:
                        if result.stderr.strip():
                            stderr_data = json.loads(result.stderr)
                            if isinstance(stderr_data, dict):
                                detailed_error = stderr_data.get("detailed_message", stderr_data.get("error", ""))
                    except json.JSONDecodeError:
                        pass
                    
                    # Try to fix common syntax errors and retry
                    if "exists(" in result.stderr.lower() and attempt < max_retries - 1:
                        query = query.replace("NOT EXISTS(", "").replace("EXISTS(", "")
                        query = self._fix_exists_syntax(query)
                        continue
                    
                    if attempt == max_retries - 1:
                        return {
                            "status": "error",
                            "results": [],
                            "error": detailed_error or result.stderr,
                            "returncode": result.returncode,
                            "cli_output": None
                        }
                
            except subprocess.TimeoutExpired:
                logger.error(f"CLI command timed out (attempt {attempt + 1})")
                if attempt == max_retries - 1:
                    return {
                        "status": "error",
                        "results": [],
                        "error": "Query execution timed out"
                    }
            except Exception as e:
                logger.error(f"CLI execution error (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return {
                        "status": "error",
                        "results": [],
                        "error": str(e)
                    }
        
        return {"status": "error", "results": [], "error": "Max retries exceeded"}
    
    def _fix_neo4j_syntax(self, query: str, version: str) -> str:
        """Fix Neo4j syntax for version compatibility"""
        if version.startswith("5."):
            # Fix EXISTS syntax for Neo4j 5.x
            query = query.replace("NOT EXISTS(", "")
            query = query.replace("EXISTS(", "")
            
            # Fix project_name checks
            if "project_name)" in query and "IS NULL" not in query:
                query = query.replace("project_name)", "project_name IS NULL)")
                
        return query
    
    def _fix_exists_syntax(self, query: str) -> str:
        """Fix EXISTS syntax for Neo4j 5.x compatibility"""
        # Replace EXISTS patterns with IS NULL patterns
        import re
        
        # Pattern for NOT EXISTS(variable.property)
        query = re.sub(r'NOT\s+EXISTS\s*\(\s*(\w+)\.(\w+)\s*\)', r'\1.\2 IS NULL', query)
        
        # Pattern for EXISTS(variable.property)  
        query = re.sub(r'EXISTS\s*\(\s*(\w+)\.(\w+)\s*\)', r'\1.\2 IS NOT NULL', query)
        
        return query


# Factory function
async def create_adaptive_cpg_workflow() -> ComprehensiveAnalysisAgentWorkflow:
    """Factory function to create the workflow"""
    workflow = ComprehensiveAnalysisAgentWorkflow()
    return workflow


# Main execution function for the MCP tool
async def execute_adaptive_cpg_workflow(user_query: str, project_name: str = "HelloWorldApp",
                                       neo4j_config: str = "/opt/genpod/neo4j_config.json",
                                       project_path: str = "/opt/HelloWorldApp/",
                                       mappings_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
                                       queries_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
                                       max_iterations: int = 10) -> Dict[str, Any]:
    """
    Main function to execute the adaptive CPG workflow
    This is what the MCP tool should call
    
    Args:
        user_query: Natural language query for analysis
        project_name: Name of project in Neo4j database
        neo4j_config: Path to Neo4j MCP configuration file
        project_path: Path to project root (stored as metadata)
        mappings_path: Path to mappings YAML (stored as metadata)
        queries_path: Path to queries directory (stored as metadata)
        max_iterations: Maximum workflow iterations (default: 10 for complex queries)
    
    Note: Only neo4j_config is used for CLI execution. Other paths are stored as metadata.
    """
    
    workflow = await create_adaptive_cpg_workflow()
    
    # Store metadata for potential use by agents (paths for future analysis commands)
    metadata = {
        "project_path": project_path,
        "mappings_path": mappings_path,
        "queries_path": queries_path
    }
    
    return await workflow.run_workflow(user_query, project_name, neo4j_config, max_iterations, metadata)


# Direct testing main function
async def main():
    """
    Direct test runner for the LangGraph Agent Workflow
    This bypasses the MCP tool and old Enhanced RAG system
    """
    import asyncio
    import json
    
    print("🚀 Testing LangGraph Agent Workflow Directly")
    print("=" * 60)
    
    # Test query
    test_query = "What are the dependencies and relationships between different classes in the HelloWorldApp?"
    
    print(f"🔍 Query: {test_query}")
    print(f"🎯 Project: HelloWorldApp")
    print(f"⚙️  Config: /opt/genpod/neo4j_config.json")
    print("=" * 60)
    
    try:
        # Run the complete agent workflow
        result = await execute_adaptive_cpg_workflow(
            user_query=test_query,
            project_name="HelloWorldApp",
            neo4j_config="/opt/genpod/neo4j_config.json",
            project_path="/opt/HelloWorldApp/",
            mappings_path="/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
            queries_path="/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
            max_iterations=10
        )
        
        print("✅ Agent Workflow Completed!")
        print("=" * 60)
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Response: {result.get('response', 'No response')[:500]}...")
        print(f"Discovered Data: {len(result.get('discovered_data', []))} items")
        print(f"Query History: {len(result.get('query_history', []))} queries")
        print(f"Iterations Used: {result.get('iterations_used', 0)}")
        
        if result.get('status') == 'error':
            print(f"❌ Error: {result.get('error', 'Unknown error')}")
        
        # Save full result
        with open('complete_workflow_test_result.json', 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print("💾 Full result saved to: complete_workflow_test_result.json")
        
    except Exception as e:
        print(f"❌ Agent Workflow Failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
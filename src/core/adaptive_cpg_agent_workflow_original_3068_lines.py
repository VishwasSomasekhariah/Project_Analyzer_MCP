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

# Data classes for LLM response validation
@dataclass
class SchemaAnalysis:
    relevant_node_types: List[str]
    data_storage_candidates: Dict[str, List[str]]  # {"content_attributes": [...], "structural_relationships": [...]}
    relationships_to_explore: List[str]
    reasoning: str

@dataclass
class ExplorationHypothesis:
    hypothesis: str
    likelihood: str  # "high", "medium", "low"
    reasoning: str
    test_approach: str

@dataclass 
class QueryStrategy:
    strategy_name: str
    purpose: str
    query: str
    expected_outcome: str
    priority: int

@dataclass
class ExecutionPlan:
    primary_queries: List[Dict[str, str]]  # [{"query": "...", "purpose": "...", "reasoning": "..."}]
    fallback_strategies: List[str]
    termination_criteria: List[str]

@dataclass
class DiscoveryResearch:
    schema_analysis: SchemaAnalysis
    hypotheses: List[ExplorationHypothesis]
    strategies: List[QueryStrategy]
    execution_plan: ExecutionPlan

class AgentState(TypedDict):
    """State maintained throughout the agent workflow"""
    # Input
    user_query: str
    project_name: str
    neo4j_config: str
    
    # Environment
    neo4j_version: str
    schema: Dict[str, Any]
    
    # Discovery & Results - DETAILED STORAGE
    discovered_data: List[Dict[str, Any]]           # Processed/combined data
    query_history: List[Dict[str, Any]]             # Query metadata
    raw_query_results: List[Dict[str, Any]]         # RAW results from each query execution
    all_executed_queries: List[Dict[str, Any]]      # Complete query details with results
    
    # Intent & Planning
    intent: Dict[str, Any]                          # Backward compatibility
    intent_analysis: Dict[str, Any]                 # Full intent analysis with strategy
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
    
    # Sufficiency Evaluation & CPG Error Handling
    data_gaps: Optional[Any]                          # Sufficiency evaluation gaps/requirements
    body_exploration_needed: bool                     # Flag for entity body exploration due to CPG errors
    
    # Research-Based Discovery
    discovery_research: Optional[Dict[str, Any]]      # Multi-step discovery research results


class AdaptiveCPGAgentWorkflow:
    """
    LangGraph-based agent workflow for adaptive CPG discovery
    """
    
    def __init__(self):
        self.graph = None
        self.llm_service = None
        self.graph_executor = None
        
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
        workflow.add_node("initial_discovery", self.initial_discovery) 
        workflow.add_node("analyze_intent", self.analyze_intent)
        workflow.add_node("generate_query", self.generate_query)
        workflow.add_node("execute_query", self.execute_query)
        workflow.add_node("evaluate_sufficiency", self.evaluate_sufficiency)
        workflow.add_node("synthesize_response", self.synthesize_response)
        
        # Define the workflow edges
        workflow.add_edge("initialize_environment", "analyze_intent")
        workflow.add_edge("analyze_intent", "initial_discovery")
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
    
    async def run_workflow(self, user_query: str, project_name: str = "HelloWorldApp", 
                          neo4j_config: str = "/opt/genpod/neo4j_config.json",
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
            "neo4j_version": "",
            "schema": {},
            "discovered_data": [],
            "query_history": [],
            "raw_query_results": [],           # NEW: Store all raw results
            "all_executed_queries": [],       # NEW: Store complete query details
            "intent": {},                      # Backward compatibility
            "intent_analysis": {},             # Full intent analysis with strategy
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
            "data_gaps": None,                # NEW: Store sufficiency evaluation gaps
            "body_exploration_needed": False, # NEW: Flag for entity body exploration
            "discovery_research": None        # NEW: Multi-step discovery research results
        }
        
        logger.info(f"🚀 Starting Adaptive CPG Agent Workflow for: {user_query}")
        
        # Execute the workflow
        try:
            final_state = await compiled_graph.ainvoke(initial_state)
            
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
            
            logger.info(f"✅ Environment initialized - Neo4j: {neo4j_version}")
            return {
                **state,
                "neo4j_version": neo4j_version,
                "schema": schema,
                "current_node": "initialize_environment"
            }
            
        except Exception as e:
            logger.error(f"❌ Environment initialization failed: {e}")
            return {
                **state,
                "error": f"Environment initialization failed: {e}",
                "should_continue": False
            }
    
    async def initial_discovery(self, state: AgentState) -> AgentState:
        """Node: Multi-step research-based discovery"""
        logger.info("📋 Node: research_discovery")
        
        try:
            # Phase 1: Disambiguation & Clarification (keep existing)
            disambiguation_result = await self._disambiguate_query_terms(state)
            
            # Update state with disambiguation results
            updated_state = {**state, **disambiguation_result}
            
            # Multi-step research discovery
            logger.info("🔬 Starting multi-step discovery research...")
            
            # Step 1: Schema Analysis
            schema_analysis = await self._analyze_schema_for_query(updated_state)
            
            # Step 2: Generate Hypotheses  
            hypotheses = await self._generate_exploration_hypotheses(updated_state, schema_analysis)
            
            # Step 3: Plan Query Strategies
            strategies = await self._plan_query_strategies(updated_state, hypotheses)
            
            # Step 4: Generate Execution Plan
            execution_plan = await self._create_execution_plan(updated_state, strategies)
            
            # Store research results
            discovery_research = {
                "schema_analysis": asdict(schema_analysis),
                "hypotheses": [asdict(h) for h in hypotheses], 
                "strategies": [asdict(s) for s in strategies],
                "execution_plan": asdict(execution_plan)
            }
            
            logger.info(f"🔬 Discovery research complete: {len(hypotheses)} hypotheses, {len(strategies)} strategies")
            logger.info(f"🔬 Execution plan: {len(execution_plan.primary_queries)} primary queries")
            
            # Execute the primary queries from research
            discovered_data = []
            query_history = []
            
            for query_info in execution_plan.primary_queries:
                query = query_info.get('query')
                purpose = query_info.get('purpose', 'research_discovery')
                
                if query:
                    logger.info(f"🔍 Executing research query: {purpose}")
                    result = await self._execute_query_with_retry(query, purpose, updated_state)
                    
                    # Store complete query execution details
                    complete_query_info = {
                        "query": query,
                        "purpose": purpose,
                        "status": result["status"],
                        "result_count": len(result.get("results", [])),
                        "results": result.get("results", []),
                        "execution_time": result.get("execution_time", 0),
                        "agent": "research_discovery",
                        "phase": "initial_discovery",
                        "error": result.get("error"),
                        "cli_output": result.get("cli_output"),
                        "research_reasoning": query_info.get('reasoning', '')
                    }
                    state.get("all_executed_queries", []).append(complete_query_info)
                    
                    if result["status"] == "success":
                        query_results = result.get("results", [])
                        discovered_data.extend(query_results)
                        state.get("raw_query_results", []).extend(query_results)
                        
                        query_history.append({
                            "query": query,
                            "purpose": purpose,
                            "result_count": len(query_results),
                            "status": "success"
                        })
                    else:
                        query_history.append({
                            "query": query,
                            "purpose": purpose,
                            "result_count": 0,
                            "status": "failure",
                            "error": result.get("error", "Unknown error")
                        })

            logger.info(f"✅ Research discovery complete: {len(discovered_data)} items found")
            
            return {
                **updated_state,
                "discovered_data": discovered_data,
                "query_history": query_history,
                "discovery_research": discovery_research,
                "current_node": "initial_discovery"
            }
            
        except Exception as e:
            logger.error(f"❌ Research discovery failed: {e}")
            return {**state, "error": f"Research discovery failed: {e}"}
    
    async def analyze_intent(self, state: AgentState) -> AgentState:
        """Node: Analyze user intent to determine discovery strategy"""
        logger.info("🎯 Node: analyze_intent")
        
        try:
            intent_prompt = f"""
            Analyze the user's query to determine the optimal discovery strategy.
            
            User Query: {state['user_query']}
            Project: {state['project_name']}
            **AVAILABLE SCHEMA**:
            **NODE TYPES**: {', '.join([f"{node} ({', '.join(attrs.get('attributes', []))})" for node, attrs in state['schema'].get('nodes', {}).items()])}
            **RELATIONSHIPS**: {', '.join([f"{rel} ({rel_def.get('from', 'Unknown')} → {rel_def.get('to', 'Unknown')})" for rel, rel_def in state['schema'].get('relationships', {}).items()])}
            
            CRITICAL: Respond with ONLY valid JSON in the exact format below:
            {{
                "query_type": "lookup|architectural|exploration",
                "scope": "specific|component|system-wide", 
                "data_needed": "minimal|moderate|comprehensive",
                "strategy": "description of discovery approach",
                "target_elements": ["list", "of", "specific", "things", "to", "find"],
                "reasoning": "why this categorization"
            }}
            
            CLASSIFICATION CRITERIA:
            
            **LOOKUP** (Finding specific, identifiable entities):
            - Queries about specific files, functions, classes, variables
            - "What is...", "Where is...", "Show me...", "Find..."
            - Content in specific files (comments, code, implementations)
            - Direct questions with clear targets
            Examples:
            - "What is the last comment line in WorkerA.cs?" → lookup/specific/minimal
            - "Where is function calculateTotal defined?" → lookup/specific/minimal
            - "Show me the WorkerFactory class" → lookup/specific/minimal
            - "Find all comments in main.cpp" → lookup/specific/moderate
            
            **ARCHITECTURAL** (Understanding relationships and structure):
            - Dependencies, inheritance, relationships between entities
            - Design patterns, architectural overview
            - "How does...", "What calls...", "Dependencies of..."
            Examples:
            - "Show class dependencies in auth module" → architectural/component/moderate
            - "How does WorkerA inherit from BaseWorker?" → architectural/specific/minimal
            - "What calls the CreateWorker function?" → architectural/component/moderate
            
            **EXPLORATION** (Broad discovery and analysis):
            - System-wide patterns, all instances of something
            - Security analysis, API discovery, comprehensive surveys
            - "All...", "List all...", "What are the security issues..."
            Examples:
            - "What are all the API endpoints?" → exploration/system-wide/comprehensive
            - "List all security vulnerabilities" → exploration/system-wide/comprehensive
            - "Show all inheritance hierarchies" → exploration/system-wide/comprehensive
            
            SCOPE GUIDELINES:
            - specific: Single entity or file
            - component: Group of related entities (module, package)
            - system-wide: Entire project or cross-cutting concerns
            
            DATA NEEDED:
            - minimal: Simple lookups, single entities
            - moderate: Relationships, moderate complexity
            - comprehensive: System-wide analysis, complex patterns
            """
            
            # Attempt intent analysis with feedback loop for format validation
            intent_analysis = await self._analyze_intent_with_validation(intent_prompt)
            
            logger.info(f"✅ Intent analyzed: {intent_analysis['query_type']} | {intent_analysis['scope']} | {intent_analysis['data_needed']}")
            return {
                **state,
                "intent_analysis": intent_analysis,
                "intent": intent_analysis["query_type"],  # Backward compatibility
                "current_node": "analyze_intent"
            }
            
        except Exception as e:
            logger.error(f"❌ Intent analysis failed: {e}")
            # Use intelligent fallback based on query keywords
            fallback_intent = self._fallback_intent_analysis(state['user_query'])
            return {
                **state,
                "intent_analysis": fallback_intent,
                "intent": fallback_intent["query_type"],
                "current_node": "analyze_intent",
                "error": f"Intent analysis failed, using fallback: {e}"
            }
    
    async def generate_query(self, state: AgentState) -> AgentState:
        """Node: Generate next query based on current state"""
        logger.info(f"🔍 Node: generate_query (iteration {state['current_iteration'] + 1})")
        
        # Check if we're in fallback mode and need diverse strategies
        if state.get("fallback_mode", False):
            return await self._generate_diverse_fallback_queries(state)
        
        try:
            state["current_iteration"] += 1
            
            # Include disambiguation results and schema information
            entities_found = state.get('entities_found', {})
            schema = state.get('schema', {})
            
            disambiguation_info = ""
            if entities_found:
                disambiguation_info = f"""
            
            DISAMBIGUATION RESULTS:
            {chr(10).join([f"- '{entity}' → {data['primary_type']} node ({'FOUND' if data['found'] else 'NOT_FOUND'})" for entity, data in entities_found.items()])}
            """
            
            # Get intent-aware discovery strategy
            intent_analysis = state.get('intent_analysis', {})
            query_type = intent_analysis.get('query_type', 'architectural')
            data_needed = intent_analysis.get('data_needed', 'moderate')
            target_elements = intent_analysis.get('target_elements', [])
            
            query_prompt = f"""
            CRITICAL: INTENT + ENTITY AWARE QUERY GENERATION
            =================================================
            This is a UNIVERSAL, LANGUAGE-AGNOSTIC Code Property Graph that represents codebases 
            written in ANY programming language (C, C++, C#, Java, JavaScript, Python, COBOL, etc.).
            Just because something is defined in the schema does not mean it is always captured, but if it is captured that's all will be present due to language parser restrictions. 
            However, nothing outside of those node types and relationships will ever exist.
            
            **INTENT ANALYSIS**:
            Query Type: {query_type.upper()}
            Data Needed: {data_needed}
            Target Elements: {target_elements}
            Strategy: {intent_analysis.get('strategy', 'Standard query generation')}
            
            **USER QUERY**: {state['user_query']}
            **ITERATION**: {state['current_iteration']}/{state['max_iterations']}
            **CURRENT DATA**: {len(state['discovered_data'])} items
            **PREVIOUS QUERIES**: {[q.get('purpose', 'unknown') if isinstance(q, dict) else str(q) for q in state['query_history']]}
            
            {disambiguation_info}
            
            **DISCOVERY STRATEGY GUIDANCE**:
            {self._generate_dynamic_strategy_guidance(state)}
            
            **RETHINK GUIDANCE FOR NEXT ITERATION**:
            {self._format_guidance_for_query_generation(state.get('data_gaps'))}
            
            **DISCOVERY RESEARCH INSIGHTS**:
            {self._format_discovery_research_for_query_generation(state.get('discovery_research'))}
            
            **COMPLETE SCHEMA INFORMATION (USE ONLY THESE)**:
            
            **NODE TYPES AND THEIR ATTRIBUTES**:
            {chr(10).join([f"- {node}: {', '.join(attrs.get('attributes', []))}" for node, attrs in schema.get('nodes', {}).items()])}
            
            **RELATIONSHIP DEFINITIONS**:
            {chr(10).join([f"- {rel}: {rel_def.get('from', 'Unknown')} → {rel_def.get('to', 'Unknown')}" for rel, rel_def in schema.get('relationships', {}).items()])}
            
            **DETAILED NODE DEFINITIONS**:
            {json.dumps(schema.get('NodeDefinitions', {}), indent=2) if schema.get('NodeDefinitions') else 'Node definitions not available'}
            
            **RELATIONSHIP USAGE GUIDANCE**:
            {json.dumps(schema.get('EdgeDefinitions', {}), indent=2) if schema.get('EdgeDefinitions') else 'Edge definitions not available'}
            
            **CRITICAL NODE TYPE DISTINCTION**:
            - ORGANIZATIONAL NODES (Project, File): Only have structural attributes (name, path) - NO content attributes
            - CONTENT NODES (Type, Function, Block, Literal): May have content attributes (body, documentation, value, etc.)
            - File nodes are purely organizational - they NEVER contain comments, code, or content themselves
            - ALWAYS traverse via: MATCH (p:Project {{name:'{state['project_name']}'}})-[:CONTAINS]->(f:File {{name:'<FILENAME>'}}) THEN MATCH (f)-[:CONTAINS]->(<CONTENT NODE>)

            **DEFINED_IN RULES (strict):**
            - Allowed sources: Function, Type, Namespace, Variable
            - Allowed targets: File, Namespace
            - Examples:
                MATCH (func:Function)-[:DEFINED_IN]->(f:File)
                MATCH (t:Type)-[:DEFINED_IN]->(ns:Namespace)
            - NEVER use:
                File-[:DEFINED_IN]->Project
                Project-[:DEFINED_IN]->File
                File-[:DEFINED_IN]->(Type|Function|Variable|Block|Literal|Macro)
            - Do NOT use DEFINED_IN to enumerate a file’s contents. Use:
                MATCH (p:Project {{name:'{state["project_name"]}'}})-[:CONTAINS]->(f:File {{name:'<FILENAME>'}})
                MATCH (f)-[:CONTAINS]->(content)
            
            **INTENT-DRIVEN QUERY STRATEGY**:
            
            **IF LOOKUP QUERY + FILE TARGET**:
            1. FOUNDATION DISCOVERY: First discover what content nodes exist in the file:
                Query:
                MATCH (p:Project {{name: '{state['project_name']}'}})-[:CONTAINS]->(f:File {{name:'filename'}})
                MATCH (f)-[:CONTAINS]->(contentNode)
                RETURN labels(contentNode), contentNode.name, contentNode.type_kind
                LIMIT 20

            2. CONTENT SEARCH: Then search all node attributes of the content node type using schema provided.
            3. ORGANIZATIONAL NODES HAVE NO CONTENT: Never search File.body, File.documentation - they don't exist
            
            **IF ARCHITECTURAL QUERY**:
            - Focus on relationships between entities (INHERITS_FROM, IMPLEMENTS, CALLS)
            - Discover structural patterns and dependencies
            
            **IF EXPLORATION QUERY**:
            - Cast wide net for patterns across multiple entities
            - Use broader relationship traversals
            
            **QUERY GENERATION RULES**:
            1. RESPECT the discovery strategy guidance above
            2. For lookup queries: follow container → contents → search pattern
            3. Use ONLY schema-defined node types and relationships
            4. Include appropriate LIMIT for performance
            5. Neo4j Version: {state['neo4j_version']} (use IS NULL, not EXISTS)
            6. Project Filter: (n.name = '{state['project_name']}' OR n.name IS NULL)
            
            Generate ONE targeted Cypher query.  
            Only return "COMPLETE" if there are absolutely no further possible queries that can be generated from the schema and intent.  
            If **RETHINK GUIDANCE FOR NEXT ITERATION** is provided, use it to refine your query generation.
            Return ONLY the Cypher query, no markdown formatting.
            If your query would require a DEFINED_IN direction not listed as VALID above, do not emit it; instead, restructure using CONTAINS, or output COMPLETE if impossible within the schema.
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
            return {**state, "error": f"Query generation failed: {e}"}
    
    async def _generate_diverse_fallback_queries(self, state: AgentState) -> AgentState:
        """
        Generate diverse query strategies when primary approach has failed
        """
        logger.info("🔄 Generating diverse fallback query strategies")
        
        try:
            state["current_iteration"] += 1
            
            # CRITICAL FIX: Check for existing remaining fallback strategies first
            remaining_strategies = state.get("remaining_fallback_strategies", [])
            if remaining_strategies:
                logger.info(f"🔄 Using next remaining fallback strategy ({len(remaining_strategies)} left)")
                selected_strategy = remaining_strategies[0]
                updated_remaining = remaining_strategies[1:]
                
                state = {
                    **state,
                    "next_query": selected_strategy["query"],
                    "current_node": "generate_query", 
                    "remaining_fallback_strategies": updated_remaining,
                    "fallback_strategy_used": selected_strategy.get("approach", "remaining_strategy")
                }
                
                logger.info(f"🔄 Selected remaining strategy: {selected_strategy.get('approach', 'unknown')}")
                return state
            
            # If no remaining strategies, check if we should terminate
            current_iteration = state.get("current_iteration", 1)
            max_fallback_attempts = 10  # Limit fallback cycles
            
            if current_iteration > max_fallback_attempts:
                logger.warning(f"🔄 Maximum fallback attempts ({max_fallback_attempts}) reached, terminating")
                state = {
                    **state,
                    "next_query": "COMPLETE",
                    "current_node": "generate_query",
                    "fallback_mode": False,
                    "should_continue": False
                }
                return state
                
            # Generate new diverse strategies
            logger.info("🔄 No remaining strategies, generating new diverse fallback strategies")
            
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
            Due to language parser restrictions, something that is defined in the schema may not always be captured, but if it is captured it will be present. 
            However, nothing outside of those node types and relationships will ever exist.
            
            DO NOT make language-specific assumptions about node types:
            - "Function" node ≠ standalone function (could be method, procedure, subroutine)
            - "Type" node ≠ just classes (could be struct, interface, enum, typedef)
            - "Variable" node ≠ just variables (could be field, parameter, constant)
            
            RELY ONLY ON THE SCHEMA RELATIONSHIPS PROVIDED BELOW.
            The schema defines the ONLY valid connections between nodes.
            
            STRICT DIRECTIONALITY FOR DEFINED_IN:
            - (Function|Type|Namespace|Variable)-[:DEFINED_IN]->(File|Namespace) ONLY
            - Use CONTAINS for container→content traversal (Project→File→Content)
            - Do NOT ever emit: File-[:DEFINED_IN]->Project, Project-[:DEFINED_IN]->File, or File-[:DEFINED_IN]->(any content node)

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
            
            1. **Content-Based Search**: Search in body properties of nodes
            2. **Fuzzy/Pattern Matching**: Use CONTAINS, regex, or partial name matching  
            3. **Broader Context Search**: Search related entities or broader scope
            4. **Alternative Entity Types**: Try different node types than previously attempted
            
            For each strategy, provide:
            - A single Cypher query that explores the codebase differently
            - Focus on finding ANY relevant information, not just exact matches
            - Use node properties by their schema attributes
            - Project filter: (n.name = '{project_name}' OR n.name IS NULL)
            
            Return JSON format:
            {{
                "strategies": [
                    {{
                        "approach": "content_search",
                        "query": ""MATCH (p:Project {{name:'{project_name}'}})-[:CONTAINS]->(f:File) \
                        MATCH (f)-[:CONTAINS]->(n) \
                        WHERE (n:Function OR n:Type) AND coalesce(n.body,'') CONTAINS 'search_term' \
                        RETURN n.name, labels(n)[0] AS label, n.body LIMIT 10",
                        "reasoning": "Search within content nodes (Function/Type) of files in this project"
                    }},
                    {{
                        "approach": "fuzzy_match",
                        "query": "MATCH (p:Project {{name:'{project_name}'}})-[:CONTAINS*1..3]->(n) \
                        WHERE n.name =~ '.*pattern.*' \
                        RETURN n.name, labels(n) LIMIT 10",
                        "reasoning": "Find similarly named entities within the project scope via container paths"
                    }}
                ]
            }}
            
            Generate queries that are FUNDAMENTALLY DIFFERENT from failed approaches. \
            If your query would require a DEFINED_IN direction not listed as VALID above, do not emit it; instead, restructure using CONTAINS, or output COMPLETE if impossible within the schema.
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
                            
                            return {
                                **state,
                                "next_query": selected_strategy["query"],
                                "current_node": "generate_query",
                                "fallback_strategy_used": selected_strategy["approach"]
                            }
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse diverse strategy JSON: {e}")
            
            # Fallback failed, mark as complete
            logger.warning("🔄 Diverse strategy generation failed, marking as complete")
            return {
                **state,
                "next_query": "COMPLETE",
                "current_node": "generate_query",
                "fallback_mode": False,
                "should_continue": False
            }
            
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
            
            return {**state, "current_node": "execute_query"}
            
        except Exception as e:
            logger.error(f"❌ Query execution failed: {e}")
            return {**state, "error": f"Query execution failed: {e}"}
    
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
            
            # JSON-based sufficiency evaluation with validation loop (up to 3 attempts)
            max_attempts = 3
            sufficiency_result = None

            """
            Analyze CPG data completeness by examining:
                    1. Does the DISCOVERED data provide sufficient structural detail to answer the user's question? Looking at its neighbor may help.
                    2. Are there references to classes/types that we haven't discovered structurally?
                    3. For type relationships and dependencies, do we have complete structural information?
                    4. Based on the query execution history, have we adequately explored the entities and their properties within the CPG?
                    5. Were there failed queries that indicate missing data or relationships we should investigate?
                    6. Do the raw query results show patterns or gaps that require additional targeted queries?
                    7. **TOLERANCE FOR CPG ERRORS**: If relationships are missing/unclear due to CPG creation issues, can we drill into entity BODY content to extract implementation details (e.g., class body, method implementations, field declarations)?
                    8. **ENTITY BODY EXPLORATION**: Are there key entities where we need to examine their body/implementation to understand relationships that weren't captured in the CPG structure?
                    9. **REPEATED QUERY DETECTION**: Have we executed similar inheritance/relationship queries multiple times with 0 results? This may indicate the relationships don't exist in this CPG structure and we should try different approaches.
                    10. Can we provide a comprehensive answer with the available CPG structural data?
            
            Return "SUFFICIENT" if we can adequately answer the user's question with the CPG data, or "NEED_MORE" explaining what specific data is missing.
                    
            **SPECIAL CASE**: If CPG relationships are corrupted/missing but entities exist, return "NEED_BODY_EXPLORATION" followed by a list of entity names whose bodies should be examined for implementation details.
            """
            feedback_section = ""
            
            sufficiency_prompt = f"""
                    Analyze the completeness of discovered data for answering the user's query:

                    {feedback_section}
                    
                    User Query: {state['user_query']}
                    Intent: {state['intent']}
                    
                    === DISCOVERED DATA ===
                    Discovered Data ({len(state['discovered_data'])} items):
                    {json.dumps(state['discovered_data'], indent=2)}
                    
                    === CPG QUERY EXECUTION HISTORY ===
                    Total Queries Executed: {len(state.get('query_history', []))}
                    Query Execution Details:
                    {chr(10).join([f"Query {i+1}: {query.get('purpose', 'Unknown')} ({'SUCCESS' if query.get('status') == 'success' else 'FAILED'})" + (f" - {query.get('results_count', 0)} results_count" if query.get('status') == 'success' else f" - {query.get('error', 'Unknown error')}") for i, query in enumerate(state.get('query_history', []))])}
                    
                    Raw Query Results ({len(state.get('raw_query_results', []))} total):
                    {json.dumps(state.get('raw_query_results', []), indent=2) if state.get('raw_query_results') else 'No raw results available'}
                    
                    **COMPLETE GRAPH SCHEMA INFORMATION**:
                    
                    **NODE TYPES AND ATTRIBUTES**:
                    {chr(10).join([f"- {node}: {', '.join(attrs.get('attributes', []))}" for node, attrs in state['schema'].get('nodes', {}).items()])}
                    
                    **RELATIONSHIP TYPES AND CONNECTIONS**:
                    {chr(10).join([f"- {rel}: {rel_def.get('from', 'Unknown')} → {rel_def.get('to', 'Unknown')}" for rel, rel_def in state['schema'].get('relationships', {}).items()])}
                    
                    **DETAILED NODE DEFINITIONS**:
                    {json.dumps(state['schema'].get('NodeDefinitions', {}), indent=2) if state['schema'].get('NodeDefinitions') else 'Node definitions not available'}
                    
                    **RELATIONSHIP DEFINITIONS**:
                    {json.dumps(state['schema'].get('EdgeDefinitions', {}), indent=2) if state['schema'].get('EdgeDefinitions') else 'Edge definitions not available'}
                    
                    Iteration: {state['current_iteration']}/{state['max_iterations']}
                    
                    CRITICAL: Respond with ONLY valid JSON in this exact format:
                    {{
                        "is_sufficient": True/False,
                        "decision": "SUFFICIENT|NEED_MORE|NEED_BODY_EXPLORATION", 
                        "gaps_summary": "Brief summary of what's missing",
                        "data_gaps": {{
                            "missing_entities": ["list of entities we need"],
                            "missing_relationships": ["list of relationships to explore"],
                            "missing_attributes": ["specific node attributes needed"],
                            "suggested_queries": ["list of suggested Cypher queries"]
                        }},
                        "body_exploration_needed": True/False,
                        "entities_for_body_exploration": ["entity1", "entity2"],
                        "confidence": 0.0-1.0,
                        "reasoning": "Detailed analysis of why sufficient or insufficient"
                    }}

                    EVALUATION CRITERIA:
                    1. Does the discovered data provide sufficient detail to answer the user's question?
                    2. Are there references to classes/types that we haven't discovered structurally?
                    3. For type relationships and dependencies, do we have complete structural information?
                    4. Have we adequately explored the entities and their properties within the CPG?
                    5. Were there failed queries indicating missing data or relationships?
                    6. Do the raw query results show patterns or gaps requiring additional targeted queries?
                    7. **TOLERANCE FOR CPG ERRORS**: If relationships are missing/unclear due to CPG creation issues, should we drill into entity BODY content?
                    8. **REPEATED QUERY DETECTION**: Have we executed similar queries multiple times with 0 results?
                    9. For lookup queries (like finding comments), is "no data found" a valid sufficient answer?
                    10. Can we provide a comprehensive answer with available CPG structural data?
                    11. **DISCOVERY RESEARCH CHECK**: Do termination criteria from initial discovery research suggest we should stop?
                    
                    **DISCOVERY RESEARCH TERMINATION GUIDANCE**:
                    {self._format_discovery_research_for_evaluation(state.get('discovery_research'))}
                
                """
            for attempt in range(max_attempts):
                try:
                    
                    result = await self.llm_service.generate_response(sufficiency_prompt, json_mode=True)
                    
                    if not result or result.error:
                        raise Exception(f"LLM service error: {result.error if result else 'No response'}")
                    
                    # Try to parse JSON response
                    try:
                        sufficiency_result = json.loads(result.content.strip())

                        logger.info(f"🔍 Raw sufficiency evaluation result: {result.content}...")
                        
                        # Validate required fields
                        required_fields = ["is_sufficient", "decision", "gaps_summary", "data_gaps"]
                        missing_fields = [field for field in required_fields if field not in sufficiency_result]
                        
                        if missing_fields:
                            if attempt < max_attempts - 1:
                                logger.warning(f"⚠️ Missing required fields (attempt {attempt + 1}/{max_attempts}): {missing_fields}")
                                
                                # Add feedback for missing fields
                                feedback_section = f"""
                                **PREVIOUS ATTEMPT MISSING REQUIRED FIELDS:**
                                Your response was missing: {', '.join(missing_fields)}
                                
                                **YOUR RESPONSE WAS:** {result.content}
                                
                                **ALL REQUIRED FIELDS MUST BE PRESENT:**
                                - is_sufficient (boolean: true or false)
                                - decision (string: "SUFFICIENT", "NEED_MORE", or "NEED_BODY_EXPLORATION")
                                - gaps_summary (string: brief description)
                                - data_gaps (object with missing_entities, missing_relationships, missing_attributes, suggested_queries arrays)
                                
                                **COMPLETE TEMPLATE:**
                                {{
                                    "is_sufficient": false,
                                    "decision": "NEED_MORE",
                                    "gaps_summary": "Brief summary of what is missing",
                                    "data_gaps": {{
                                        "missing_entities": [],
                                        "missing_relationships": [],
                                        "missing_attributes": [],
                                        "suggested_queries": []
                                    }},
                                    "body_exploration_needed": false,
                                    "entities_for_body_exploration": [],
                                    "confidence": 0.7,
                                    "reasoning": "Detailed explanation"
                                }}
                                """
                                continue  # Retry with feedback
                            else:
                                raise json.JSONDecodeError(f"Missing required fields: {missing_fields}", result.content, 0)
                        
                        # Set defaults for optional fields
                        sufficiency_result.setdefault("body_exploration_needed", sufficiency_result.get("decision") == "NEED_BODY_EXPLORATION")
                        sufficiency_result.setdefault("entities_for_body_exploration", [])
                        sufficiency_result.setdefault("confidence", 0.5)
                        sufficiency_result.setdefault("reasoning", "No reasoning provided")
                        
                        logger.info(f"🔍 Sufficiency evaluation (attempt {attempt + 1}): {sufficiency_result.get('decision', 'Unknown')}")
                        break  # Success, exit retry loop
                        
                    except json.JSONDecodeError as je:
                        if attempt < max_attempts - 1:
                            logger.warning(f"⚠️ JSON parsing failed (attempt {attempt + 1}/{max_attempts}): {je}")
                            logger.warning(f"Raw response: {result.content[:200]}...")
                            
                            # Add feedback for next attempt
                            feedback_section = f"""
                            **PREVIOUS ATTEMPT FAILED - JSON PARSING ERROR:**
                            Your last response was: {result.content[:500]}...
                            
                            **ERROR:** {str(je)}
                            
                            **CRITICAL FIXES NEEDED:**
                            - Use "true"/"false" (lowercase) not "True"/"False" 
                            - All strings must be in quotes
                            - No trailing commas after last item
                            - Proper bracket matching {{}} and []
                            - No comments in JSON
                            - Numbers should be unquoted (0.8 not "0.8")
                            
                            **CORRECT FORMAT EXAMPLE:**
                            {{
                                "is_sufficient": false,
                                "decision": "NEED_MORE",
                                "gaps_summary": "Missing data",
                                "data_gaps": {{
                                    "missing_entities": [],
                                    "missing_relationships": [],
                                    "missing_attributes": [],
                                    "suggested_queries": []
                                }},
                                "body_exploration_needed": true,
                                "entities_for_body_exploration": [],
                                "confidence": 0.5,
                                "reasoning": "Explanation here"
                            }}
                            """
                            continue  # Retry with feedback
                        else:
                            # Final attempt failed, create fallback structure
                            logger.error(f"❌ All JSON parsing attempts failed. Using fallback structure.")
                            sufficiency_result = {
                                "is_sufficient": False,
                                "decision": "NEED_MORE",
                                "gaps_summary": "JSON parsing failed - need more data",
                                "data_gaps": {"parsing_error": str(je), "raw_response": result.content},
                                "body_exploration_needed": False,
                                "entities_for_body_exploration": [],
                                "confidence": 0.0,
                                "reasoning": f"JSON parsing failed after {max_attempts} attempts: {je}"
                            }
                            
                except Exception as e:
                    if attempt < max_attempts - 1:
                        logger.warning(f"⚠️ Sufficiency evaluation failed (attempt {attempt + 1}/{max_attempts}): {e}")
                        continue  # Retry
                    else:
                        logger.error(f"❌ All sufficiency evaluation attempts failed: {e}")
                        sufficiency_result = {
                            "is_sufficient": False,
                            "decision": "NEED_MORE", 
                            "gaps_summary": "Evaluation failed - need more data",
                            "data_gaps": {"error": str(e)},
                            "body_exploration_needed": False,
                            "entities_for_body_exploration": [],
                            "confidence": 0.0,
                            "reasoning": f"Evaluation failed after {max_attempts} attempts: {e}"
                        }

            logger.info(f"🔍 Sufficiency evaluation result: {json.dumps(sufficiency_result, indent=2)}")
            logger.info(f"Query History Details: {state.get('query_history', [])}")
            # Secondary validation: Check for schema violations and correct guidance
            if sufficiency_result and not sufficiency_result.get("is_sufficient", True):
                correction_prompt = f"""
                Review this sufficiency evaluation result for schema violations and correct any invalid suggestions:
                
                User Query: {state['user_query']}
                Intent: {state['intent']}
                
                ORIGINAL RESULT:
                {json.dumps(sufficiency_result, indent=2)}

                CORRECTION RULES:
                1. Replace invalid "missing_entities" with actual schema entities that might contain needed information (e.g., replace "Comment" with ["Type", "Function", "Block"])
                2. Replace invalid "missing_relationships" with actual schema relationships that should be explored (e.g., ["CONTAINS", "DEFINED_IN"])
                3. Fix "suggested_queries" to only use valid node types, node attributes and relationships
                4. For comments/documentation, suggest exploring existing node body attributes (Type.body, Function.body, Block.statements)
                5. Populate missing_entities and missing_relationships with actionable schema entities/relationships, don't leave them empty
                6. Learn from executed queries and raw results to provide specific guidance within schema constraints, don't recommend things that have already been tried
                7. Keep the same decision and reasoning, just fix the technical suggestions.
                8. Only if you cannot think of any new valid queries to answer the user's question, return "SUFFICIENT" as the decision, with valid reasoning.

                === COMPLETE GRAPH SCHEMA INFORMATION ===
                **NODE TYPES AND ATTRIBUTES**:
                {chr(10).join([f"- {node}: {', '.join(attrs.get('attributes', []))}" for node, attrs in state['schema'].get('nodes', {}).items()])}
                
                **RELATIONSHIP TYPES AND CONNECTIONS**:
                {chr(10).join([f"- {rel}: {rel_def.get('from', 'Unknown')} → {rel_def.get('to', 'Unknown')}" for rel, rel_def in state['schema'].get('relationships', {}).items()])}
                
                **DETAILED NODE DEFINITIONS**:
                {json.dumps(state['schema'].get('NodeDefinitions', {}), indent=2) if state['schema'].get('NodeDefinitions') else 'Node definitions not available'}
                
                **RELATIONSHIP DEFINITIONS**:
                {json.dumps(state['schema'].get('EdgeDefinitions', {}), indent=2) if state['schema'].get('EdgeDefinitions') else 'Edge definitions not available'}
                
                Total Queries Executed: {len(state.get('query_history', []))}

                Query Execution Details:
                {chr(10).join([f"Query {i+1}: {query.get('purpose', 'Unknown')} ({'SUCCESS' if query.get('status') == 'success' else 'FAILED'})" + (f" - {query.get('results_count', 0)} results_count" if query.get('status') == 'success' else f" - {query.get('error', 'Unknown error')}") for i, query in enumerate(state.get('query_history', []))])}
                
                Raw Query Results ({len(state.get('raw_query_results', []))} total):
                {json.dumps(state.get('raw_query_results', []), indent=2) if state.get('raw_query_results') else 'No raw results available'}
                
                Return ONLY the corrected JSON in the same format:
                """
                
                correction_result = await self.llm_service.generate_response(correction_prompt, json_mode=True)
                
                if correction_result and not correction_result.error:
                    try:
                        logger.info(f"🔍 Corrected sufficiency evaluation: {correction_result.content.strip()}")
                        corrected_sufficiency = json.loads(correction_result.content)
                        # Validate the corrected result has same structure
                        if all(key in corrected_sufficiency for key in ["is_sufficient", "decision", "gaps_summary", "data_gaps"]):
                            sufficiency_result = corrected_sufficiency
                            logger.info("🔧 Applied schema-based corrections to sufficiency evaluation")
                        else:
                            logger.warning("⚠️ Corrected result missing required fields, keeping original")
                    except json.JSONDecodeError:
                        logger.warning("⚠️ Failed to parse corrected sufficiency result, keeping original")

            # Extract decision from validated JSON result
            is_sufficient = sufficiency_result.get("is_sufficient", False)
            state["data_gaps"] = sufficiency_result.get("data_gaps", {})
            state["body_exploration_needed"] = sufficiency_result.get("body_exploration_needed", False)
            
            logger.info(f"✅ Sufficiency evaluation: {sufficiency_result.get('decision', 'Unknown')} - {'Sufficient' if is_sufficient else 'Insufficient'}")
            logger.info(f"🔍 Data gaps: {sufficiency_result.get('gaps_summary', 'None')}")
            logger.info(f"🔍 Confidence: {sufficiency_result.get('confidence', 0.0)}")
            
            return {
                **state,
                "should_continue": not is_sufficient,
                "current_node": "evaluate_sufficiency"
            }
            
        except Exception as e:
            logger.error(f"❌ Sufficiency evaluation failed: {e}")
            return {**state, "error": f"Sufficiency evaluation failed: {e}"}
    
    def _format_guidance_for_query_generation(self, data_gaps) -> str:
        """Format the data_gaps guidance in an actionable way for query generation"""
        if not data_gaps:
            return "No specific rethink guidance yet - this is the first query."
            
        if isinstance(data_gaps, dict):
            guidance_parts = []
            
            # Missing entities guidance
            missing_entities = data_gaps.get('missing_entities', [])
            if missing_entities:
                guidance_parts.append(f"**FOCUS ON THESE ENTITIES**: {', '.join(missing_entities)}")
            
            # Missing relationships guidance  
            missing_relationships = data_gaps.get('missing_relationships', [])
            if missing_relationships:
                guidance_parts.append(f"**EXPLORE THESE RELATIONSHIPS**: {', '.join(missing_relationships)}")
            
            # Missing attributes guidance
            missing_attributes = data_gaps.get('missing_attributes', [])
            if missing_attributes:
                guidance_parts.append(f"**CHECK THESE ATTRIBUTES**: {', '.join(missing_attributes)}")
            
            # Suggested queries (most actionable)
            suggested_queries = data_gaps.get('suggested_queries', [])
            if suggested_queries:
                guidance_parts.append("**SUGGESTED APPROACH**:")
                for i, query in enumerate(suggested_queries[:2], 1):  # Limit to 2 most relevant
                    guidance_parts.append(f"{i}. {query}")
            
            # Gaps summary
            gaps_summary = data_gaps.get('gaps_summary', '')
            if gaps_summary:
                guidance_parts.append(f"**WHAT'S MISSING**: {gaps_summary}")
            
            return '\n'.join(guidance_parts) if guidance_parts else "No specific guidance available."
            
        else:
            return str(data_gaps)

    def _format_discovery_research_for_query_generation(self, discovery_research) -> str:
        """Format discovery research insights for query generation guidance"""
        if not discovery_research:
            return "No discovery research available - this is initial exploration."
        
        guidance_parts = []
        
        # Schema analysis insights
        schema_analysis = discovery_research.get('schema_analysis', {})
        if schema_analysis:
            relevant_nodes = schema_analysis.get('relevant_node_types', [])
            if relevant_nodes:
                guidance_parts.append(f"**RESEARCH IDENTIFIED RELEVANT NODES**: {', '.join(relevant_nodes)}")
            
            data_candidates = schema_analysis.get('data_storage_candidates', {})
            if data_candidates:
                content_attrs = data_candidates.get('content_attributes', [])
                if content_attrs:
                    guidance_parts.append(f"**CONTENT LIKELY STORED IN**: {', '.join(content_attrs)} attributes")
        
        # Hypothesis insights
        hypotheses = discovery_research.get('hypotheses', [])
        if hypotheses:
            high_likelihood = [h for h in hypotheses if h.get('likelihood') == 'high']
            if high_likelihood:
                guidance_parts.append("**HIGH-LIKELIHOOD HYPOTHESES**:")
                for h in high_likelihood:
                    guidance_parts.append(f"- {h.get('hypothesis', 'Unknown')}")
        
        # Execution plan insights
        execution_plan = discovery_research.get('execution_plan', {})
        if execution_plan:
            fallbacks = execution_plan.get('fallback_strategies', [])
            if fallbacks:
                guidance_parts.append(f"**AVAILABLE FALLBACK STRATEGIES**: {', '.join(fallbacks[:2])}")
            
            termination = execution_plan.get('termination_criteria', [])
            if termination:
                guidance_parts.append(f"**RESEARCH TERMINATION CRITERIA**: {termination[0] if termination else 'None'}")
        
        return '\n'.join(guidance_parts) if guidance_parts else "Discovery research completed - use insights to guide targeted queries."

    def _format_discovery_research_for_evaluation(self, discovery_research) -> str:
        """Format discovery research insights for sufficiency evaluation guidance"""
        if not discovery_research:
            return "No discovery research available - standard evaluation applies."
        
        guidance_parts = []
        
        # Check termination criteria from execution plan
        execution_plan = discovery_research.get('execution_plan', {})
        if execution_plan:
            termination_criteria = execution_plan.get('termination_criteria', [])
            if termination_criteria:
                guidance_parts.append("**RESEARCH-DEFINED TERMINATION CRITERIA**:")
                for criterion in termination_criteria:
                    guidance_parts.append(f"- {criterion}")
                
                guidance_parts.append("\n**EVALUATION GUIDANCE**: Check if any of the above criteria are met by current query results.")
        
        # Include research expectations for comparison
        hypotheses = discovery_research.get('hypotheses', [])
        if hypotheses:
            high_likelihood = [h for h in hypotheses if h.get('likelihood') == 'high']
            if high_likelihood:
                guidance_parts.append("\n**RESEARCH EXPECTATIONS TO VALIDATE**:")
                for h in high_likelihood:
                    guidance_parts.append(f"- Expected: {h.get('hypothesis', 'Unknown')}")
                    guidance_parts.append(f"  Reason: {h.get('reasoning', 'No reasoning provided')}")
        
        # Add strategy-specific guidance
        strategies = discovery_research.get('strategies', [])
        if strategies:
            primary_strategy = strategies[0] if strategies else {}
            expected_queries = primary_strategy.get('expected_query_count', 0)
            if expected_queries > 0:
                guidance_parts.append(f"\n**RESEARCH EXPECTED ~{expected_queries} QUERIES** - consider this when evaluating if exploration is complete.")
        
        return '\n'.join(guidance_parts) if guidance_parts else "Discovery research completed - standard sufficiency evaluation applies."

    async def _check_fallback_needed(self, state: AgentState) -> bool:
        """
        Enhanced fallback detection for CPG-only workflow to catch inheritance query loops
        """
        current_iteration = state.get('current_iteration', 1)
        discovered_data = state.get('discovered_data', [])
        query_history = state.get('query_history', [])
        
        # Activate fallback if:
        # 1. We're past iteration 3 (reduced from 2 to catch loops faster)
        # 2. Recent queries are returning empty results (even with substantial data)
        # 3. Repeated inheritance/relationship pattern queries
        
        if current_iteration <= 3:
            return False
            
        # Check for repeated query patterns (inheritance query loops)
        if len(query_history) >= 4:
            recent_queries = query_history[-4:]
            inheritance_queries = [q for q in recent_queries if 'INHERITS_FROM' in q.get('query', '') or 'IMPLEMENTS' in q.get('query', '')]
            failed_inheritance_queries = [q for q in inheritance_queries if q.get('result_count', 0) == 0]
            
            # If we have 3+ failed inheritance queries, activate fallback regardless of total data
            if len(failed_inheritance_queries) >= 3:
                logger.info(f"🔄 Fallback needed: {len(failed_inheritance_queries)} failed inheritance queries detected")
                return True
        
        # Original logic: Check if recent queries are consistently failing
        recent_queries = query_history[-3:] if len(query_history) >= 3 else query_history
        recent_failures = [q for q in recent_queries if q.get('result_count', 0) == 0]
        
        if len(recent_failures) >= 2:  # 2+ consecutive failures
            logger.info(f"🔄 Fallback needed: {len(recent_failures)} recent failures, {len(discovered_data)} total results")
            return True
            
        return False
    
    async def synthesize_response(self, state: AgentState) -> AgentState:
        """Node: Synthesize final response with smart context management"""
        logger.info("🧠 Node: synthesize_response")
        
        try:
            # Use smart context management - prioritize organized data over raw data
            context_data = self._prepare_synthesis_context(state)
            
            synthesis_prompt = f"""
            Synthesize a comprehensive answer based on the discovered CPG data:
            
            User Query: {state['user_query']}
            Intent: {state.get('intent', 'Unknown')}
            
            === ARCHITECTURAL SUMMARY ===
            {json.dumps(context_data['architectural_summary'], indent=2)}
            
            === ORGANIZED STRUCTURE ===
            {json.dumps(context_data['organized_data'], indent=2)}
            
            === COMPLETE RAW DATA ===
            {json.dumps(state.get('discovered_data', []), indent=2)}
            
            === ALL QUERY EXECUTION DETAILS ===
            {json.dumps(state.get('all_executed_queries', []), indent=2)}
            
            === EXECUTION METADATA ===
            Project: {state['project_name']}
            Iterations: {state['current_iteration']}
            Queries Executed: {len(state['query_history'])}
            Total Raw Results: {len(state['discovered_data'])}
            
            === QUERY EXECUTION SUMMARY ===
            {chr(10).join([f"Query {i+1}: {query.get('purpose', 'Unknown')} ({'SUCCESS' if query.get('status') == 'success' else 'FAILED'})" + (f" - {query.get('results_count', 0)} results_count" if query.get('status') == 'success' else f" - {query.get('error', 'Unknown error')}") for i, query in enumerate(state.get('query_history', []))])}
            
            === SYNTHESIS INSTRUCTIONS ===
            Provide a direct, clear response that:
            1. **SPECIFICALLY ANSWERS THE USER'S QUESTION** - if no data was found, explicitly state that
            2. **DISTINGUISHES BETWEEN**: 
               - "No data found" (successful query with 0 results) vs "Insufficient data" (failed queries/incomplete exploration)
               - For file-specific queries (comments, specific code), clearly state if the file contains no such content
            3. Uses actual discovered data (no fabrication or speculation)
            4. For architectural queries: explains patterns and relationships found
            5. For lookup queries: provides direct, concise answers
            6. **EXAMPLES OF CLEAR RESPONSES**:
               - "WorkerA.cs contains no comment lines" (for comment queries with 0 results)
               - "No inheritance relationships found in HelloWorldApp" (for inheritance with 0 results)
               - "Unable to determine due to insufficient CPG data" (for failed queries)
            
            **CRITICAL**: If queries successfully executed but returned 0 results for specific content (comments, etc.), this means the content doesn't exist - state this clearly rather than claiming insufficient data.
            
            **DATA USAGE**: Use the COMPLETE RAW DATA and ALL QUERY EXECUTION DETAILS for synthesis - do not rely only on organized summaries as they may miss important details. Examine all query results and their raw outputs to provide accurate answers.
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
            
            logger.info(f"✅ Response synthesized and validated ({len(response)} chars) using {context_data['context_size']} context chars")
            return {
                **state,
                "response": response,
                "final_results": state["discovered_data"],
                "current_node": "synthesize_response",
                "synthesis_context_used": context_data['context_size']
            }
            
        except Exception as e:
            logger.error(f"❌ Response synthesis failed: {e}")
            return {
                **state,
                "error": f"Response synthesis failed: {e}",
                "response": f"Error generating response: {e}"
            }
    
    # ========== WORKFLOW CONTROL FUNCTIONS ==========
    
    def should_continue_exploring(self, state: AgentState) -> str:
        """Conditional edge: decide whether to continue exploring or synthesize"""
        
        if state.get("error"):
            return "error"
        
        if not state.get("should_continue", True):
            return "synthesize"
        
        if state.get("current_iteration", 0) >= state.get("max_iterations", 5):
            return "synthesize"
        
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
    
    # Research-based discovery methods
    async def _analyze_schema_for_query(self, state: AgentState) -> SchemaAnalysis:
        """Step 1: Analyze schema to understand data storage possibilities"""
        
        schema_prompt = f"""
        Analyze this CPG schema to understand how the user's query data might be stored.
        
        User Query: {state['user_query']}
        Intent: {state.get('intent_analysis', {}).get('query_type', 'unknown')}
        
        **COMPLETE SCHEMA**:
        {json.dumps(state['schema'], indent=2)}
        
        Based on the query and schema, identify:
        1. Which node types are most relevant to this query
        2. How the requested data might be stored (attributes, relationships, etc.)
        3. Which relationships should be explored
        4. Your reasoning for these choices
        
        Respond with JSON:
        {{
            "relevant_node_types": ["list", "of", "relevant", "node", "types"],
            "data_storage_candidates": {{
                "content_attributes": ["attribute1", "attribute2"],
                "structural_relationships": ["rel1", "rel2"],
                "metadata_fields": ["field1", "field2"]
            }},
            "relationships_to_explore": ["relationship1", "relationship2"],
            "reasoning": "detailed explanation of analysis"
        }}
        """
        
        # Retry loop with feedback for schema analysis
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                result = await self.llm_service.generate_response(schema_prompt, json_mode=True)
                data = json.loads(result.content)
                
                # Validate required fields
                required_fields = ["relevant_node_types", "data_storage_candidates", "relationships_to_explore", "reasoning"]
                missing_fields = [field for field in required_fields if field not in data]
                
                if missing_fields:
                    if attempt < max_attempts - 1:
                        logger.warning(f"⚠️ Schema analysis missing fields (attempt {attempt + 1}): {missing_fields}")
                        schema_prompt += f"\n\n**PREVIOUS ATTEMPT MISSING**: {', '.join(missing_fields)}\nMust include ALL required fields in JSON response."
                        continue
                    else:
                        raise ValueError(f"Missing required fields: {missing_fields}")
                
                return SchemaAnalysis(**data)
                
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Schema analysis failed (attempt {attempt + 1}): {e}")
                    schema_prompt += f"\n\n**PREVIOUS ATTEMPT ERROR**: {str(e)}\nRespond with ONLY valid JSON in exact format specified."
                    continue
                else:
                    logger.error(f"❌ All schema analysis attempts failed: {e}")
                    return SchemaAnalysis(
                        relevant_node_types=["File", "Function", "Type"],
                        data_storage_candidates={"content_attributes": ["body"], "structural_relationships": ["CONTAINS"]},
                        relationships_to_explore=["CONTAINS", "DEFINED_IN"],
                        reasoning=f"Fallback analysis due to parsing error: {e}"
                    )
    
    async def _generate_exploration_hypotheses(self, state: AgentState, schema_analysis: SchemaAnalysis) -> List[ExplorationHypothesis]:
        """Step 2: Generate hypotheses about how data might be represented"""
        
        hypothesis_prompt = f"""
        Based on schema analysis, generate hypotheses about how to find the requested data.
        
        User Query: {state['user_query']}
        Schema Analysis: {asdict(schema_analysis)}
        
        Generate 2-4 hypotheses about where/how the data might be stored, ordered by likelihood.
        Each hypothesis should suggest a different approach to find the data.
        
        Respond with JSON:
        {{
            "hypotheses": [
                {{
                    "hypothesis": "description of where/how data might be stored",
                    "likelihood": "high|medium|low",
                    "reasoning": "why this approach makes sense",
                    "test_approach": "how to test this hypothesis"
                }}
            ]
        }}
        """
        
        # Retry loop with feedback for hypotheses generation
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                result = await self.llm_service.generate_response(hypothesis_prompt, json_mode=True)
                data = json.loads(result.content)
                
                if 'hypotheses' not in data:
                    if attempt < max_attempts - 1:
                        logger.warning(f"⚠️ Hypotheses missing 'hypotheses' field (attempt {attempt + 1})")
                        hypothesis_prompt += f"\n\n**PREVIOUS ATTEMPT ERROR**: Response must include 'hypotheses' array field."
                        continue
                    else:
                        raise ValueError("Missing 'hypotheses' field")
                
                # Validate each hypothesis has required fields
                hypotheses = []
                for h in data.get('hypotheses', []):
                    required_fields = ["hypothesis", "likelihood", "reasoning", "test_approach"]
                    if all(field in h for field in required_fields):
                        hypotheses.append(ExplorationHypothesis(**h))
                
                if not hypotheses and attempt < max_attempts - 1:
                    logger.warning(f"⚠️ No valid hypotheses parsed (attempt {attempt + 1})")
                    hypothesis_prompt += f"\n\n**PREVIOUS ATTEMPT ERROR**: Each hypothesis must have: hypothesis, likelihood, reasoning, test_approach fields."
                    continue
                
                return hypotheses if hypotheses else [
                    ExplorationHypothesis(
                        hypothesis="Data stored in node body attributes",
                        likelihood="high", 
                        reasoning="Most content is typically stored in body fields",
                        test_approach="Search body attributes for patterns"
                    )
                ]
                
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Hypotheses generation failed (attempt {attempt + 1}): {e}")
                    hypothesis_prompt += f"\n\n**PREVIOUS ATTEMPT ERROR**: {str(e)}\nRespond with ONLY valid JSON."
                    continue
                else:
                    logger.error(f"❌ All hypotheses attempts failed: {e}")
                    return [
                        ExplorationHypothesis(
                            hypothesis="Data stored in node body attributes",
                            likelihood="high",
                            reasoning="Most content is typically stored in body fields",
                            test_approach="Search body attributes for patterns"
                        )
                    ]
    
    async def _plan_query_strategies(self, state: AgentState, hypotheses: List[ExplorationHypothesis]) -> List[QueryStrategy]:
        """Step 3: Plan query strategies to test hypotheses"""
        
        strategy_prompt = f"""
        Create query strategies to systematically test these hypotheses.
        
        User Query: {state['user_query']}
        Target Elements: {state.get('intent_analysis', {}).get('target_elements', [])}
        Hypotheses: {[asdict(h) for h in hypotheses]}
        
        **SCHEMA**: {json.dumps(state['schema'], indent=2)}
        
        Generate 2-3 query strategies that will efficiently explore the hypotheses.
        Each strategy should be a complete Cypher query.
        
        Respond with JSON:
        {{
            "strategies": [
                {{
                    "strategy_name": "descriptive name",
                    "purpose": "what this strategy tests/discovers",
                    "query": "complete Cypher query",
                    "expected_outcome": "what results indicate success",
                    "priority": 1-5 (1=highest)
                }}
            ]
        }}
        """
        
        # Retry loop with feedback for query strategies
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                result = await self.llm_service.generate_response(strategy_prompt, json_mode=True)
                data = json.loads(result.content)
                
                if 'strategies' not in data:
                    if attempt < max_attempts - 1:
                        logger.warning(f"⚠️ Strategies missing 'strategies' field (attempt {attempt + 1})")
                        strategy_prompt += f"\n\n**PREVIOUS ATTEMPT ERROR**: Response must include 'strategies' array field."
                        continue
                    else:
                        raise ValueError("Missing 'strategies' field")
                
                # Validate each strategy has required fields
                strategies = []
                for s in data.get('strategies', []):
                    required_fields = ["strategy_name", "purpose", "query", "expected_outcome", "priority"]
                    if all(field in s for field in required_fields):
                        strategies.append(QueryStrategy(**s))
                
                if not strategies and attempt < max_attempts - 1:
                    logger.warning(f"⚠️ No valid strategies parsed (attempt {attempt + 1})")
                    strategy_prompt += f"\n\n**PREVIOUS ATTEMPT ERROR**: Each strategy must have: strategy_name, purpose, query, expected_outcome, priority fields."
                    continue
                
                return strategies if strategies else [
                    QueryStrategy(
                        strategy_name="structural_exploration",
                        purpose="Understand file structure",
                        query=f"MATCH (f:File {{name: '{state.get('intent_analysis', {}).get('target_elements', [''])[0] or 'unknown'}'}})-[:CONTAINS]->(n) RETURN labels(n)[0] as type, count(*)",
                        expected_outcome="Shows node types in file",
                        priority=1
                    )
                ]
                
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Query strategies failed (attempt {attempt + 1}): {e}")
                    strategy_prompt += f"\n\n**PREVIOUS ATTEMPT ERROR**: {str(e)}\nRespond with ONLY valid JSON."
                    continue
                else:
                    logger.error(f"❌ All strategy attempts failed: {e}")
                    return [
                        QueryStrategy(
                            strategy_name="structural_exploration",
                            purpose="Understand file structure",
                            query=f"MATCH (f:File {{name: '{state.get('intent_analysis', {}).get('target_elements', [''])[0] or 'unknown'}'}})-[:CONTAINS]->(n) RETURN labels(n)[0] as type, count(*)",
                            expected_outcome="Shows node types in file",
                            priority=1
                        )
                    ]
    
    async def _create_execution_plan(self, state: AgentState, strategies: List[QueryStrategy]) -> ExecutionPlan:
        """Step 4: Create execution plan with prioritized queries"""
        
        # Sort strategies by priority
        sorted_strategies = sorted(strategies, key=lambda x: x.priority)
        
        primary_queries = []
        for strategy in sorted_strategies[:3]:  # Top 3 strategies
            primary_queries.append({
                "query": strategy.query,
                "purpose": strategy.strategy_name,
                "reasoning": f"{strategy.purpose} - {strategy.expected_outcome}"
            })
        
        execution_plan = ExecutionPlan(
            primary_queries=primary_queries,
            fallback_strategies=[
                "Comprehensive content search across all text fields",
                "Metadata exploration if content search fails",
                "Relationship traversal exploration"
            ],
            termination_criteria=[
                "Found requested data in any query result",
                "Exhausted all reasonable exploration approaches",
                "Confirmed data does not exist in CPG"
            ]
        )
        
        return execution_plan
    
    def _generate_dynamic_strategy_guidance(self, state: AgentState) -> str:
        """Generate intent + entity aware discovery strategy based on schema analysis"""
        
        entities_found = state.get('entities_found', {})
        intent_analysis = state.get('intent_analysis', {})
        schema = state.get('schema', {})
        user_query = state.get('user_query', '')
        data_needed = intent_analysis.get('data_needed', [])
        
        if not entities_found or not schema:
            return "Missing entities or schema - use general discovery patterns"
        
        guidance_parts = [
            "**INTENT + ENTITY AWARE DISCOVERY STRATEGY**:",
            f"Query Intent: {intent_analysis.get('query_type', 'unknown').upper()}",
            f"Data Needed: {', '.join(data_needed) if data_needed else 'Not specified'}",
            ""
        ]
        
        # Analyze each disambiguated entity
        for entity, entity_data in entities_found.items():
            if not entity_data.get('found'):
                continue
                
            primary_type = entity_data.get('primary_type')
            if not primary_type:
                continue
                
            guidance_parts.append(f"**{entity} ({primary_type}) DISCOVERY STRATEGY**:")
            
            # Get node attributes and relationships from schema
            node_attrs = schema.get('nodes', {}).get(primary_type, {}).get('attributes', [])
            
            # Find outgoing relationships from this node type
            outgoing_rels = []
            incoming_rels = []
            for rel_name, rel_def in schema.get('relationships', {}).items():
                if rel_def.get('from') == primary_type:
                    outgoing_rels.append((rel_name, rel_def.get('to')))
                if rel_def.get('to') == primary_type:
                    incoming_rels.append((rel_name, rel_def.get('from')))
            
            # Strategy 1: Content vs Structure analysis
            has_content_attrs = any(attr in ['body', 'content', 'code', 'text'] for attr in node_attrs)
            
            if has_content_attrs and any(need in user_query.lower() for need in ['comment', 'content', 'code', 'implementation']):
                guidance_parts.append(f"→ CONTENT-LEVEL ANALYSIS: {primary_type} has content attributes {[a for a in node_attrs if a in ['body', 'content', 'code', 'text']]}")
                guidance_parts.append(f"→ Direct content search possible on {entity}")
            
            # Strategy 2: Containment-based discovery
            contains_rels = [rel for rel, target in outgoing_rels if 'CONTAINS' in rel.upper()]
            if contains_rels:
                targets = [target for rel, target in outgoing_rels if 'CONTAINS' in rel.upper()]
                guidance_parts.append(f"→ CONTAINMENT DISCOVERY: {entity} can contain {set(targets)} via {contains_rels}")
                guidance_parts.append(f"→ FOUNDATION STEP: First discover what {entity} contains, then query contained entities")
            
            # Strategy 3: Relationship-based discovery  
            if intent_analysis.get('query_type') in ['architectural', 'exploration']:
                if outgoing_rels:
                    guidance_parts.append(f"→ OUTGOING RELATIONSHIPS: {entity} connects to {dict(outgoing_rels)}")
                if incoming_rels:
                    guidance_parts.append(f"→ INCOMING RELATIONSHIPS: {entity} is referenced by {dict(incoming_rels)}")
            
            # Strategy 4: Data need specific guidance
            for need in data_needed:
                need_lower = need.lower()
                if 'inherit' in need_lower or 'extend' in need_lower:
                    inherit_rels = [rel for rel, target in outgoing_rels + incoming_rels if 'INHERIT' in rel.upper() or 'EXTEND' in rel.upper() or 'IMPLEMENT' in rel.upper()]
                    if inherit_rels:
                        guidance_parts.append(f"→ INHERITANCE ANALYSIS: Use relationships {inherit_rels} for inheritance queries")
                
                elif 'depend' in need_lower or 'import' in need_lower or 'reference' in need_lower:
                    dep_rels = [rel for rel, target in outgoing_rels + incoming_rels if any(word in rel.upper() for word in ['DEPEND', 'IMPORT', 'REFERENCE', 'CALL', 'USE'])]
                    if dep_rels:
                        guidance_parts.append(f"→ DEPENDENCY ANALYSIS: Use relationships {dep_rels} for dependency queries")
        
        # General schema-driven principles
        guidance_parts.extend([
            "",
            "**SCHEMA-DRIVEN DISCOVERY PRINCIPLES**:",
            "→ Container nodes organize structure but don't hold content - follow CONTAINS relationships",
            "→ Content queries require nodes with content attributes (body, code, text)",
            "→ Relationship queries use the specific relationship types defined in schema",
            "→ Multi-step discovery: broad containment first, then specific relationship traversal",
            f"→ Available node types: {list(schema.get('nodes', {}).keys())}",
            f"→ Available relationships: {list(schema.get('relationships', {}).keys())}"
        ])
        
        return '\n'.join(guidance_parts)
    
    async def _analyze_intent_with_validation(self, intent_prompt: str, max_attempts: int = 3) -> dict:
        """Analyze intent with LLM feedback loop for JSON format validation"""
        
        for attempt in range(max_attempts):
            try:
                logger.info(f"🎯 Intent analysis attempt {attempt + 1}/{max_attempts}")
                
                # Get LLM response
                intent_result = await self.llm_service.generate_response(intent_prompt, json_mode=True)
                
                if not intent_result or intent_result.error:
                    raise Exception(f"LLM error: {intent_result.error if intent_result else 'No response'}")
                
                # Try to parse JSON
                try:
                    parsed_intent = json.loads(intent_result.content)
                    
                    # Validate required fields
                    required_fields = ["query_type", "scope", "data_needed", "strategy", "target_elements", "reasoning"]
                    missing_fields = [field for field in required_fields if field not in parsed_intent]
                    
                    if missing_fields:
                        raise ValueError(f"Missing required fields: {missing_fields}")
                    
                    # Validate enum values
                    valid_query_types = ["lookup", "architectural", "exploration"]
                    valid_scopes = ["specific", "component", "system-wide"]
                    valid_data_needs = ["minimal", "moderate", "comprehensive"]
                    
                    if parsed_intent["query_type"] not in valid_query_types:
                        raise ValueError(f"Invalid query_type: {parsed_intent['query_type']}")
                    if parsed_intent["scope"] not in valid_scopes:
                        raise ValueError(f"Invalid scope: {parsed_intent['scope']}")
                    if parsed_intent["data_needed"] not in valid_data_needs:
                        raise ValueError(f"Invalid data_needed: {parsed_intent['data_needed']}")
                    
                    logger.info(f"✅ Valid intent analysis on attempt {attempt + 1}")
                    return parsed_intent
                    
                except json.JSONDecodeError as je:
                    logger.warning(f"JSON parse error on attempt {attempt + 1}: {je}")
                    error_msg = f"JSON parse error: {je}"
                except ValueError as ve:
                    logger.warning(f"Validation error on attempt {attempt + 1}: {ve}")
                    error_msg = f"Validation error: {ve}"
                
                # If not the last attempt, create feedback prompt for correction
                if attempt < max_attempts - 1:
                    feedback_prompt = f"""
                    The previous response had an error: {error_msg}
                    
                    Original response was: {intent_result.content}
                    
                    Please provide a corrected response with ONLY valid JSON in this exact format:
                    {{
                        "query_type": "lookup|architectural|exploration",
                        "scope": "specific|component|system-wide", 
                        "data_needed": "minimal|moderate|comprehensive",
                        "strategy": "description of discovery approach",
                        "target_elements": ["list", "of", "specific", "things", "to", "find"],
                        "reasoning": "why this categorization"
                    }}
                    
                    Ensure all required fields are present and use only the specified enum values.
                    """
                    intent_prompt = feedback_prompt
                
            except Exception as e:
                logger.warning(f"Intent analysis attempt {attempt + 1} failed: {e}")
                if attempt == max_attempts - 1:
                    raise e
        
        # Should not reach here, but just in case
        raise Exception("All intent analysis attempts failed")
    
    def _fallback_intent_analysis(self, user_query: str) -> dict:
        """Intelligent fallback intent analysis based on keyword patterns"""
        
        query_lower = user_query.lower()
        
        # Lookup patterns
        lookup_patterns = [
            "what is", "where is", "show me", "find", "get", "display",
            "last", "first", "content", "comment", "line", "specific"
        ]
        
        # Architectural patterns  
        architectural_patterns = [
            "how does", "what calls", "dependencies", "inherit", "implement",
            "relationship", "connect", "extend", "derive"
        ]
        
        # Exploration patterns
        exploration_patterns = [
            "all", "list all", "every", "throughout", "across", "security",
            "vulnerabilities", "patterns", "analysis"
        ]
        
        # Score each category
        lookup_score = sum(1 for pattern in lookup_patterns if pattern in query_lower)
        arch_score = sum(1 for pattern in architectural_patterns if pattern in query_lower)
        explore_score = sum(1 for pattern in exploration_patterns if pattern in query_lower)
        
        # Determine category
        if lookup_score >= arch_score and lookup_score >= explore_score:
            query_type = "lookup"
            scope = "specific" if any(word in query_lower for word in ["specific", "particular", "one", "this", "that"]) else "component"
            data_needed = "minimal"
        elif arch_score >= explore_score:
            query_type = "architectural"
            scope = "component"
            data_needed = "moderate"
        else:
            query_type = "exploration"
            scope = "system-wide"
            data_needed = "comprehensive"
        
        logger.info(f"🎯 Fallback analysis: lookup={lookup_score}, arch={arch_score}, explore={explore_score} → {query_type}")
        
        return {
            "query_type": query_type,
            "scope": scope,
            "data_needed": data_needed,
            "strategy": f"Fallback {query_type} analysis based on keyword patterns",
            "target_elements": [],
            "reasoning": f"Fallback analysis - {query_type} keywords detected"
        }
    
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
            Just because something is defined in the schema does not mean it is always captured, but if it is captured that's all will be present due to language parser restrictions. 
            However, nothing outside of those node types and relationships will ever exist.
            
            
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
            
            VALIDATION TASK:
            1. Analyze ALL the raw data to extract every entity name, relationship, and piece of information
            2. Cross-reference the response against this complete data inventory
            3. Identify any entities or information in the response that are NOT found in the raw data
            4. Detect data quality issues in the raw data (e.g., impossible relationships, duplicates, inconsistencies)
            5. Assess if data corruption contributed to potential hallucination in the response
            
            Return JSON with:
            {{
                "validated_response": "Corrected response that only uses information found in raw data",
                "hallucination_detected": true/false,
                "fabricated_entities": ["entities mentioned in response but not in raw data"],
                "data_quality_assessment": "Analysis of raw data quality issues discovered",
                "data_quality_score": "HIGH/MEDIUM/LOW based on data consistency",
                "next_iteration_recommendation": "Suggested approach for next iteration if data quality is poor"
            }}
            
            CORRECTION RULES:
            - If entities are mentioned that don't exist in raw data, remove them or replace with "Data not available"
            - If data quality is poor, acknowledge limitations and suggest body content search
            - If relationships seem impossible (class implementing itself), flag as data corruption
            - Be transparent about data quality issues rather than fabricating information
            """
            
            validation_result = await self.llm_service.generate_response(validation_prompt, json_mode=True)
            
            if validation_result and not validation_result.error:
                try:
                    validation_data = json.loads(validation_result.content)
                    
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
                    
                except json.JSONDecodeError:
                    logger.error("❌ Failed to parse validation result as JSON")
                    return response
            else:
                logger.warning("⚠️  Validation failed, returning original response")
                return response
                
        except Exception as e:
            logger.error(f"❌ Response validation failed: {e}")
            return response
    
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
                    capture_output=True,
                    timeout=120  # 2 minute timeout
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
async def create_adaptive_cpg_workflow() -> AdaptiveCPGAgentWorkflow:
    """Factory function to create the workflow"""
    workflow = AdaptiveCPGAgentWorkflow()
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
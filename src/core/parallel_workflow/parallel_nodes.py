"""
LangGraph Workflow Nodes for the Adaptive CPG Agent Workflow.

This module contains all the core LangGraph node implementations that form
the workflow orchestration. Each node is a discrete step in the CPG analysis process.

Key nodes:
- initialize_environment: Set up services and schema
- initial_discovery: Research-based discovery using ResearchEngine
- analyze_intent: Intent analysis with Pydantic validation
- generate_query: Query generation with research insights
- execute_query: CPG query execution via MCP
- evaluate_sufficiency: Data sufficiency evaluation
- synthesize_response: Final response synthesis

All nodes maintain LangGraph state management patterns and return proper state updates.
"""
import json
import logging
from typing import Dict, Any, List, Tuple
from pydantic import ValidationError

from .parallel_models import AgentState, DiagnosticQueryGeneration, EmptyResultConclusion, IntentAnalysis, SufficiencyEvaluation, ScopeAnalysis, QueryGeneration, SynthesisValidation, BatchConfiguration, ApproachBatch, ParallelExecutionState, BatchExecutionSummary
from .parallel_research_engine import ResearchEngine
from .parallel_context_manager import ContextManager
from ..llm_service import LLMResponse
from src.core.paths import NEO4J_CONFIG, SCHEMA_PATH, STATE_PKL, GENPOD_GRAPH_INDEXER_BIN

logger = logging.getLogger(__name__)


class WorkflowNodes:
    """
    Collection of LangGraph workflow nodes for the Adaptive CPG Agent.
    
    All methods are async and follow the LangGraph pattern:
    - Accept AgentState as input
    - Return updated AgentState
    - Handle errors gracefully
    - Log progress appropriately
    """
    
    def __init__(self):
        self.research_engine = None  # Will be initialized with llm_service
        self.context_manager = None  # Will be initialized with llm_service

    async def initialize_services(self, llm_service):
        """Initialize services that require LLM access."""
        self.research_engine = ResearchEngine(llm_service)
        self.context_manager = ContextManager(llm_service)

    async def initialize_environment(self, state: AgentState) -> AgentState:
        """
        Node: Initialize the workflow environment and load schema.
        
        Sets up the basic environment for the CPG workflow including
        schema loading and service initialization.
        """
        logger.info("🚀 Node: initialize_environment")
        
        try:
            # Initialize services if not already done
            if not self.research_engine and state.get('llm_service'):
                await self.initialize_services(state['llm_service'])
            
            # Load CPG schema
            import yaml
            schema_path = SCHEMA_PATH

            try:
                with open(schema_path, 'r') as f:
                    schema = yaml.safe_load(f)
                logger.info("✅ CPG schema loaded successfully")
            except Exception as e:
                logger.error(f"❌ Failed to load schema: {e}")
                # Provide fallback schema
                schema = {
                    "nodes": {
                        "Function": {"attributes": ["name", "body", "parameters"]},
                        "Type": {"attributes": ["name", "type_kind", "fields"]},
                        "Variable": {"attributes": ["name", "value", "type_kind"]},
                        "File": {"attributes": ["name", "file_path"]}
                    },
                    "relationships": {
                        "CALLS": {"from": "Function", "to": "Function"},
                        "CONTAINS": {"from": "File", "to": "Function"},
                        "DEFINED_IN": {"from": "Function", "to": "File"}
                    }
                }
            
            return {
                **state,
                "schema": schema,
                "current_node": "initialize_environment",
                "current_iteration": 1
            }
            
        except Exception as e:
            logger.error(f"❌ Environment initialization failed: {e}")
            return {
                **state,
                "current_node": "initialize_environment",
                "error": f"Environment initialization failed: {e}"
            }

    async def initial_discovery(self, state: AgentState) -> AgentState:
        """
        Node: Conduct research-based discovery analysis.
        
        Uses the ResearchEngine to perform systematic discovery research
        instead of making restrictive assumptions about data location.
        """
        logger.info("🔬 Node: initial_discovery (research-based)")
        
        try:
            if not self.research_engine:
                raise Exception("Research engine not initialized")
            
            # Conduct comprehensive discovery research
            research_results = await self.research_engine.conduct_discovery_research(state)
            
            # 🔍 DEBUG: Print research stage results
            logger.info("=" * 80)
            logger.info("📋 RESEARCH STAGE OUTPUT:")
            logger.info("=" * 80)
            
            if research_results:
                # Print data collection approaches
                if 'data_collection_approaches' in research_results:
                    logger.info("🔍 DATA COLLECTION APPROACHES:")
                    for i, approach in enumerate(research_results['data_collection_approaches'], 1):
                        logger.info(f"  {i}. {approach.get('approach_name', f'Approach {i}')}")
                        logger.info(f"     • Description: {approach.get('description', 'N/A')}")
                        logger.info(f"     • Target Nodes: {approach.get('target_nodes', [])}")
                        logger.info(f"     • Key Attributes: {approach.get('key_attributes', [])}")
                        logger.info(f"     • Relationships: {approach.get('relationships', [])}")
                        logger.info(f"     • Strategy: {approach.get('strategy', 'N/A')}")
                        if 'corrections_applied' in approach:
                            logger.info(f"     • Corrections: {approach.get('corrections_applied', [])}")
                        logger.info("")
                
                # Print audit results and research summary
                if 'audit_passed' in research_results:
                    logger.info("🔍 SCHEMA AUDIT RESULTS:")
                    logger.info(f"  • Audit Status: {'✅ PASSED' if research_results['audit_passed'] else '❌ FAILED'}")
                    if research_results.get('corrections_applied'):
                        logger.info(f"  • Schema Corrections Made: {research_results['corrections_applied']}")
                    logger.info("")
                
                if 'total_approaches' in research_results:
                    logger.info("📊 RESEARCH SUMMARY:")
                    logger.info(f"  • Total Validated Approaches: {research_results['total_approaches']}")
                    logger.info(f"  • Research Type: {research_results.get('research_type', 'simplified')}")
                    logger.info("  • Schema-Validated and Ready for Think → Generate → Execute → Rethink workflow phases")
                    logger.info("")
            
            logger.info("=" * 80)
            logger.info("✅ Research-based discovery completed successfully")
            
            # Set total approaches count for Think → Generate → Execute → Rethink workflow
            total_approaches = len(research_results.get('data_collection_approaches', []))
            
            return {
                "discovery_research": research_results,
                "total_approaches": total_approaches,  # Initialize for think step
                "current_node": "initial_discovery"
            }
            
        except Exception as e:
            logger.error(f"❌ Research-based discovery failed: {e}")
            return {
                **state,
                "current_node": "initial_discovery",
                "error": f"Discovery research failed: {e}"
            }

    async def analyze_intent(self, state: AgentState) -> AgentState:
        """
        Node: Analyze user intent with Pydantic validation.
        
        Determines whether the query is lookup, architectural, or hybrid
        with proper error handling and validation.
        """
        logger.info("🧠 Node: analyze_intent")
        
        try:
            # Perform intent analysis with validation
            intent_result = await self._analyze_intent_with_validation(state)
            
            # Extract intent information
            intent_type = intent_result.get('intent_type', 'lookup')
            confidence = intent_result.get('confidence', 0.7)
            
            logger.info(f"✅ Intent analyzed: {intent_type} (confidence: {confidence:.2f})")
            
            return {
                **state,
                "intent": intent_result,  # Store full intent analysis dict, not just the type string
                "intent_analysis": intent_result,
                "current_node": "analyze_intent"
            }
            
        except Exception as e:
            logger.error(f"❌ Intent analysis failed: {e}")
            # Fallback to default intent
            fallback_analysis = self._fallback_intent_analysis(state['user_query'])
            return {
                **state,
                "intent": fallback_analysis,  # Store full intent analysis dict, not just the type string
                "intent_analysis": fallback_analysis,
                "current_node": "analyze_intent"
            }

    async def generate_query(self, state: AgentState) -> AgentState:
        """
        Node: Generate targeted CPG queries using Think step results or regenerate queries based on syntax error feedback.
        
        Takes the current approach from Think step and generates specific
        Cypher queries with appropriate scope and limits. Also handles syntax error 
        feedback to regenerate corrected queries.
        """
        logger.info("🔍 Node: generate_query")
        
        try:
            # Check for syntax error feedback from previous execution
            execution_results = state.get('execution_results', [])
            has_syntax_error_feedback = False
            error_feedback = None
            original_failed_query = None
            
            if execution_results:
                latest_result = execution_results[-1]
                if (latest_result.get('status') == 'syntax_error' and 
                    latest_result.get('needs_regeneration')):
                    has_syntax_error_feedback = True
                    error_feedback = latest_result.get('error_feedback', '')
                    original_failed_query = latest_result.get('original_query', '')
                    logger.info("🔧 REGENERATION MODE: Fixing syntax error in previous query")
                    logger.info(f"🚫 Original failed query: {original_failed_query}")
                    logger.info(f"❌ Error feedback: {error_feedback}")
            
            # Get discovery research (contains all approaches)
            discovery_research = state.get('discovery_research', {})
            if not discovery_research:
                raise Exception("No discovery research available")
            
            data_collection_approaches = discovery_research.get('data_collection_approaches', [])
            if not data_collection_approaches:
                raise Exception("No data collection approaches available")
            
            # Get current approach index (Think step just analyzed this approach)
            current_approach_index = state.get('current_approach_index', 0)
            total_approaches = len(data_collection_approaches)
            
            # Get the current approach that Think step just analyzed
            current_approach_details = data_collection_approaches[current_approach_index]
            
            logger.info(f"🎯 Generate: {'Regenerating' if has_syntax_error_feedback else 'Creating'} query for approach {current_approach_index + 1}/{total_approaches}")
            
            # 🚀 DETAILED APPROACH QUEUE AND SELECTION LOGGING
            logger.info("")
            logger.info("=" * 150)
            logger.info("🔍 GENERATE STEP: APPROACH QUEUE AND SELECTION ANALYSIS")
            logger.info("=" * 150)
            
            # Show all available approaches in queue
            logger.info(f"📋 TOTAL APPROACHES IN QUEUE: {total_approaches}")
            for i, approach in enumerate(data_collection_approaches):
                prefix = "👉" if i == current_approach_index else "  "
                logger.info(f"{prefix} [{i+1}] {approach.get('approach_name', 'Unknown')}")
                if i == current_approach_index:
                    logger.info(f"     📝 Description: {approach.get('description', 'No description')}")
                    logger.info(f"     🎮 Target Nodes: {approach.get('target_nodes', [])}")
                    logger.info(f"     🔑 Key Attributes: {approach.get('key_attributes', [])}")
                    logger.info(f"     🔗 Relationships: {approach.get('relationships', [])}")
                    logger.info(f"     📊 Strategy: {approach.get('strategy', 'No strategy')}")
                    corrections = approach.get('corrections', [])
                    if corrections:
                        logger.info(f"     🔧 Schema Corrections: {corrections}")
            
            logger.info("")
            logger.info(f"🎯 SELECTED APPROACH: [{current_approach_index + 1}/{total_approaches}] {current_approach_details.get('approach_name', 'Unknown')}")
            logger.info("")
            logger.info("📋 COMPLETE APPROACH DETAILS (RAW):")
            import json
            logger.info(json.dumps(current_approach_details, indent=2, default=str))
            logger.info("")
            
            # For scope analysis, we need the thinking results from when this approach was analyzed
            thinking_results = state.get('thinking_results', {})
            
            # Extract approach details
            approach_name = current_approach_details.get('approach_name', 'Unknown')
            target_nodes = current_approach_details.get('target_nodes', [])
            key_attributes = current_approach_details.get('key_attributes', [])
            relationships = current_approach_details.get('relationships', [])
            strategy = current_approach_details.get('strategy', 'general')
            description = current_approach_details.get('description', 'No description')
            corrections = current_approach_details.get('corrections', [])
            
            # Get scope analysis from Think step
            current_scope = state.get('current_scope', 'single_file')
            retrieval_strategy = thinking_results.get('retrieval_strategy', {})
            query_limit = retrieval_strategy.get('limit', 75)
            
            logger.info("")
            logger.info("🎯 COMPLETE APPROACH DETAILS FOR QUERY GENERATION:")
            logger.info(f"  📝 Name: {approach_name}")
            logger.info(f"  📖 Description: {description}")
            logger.info(f"  📊 Strategy: {strategy}")
            logger.info(f"  🎮 Target Nodes: {target_nodes}")
            logger.info(f"  🔑 Key Attributes: {key_attributes}")
            logger.info(f"  🔗 Relationships: {relationships}")
            if corrections:
                logger.info(f"  🔧 Schema Corrections Applied: {corrections}")
            logger.info(f"  📊 Think Step Scope: {current_scope}")
            logger.info(f"  🎯 Query Limit: {query_limit}")
            logger.info(f"  🔍 Focus: {retrieval_strategy.get('focus', 'targeted')}")
            logger.info(f"  📏 Context Window: {retrieval_strategy.get('context_window', 'small')}")
            logger.info("=" * 150)
            logger.info("")
            
            # Build appropriate prompt based on whether we're fixing an error or generating new query
            if has_syntax_error_feedback:
                query_prompt = self._build_syntax_error_fix_prompt(
                    original_failed_query, error_feedback, current_approach_details, 
                    thinking_results, discovery_research, state
                )
            else:
                query_prompt = self._build_targeted_query_generation_prompt(
                    state, current_approach_details, thinking_results, discovery_research
                )
            
            # logger.info(f"📝 Query Generation Prompt:\n{query_prompt}")
            
            # Generate query using LLM service with retry and validation
            llm_service = state.get('llm_service')
            if not llm_service:
                raise Exception("LLM service not available")
            
            # Use retry mechanism with Pydantic validation for query generation
            query_data = await self._retry_llm_with_validation(
                llm_service=llm_service,
                initial_prompt=query_prompt,
                model_class=QueryGeneration,
                max_retries=3,
                operation_name="query generation"
            )
            
            # Extract multiple queries from the validated response
            queries_list = query_data.get('queries', [])
            approach_summary = query_data.get('approach_summary', '')
            
            # Handle approach index and syntax error count based on mode
            if has_syntax_error_feedback:
                # In regeneration mode, don't increment approach index but increment syntax error count
                next_approach_index = current_approach_index
                syntax_error_count = state.get('syntax_error_count', 0) + 1
                logger.info(f"🔧 Syntax error regeneration complete (retry #{syntax_error_count})")
            else:
                # In normal generation mode, increment approach index for next cycle
                next_approach_index = current_approach_index + 1
                syntax_error_count = state.get('syntax_error_count', 0)  # Keep current count
            
            # Log full results after successful generation
            self._log_generation_results_multiple(current_approach_details, queries_list, approach_summary)
            
            # Format queries for execute_queries node (all queries for this approach)
            generated_queries = []
            for i, single_query in enumerate(queries_list):
                generated_query = {
                    'approach_name': f"{approach_name} (Query {i+1})" if len(queries_list) > 1 else approach_name,
                    'cypher_query': single_query['cypher_query'],
                    'reasoning': single_query['reasoning'],
                    'query_purpose': single_query.get('query_purpose', ''),
                    'target_nodes': target_nodes,
                    'key_attributes': key_attributes,
                    'relationships': relationships,
                    'strategy': strategy
                }
                generated_queries.append(generated_query)
            
            # Manually manage generated_queries list to avoid exponential accumulation
            existing_queries = state.get('generated_queries', [])
            updated_queries = existing_queries + [generated_queries]  # Append new approach queries
            
            return {
                **state,  # Preserve existing state
                "current_query": generated_queries[0]['cypher_query'] if generated_queries else '',  # Keep first query for backward compatibility
                "generated_queries": updated_queries,  # Manually append approach queries
                "query_reasoning": approach_summary,  # Overall approach summary
                "expected_results": f"{len(generated_queries)} queries generated for approach: {approach_name}",
                "current_approach_details": current_approach_details,
                "current_approach_index": next_approach_index,  # Increment only in normal mode
                "syntax_error_count": syntax_error_count,  # Track syntax error retries
                "current_node": "generate_query"
            }
                
        except Exception as e:
            logger.error(f"❌ Query generation failed: {e}")
            
            # Fallback: Create simple query based on approach targets
            try:
                current_approach_details = state.get('current_approach_details', {})
                target_nodes = current_approach_details.get('target_nodes', ['Variable'])
                limit = state.get('thinking_results', {}).get('retrieval_strategy', {}).get('limit', 10)
                
                fallback_query = f"MATCH (n:{target_nodes[0]}) RETURN n LIMIT {limit}"
                
                logger.warning(f"🔄 Using fallback query: {fallback_query}")
                
                # INCREMENT approach index for next cycle even in fallback
                next_approach_index = current_approach_index + 1
                
                # Format fallback query for execute_queries node
                fallback_generated_query = {
                    'approach_name': current_approach_details.get('approach_name', 'Fallback'),
                    'cypher_query': fallback_query,
                    'reasoning': f"Fallback query for {target_nodes[0]} nodes due to generation failure",
                    'expected_results': f"Basic data from {target_nodes[0]} nodes",
                    'target_nodes': target_nodes,
                    'key_attributes': ['name'],
                    'relationships': [],
                    'strategy': 'fallback'
                }
                
                # Manually manage generated_queries list for fallback too
                existing_queries = state.get('generated_queries', [])
                updated_queries = existing_queries + [[fallback_generated_query]]  # Append fallback approach
                
                return {
                    **state,  # Preserve existing state
                    "current_query": fallback_query,
                    "generated_queries": updated_queries,  # Manually append fallback queries
                    "query_reasoning": f"Fallback query for {target_nodes[0]} nodes due to generation failure",
                    "current_approach_index": next_approach_index,
                    "current_node": "generate_query"
                }
            except:
                # Basic fallback - try to increment or default to 1 if unknown
                current_approach_index = state.get('current_approach_index', 0)
                next_approach_index = current_approach_index + 1
                
                # Format basic fallback query for execute_queries node
                basic_fallback_query = {
                    'approach_name': 'Basic Fallback',
                    'cypher_query': "MATCH (n) RETURN n LIMIT 10",
                    'reasoning': "Basic fallback query due to complete generation failure",
                    'expected_results': "Any available nodes from graph",
                    'target_nodes': ['Any'],
                    'key_attributes': ['name'],
                    'relationships': [],
                    'strategy': 'basic_fallback'
                }
                
                # Manually manage generated_queries list for basic fallback too
                existing_queries = state.get('generated_queries', [])
                updated_queries = existing_queries + [[basic_fallback_query]]  # Append basic fallback approach
                
                return {
                    **state,  # Preserve existing state
                    "current_query": "MATCH (n) RETURN n LIMIT 10",
                    "generated_queries": updated_queries,  # Manually append basic fallback queries
                    "query_reasoning": "Basic fallback query",
                    "current_approach_index": next_approach_index,
                    "current_node": "generate_query"
                }

    async def execute_query(self, state: AgentState) -> AgentState:
        """
        Node: Execute CPG queries via MCP service.
        
        Executes the generated query against the CPG database
        and processes the results.
        """
        logger.info("⚡ Node: execute_query")
        
        try:
            current_query = state.get('current_query')
            logger.info(f"🔍 DEBUG: Looking for current_query, found: {current_query}")
            logger.info(f"🔍 DEBUG: Full state keys: {list(state.keys())}")
            if not current_query:
                raise Exception("No query to execute")
            
            # Execute query using CLI (same pattern as original workflow)
            query_result = await self._execute_query_with_retry(current_query, f"iteration_{state.get('current_iteration', 1)}", state)
            
            # Process results
            if query_result and query_result.get('status') == 'success':
                response_data = query_result.get('response', [])
                results_count = len(response_data) if isinstance(response_data, list) else 0
                
                # Update state with results
                discovered_data = state.get('discovered_data', [])
                discovered_data.extend(response_data if isinstance(response_data, list) else [])
                
                # Track query history
                query_history = state.get('query_history', [])
                query_history.append({
                    'query': current_query,
                    'status': 'success',
                    'results_count': results_count,
                    'purpose': f'Iteration {state.get("current_iteration", 1)} query'
                })
                
                # Track raw results
                raw_query_results = state.get('raw_query_results', [])
                raw_query_results.extend(response_data if isinstance(response_data, list) else [])
                
                logger.info(f"✅ Query executed successfully: {results_count} results")
                
                # Return partial state update with new data to append
                return {
                    "discovered_data": response_data if isinstance(response_data, list) else [],
                    "query_history": [{
                        'query': current_query,
                        'status': 'success',
                        'results_count': results_count,
                        'purpose': f'Iteration {state.get("current_iteration", 1)} query'
                    }],
                    "raw_query_results": response_data if isinstance(response_data, list) else [],
                    "current_node": "execute_query"
                }
            else:
                error_msg = query_result.get('error', 'Unknown query execution error')
                
                # Track failed query
                query_history = state.get('query_history', [])
                query_history.append({
                    'query': current_query,
                    'status': 'failed',
                    'error': error_msg,
                    'purpose': f'Iteration {state.get("current_iteration", 1)} query'
                })
                
                logger.warning(f"⚠️ Query execution failed: {error_msg}")
                
                return {
                    "query_history": [{
                        'query': current_query,
                        'status': 'failed',
                        'error': error_msg,
                        'purpose': f'Iteration {state.get("current_iteration", 1)} query'
                    }],
                    "current_node": "execute_query"
                }
                
        except Exception as e:
            logger.error(f"❌ Query execution failed: {e}")
            
            # If query execution fails critically, stop the workflow
            critical_errors = ["No query to execute", "Query execution timed out"]
            should_stop = any(error in str(e) for error in critical_errors)
            
            if should_stop:
                logger.error(f"💥 Critical query execution error, stopping workflow: {e}")
                
            return {
                "current_node": "execute_query",
                "should_continue": not should_stop
            }

    async def evaluate_sufficiency(self, state: AgentState) -> AgentState:
        """
        Node: Evaluate if we have sufficient data with research insights.
        
        Uses Pydantic validation for sufficiency evaluation results
        and incorporates discovery research termination criteria.
        """
        logger.info("🧠 Node: evaluate_sufficiency")
        
        try:
            # Check iteration limit
            if state["current_iteration"] >= state["max_iterations"]:
                logger.info(f"✅ Reached max iterations ({state['max_iterations']})")
                return {
                    **state,
                    "should_continue": False,
                    "current_node": "evaluate_sufficiency"
                }
            
            # Check fallback activation
            fallback_activated = await self._check_fallback_needed(state)
            if fallback_activated:
                logger.info("🔄 Activating diverse query fallback system")
                return {
                    **state,
                    "fallback_mode": True,
                    "should_continue": True,
                    "current_node": "evaluate_sufficiency"
                }
            
            # Perform sufficiency evaluation with validation
            evaluation_result = await self._evaluate_sufficiency_with_validation(state)
            
            # Determine continuation based on evaluation
            should_continue = not evaluation_result.is_sufficient
            
            logger.info(f"✅ Sufficiency evaluation: {'SUFFICIENT' if evaluation_result.is_sufficient else 'NEED MORE'}")
            
            return {
                "sufficiency_evaluation": evaluation_result.dict(),
                "should_continue": should_continue,
                "current_node": "evaluate_sufficiency"
            }
            
        except Exception as e:
            logger.error(f"❌ Sufficiency evaluation failed: {e}")
            logger.error("💥 Stopping workflow due to sufficiency evaluation failure")
            return {
                **state,
                "should_continue": False,  # Stop on evaluation failure
                "current_node": "evaluate_sufficiency",
                "error": f"Sufficiency evaluation failed: {e}"
            }

    async def synthesize_response(self, state: AgentState) -> AgentState:
        """
        Node: Synthesize final response from discovered data.
        
        Uses ContextManager for data organization and response synthesis.
        """
        logger.info("📝 Node: synthesize_response")
        
        # DEBUG: Save complete state to pickle file for analysis
        await self._debug_save_state_to_pickle(state)
        
        try:
            if not self.context_manager:
                raise Exception("Context manager not initialized")
            
            # Prepare synthesis context
            context_data = self.context_manager.prepare_synthesis_context(state)
            
            # Generate response with fallback logic
            llm_service = state.get('llm_service')
            if not llm_service:
                raise Exception("LLM service not available")
                
            # Generate structured JSON response with context limit fallback
            result = await self._generate_synthesis_with_fallback(state, context_data, llm_service)
            
            if result and not result.error:
                response_text = result.content
                logger.info(f"✅ Response synthesized ({len(response_text)} chars)")
                
                # Parse JSON response - let existing critic handle validation
                try:
                    response = json.loads(response_text)
                    logger.info(f"✅ JSON response parsed: {response.get('status', 'unknown')} (confidence: {response.get('confidence', 'N/A')})")
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ JSON parsing failed: {e}")
                    # Keep as text - existing critic will handle validation
                    response = response_text
                
                # Print complete generated queries list of lists for validation
                generated_queries = state.get('generated_queries', [])
                logger.info("")
                logger.info("=" * 120)
                logger.info("🔍 COMPLETE GENERATED QUERIES LIST OF LISTS (VALIDATION)")
                logger.info("=" * 120)
                logger.info(f"📊 Total Approaches: {len(generated_queries)}")
                
                for approach_idx, approach_queries in enumerate(generated_queries):
                    logger.info(f"")
                    logger.info(f"📋 APPROACH {approach_idx + 1} QUERIES:")
                    logger.info(f"  📝 Query Count: {len(approach_queries)}")
                    
                    for query_idx, query_data in enumerate(approach_queries):
                        approach_name = query_data.get('approach_name', 'Unknown')
                        cypher_query = query_data.get('cypher_query', 'N/A')
                        logger.info(f"  🔍 Query {query_idx + 1}: {approach_name}")
                        logger.info(f"     Cypher: {cypher_query}")
                
                logger.info("")
                logger.info("=" * 120)
                logger.info("")
                
                # Validate synthesis quality
                try:
                    validation = await self._validate_synthesis_quality(
                        response, state, llm_service
                    )
                    
                    logger.info(f"🔍 Synthesis validation: {validation.decision} (score: {validation.overall_score:.2f})")
                    
                    if validation.decision == 'retry' and validation.overall_score < 0.6:
                        logger.warning(f"⚠️ Synthesis quality issues: {', '.join(validation.validation_issues)}")
                        logger.info("🔄 Attempting to fix synthesis based on critic feedback...")
                        
                        # Use critic feedback to improve the synthesis
                        improved_response = await self._fix_synthesis_with_critic_feedback(
                            original_response=response,
                            validation_result=validation,
                            state=state,
                            llm_service=llm_service
                        )
                        
                        if improved_response:
                            logger.info("✅ Synthesis improved using critic feedback")
                            response = improved_response
                        else:
                            logger.warning("⚠️ Could not improve synthesis, using original response")
                    
                    # FIXED: Include comprehensive results from all approaches and diagnostics
                    comprehensive_final_results = self._build_comprehensive_final_results(state)
                    
                    # FIXED: Rebuild comprehensive raw_query_results to include ALL executed queries
                    comprehensive_raw_query_results = self._rebuild_comprehensive_raw_query_results(state)
                    
                    return {
                        **state,
                        "response": response,
                        "final_results": comprehensive_final_results,
                        "discovered_data": comprehensive_final_results,  # Update discovered_data with comprehensive data
                        "raw_query_results": comprehensive_raw_query_results,  # Include ALL queries (primary + diagnostic)
                        "current_node": "synthesize_response",
                        "synthesis_context_used": context_data.get('context_size', 0),
                        "synthesis_validation": validation.dict()
                    }
                    
                except Exception as validation_error:
                    logger.warning(f"⚠️ Synthesis validation failed: {validation_error}")
                    # Continue without validation if critic fails
                    # FIXED: Include comprehensive results from all approaches and diagnostics
                    comprehensive_final_results = self._build_comprehensive_final_results(state)
                    
                    # FIXED: Rebuild comprehensive raw_query_results to include ALL executed queries
                    comprehensive_raw_query_results = self._rebuild_comprehensive_raw_query_results(state)
                    
                    return {
                        **state,
                        "response": response,
                        "final_results": comprehensive_final_results,
                        "discovered_data": comprehensive_final_results,  # Update discovered_data with comprehensive data
                        "raw_query_results": comprehensive_raw_query_results,  # Include ALL queries (primary + diagnostic)
                        "current_node": "synthesize_response",
                        "synthesis_context_used": context_data.get('context_size', 0),
                        "validation_error": str(validation_error)
                    }
            else:
                raise Exception(f"Response synthesis failed: {result.error if result else 'No result'}")
                
        except Exception as e:
            logger.error(f"❌ Response synthesis failed: {e}")
            
            # For testing: create a summary of all Think → Generate cycles
            try:
                discovery_research = state.get('discovery_research', {})
                approaches = discovery_research.get('data_collection_approaches', [])
                total_approaches = len(approaches)
                current_query = state.get('current_query', 'No query generated')
                query_reasoning = state.get('query_reasoning', 'No reasoning available')
                
                summary = f"""📊 THINK → GENERATE CYCLE COMPLETE
                
🎯 User Query: {state.get('user_query', 'N/A')}
📈 Total Approaches Processed: {total_approaches}

All {total_approaches} research approaches have been processed through the Think → Generate cycle.
Each approach was analyzed for scope and had a targeted Cypher query generated.

🔍 LAST GENERATED QUERY:
{current_query}

📝 QUERY REASONING:
{query_reasoning}

This completes the Think → Generate cycle testing phase.
"""
                
                logger.info("=" * 80)
                logger.info("🏁 THINK STEP ANALYSIS SUMMARY")
                logger.info("=" * 80)
                logger.info(summary)
                logger.info("=" * 80)
                
                # FIXED: Rebuild comprehensive raw_query_results even on synthesis error
                comprehensive_raw_query_results = self._rebuild_comprehensive_raw_query_results(state)
                
                return {
                    **state,
                    "response": summary,
                    "raw_query_results": comprehensive_raw_query_results,  # Include ALL queries even on error
                    "current_node": "synthesize_response"
                }
            except:
                # FIXED: Rebuild comprehensive raw_query_results even on fallback error
                try:
                    comprehensive_raw_query_results = self._rebuild_comprehensive_raw_query_results(state)
                except:
                    comprehensive_raw_query_results = state.get('raw_query_results', [])
                
                return {
                    **state,
                    "response": "Think step analysis completed. See logs for detailed results.",
                    "raw_query_results": comprehensive_raw_query_results,  # Include queries even on fallback error
                    "current_node": "synthesize_response",
                    "error": f"Response synthesis failed: {e}"
                }

    async def rethink(self, state: AgentState) -> AgentState:
        """
        Node: Rethink - Analyze current approach results and determine sufficiency.
        
        This node:
        1. Analyzes the results from the executed queries for current approach
        2. Assesses cumulative findings across all iterations so far  
        3. Determines if sufficient data has been gathered to answer the user query
        4. Creates progressive summaries to prevent context explosion
        5. Decides whether to continue with more approaches or synthesize response
        """
        logger.info("🤔 Node: rethink")
        
        try:
            current_approach_index = state.get('current_approach_index', 0)
            approach_raw_results = state.get('approach_raw_results', {})
            
            # Get current approach details
            discovery_research = state.get('discovery_research', {})
            approaches = discovery_research.get('data_collection_approaches', [])
            
            if current_approach_index >= len(approaches):
                logger.error(f"❌ Invalid approach index {current_approach_index}, total approaches: {len(approaches)}")
                return {
                    **state,
                    "should_synthesize": True,  # Force synthesis if we're out of approaches
                    "current_node": "rethink"
                }
            
            current_approach = approaches[current_approach_index]
            approach_name = current_approach.get('approach_name', f'Approach {current_approach_index + 1}')
            
            # Get results for current approach with defensive handling
            current_results = approach_raw_results.get(current_approach_index, [])
            queries_executed = len(current_results)
            
            # Defensive calculation - handle malformed results
            total_results_this_approach = 0
            logger.info(f"🔍 DEBUG: current_results type: {type(current_results)}, length: {len(current_results) if hasattr(current_results, '__len__') else 'No length'}")
            for i, item in enumerate(current_results):
                logger.info(f"🔍 DEBUG: current_results[{i}] type: {type(item)}, value: {str(item)[:150]}...")
                try:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        query, results = item[0], item[1]
                        logger.info(f"🔍 DEBUG: Unpacked - query type: {type(query)}, results type: {type(results)}")
                        if isinstance(results, list):
                            total_results_this_approach += len(results)
                            logger.info(f"🔍 DEBUG: Added {len(results)} from list results")
                        elif isinstance(results, dict):
                            total_results_this_approach += 1
                            logger.info(f"🔍 DEBUG: Added 1 from dict result")
                        # Skip if results is string or other type
                    else:
                        logger.info(f"🔍 DEBUG: Skipping malformed item - not tuple/list or insufficient length")
                except Exception as e:
                    logger.info(f"🔍 DEBUG: Exception processing item {i}: {e}")
                    continue
            
            # Calculate cumulative results across all approaches with defensive handling
            cumulative_results = 0
            for approach_results in approach_raw_results.values():
                for item in approach_results:
                    try:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            query, results = item[0], item[1]
                            if isinstance(results, list):
                                cumulative_results += len(results)
                            elif isinstance(results, dict):
                                cumulative_results += 1
                    except Exception:
                        continue
            
            # Perform rethink analysis with LLM
            rethink_analysis = await self._perform_rethink_analysis_with_llm(
                state, current_approach_index, approach_name, 
                queries_executed, total_results_this_approach, cumulative_results, current_results
            )
            
            # Create iteration summary for progressive context management
            iteration_summary = await self._create_iteration_summary(
                state, current_approach_index, approach_name, rethink_analysis, current_results
            )
            
            # Update cumulative findings
            existing_summaries = state.get('iteration_summaries', [])
            updated_summaries = existing_summaries + [iteration_summary]
            
            # Update cumulative findings summary
            cumulative_findings = self._update_cumulative_findings(
                state.get('cumulative_findings', ''), iteration_summary, state.get('user_query', '')
            )
            
            # Add to sufficiency check history
            sufficiency_history = state.get('sufficiency_check_history', [])
            updated_history = sufficiency_history + [{
                'approach_index': current_approach_index,
                'approach_name': approach_name,
                'sufficiency_assessment': rethink_analysis.sufficiency_assessment.dict(),
                'iteration_summary': iteration_summary
            }]
            
            # Workflow decision based on LLM's sufficiency analysis (not LLM workflow decisions)
            sufficiency_assessment = rethink_analysis.sufficiency_assessment
            is_sufficient = sufficiency_assessment.is_sufficient
            confidence = sufficiency_assessment.confidence
            
            # Workflow logic determines routing decisions
            current_approach_index = state.get('current_approach_index', 0)
            discovery_research = state.get('discovery_research', {})
            approaches = discovery_research.get('data_collection_approaches', [])
            total_approaches = len(approaches)
            current_iteration = state.get('current_iteration', 1)
            max_iterations = state.get('max_iterations', 5)
            
            # Calculate workflow decision
            should_synthesize = False
            should_continue = True
            
            # High confidence sufficiency -> synthesize
            if is_sufficient and confidence >= 0.8:
                should_synthesize = True
                should_continue = False
                decision_reason = "High confidence sufficiency"
            # No more approaches or iterations -> synthesize  
            elif (current_approach_index + 1) >= total_approaches:
                should_synthesize = True
                should_continue = False
                decision_reason = "All approaches exhausted"
            elif current_iteration >= max_iterations:
                should_synthesize = True
                should_continue = False
                decision_reason = "Iteration limit reached"
            # Intent-specific logic
            else:
                intent = state.get('intent', {})
                intent_type = intent.get('intent_type', 'unknown') if isinstance(intent, dict) else 'unknown'
                
                if intent_type == 'lookup':
                    # Lookup can synthesize if found data or tried multiple approaches
                    cumulative_results = sum(
                        sum(len(results) for _, results in approach_results) 
                        for approach_results in state.get('approach_raw_results', {}).values()
                    )
                    if (is_sufficient and cumulative_results > 0) or current_approach_index >= 2:
                        should_synthesize = True
                        should_continue = False
                        decision_reason = f"Lookup sufficient or multiple attempts ({cumulative_results} results)"
                    else:
                        decision_reason = f"Lookup needs more exploration ({cumulative_results} results)"
                else:
                    # Architectural - continue exploring unless very confident
                    decision_reason = f"Architectural query needs more approaches"
            
            logger.info(f"✅ Rethink completed for approach {current_approach_index + 1}: {approach_name}")
            logger.info(f"📊 Approach results: {total_results_this_approach}, Cumulative: {cumulative_results}")
            logger.info(f"🔍 LLM Sufficiency: {is_sufficient} (confidence: {confidence:.1f})")
            logger.info(f"🎯 Workflow Decision: {'Synthesize' if should_synthesize else 'Continue'} - {decision_reason}")
            
            return {
                **state,
                "rethink_analysis": rethink_analysis.dict(),
                "iteration_summaries": updated_summaries,
                "cumulative_findings": cumulative_findings,
                "sufficiency_check_history": updated_history,
                "should_synthesize": should_synthesize,  # Set by workflow logic, not LLM
                "should_continue": should_continue,      # Set by workflow logic, not LLM
                "current_node": "rethink"
            }
            
        except Exception as e:
            logger.error(f"❌ Rethink analysis failed: {e}")
            
            # Fallback workflow decision when rethink analysis fails
            current_approach_index = state.get('current_approach_index', 0)
            discovery_research = state.get('discovery_research', {})
            approaches = discovery_research.get('data_collection_approaches', [])
            total_approaches = len(approaches)
            current_iteration = state.get('current_iteration', 1)
            max_iterations = state.get('max_iterations', 5)
            
            # Fallback logic: synthesize if we've tried enough or reached limits
            should_synthesize = (current_approach_index >= 2 or 
                               (current_approach_index + 1) >= total_approaches or 
                               current_iteration >= max_iterations)
            should_continue = not should_synthesize
            
            return {
                **state,
                "should_synthesize": should_synthesize,
                "should_continue": should_continue,
                "current_node": "rethink",
                "error": f"Rethink analysis failed: {e}"
            }

    async def _perform_rethink_analysis_with_llm(self, state: AgentState, approach_index: int, 
                                              approach_name: str, queries_executed: int, 
                                              total_results_this_approach: int, cumulative_results: int, 
                                              current_results: List[Tuple[str, List[Dict]]]) -> 'RethinkAnalysis':
        """Perform rethink analysis using LLM with Pydantic validation."""
        from .models import RethinkAnalysis, SufficiencyEvaluation
        
        # Get query intent to guide analysis
        intent_type = state.get('intent', {}).get('intent_type', 'unknown')
        
        # Build enhanced rethink prompt with raw query-result data
        rethink_prompt = f"""
        Analyze the results from executing queries for the current research approach and determine next steps.
        CRITICAL: Distinguish between "entity doesn't exist" vs "insufficient exploration".

        **USER QUERY**: {state.get('user_query', 'N/A')}
        **QUERY INTENT**: {intent_type} (lookup=find specific item, architectural=understand structure)
        **CURRENT APPROACH**: {approach_name} (#{approach_index + 1})

        **EXECUTED QUERIES AND RESULTS**:
        {self._format_approach_results_for_analysis(current_results)}

        **CUMULATIVE FINDINGS SO FAR**:
        {state.get('cumulative_findings', 'No previous findings')}

        **PREVIOUS ITERATIONS**:
        {self._format_previous_iterations(state.get('sufficiency_check_history', []))}

        **CRITICAL ANALYSIS GUIDANCE**:
        - For LOOKUP queries: If specific entity (e.g., "workerZ") is not found across comprehensive searches, it likely doesn't exist in the codebase
        - For ARCHITECTURAL queries: May need data from ALL approaches before determining sufficiency
        - Distinguish between: (1) Entity doesn't exist, (2) Wrong search strategy, (3) Need more exploration
        - If user asks for "workerZ" but only "workerA" and "workerB" exist, this is "entity doesn't exist" not "insufficient data"

        **YOUR TASK**: Analyze the data sufficiency and approach effectiveness. The workflow will decide whether to continue or synthesize based on your analysis.

        Respond with valid JSON following this structure:
        {{
            "approach_index": {approach_index},
            "approach_name": "{approach_name}",
            "approach_effectiveness": <float 0.0-1.0: how well this approach worked>,
            "key_findings": [<list of key findings from the executed queries>],
            "sufficiency_assessment": {{
                "is_sufficient": <true/false: do we have enough data to answer the user's question?>,
                "decision": "<SUFFICIENT|NEED_MORE|NEED_BODY_EXPLORATION: your assessment of data completeness>",
                "gaps_summary": "<what information is still missing to fully answer the question>",
                "data_gaps": {{"missing_entities": [], "missing_relationships": []}},
                "body_exploration_needed": <true/false: should we examine function/method bodies?>,
                "entities_for_body_exploration": [<list of entities to examine further>],
                "confidence": <float 0.0-1.0: confidence in your sufficiency assessment>,
                "reasoning": "<your detailed analysis of why the data is/isn't sufficient>"
            }},
            "iteration_summary": "<concise summary of this approach's results for context>",
            "next_step_reasoning": "<analysis of data quality and what might be needed next - NOT a workflow decision>"
        }}
        """
        
        # Generate response using LLM with retry and validation feedback
        llm_service = state.get('llm_service')
        if not llm_service:
            raise Exception("LLM service not available")
        
        # DEBUG: Log the complete rethink prompt for analysis
        # logger.info("=" * 120)
        # logger.info("🤔 RETHINK PROMPT SENT TO LLM:")
        # logger.info("=" * 120)
        # logger.info(rethink_prompt)
        # logger.info("=" * 120)
        
        try:
            # Use retry mechanism with Pydantic validation and error feedback
            rethink_data = await self._retry_llm_with_validation(
                llm_service=llm_service,
                initial_prompt=rethink_prompt,
                model_class=RethinkAnalysis,
                max_retries=3,
                operation_name="rethink analysis"
            )
            
            # # DEBUG: Log the LLM response for analysis
            # logger.info("=" * 120)
            # logger.info("🤔 RETHINK RESPONSE FROM LLM:")
            # logger.info("=" * 120)
            # logger.info(f"LLM Response: {json.dumps(rethink_data, indent=2)}")
            # logger.info("=" * 120)
            
            # The retry method returns validated dict, create RethinkAnalysis object
            return RethinkAnalysis(**rethink_data)
            
        except Exception as e:
            logger.warning(f"⚠️ Rethink analysis failed after retries: {e}")
            # Only fallback after all retries exhausted
            return self._fallback_rethink_analysis(state, approach_index, approach_name, 
                                                 current_results)

    def _format_approach_results_for_analysis(self, current_results: List[Tuple[str, List[Dict]]]) -> str:
        """Format current approach results for LLM analysis (limited to prevent context explosion)."""
        if not current_results:
            return "No results found for this approach"
        
        summary_parts = []
        for i, item in enumerate(current_results):
            try:
                # Defensive unpacking - handle tuple format (query, results)
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    query, results = item[0], item[1]
                else:
                    summary_parts.append(f"Query {i+1}: Malformed item - {type(item).__name__}")
                    continue
                
                # Handle results - don't filter, just count and show
                if isinstance(results, list):
                    result_count = len(results)
                    summary_parts.append(f"Query {i+1}: {result_count} results")
                    if result_count > 0 and results:
                        # Show the actual results without filtering
                        summary_parts.append(f"  Sample: {json.dumps(results[:2], indent=1)}")  # First 2 for brevity
                elif isinstance(results, dict):
                    summary_parts.append(f"Query {i+1}: 1 result")
                    summary_parts.append(f"  Sample: {json.dumps(results, indent=1)}")
                else:
                    summary_parts.append(f"Query {i+1}: Unknown format - {type(results).__name__}")
                    
            except Exception as e:
                summary_parts.append(f"Query {i+1}: Error processing - {str(e)}")
                continue
        
        return "\n".join(summary_parts)

    def _format_previous_iterations(self, sufficiency_history: List[Dict]) -> str:
        """Format previous iteration summaries for context (limited)."""
        if not sufficiency_history:
            return "No previous iterations"
        
        summaries = []
        for i, history in enumerate(sufficiency_history[-3:]):  # Only last 3 iterations
            # Defensive handling: ensure history is a dict before calling .get()
            if isinstance(history, dict):
                approach_name = history.get('approach_name', f'Approach {i+1}')
                summary = history.get('iteration_summary', 'No summary')[:200] + "..."  # Limit length
                summaries.append(f"Iteration {i+1} ({approach_name}): {summary}")
            elif isinstance(history, str):
                # If it's a string, just include it as-is
                summaries.append(f"Iteration {i+1}: {history[:200]}...")
            else:
                # Unknown format - include type info for debugging
                summaries.append(f"Iteration {i+1}: Unknown format ({type(history).__name__})")
        
        return "\n".join(summaries)

    def _fallback_rethink_analysis(self, state: AgentState, approach_index: int, approach_name: str, 
                                 current_results: List) -> 'RethinkAnalysis':
        """Generate fallback rethink analysis when LLM fails after retries."""
        from .models import RethinkAnalysis, SufficiencyEvaluation
        
        # Analyze actual data instead of misleading stats
        actual_results_count = sum(len(results) for _, results in current_results if isinstance(results, list))
        has_meaningful_data = any(len(results) > 0 for _, results in current_results if isinstance(results, list))
        
        # Fallback strategy: Continue to next approach as long as more approaches are available
        total_approaches = state.get('total_approaches', 0)
        has_more_approaches = (approach_index + 1) < total_approaches
        current_iteration = state.get('current_iteration', 1)
        max_iterations = state.get('max_iterations', 5)
        within_iteration_limit = current_iteration < max_iterations
        
        # Only synthesize if: no more approaches OR iteration limit reached
        should_synthesize = not has_more_approaches or not within_iteration_limit
        
        fallback_sufficiency = SufficiencyEvaluation(
            is_sufficient=should_synthesize,
            decision="SUFFICIENT" if should_synthesize else "NEED_MORE", 
            gaps_summary=f"Fallback analysis after approach {approach_index + 1}/{total_approaches} (LLM retry failed)",
            confidence=0.6,
            reasoning=f"Fallback heuristic after LLM retry failure: Continue to next approach if available. Approaches left: {total_approaches - approach_index - 1}, Iterations left: {max_iterations - current_iteration}"
        )
        
        return RethinkAnalysis(
            approach_index=approach_index,
            approach_name=approach_name,
            approach_effectiveness=0.7 if has_meaningful_data else 0.3,
            key_findings=[f"Fallback analysis: LLM retry failed after 3 attempts, using heuristic decision"],
            sufficiency_assessment=fallback_sufficiency,
            iteration_summary=f"Fallback for approach {approach_index + 1}/{total_approaches}: {actual_results_count} results found",
            next_step_reasoning=f"Fallback analysis after LLM failure. Data quality: {'Good' if has_meaningful_data else 'Limited'}. Approaches remaining: {total_approaches - approach_index - 1}"
        )

    async def _create_iteration_summary(self, state: AgentState, approach_index: int, approach_name: str, 
                                      rethink_analysis: 'RethinkAnalysis', current_results: List) -> str:
        """Create concise iteration summary for progressive context management."""
        key_findings = rethink_analysis.key_findings[:3]  # Limit key findings
        findings_text = ", ".join(key_findings) if key_findings else "No significant findings"
        
        # FIXED: Use LLM-based summarization of actual query results data
        llm_service = state.get('llm_service')
        user_query = state.get('user_query', '')
        
        if llm_service and current_results:
            try:
                results_summary = await self._summarize_query_results_with_llm(
                    current_results, approach_name, user_query, llm_service
                )
            except Exception as e:
                # Fallback to basic summary if LLM fails
                total_queries = len(current_results)
                successful_queries = sum(1 for item in current_results 
                                       if isinstance(item, (list, tuple)) and len(item) >= 2 
                                       and isinstance(item[1], list) and len(item[1]) > 0)
                results_summary = f"{successful_queries}/{total_queries} queries successful"
        else:
            results_summary = f"{len(current_results)} queries executed" if current_results else "No queries"
        
        return f"Approach {approach_index + 1} ({approach_name}): effectiveness {rethink_analysis.approach_effectiveness:.1f}. " \
               f"Key findings: {findings_text}. " \
               f"Query results: {results_summary}. " \
               f"Sufficiency: {rethink_analysis.sufficiency_assessment.is_sufficient} (confidence: {rethink_analysis.sufficiency_assessment.confidence:.1f})"

    async def _summarize_query_results_with_llm(self, current_results: List, approach_name: str, user_query: str, llm_service) -> str:
        """Create comprehensive LLM-based summary using ALL query results to help answer the user query."""
        if not current_results:
            return "No results found"
        
        # Format ALL results without truncation for comprehensive analysis
        formatted_results = []
        for i, item in enumerate(current_results):
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    query, results = item[0], item[1]
                    result_count = len(results) if isinstance(results, list) else 0
                    
                    # Include ALL data for comprehensive analysis
                    formatted_results.append({
                        'query_number': i + 1,
                        'query': query,  # Full query, no truncation
                        'result_count': result_count,
                        'results': results if isinstance(results, list) else []  # All results, no sampling
                    })
            except Exception:
                continue
        
        if not formatted_results:
            return "No valid results to summarize"
        
        try:
            # Try comprehensive summary with all data first
            return await self._create_comprehensive_summary(formatted_results, approach_name, user_query, llm_service)
        except Exception as e:
            logger.warning(f"Comprehensive summary failed: {e}. Falling back to step-by-step summarization.")
            # Fallback to step-by-step summarization to handle large datasets
            return await self._create_step_by_step_summary(formatted_results, approach_name, user_query, llm_service)

    async def _create_comprehensive_summary(self, formatted_results: List, approach_name: str, user_query: str, llm_service) -> str:
        """Create comprehensive summary using all query results at once."""
        prompt = f"""You are analyzing query results to help answer the user's question. Focus on extracting information that directly helps answer their query.

USER QUERY: "{user_query}"
APPROACH: "{approach_name}"

COMPLETE QUERY RESULTS:
{json.dumps(formatted_results, indent=2)}

TASK: Analyze ALL the query results comprehensively and create a summary that:
1. Directly addresses what the user is asking about
2. Highlights specific data/entities found that are relevant to the user's question
3. Identifies key attributes, relationships, or patterns that help answer the query
4. Points out any partial answers or leads toward the final answer
5. If no direct answer is found, explains what was discovered and what might be missing

Focus on the actual content and its relevance to answering the user's question, not just statistics.
Provide a detailed summary that helps guide toward the final answer."""
        
        result = await llm_service.generate_response(prompt, use_cache=False)
        if result and not result.error:
            return result.content.strip()
        else:
            raise Exception(f"LLM failed: {result.error if result else 'No result'}")

    async def _create_step_by_step_summary(self, formatted_results: List, approach_name: str, user_query: str, llm_service) -> str:
        """Create summary by processing queries in smaller batches, then combining."""
        batch_size = 3  # Process 3 queries at a time
        batch_summaries = []
        
        for i in range(0, len(formatted_results), batch_size):
            batch = formatted_results[i:i + batch_size]
            
            batch_prompt = f"""Analyze this batch of query results for approach "{approach_name}" to help answer: "{user_query}"

BATCH RESULTS:
{json.dumps(batch, indent=2)}

Summarize key findings from this batch that are relevant to answering the user's question. Focus on specific data found and how it relates to the query."""
            
            try:
                result = await llm_service.generate_response(batch_prompt, use_cache=False)
                if result and not result.error:
                    batch_summaries.append(f"Batch {i//batch_size + 1}: {result.content.strip()}")
            except Exception as e:
                logger.warning(f"Batch {i//batch_size + 1} summarization failed: {e}")
                # Add basic fallback for this batch
                batch_count = sum(len(item.get('results', [])) for item in batch)
                batch_summaries.append(f"Batch {i//batch_size + 1}: {len(batch)} queries, {batch_count} results")
        
        # Combine all batch summaries into final summary
        if len(batch_summaries) > 1:
            final_prompt = f"""Combine these batch summaries into a final comprehensive summary for approach "{approach_name}" that helps answer: "{user_query}"

BATCH SUMMARIES:
{chr(10).join(batch_summaries)}

Create a unified summary that:
1. Synthesizes findings across all batches
2. Highlights the most relevant information for answering the user's question
3. Identifies any patterns or connections between batches
4. Points toward the final answer or next steps needed"""
            
            try:
                result = await llm_service.generate_response(final_prompt, use_cache=False)
                if result and not result.error:
                    return result.content.strip()
            except Exception as e:
                logger.warning(f"Final combination failed: {e}")
        
        # Fallback: just concatenate batch summaries
        return "; ".join(batch_summaries) if batch_summaries else "Step-by-step summarization failed"

    def _update_cumulative_findings(self, existing_findings: str, iteration_summary: str, user_query: str) -> str:
        """Update cumulative findings with new iteration, keeping it concise."""
        if not existing_findings:
            return f"User Query: {user_query}\n\nFindings:\n- {iteration_summary}"
        
        # Keep only essential information to prevent context explosion
        lines = existing_findings.split('\n')
        findings_lines = [line for line in lines if line.startswith('- ')]
        
        # Limit to last 5 findings + new one
        recent_findings = findings_lines[-4:] + [f"- {iteration_summary}"]
        
        return f"User Query: {user_query}\n\nFindings:\n" + "\n".join(recent_findings)

    def should_continue_after_rethink(self, state: AgentState) -> str:
        """
        Determine next step after rethink analysis.
        
        Enhanced logic for architectural queries and better "not found" handling.
        
        Routes to:
        - "think": Continue with next approach if more exploration needed
        - "synthesize_response": Synthesize final response if sufficient data gathered
        """
        logger.info("🤔 Decision: should_continue_after_rethink")
        
        try:
            # Get workflow context
            intent = state.get('intent', {})
            intent_type = intent.get('intent_type', 'unknown') if isinstance(intent, dict) else 'unknown'
            current_approach_index = state.get('current_approach_index', 0)
            discovery_research = state.get('discovery_research', {})
            approaches = discovery_research.get('data_collection_approaches', [])
            total_approaches = len(approaches)
            current_iteration = state.get('current_iteration', 1)
            max_iterations = state.get('max_iterations', 5)
            
            # Get rethink analysis results (LLM's sufficiency assessment)
            rethink_analysis = state.get('rethink_analysis', {})
            if rethink_analysis:
                sufficiency_assessment = rethink_analysis.get('sufficiency_assessment', {})
                is_sufficient = sufficiency_assessment.get('is_sufficient', False)
                decision = sufficiency_assessment.get('decision', 'NEED_MORE')
                confidence = sufficiency_assessment.get('confidence', 0.5)
                reasoning = sufficiency_assessment.get('reasoning', '')
            else:
                # Fallback if no rethink analysis
                logger.warning("⚠️ No rethink analysis available, using fallback logic")
                is_sufficient = False
                decision = 'NEED_MORE'
                confidence = 0.3
                reasoning = 'No rethink analysis available'
            
            # Workflow decision logic (based on LLM's analysis + workflow constraints)
            logger.info("🔍 DECISION ANALYSIS:")
            logger.info(f"  📊 LLM Sufficiency: {is_sufficient} ({decision}, confidence: {confidence:.1f})")
            logger.info(f"  📈 Current approach: {current_approach_index + 1}/{total_approaches}")
            logger.info(f"  🔄 Current iteration: {current_iteration}/{max_iterations}")
            logger.info(f"  📝 Intent: {intent_type}")
            logger.info(f"  🎯 Reasoning: {reasoning[:100]}...")
            
            # Decision 1: Check if LLM says data is sufficient with high confidence
            if is_sufficient and confidence >= 0.8:
                logger.info("✅ Decision: synthesize_response - LLM reports sufficient data with high confidence")
                return "synthesize_response"
            
            # Decision 2: Check workflow constraints (no more approaches or iterations)
            has_more_approaches = (current_approach_index + 1) < total_approaches
            within_iteration_limit = current_iteration < max_iterations
            
            # FIXED: Only apply workflow constraints if LLM doesn't explicitly say more data is needed
            if not has_more_approaches:
                if not is_sufficient:
                    logger.info("🔄 Decision: think - LLM says insufficient data but no more approaches, will continue to synthesis after this cycle")
                logger.info("✅ Decision: synthesize_response - All approaches exhausted")
                return "synthesize_response"
                
            if not within_iteration_limit:
                if not is_sufficient:
                    logger.info("🔄 Decision: think - LLM says insufficient data but iteration limit reached, will synthesize what we have")
                logger.info("✅ Decision: synthesize_response - Iteration limit reached")
                return "synthesize_response"
            
            # Decision 2.5: If LLM explicitly says insufficient and we have more approaches, continue regardless of other factors
            if not is_sufficient and has_more_approaches and within_iteration_limit:
                logger.info(f"🔄 Decision: think - LLM says insufficient data (confidence: {confidence:.1f}), continuing with approach {current_approach_index + 2}/{total_approaches}")
                return "think"
            
            # Decision 3: Intent-based logic with sufficiency consideration
            if intent_type == 'architectural':
                # Architectural queries may need more approaches even if LLM thinks current data is sufficient
                if is_sufficient and confidence >= 0.7 and current_approach_index >= 2:  # At least 3 approaches tried
                    logger.info("✅ Decision: synthesize_response - Architectural query has sufficient data after multiple approaches")
                    return "synthesize_response"
                else:
                    logger.info(f"🔄 Decision: think - Architectural query needs more approaches (tried {current_approach_index + 1}/{total_approaches})")
                    return "think"
                    
            elif intent_type == 'lookup':
                # Lookup queries can synthesize earlier if we've tried multiple approaches and found some data
                cumulative_results = sum(
                    sum(len(results) for _, results in approach_results) 
                    for approach_results in state.get('approach_raw_results', {}).values()
                )
                
                if cumulative_results == 0 and current_approach_index >= 2:  # No results after 3 approaches
                    logger.info("✅ Decision: synthesize_response - Lookup query found no results after multiple approaches")
                    return "synthesize_response"
                elif is_sufficient or cumulative_results > 0:  # Found something and LLM says sufficient, or just found something
                    logger.info(f"✅ Decision: synthesize_response - Lookup query found {cumulative_results} results, sufficiency: {is_sufficient}")  
                    return "synthesize_response"
                else:
                    logger.info(f"🔄 Decision: think - Lookup query needs more approaches (tried {current_approach_index + 1}/{total_approaches}, found {cumulative_results} results)")
                    return "think"
            
            # Default: continue if we have more approaches and the LLM indicates we need more data
            logger.info(f"🔄 Decision: think - Continue with next approach {current_approach_index + 2}/{total_approaches}")
            return "think"
            
        except Exception as e:
            logger.error(f"❌ Decision error in should_continue_after_rethink: {e}")
            # Fallback: if error, synthesize what we have
            return "synthesize_response"

    async def think(self, state: AgentState) -> AgentState:
        """
        Node: Think - Analyze current approach and determine scope.
        
        Key responsibilities:
        1. Check if there are more research approaches to try
        2. Select the next untried approach
        3. Analyze scope: single_file vs multi_file
        4. Set appropriate retrieval strategy
        """
        logger.info("🧠 Node: think")
        
        try:
            # Get research results and current state
            discovery_research = state.get('discovery_research', {})
            if not discovery_research:
                raise Exception("No research results available for thinking phase")
            
            data_collection_approaches = discovery_research.get('data_collection_approaches', [])
            current_approach_index = state.get('current_approach_index', 0)
            total_approaches = len(data_collection_approaches)
            
            # Check if there are more approaches to try
            if current_approach_index >= total_approaches:
                logger.info("✅ All research approaches have been exhausted")
                return {
                    **state,
                    "should_continue": False,  # Signal to stop exploration
                    "thinking_results": {
                        "status": "exhausted", 
                        "message": "All research approaches have been tried"
                    },
                    "current_node": "think"
                }
            
            # Select the current approach to try
            current_approach = data_collection_approaches[current_approach_index]
            approach_name = current_approach.get('approach_name', f'Approach {current_approach_index + 1}')
            
            logger.info(f"🎯 Thinking: Selecting approach {current_approach_index + 1}/{total_approaches}: {approach_name}")
            
            # Analyze scope using LLM: single_file vs multi_file
            scope_analysis = await self._analyze_approach_scope_with_llm(current_approach, state)
            current_scope = scope_analysis['scope']
            retrieval_strategy = scope_analysis['retrieval_strategy']
            
            # Prepare thinking results
            thinking_results = {
                "approach_name": approach_name,
                "approach_index": current_approach_index,
                "scope": current_scope,
                "retrieval_strategy": retrieval_strategy,
                "scope_reasoning": scope_analysis['reasoning'],
                "status": "ready_for_generation"
            }
            
            # Log full results after successful thinking
            self._log_think_results(current_approach, scope_analysis)
            
            # DON'T increment here - Generate step will increment for the cycle
            return {
                **state,
                "current_approach_details": current_approach,
                "current_scope": current_scope,
                "thinking_results": thinking_results,
                # Keep current_approach_index unchanged - Generate will increment it
                "current_node": "think"
            }
            
        except Exception as e:
            logger.error(f"❌ Thinking phase failed: {e}")
            
            # Fallback: move to next approach or stop
            current_approach_index = state.get('current_approach_index', 0)
            total_approaches = state.get('total_approaches', 0)
            
            if current_approach_index + 1 >= total_approaches:
                logger.warning("⚠️ Thinking failed and no more approaches available")
                return {
                    **state,
                    "should_continue": False,
                    "thinking_results": {"status": "failed", "error": str(e)},
                    "current_node": "think"
                }
            else:
                logger.warning(f"⚠️ Thinking failed, will try next approach")
                return {
                    **state,
                    "current_approach_index": current_approach_index + 1,
                    "thinking_results": {"status": "failed_retry", "error": str(e)},
                    "current_node": "think"
                }


    def should_continue_thinking(self, state: AgentState) -> str:
        """
        Conditional edge function for Think step self-loop.
        
        Determines whether to continue thinking (analyze next approach) or move to generation.
        """
        current_approach_index = state.get("current_approach_index", 0)
        total_approaches = state.get("total_approaches", 0)
        thinking_results = state.get("thinking_results", {})
        
        # Check if thinking failed and we should stop
        if thinking_results.get("status") == "exhausted":
            logger.info("🏁 All approaches analyzed, moving to generation")
            return "generate_query"
        
        # Check if there are more approaches to analyze (current_approach_index is already incremented in think node)
        if current_approach_index < total_approaches:
            logger.info(f"🔄 Moving to next approach: {current_approach_index + 1}/{total_approaches}")
            return "think"  # Self-loop to analyze next approach
        else:
            logger.info("✅ All approaches have been analyzed, starting generation phase")
            
            # Note: We need to reset approach index to 0 for generation phase
            # This will be handled in the generate_query method
            return "generate_query"  # Start executing the approaches

    def should_continue_generating(self, state: AgentState) -> str:
        """
        Conditional edge function for Generate step cycling.
        
        Determines whether to continue with Think → Generate cycle or finish.
        """
        current_approach_index = state.get("current_approach_index", 0)
        discovery_research = state.get('discovery_research', {})
        data_collection_approaches = discovery_research.get('data_collection_approaches', [])
        total_approaches = len(data_collection_approaches)
        
        # Check if there are more approaches to process (current_approach_index was incremented in Generate)
        if current_approach_index < total_approaches:
            logger.info(f"🔄 Moving to Think → Generate cycle for approach {current_approach_index + 1}/{total_approaches}")
            return "think"  # Go back to Think for next approach
        else:
            logger.info("✅ All approaches have been processed, finishing")
            return "synthesize_response"  # Exit cycle, all approaches done

    def should_continue_exploring(self, state: AgentState) -> str:
        """
        Conditional edge function for LangGraph workflow.
        
        Determines the next node based on current state.
        """
        should_continue = state.get("should_continue", True)
        current_iteration = state.get("current_iteration", 1)
        max_iterations = state.get("max_iterations", 5)
        
        if not should_continue or current_iteration >= max_iterations:
            return "synthesize_response"
        else:
            # Increment iteration for next round
            state["current_iteration"] = current_iteration + 1
            return "generate_query"

    # Helper methods
    
    def _extract_cypher_query(self, llm_response: str) -> str:
        """Extract pure Cypher query from LLM response text."""
        import re
        
        # Try to find Cypher query in code blocks first
        cypher_block_pattern = r'```(?:cypher)?\n?(.*?)\n?```'
        matches = re.findall(cypher_block_pattern, llm_response, re.DOTALL | re.IGNORECASE)
        
        if matches:
            # Return the first Cypher query found in code blocks
            query = matches[0].strip()
            if query.upper().startswith(('MATCH', 'CREATE', 'MERGE', 'DELETE', 'RETURN', 'WITH')):
                return query
        
        # Fallback: Look for lines that start with Cypher keywords
        lines = llm_response.split('\n')
        query_lines = []
        in_query = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Start of query
            if line.upper().startswith(('MATCH', 'CREATE', 'MERGE', 'DELETE', 'WITH')):
                in_query = True
                query_lines = [line]
            elif in_query:
                # Continue query if it's a valid Cypher line
                if (line.upper().startswith(('WHERE', 'AND', 'OR', 'RETURN', 'ORDER', 'LIMIT', 'SET', 'REMOVE')) or
                    line.startswith(('  ', '\t')) or  # Indented continuation
                    not line[0].isupper()):  # Lowercase continuation
                    query_lines.append(line)
                else:
                    # End of query
                    break
        
        if query_lines:
            return '\n'.join(query_lines)
        
        # Last resort: return original if it looks like a query
        if llm_response.strip().upper().startswith(('MATCH', 'CREATE', 'MERGE', 'DELETE', 'RETURN', 'WITH')):
            return llm_response.strip()
        
        logger.warning(f"Could not extract Cypher query from: {llm_response[:200]}...")
        return "MATCH (n) RETURN n LIMIT 10"  # Safe fallback
    

    def _build_targeted_query_generation_prompt(self, state: AgentState, approach_details: Dict[str, Any], 
                                                thinking_results: Dict[str, Any], discovery_research: Dict[str, Any]) -> str:
        """Build targeted query generation prompt using Think step results and discovery research."""
        
        # Extract key information
        user_query = state.get('user_query', '')
        schema = state.get('schema', {})
        current_scope = state.get('current_scope', 'single_file')
        retrieval_strategy = thinking_results.get('retrieval_strategy', {})
        
        # Format approach details
        approach_name = approach_details.get('approach_name', 'Unknown')
        target_nodes = approach_details.get('target_nodes', [])
        key_attributes = approach_details.get('key_attributes', [])
        relationships = approach_details.get('relationships', [])
        strategy = approach_details.get('strategy', 'general')
        
        # Get discovered entities and schema corrections (already validated during research)
        discovered_entities = discovery_research.get('discovered_entities', {})
        schema_corrections = approach_details.get('schema_corrections', [])
        
        return f"""You are an expert Neo4j Cypher query generator for Code Property Graph (CPG) analysis.

**TASK**: Generate targeted Cypher queries implementing this research approach (schema already validated).

**USER QUERY**: {user_query}

**VALIDATED RESEARCH APPROACH** (schema-corrected):
- Name: {approach_name}
- Strategy: {strategy}
- Target Node Types: {target_nodes} (✓ schema-validated)
- Key Attributes: {key_attributes} (✓ schema-validated)  
- Target Relationships: {relationships} (✓ schema-validated)
- Applied Corrections: {schema_corrections}

**SCOPE ANALYSIS**:
- Scope: {current_scope} (limit: {retrieval_strategy.get('limit', 75)} results)
- Focus: {retrieval_strategy.get('focus', 'targeted')} analysis
- Context: {retrieval_strategy.get('context_window', 'small')} window

**DISCOVERED ENTITIES** (from research):
{json.dumps(discovered_entities, indent=2) if discovered_entities else 'No specific entities discovered yet'}

**REQUIREMENTS**:
1. Use ONLY the validated target node types, relationships, and attributes from above
2. Generate 1-8 Cypher queries implementing this approach (multiple queries if needed for comprehensive coverage)
3. Apply the scope-based limit ({retrieval_strategy.get('limit', 75)} results max per query)
4. Focus on this approach's strategy: {strategy}
5. Incorporate discovered entities if available for targeting
6. Trust the schema validation - no need to double-check node types or relationships

**OUTPUT FORMAT** (JSON):
{{
    "queries": [
        {{
            "cypher_query": "MATCH ... RETURN ... LIMIT ...",
            "reasoning": "How this query implements the approach strategy",
            "query_purpose": "Specific aspect this query covers"
        }}
    ],
    "approach_summary": "How these queries collectively implement the research approach"
}}

Generate the queries now:"""

    def _build_syntax_error_fix_prompt(self, original_failed_query: str, error_feedback: str, 
                                     approach_details: Dict[str, Any], thinking_results: Dict[str, Any], 
                                     discovery_research: Dict[str, Any], state: AgentState) -> str:
        """Build prompt for fixing syntax errors in Cypher queries using Neo4j error feedback."""
        
        # Extract key information
        user_query = state.get('user_query', '')
        schema = state.get('schema', {})
        current_scope = state.get('current_scope', 'single_file')
        retrieval_strategy = thinking_results.get('retrieval_strategy', {})
        
        # Format approach details
        approach_name = approach_details.get('approach_name', 'Unknown')
        target_nodes = approach_details.get('target_nodes', [])
        key_attributes = approach_details.get('key_attributes', [])
        relationships = approach_details.get('relationships', [])
        strategy = approach_details.get('strategy', 'general')
        
        return f"""You are an expert Neo4j Cypher query debugger for Code Property Graph (CPG) analysis.

**TASK**: Fix the syntax error in the provided Cypher query based on the Neo4j error feedback.

**USER QUERY**: {user_query}

**RESEARCH APPROACH CONTEXT**:
- Name: {approach_name}
- Strategy: {strategy}
- Target Node Types: {target_nodes}
- Key Attributes: {key_attributes}
- Relationships: {relationships}

**FAILED QUERY**:
```cypher
{original_failed_query}
```

**NEO4J ERROR FEEDBACK**:
{error_feedback}

**CPG SCHEMA** (for reference):
{json.dumps(schema, indent=2)}

**REQUIREMENTS**:
1. Analyze the Neo4j error message to understand what went wrong
2. Fix the syntax error while preserving the query's original intent and approach
3. Ensure the corrected query still targets the specified node types and attributes
4. Apply the same scope-based limit ({retrieval_strategy.get('limit', 75)} results max)
5. Return a corrected query that implements the same research approach but with valid syntax

**COMMON NEO4J SYNTAX FIXES**:
- Use `contains()` instead of `indexOf()` for string matching
- Use proper property access syntax: `n.propertyName` not `n[propertyName]`
- Ensure proper WHERE clause syntax and boolean operations
- Check for missing or extra parentheses, brackets, and braces
- Verify relationship syntax: `()-[:REL_TYPE]->()`

**OUTPUT FORMAT** (JSON):
{{
    "cypher_query": "MATCH ... RETURN ... LIMIT ...",
    "reasoning": "Explanation of what was wrong and how it was fixed",
    "expected_results": "Description of what type of data this corrected query should return"
}}

Fix the query now:"""

    async def _retry_llm_with_validation(self, llm_service, initial_prompt: str, model_class, 
                                         max_retries: int = 3, operation_name: str = "LLM operation") -> Dict[str, Any]:
        """
        Retry LLM call with Pydantic validation and feedback on errors.
        
        Args:
            llm_service: LLM service instance
            initial_prompt: Initial prompt to send
            model_class: Pydantic model class for validation
            max_retries: Maximum number of retry attempts
            operation_name: Name of operation for logging
            
        Returns:
            Validated data as dictionary or raises exception
        """
        from src.core.llm_service import LLMModel
        
        prompt = initial_prompt
        last_error = None
        
        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                logger.info(f"🔄 {operation_name} attempt {attempt + 1}/{max_retries + 1}")
                
                # Make LLM call
                result = await llm_service.generate_response(
                    prompt, 
                    json_mode=True, 
                    model=LLMModel.GPT4O, 
                    max_tokens=4000,
                    temperature=0.2
                )
                
                if not result or result.error:
                    raise Exception(f"LLM call failed: {result.error if result else 'No response'}")
                
                # Parse JSON
                try:
                    response_data = json.loads(result.content.strip())
                except json.JSONDecodeError as e:
                    raise Exception(f"Invalid JSON response: {e}")
                
                # Validate with Pydantic model
                try:
                    validated_model = model_class(**response_data)
                    logger.info(f"✅ {operation_name} succeeded with Pydantic validation on attempt {attempt + 1}")
                    
                    # Return as dictionary for compatibility
                    return validated_model.dict()
                    
                except ValidationError as e:
                    last_error = e
                    
                    if attempt < max_retries:
                        # Create feedback prompt for retry
                        error_details = self._format_validation_errors(e)
                        retry_prompt = f"""{initial_prompt}

**PREVIOUS ATTEMPT FAILED VALIDATION**:
{error_details}

**PLEASE FIX THE FOLLOWING ISSUES AND PROVIDE A CORRECTED RESPONSE**:
- Ensure all required fields are present
- Validate data types and constraints
- Follow the exact JSON schema format specified above

Provide the corrected JSON response:"""
                        
                        prompt = retry_prompt
                        logger.warning(f"⚠️ {operation_name} validation failed on attempt {attempt + 1}, retrying with feedback...")
                        logger.warning(f"🔍 Validation errors: {error_details}")
                        continue
                    else:
                        # Max retries reached
                        logger.error(f"❌ {operation_name} failed validation after {max_retries + 1} attempts")
                        raise Exception(f"{operation_name} validation failed after all retries: {last_error}")
                        
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"⚠️ {operation_name} failed on attempt {attempt + 1}: {e}")
                    continue
                else:
                    logger.error(f"❌ {operation_name} failed after {max_retries + 1} attempts: {e}")
                    raise e
                    
        # Should never reach here
        raise Exception(f"{operation_name} failed after all attempts")

    def _format_validation_errors(self, validation_error: ValidationError) -> str:
        """Format Pydantic validation errors for LLM feedback."""
        error_lines = []
        for error in validation_error.errors():
            field = " -> ".join(str(x) for x in error["loc"])
            message = error["msg"]
            error_lines.append(f"- Field '{field}': {message}")
        return "\n".join(error_lines)

    def _log_generation_results(self, approach_details: Dict[str, Any], query: str, reasoning: str, expected_results: str):
        """Log full query generation results after successful completion."""
        approach_name = approach_details.get('approach_name', 'Unknown')
        strategy = approach_details.get('strategy', 'N/A')
        target_nodes = approach_details.get('target_nodes', [])
        key_attributes = approach_details.get('key_attributes', [])
        relationships = approach_details.get('relationships', [])
        
        logger.info("")
        logger.info("=" * 120)
        logger.info("🎯 QUERY GENERATION COMPLETED")
        logger.info("=" * 120)
        logger.info(f"📋 Approach: {approach_name}")
        logger.info(f"📊 Strategy: {strategy}")
        logger.info(f"🎮 Target Nodes: {target_nodes}")
        logger.info(f"🔑 Key Attributes: {key_attributes}")
        logger.info(f"🔗 Relationships: {relationships}")
        logger.info("")
        logger.info("📝 COMPLETE REASONING:")
        logger.info(f"{reasoning}")
        logger.info("")
        logger.info("🔍 COMPLETE GENERATED QUERY:")
        logger.info(f"{query}")
        logger.info("")
        logger.info("🎯 COMPLETE EXPECTED RESULTS:")
        logger.info(f"{expected_results}")
        logger.info("")
        logger.info("🔍 QUERY VALIDATION:")
        
        # Simple validation checks
        validations = []
        
        # Check if target nodes appear in query
        nodes_in_query = [node for node in target_nodes if f":{node}" in query or f"{node})" in query]
        validations.append(f"✅ Target nodes in query: {nodes_in_query}" if nodes_in_query else f"⚠️ Target nodes missing: {target_nodes}")
        
        # Check if key attributes appear in query  
        attrs_in_query = [attr for attr in key_attributes if attr.split('.')[-1] in query]
        validations.append(f"✅ Key attributes in query: {attrs_in_query}" if attrs_in_query else f"⚠️ Key attributes missing: {key_attributes}")
        
        # Check if relationships appear in query
        rels_in_query = [rel for rel in relationships if rel in query]
        validations.append(f"✅ Relationships in query: {rels_in_query}" if rels_in_query else f"ℹ️ No relationships found (may be intentional): {relationships}")
        
        # Check if query implements the strategy
        strategy_lower = strategy.lower()
        query_lower = query.lower()
        
        # Dynamic strategy validation based on approach content
        strategy_implemented = False
        implementation_details = []
        
        # Check for specific entity targeting (extract from target nodes or key attributes)
        specific_targets = []
        for node in target_nodes:
            if node.lower() in query_lower:
                specific_targets.append(node)
        
        if specific_targets:
            implementation_details.append(f"Target nodes implemented: {specific_targets}")
            strategy_implemented = True
        
        # Check for strategy-specific patterns
        strategy_patterns = {
            'member variable': ['contains', 'variable'],
            'method-local': ['function', 'contains', 'variable'],
            'file-scoped': ['file', 'file_path'],
            'pattern matching': ['name', 'contains', '=~'],
            'function body': ['body', 'contains'],
            'namespace': ['namespace', 'contains'],
            'block-scoped': ['block', 'start_byte', 'end_byte'],
            'hierarchy': ['inherits_from', 'implements'],
            'call graph': ['calls'],
            'singleton': ['modifier', 'static', 'private'],
            'documentation': ['documentation', 'attribute'],
            'macro': ['macro', 'included_in'],
            'layer identification': ['file_path', 'split']
        }
        
        for pattern_name, keywords in strategy_patterns.items():
            if pattern_name in strategy_lower:
                matching_keywords = [kw for kw in keywords if kw in query_lower]
                if matching_keywords:
                    implementation_details.append(f"{pattern_name.title()} pattern: {matching_keywords}")
                    strategy_implemented = True
        
        # Final validation
        if strategy_implemented:
            validations.append(f"✅ Strategy implementation: {'; '.join(implementation_details)}")
        else:
            validations.append("ℹ️ Strategy implementation: General query pattern (validation skipped)")
        
        for validation in validations:
            logger.info(validation)
        
        logger.info("=" * 120)
        logger.info("")

    def _log_generation_results_multiple(self, approach_details: Dict[str, Any], queries_list: List[Dict[str, Any]], approach_summary: str):
        """Log multiple query generation results after successful completion."""
        approach_name = approach_details.get('approach_name', 'Unknown')
        strategy = approach_details.get('strategy', 'N/A')
        target_nodes = approach_details.get('target_nodes', [])
        key_attributes = approach_details.get('key_attributes', [])
        relationships = approach_details.get('relationships', [])
        
        logger.info("")
        logger.info("=" * 120)
        logger.info("🎯 MULTIPLE QUERIES GENERATION COMPLETED")
        logger.info("=" * 120)
        logger.info(f"📋 Approach: {approach_name}")
        logger.info(f"📊 Strategy: {strategy}")
        logger.info(f"🎮 Target Nodes: {target_nodes}")
        logger.info(f"🔑 Key Attributes: {key_attributes}")
        logger.info(f"🔗 Relationships: {relationships}")
        logger.info(f"📝 Query Count: {len(queries_list)}")
        logger.info("")
        logger.info("📝 APPROACH SUMMARY:")
        logger.info(f"{approach_summary}")
        logger.info("")
        
        # Log each query individually
        for i, single_query in enumerate(queries_list):
            logger.info(f"🔍 QUERY {i+1}:")
            logger.info(f"  Purpose: {single_query.get('query_purpose', 'N/A')}")
            logger.info(f"  Reasoning: {single_query.get('reasoning', 'N/A')}")
            logger.info(f"  Cypher: {single_query.get('cypher_query', 'N/A')}")
            logger.info("")
        
        logger.info("=" * 120)
        logger.info("")

    def _log_think_results(self, approach_details: Dict[str, Any], scope_analysis: Dict[str, Any]):
        """Log full think step results after successful completion."""
        approach_name = approach_details.get('approach_name', 'Unknown')
        description = approach_details.get('description', 'N/A')
        
        logger.info("")
        logger.info("=" * 120)
        logger.info("🧠 THINK STEP COMPLETED")
        logger.info("=" * 120)
        logger.info(f"📋 Approach: {approach_name}")
        logger.info(f"📝 Description: {description}")
        logger.info(f"📊 Scope Decision: {scope_analysis.get('scope', 'N/A')}")
        logger.info(f"🎯 Confidence: {scope_analysis.get('confidence', 'N/A')}")
        logger.info("")
        logger.info("📝 COMPLETE REASONING:")
        logger.info(f"{scope_analysis.get('reasoning', 'N/A')}")
        logger.info("")
        logger.info("🎮 COMPLETE RETRIEVAL STRATEGY:")
        retrieval_strategy = scope_analysis.get('retrieval_strategy', {})
        logger.info(f"  • Limit: {retrieval_strategy.get('limit', 'N/A')}")
        logger.info(f"  • Focus: {retrieval_strategy.get('focus', 'N/A')}")
        logger.info(f"  • Context Window: {retrieval_strategy.get('context_window', 'N/A')}")
        logger.info("=" * 120)
        logger.info("")

    def _build_synthesis_prompt(self, state: AgentState, context_data: Dict[str, Any]) -> str:
        """Build synthesis prompt using progressive summaries to prevent context explosion."""
        
        # NEW: Use progressive summaries and cumulative findings instead of raw data
        cumulative_findings = state.get('cumulative_findings', '')
        iteration_summaries = state.get('iteration_summaries', [])
        sufficiency_history = state.get('sufficiency_check_history', [])
        
        # Get approach summary instead of full query history
        approach_count = len(iteration_summaries)
        total_results = sum(
            sum(len(results) for _, results in approach_results) 
            for approach_results in state.get('approach_raw_results', {}).values()
        )
        
        # Build concise execution summary
        execution_summary = f"Completed {approach_count} research approaches, found {total_results} total results across all queries"
        
        # Use ALL iteration summaries (no truncation)
        findings_summary = "\n".join(f"• {summary}" for summary in iteration_summaries)
        
        # Get final sufficiency assessment
        final_assessment = sufficiency_history[-1] if sufficiency_history else {}
        assessment_summary = final_assessment.get('sufficiency_assessment', {})
        decision = assessment_summary.get('decision', 'SUFFICIENT')
        confidence = assessment_summary.get('confidence', 0.9)
        
        # Store all data combinations for potential fallback - no character counting
        final_cumulative_findings = cumulative_findings
        final_findings_summary = findings_summary
        
        logger.info("✅ Using complete cumulative findings + all iteration summaries")
        
        return f"""
        Synthesize a structured JSON response to the user's query based on the progressive research findings.
        CRITICAL: Provide specific, helpful responses for "not found" scenarios.

        **USER QUERY**: {state.get('user_query', 'N/A')}
        **RESEARCH INTENT**: {state.get('intent', 'N/A')}

        **CUMULATIVE RESEARCH FINDINGS**:
        {final_cumulative_findings}

        **ITERATION SUMMARIES**:
        {final_findings_summary}

        **RESEARCH EXECUTION SUMMARY**:
        {execution_summary}

        **FINAL ASSESSMENT**:
        Decision: {decision} (Confidence: {confidence:.1f})

        **RESPONSE GUIDELINES**:
        - If user asks for specific entity that doesn't exist, clearly state it doesn't exist and suggest similar entities found
        - If no relevant data found after comprehensive search, explain what WAS found instead
        - For architectural queries, synthesize patterns and structure from available data
        - Distinguish between "entity doesn't exist" vs "insufficient data to answer"
        - Provide actionable next steps or suggestions
        - ONLY mention entities that were actually found in the search results - do not mention examples that weren't searched for

        **OUTPUT FORMAT**:
        Return ONLY a valid JSON object with this exact structure:

        {{
            "answer": "Direct, concise answer to the user's question",
            "details": "Comprehensive explanation with specific findings, code locations, and technical details",
            "confidence": {confidence:.1f},
            "status": "found|not_found|partial",
            "suggestions": ["Alternative approaches", "Related findings", "Next steps"]
        }}

        **FIELD SPECIFICATIONS**:
        - "answer": 1-2 sentences directly answering the question
        - "details": Technical explanation with file paths, line numbers, code snippets where relevant
        - "confidence": Numeric confidence from final assessment
        - "status": "found" (definitive answer), "not_found" (entity doesn't exist), "partial" (some info found)
        - "suggestions": Array of actionable next steps or related findings (empty array if not applicable)

        Based on this progressive research across multiple approaches, provide the structured JSON response that:
        1. Gives a direct answer in the "answer" field
        2. Provides comprehensive technical details in the "details" field
        3. Includes relevant suggestions for further exploration
        4. Uses precise language and specific code locations when available
        """

    async def _generate_synthesis_with_fallback(self, state: AgentState, context_data: Dict[str, Any], llm_service) -> LLMResponse:
        """
        Generate synthesis response with smart fallback logic based on actual LLM context limits.
        
        Tries different data combinations in priority order:
        1. Complete cumulative findings + all iteration summaries
        2. All iteration summaries only (often more comprehensive)
        3. Cumulative findings only
        4. Recent iteration summaries that fit
        """
        cumulative_findings = state.get('cumulative_findings', '')
        iteration_summaries = state.get('iteration_summaries', [])
        
        # Data combination strategies in priority order
        strategies = [
            {
                'name': 'complete_data',
                'cumulative': cumulative_findings,
                'summaries': iteration_summaries,
                'description': 'Complete cumulative findings + all iteration summaries'
            },
            {
                'name': 'summaries_only', 
                'cumulative': '',
                'summaries': iteration_summaries,
                'description': 'All iteration summaries only (often more comprehensive)'
            },
            {
                'name': 'cumulative_only',
                'cumulative': cumulative_findings,
                'summaries': [],
                'description': 'Cumulative findings only'
            },
            {
                'name': 'recent_summaries',
                'cumulative': '',
                'summaries': iteration_summaries[-3:] if len(iteration_summaries) > 3 else iteration_summaries,
                'description': f'Most recent {min(3, len(iteration_summaries))} iteration summaries'
            }
        ]
        
        for strategy in strategies:
            try:
                logger.info(f"🔄 Trying synthesis strategy: {strategy['description']}")
                
                # Build prompt with this strategy's data
                temp_state = dict(state)
                temp_state['cumulative_findings'] = strategy['cumulative']
                temp_state['iteration_summaries'] = strategy['summaries']
                
                prompt = self._build_synthesis_prompt(temp_state, context_data)
                
                # Try LLM call
                result = await llm_service.generate_response(
                    prompt,
                    json_mode=True  
                )
                
                if result and not result.error:
                    logger.info(f"✅ Synthesis successful with strategy: {strategy['name']}")
                    return result
                else:
                    error_msg = result.error if result else "No response"
                    logger.warning(f"⚠️ Strategy '{strategy['name']}' failed: {error_msg}")
                    
                    # Check if it's a context limit error
                    if result and result.error and any(phrase in str(result.error).lower() for phrase in 
                                                     ['context', 'token', 'limit', 'length', 'too long']):
                        logger.info(f"🔄 Context limit detected, trying next strategy...")
                        continue
                    else:
                        # If it's not a context error, don't try other strategies
                        logger.error(f"❌ Non-context error in synthesis: {error_msg}")
                        return result
                        
            except Exception as e:
                logger.error(f"❌ Strategy '{strategy['name']}' exception: {e}")
                # Check if it's a context-related exception
                if any(phrase in str(e).lower() for phrase in ['context', 'token', 'limit', 'length', 'too long']):
                    logger.info(f"🔄 Context limit exception detected, trying next strategy...")
                    continue
                else:
                    # If it's not context-related, re-raise
                    raise
        
        # If all strategies failed
        logger.error("❌ All synthesis strategies failed")
        return None

    def _build_comprehensive_final_results(self, state: AgentState) -> List[Dict]:
        """
        Build comprehensive final results from all approaches and diagnostics.
        
        Collects all discovered data from:
        - discovered_data (basic results) 
        - approach_raw_results (comprehensive query results including diagnostics)
        - successful query results with actual content
        """
        comprehensive_results = []
        
        # Start with existing discovered_data
        existing_discovered = state.get("discovered_data", [])
        if existing_discovered:
            comprehensive_results.extend(existing_discovered)
        
        # Add comprehensive data from all approach results
        approach_raw_results = state.get("approach_raw_results", {})
        for approach_index, approach_results in approach_raw_results.items():
            for query, results in approach_results:
                if isinstance(results, list):
                    for result_item in results:
                        if isinstance(result_item, dict) and result_item not in comprehensive_results:
                            # Add metadata about which approach found this result
                            result_with_meta = {
                                **result_item,
                                "_source_approach": approach_index,
                                "_source_query": query[:100] + "..." if len(query) > 100 else query
                            }
                            comprehensive_results.append(result_with_meta)
        
        # Deduplicate results while preserving order
        seen = set()
        deduplicated_results = []
        for result in comprehensive_results:
            # Create a hashable key for deduplication
            if isinstance(result, dict):
                # Use a subset of fields for deduplication key
                key_fields = {k: v for k, v in result.items() 
                             if not k.startswith('_') and isinstance(v, (str, int, float, bool))}
                result_key = str(sorted(key_fields.items()))
                
                if result_key not in seen:
                    seen.add(result_key)
                    deduplicated_results.append(result)
            else:
                # For non-dict results, use string representation
                result_key = str(result)
                if result_key not in seen:
                    seen.add(result_key)
                    deduplicated_results.append(result)
        
        logger.info(f"📊 Built comprehensive final results: {len(deduplicated_results)} items from {len(approach_raw_results)} approaches")
        return deduplicated_results

    async def _debug_save_state_to_pickle(self, state: AgentState):
        """
        Save complete state to pickle file for debugging analysis.
        """
        try:
            import pickle
            from datetime import datetime
            
            # Create state copy and replace non-serializable llm_service
            state_copy = dict(state)
            state_copy['llm_service'] = '<LLM_SERVICE_OBJECT_REMOVED>'
            
            # Add debug timestamp
            state_copy['_debug_timestamp'] = datetime.now().isoformat()
            
            # Save to pickle file
            pickle_path = STATE_PKL
            with open(pickle_path, 'wb') as f:
                pickle.dump(state_copy, f)
            
            # Log summary
            approach_raw_results = state.get('approach_raw_results', {})
            raw_query_results = state.get('raw_query_results', [])
            query_history = state.get('query_history', [])
            
            logger.info(f"🐛 DEBUG: Complete state saved to {pickle_path}")
            logger.info(f"🔍 Summary: {len(approach_raw_results)} approaches, {len(raw_query_results)} raw results, {len(query_history)} history items")
            
        except Exception as e:
            logger.error(f"❌ Failed to save debug state: {e}")
            import traceback
            traceback.print_exc()

    async def _validate_synthesis_quality(self, response: str, state: AgentState, llm_service) -> 'SynthesisValidation':
        """
        Validate synthesis quality using an LLM critic.
        
        Checks for faithfulness, completeness, accuracy, and overall quality.
        """
        from .models import SynthesisValidation
        
        # Extract key information for validation context
        user_query = state.get('user_query', '')
        cumulative_findings = state.get('cumulative_findings', '')
        iteration_summaries = state.get('iteration_summaries', [])
        discovered_data_count = len(state.get('discovered_data', []))
        query_history_count = len(state.get('query_history', []))
        
        # Build validation prompt
        validation_prompt = f"""
        You are a synthesis quality critic. Evaluate this response for faithfulness, completeness, accuracy, and quality.
        
        **USER'S ORIGINAL QUERY**: {user_query}
        
        **RESEARCH FINDINGS SUMMARY**: 
        {cumulative_findings}  # Complete findings, no truncation
        
        **ITERATION SUMMARIES**:
        {chr(10).join(iteration_summaries)}  # All iteration summaries
        
        **RESEARCH STATS**: 
        - Discovered data items: {discovered_data_count}
        - Queries executed: {query_history_count}
        
        **GENERATED RESPONSE TO VALIDATE**:
        {response}
        
        **EVALUATION CRITERIA**:
        1. **Faithfulness** (0.0-1.0): Is the response based only on actual research findings? No hallucinations?
        2. **Completeness** (0.0-1.0): Are all important findings from the research included?
        3. **Accuracy** (0.0-1.0): Does the response actually answer the user's specific question?
        4. **Quality** (0.0-1.0): Is the response clear, well-structured, and helpful?
        
        **VALIDATION GUIDELINES**:
        - Score 0.8+ = accept (high quality)
        - Score 0.6-0.8 = accept with minor issues
        - Score <0.6 = retry recommended
        - Identify specific hallucinated content (mentions things not in findings)
        - Identify missing important entities or data
        - Check if the response format matches what user asked for
        
        Respond with valid JSON:
        {{
            "is_valid": <true if overall acceptable>,
            "faithfulness_score": <0.0-1.0>,
            "completeness_score": <0.0-1.0>, 
            "accuracy_score": <0.0-1.0>,
            "quality_score": <0.0-1.0>,
            "validation_issues": [<list of specific issues found>],
            "missing_entities": [<important entities not mentioned>],
            "hallucinated_content": [<content not supported by findings>],
            "overall_score": <average of the 4 scores>,
            "decision": "<accept|retry|fallback>",
            "reasoning": "<detailed explanation of evaluation>"
        }}
        """
        
        try:
            # Use the same retry mechanism as other LLM calls
            validation_data = await self._retry_llm_with_validation(
                llm_service=llm_service,
                initial_prompt=validation_prompt,
                model_class=SynthesisValidation,
                max_retries=2,  # Fewer retries for validation
                operation_name="synthesis validation"
            )
            
            return SynthesisValidation(**validation_data)
            
        except Exception as e:
            logger.warning(f"⚠️ Synthesis validation failed: {e}")
            # Return a fallback validation that accepts the response
            return SynthesisValidation(
                is_valid=True,
                faithfulness_score=0.7,
                completeness_score=0.7,
                accuracy_score=0.7,
                quality_score=0.7,
                overall_score=0.7,
                decision='accept',
                reasoning=f"Validation failed ({str(e)}), accepting response by default",
                validation_issues=[f"Validation error: {str(e)}"]
            )

    async def _fix_synthesis_with_critic_feedback(self, original_response: str, validation_result: SynthesisValidation, 
                                                  state: AgentState, llm_service) -> str:
        """
        Use critic feedback to improve the synthesis response.
        
        Takes the original response, critic feedback, and generates an improved version.
        """
        user_query = state.get('user_query', '')
        cumulative_findings = state.get('cumulative_findings', '')
        iteration_summaries = state.get('iteration_summaries', [])
        
        # Build improvement prompt using critic feedback
        improvement_prompt = f"""You are a synthesis expert. Improve this response based on detailed critic feedback.

**USER'S ORIGINAL QUERY**: {user_query}

**COMPLETE RESEARCH FINDINGS**:
{cumulative_findings}

**ALL ITERATION SUMMARIES**:
{chr(10).join(iteration_summaries)}

**ORIGINAL RESPONSE (needs improvement)**:
{original_response}

**CRITIC FEEDBACK ANALYSIS**:
- Overall Score: {validation_result.overall_score:.2f}/1.0
- Faithfulness Score: {validation_result.faithfulness_score:.2f} (hallucinations check)
- Completeness Score: {validation_result.completeness_score:.2f} (missing findings check)  
- Accuracy Score: {validation_result.accuracy_score:.2f} (answers user question)
- Quality Score: {validation_result.quality_score:.2f} (clarity and structure)

**SPECIFIC ISSUES TO FIX**:
{chr(10).join(f"• {issue}" for issue in validation_result.validation_issues)}

**MISSING ENTITIES** (add these if relevant):
{chr(10).join(f"• {entity}" for entity in validation_result.missing_entities)}

**HALLUCINATED CONTENT** (remove/correct these):
{chr(10).join(f"• {content}" for content in validation_result.hallucinated_content)}

**CRITIC'S REASONING**: 
{validation_result.reasoning}

**IMPROVEMENT TASK**:
1. **Fix Faithfulness Issues**: Remove any content not supported by the research findings
2. **Address Completeness**: Include important findings that were missed in the original response  
3. **Improve Accuracy**: Ensure the response directly answers the user's specific question
4. **Enhance Quality**: Improve clarity, structure, and helpfulness
5. **Maintain Exact JSON Format**: Follow the exact JSON structure required

**REQUIRED JSON OUTPUT FORMAT**:
Return ONLY a valid JSON object with this exact structure:

{{
    "answer": "Direct, concise answer to the user's question",
    "details": "Comprehensive explanation with specific findings, code locations, and technical details",
    "confidence": <numeric confidence 0.0-1.0>,
    "status": "found|not_found|partial",
    "suggestions": ["Alternative approaches", "Related findings", "Next steps"]
}}

**FIELD REQUIREMENTS**:
- "answer": 1-2 sentences directly answering the question
- "details": Technical explanation with file paths, line numbers, code snippets where relevant
- "confidence": Numeric confidence (0.0-1.0)
- "status": "found" (definitive answer), "not_found" (entity doesn't exist), "partial" (some info found)
- "suggestions": Array of actionable next steps or related findings (empty array if not applicable)

**CRITICAL**: Base your improved response ONLY on the research findings provided above. Do not add information not found in the research data.

**IMPROVED JSON RESPONSE**:"""

        try:
            # Generate improved synthesis with critic feedback
            result = await llm_service.generate_response(
                improvement_prompt, 
                temperature=0.2,  # Lower temperature for more focused improvement
                max_tokens=16000, # Use maximum possible tokens for comprehensive improvements
                json_mode=True,   # Enable JSON mode for structured response
                use_cache=False   # Don't cache correction attempts
            )
            
            if result and not result.error:
                improved_response = result.content.strip()
                
                # Optional: Re-validate the improved response to ensure it's actually better
                try:
                    re_validation = await self._validate_synthesis_quality(
                        improved_response, state, llm_service
                    )
                    
                    if re_validation.overall_score > validation_result.overall_score:
                        logger.info(f"📈 Improvement successful: {validation_result.overall_score:.2f} → {re_validation.overall_score:.2f}")
                        return improved_response
                    else:
                        logger.warning(f"📉 Improvement didn't help: {validation_result.overall_score:.2f} → {re_validation.overall_score:.2f}")
                        return None  # Return None to use original response
                        
                except Exception as revalidation_error:
                    logger.warning(f"⚠️ Re-validation failed: {revalidation_error}")
                    # Return improved response anyway since we can't re-validate
                    return improved_response
                    
            else:
                logger.warning(f"⚠️ Synthesis improvement failed: {result.error if result else 'No result'}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error in synthesis improvement: {e}")
            return None

    async def _analyze_intent_with_validation(self, state: AgentState, max_attempts: int = 3) -> dict:
        """Analyze intent with Pydantic validation."""
        for attempt in range(max_attempts):
            try:
                intent_prompt = f"""
                Analyze the user's intent and classify it appropriately.

                User Query: {state['user_query']}

                Classify as:
                - "lookup": Specific data retrieval (find comments, specific functions, etc.)
                - "architectural": Understanding structure, relationships, patterns
                - "hybrid": Combination of lookup and architectural analysis

                Respond with valid JSON:
                {{
                    "intent_type": "lookup|architectural|hybrid",
                    "confidence": 0.95,
                    "reasoning": "Detailed reasoning for classification",
                    "expected_result_type": "Description of expected results"
                }}
                """
                
                llm_service = state.get('llm_service')
                if not llm_service:
                    raise Exception("LLM service not available")
                    
                result = await llm_service.generate_response(intent_prompt, json_mode=True)
                
                if result and not result.error:
                    intent_data = json.loads(result.content.strip())
                    
                    # Validate with Pydantic
                    intent_analysis = IntentAnalysis(**intent_data)
                    return intent_analysis.dict()
                else:
                    raise Exception(f"Intent analysis failed: {result.error if result else 'No result'}")
                    
            except (json.JSONDecodeError, ValidationError) as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Intent analysis validation failed (attempt {attempt + 1}): {e}")
                    continue
                else:
                    logger.error(f"❌ Intent analysis failed after {max_attempts} attempts: {e}")
                    return self._fallback_intent_analysis(state['user_query'])
            except Exception as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Intent analysis error (attempt {attempt + 1}): {e}")
                    continue
                else:
                    raise e

        return self._fallback_intent_analysis(state['user_query'])

    def _fallback_intent_analysis(self, user_query: str) -> dict:
        """Provide fallback intent analysis."""
        query_lower = user_query.lower()
        
        if any(word in query_lower for word in ['find', 'show', 'list', 'what', 'where', 'comment']):
            intent_type = 'lookup'
        elif any(word in query_lower for word in ['structure', 'architecture', 'relationship', 'inherit', 'depend']):
            intent_type = 'architectural'
        else:
            intent_type = 'hybrid'
        
        return {
            "intent_type": intent_type,
            "confidence": 0.6,
            "reasoning": f"Fallback analysis based on keywords in query: {user_query}",
            "expected_result_type": "Mixed results based on fallback analysis"
        }

    async def _evaluate_sufficiency_with_validation(self, state: AgentState, max_attempts: int = 3) -> SufficiencyEvaluation:
        """Evaluate sufficiency with Pydantic validation."""
        
        # Get research guidance
        discovery_research = state.get('discovery_research', {})
        research_guidance = ""
        if discovery_research and self.context_manager:
            research_guidance = self.context_manager.format_discovery_research_for_evaluation(discovery_research)
        
        for attempt in range(max_attempts):
            try:
                evaluation_prompt = f"""
                Evaluate if we have sufficient data to answer the user's query.

                User Query: {state['user_query']}
                Intent: {state['intent']}

                **DISCOVERED DATA**: {len(state.get('discovered_data', []))} items
                **QUERIES EXECUTED**: {len(state.get('query_history', []))}
                **ITERATION**: {state.get('current_iteration', 1)}/{state.get('max_iterations', 5)}

                {research_guidance}

                Respond with valid JSON:
                {{
                    "is_sufficient": true,
                    "decision": "SUFFICIENT",
                    "gaps_summary": "Brief summary of any gaps",
                    "data_gaps": {{"missing_entities": [], "missing_relationships": []}},
                    "body_exploration_needed": false,
                    "entities_for_body_exploration": [],
                    "confidence": 0.95,
                    "reasoning": "Detailed reasoning for the evaluation"
                }}
                
                IMPORTANT: For the "decision" field, use exactly one of these values:
                - "SUFFICIENT" (if data is adequate)
                - "NEED_MORE" (if insufficient data, more exploration needed)
                - "NEED_BODY_EXPLORATION" (if specific entity body exploration needed)
                """
                
                llm_service = state.get('llm_service')
                result = await llm_service.generate_response(evaluation_prompt, json_mode=True)
                
                if result and not result.error:
                    eval_data = json.loads(result.content.strip())
                    
                    # Validate with Pydantic
                    evaluation = SufficiencyEvaluation(**eval_data)
                    return evaluation
                else:
                    raise Exception(f"Evaluation failed: {result.error if result else 'No result'}")
                    
            except (json.JSONDecodeError, ValidationError) as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Sufficiency evaluation validation failed (attempt {attempt + 1}): {e}")
                    continue
                else:
                    logger.error(f"❌ Sufficiency evaluation failed after {max_attempts} attempts: {e}")
                    # Return fallback evaluation
                    return SufficiencyEvaluation(
                        is_sufficient=False,
                        decision="NEED_MORE",
                        gaps_summary="Evaluation failed - need more exploration",
                        confidence=0.5,
                        reasoning="Fallback evaluation due to validation failures"
                    )
            except Exception as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Sufficiency evaluation error (attempt {attempt + 1}): {e}")
                    continue
                else:
                    raise e

        # Fallback evaluation
        return SufficiencyEvaluation(
            is_sufficient=False,
            decision="NEED_MORE",
            gaps_summary="Default evaluation - continue exploration",
            confidence=0.5,
            reasoning="Fallback evaluation after all attempts failed"
        )

    async def _execute_query_with_retry(self, query: str, purpose: str, state: AgentState, max_retries: int = 2) -> Dict[str, Any]:
        """Execute query using project-analyzer CLI tool (same pattern as original workflow)"""
        import subprocess
        import json
        
        for attempt in range(max_retries):
            try:
                # Fix Neo4j 5.x syntax issues
                fixed_query = self._fix_neo4j_syntax(query, state.get("neo4j_version", ""))
                
                # Use project-analyzer CLI (same pattern as other tools)
                cli_command = [
                    GENPOD_GRAPH_INDEXER_BIN,
                    "--config-file", state.get("neo4j_config", NEO4J_CONFIG),
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
                                "response": [],
                                "error": output_data.get("error", "Unknown error"),
                                "query": fixed_query,
                                "purpose": purpose
                            }
                        
                        return {
                            "status": "success",
                            "response": output_data.get("results", []),
                            "query": fixed_query,
                            "purpose": purpose
                        }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse CLI JSON output: {e}")
                        return {
                            "status": "error",
                            "response": [],
                            "error": f"JSON parse error: {e}",
                            "raw_output": result.stdout
                        }
                else:
                    logger.warning(f"CLI command failed (attempt {attempt + 1}): {result.stderr}")
                    
                    if attempt == max_retries - 1:
                        return {
                            "status": "error",
                            "response": [],
                            "error": result.stderr,
                            "returncode": result.returncode
                        }
                
            except subprocess.TimeoutExpired:
                logger.error(f"CLI command timed out (attempt {attempt + 1})")
                if attempt == max_retries - 1:
                    return {
                        "status": "error",
                        "response": [],
                        "error": "Query execution timed out"
                    }
            except Exception as e:
                logger.error(f"Unexpected error during query execution (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return {
                        "status": "error",
                        "response": [],
                        "error": str(e)
                    }
        
        return {
            "status": "error",
            "response": [],
            "error": "All retry attempts failed"
        }

    def _fix_neo4j_syntax(self, query: str, neo4j_version: str) -> str:
        """Fix Neo4j syntax issues for compatibility"""
        # Basic syntax fixes for Neo4j 5.x compatibility
        fixed_query = query
        
        # Remove problematic EXISTS patterns
        if "NOT EXISTS(" in fixed_query:
            fixed_query = fixed_query.replace("NOT EXISTS(", "NOT (")
        if "EXISTS(" in fixed_query:
            fixed_query = fixed_query.replace("EXISTS(", "(")
            
        return fixed_query

    async def _check_fallback_needed(self, state: AgentState) -> bool:
        """Check if fallback strategies are needed."""
        current_iteration = state.get('current_iteration', 1)
        discovered_data = state.get('discovered_data', [])
        query_history = state.get('query_history', [])
        
        # Activate fallback if multiple iterations with no progress
        if current_iteration >= 3 and len(discovered_data) == 0:
            return True
            
        # Activate fallback if repeated failures
        recent_failures = sum(1 for q in query_history[-3:] if q.get('status') == 'failed')
        if recent_failures >= 2:
            return True
            
        return False

    async def _analyze_approach_scope_with_llm(self, approach: Dict[str, Any], state: AgentState) -> Dict[str, Any]:
        """
        Use LLM to analyze approach scope and determine retrieval strategy.
        
        Args:
            approach: Research approach details
            state: Current agent state
            
        Returns:
            Dict with scope, retrieval_strategy, and reasoning
        """
        user_query = state.get('user_query', '')
        
        # Build scope analysis prompt
        prompt = f"""You are a CPG query scope analyzer. Analyze this research approach and determine if it needs single-file or multi-file data retrieval.

**USER QUERY**: {user_query}

**APPROACH TO ANALYZE**:
- **Name**: {approach.get('approach_name', 'Unknown')}
- **Description**: {approach.get('description', 'N/A')}
- **Target Nodes**: {approach.get('target_nodes', [])}
- **Key Attributes**: {approach.get('key_attributes', [])}
- **Relationships**: {approach.get('relationships', [])}
- **Strategy**: {approach.get('strategy', 'N/A')}

**YOUR TASK**: Determine the scope needed for this approach:

**SINGLE_FILE SCOPE** (when the approach can be answered by looking at one file):
- Searching within a specific function (e.g., "find variables in WorkerA function")
- Analyzing parameters or local variables of one function
- Looking at class/type members in one location
- Function body analysis
- Typical limits: 50-75 results

**MULTI_FILE SCOPE** (when the approach needs data from multiple files):
- Searching across the entire codebase
- Finding all instances of something project-wide
- Cross-file relationship traversal
- Global searches or file-scoped analysis
- Typical limits: 150-200 results

**RESPONSE FORMAT** (JSON only):
{{
  "scope": "single_file" or "multi_file",
  "reasoning": "Detailed explanation why this scope is needed",
  "confidence": 0.8,
  "retrieval_strategy": {{
    "limit": 75,
    "focus": "targeted" or "comprehensive",
    "context_window": "small" or "large"
  }}
}}

Focus on what the approach actually needs to do to answer the user query."""

        try:
            # Use GPT-4o with low temperature for precise analysis
            llm_service = state.get('llm_service')
            if not llm_service:
                raise Exception("LLM service not available")
            
            from src.core.llm_service import LLMModel
            result = await llm_service.generate_response(
                prompt, 
                json_mode=True, 
                model=LLMModel.GPT4O, 
                max_tokens=2000,
                temperature=0.2  # Low temperature for consistent analysis
            )
            
            if not result or result.error:
                raise Exception(f"LLM scope analysis failed: {result.error if result else 'No response'}")
            
            # Use retry mechanism with Pydantic validation
            return await self._retry_llm_with_validation(
                llm_service=llm_service,
                initial_prompt=prompt,
                model_class=ScopeAnalysis,
                max_retries=3,
                operation_name="scope analysis"
            )
            
        except Exception as e:
            logger.error(f"❌ LLM scope analysis failed: {e}")
            # Fallback to simple heuristic
            return self._fallback_scope_analysis(approach)

    def _fallback_scope_analysis(self, approach: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback scope analysis when LLM fails."""
        approach_name = approach.get('approach_name', '').lower()
        
        # Simple fallback logic
        if 'function-local' in approach_name or 'parameter' in approach_name:
            scope = 'single_file'
            limit = 50
        else:
            scope = 'multi_file'  
            limit = 100
        
        retrieval_strategy = {
            'limit': limit,
            'focus': 'targeted' if scope == 'single_file' else 'comprehensive',
            'context_window': 'small' if scope == 'single_file' else 'large'
        }
        
        return {
            'scope': scope,
            'retrieval_strategy': retrieval_strategy,
            'reasoning': f"Fallback analysis for {approach_name}",
            'confidence': 0.5
        }

    async def execute_queries(self, state: AgentState) -> AgentState:
        """
        Node: Execute generated Cypher queries with comprehensive error handling.
        
        This node handles:
        - Syntax error capture and handling
        - Empty result detection and analysis
        - Secondary validation with followup queries
        - Comprehensive conclusion generation
        """
        logger.info("⚡ Node: execute_queries")
        
        try:
            generated_queries = state.get('generated_queries', [])
            if not generated_queries:
                logger.error("❌ No queries to execute")
                return {
                    **state,
                    "current_node": "execute_queries",
                    "execution_results": [],
                    "execution_status": "failed",
                    "execution_error": "No queries available for execution"
                }
            
            # Execute queries from the current approach (last list in generated_queries)
            # generated_queries is now a list of lists - each inner list contains queries for one approach
            queries_to_execute = generated_queries[-1] if generated_queries else []
            
            execution_results = []
            all_successful = True
            total_results_found = 0
            
            logger.info(f"🔄 Executing {len(queries_to_execute)} query for current approach...")
            logger.info(f"📊 Total queries generated so far: {len(generated_queries)}")
            
            for i, query_data in enumerate(queries_to_execute, 1):
                logger.info(f"📋 Executing Query {i}/{len(queries_to_execute)}")
                logger.info(f"🎯 Query: {query_data.get('cypher_query', 'N/A')}")
                
                # Execute query with error handling
                result = await self._execute_single_query_with_validation(query_data, i, state)
                execution_results.append(result)
                
                # Track success and results
                if result['status'] != 'success':
                    all_successful = False
                else:
                    total_results_found += len(result.get('data', []))
                
                # Log result summary
                self._log_query_execution_result(result, i)
            
            # Analyze overall execution results
            execution_analysis = await self._analyze_execution_results(execution_results, state)
            
            # Log execution summary
            self._log_execution_summary(execution_results, execution_analysis, total_results_found)
            
            # Don't increment approach index here - Generate step already handles this
            current_approach_index = state.get('current_approach_index', 0)
            
            # Collect successful results for discovered_data
            successful_data = []
            for result in execution_results:
                if result['status'] == 'success':
                    successful_data.extend(result.get('data', []))
            
            # Update discovered_data with new results
            existing_discovered_data = state.get('discovered_data', [])
            updated_discovered_data = existing_discovered_data + successful_data
            
            # NEW: Store results in approach_raw_results structure for rethink analysis
            approach_raw_results = state.get('approach_raw_results', {})
            
            # Create list of (query, results) tuples for current approach
            current_approach_tuples = []
            for result in execution_results:
                query = result.get('cypher_query', '')
                
                # Handle both expected formats: {'status': 'success', 'data': [...]} and {'success': True, 'results': [...]}
                if result.get('status') == 'success':
                    query_results = result.get('data', [])
                elif result.get('success') is True:
                    query_results = result.get('results', [])
                else:
                    query_results = []
                
                current_approach_tuples.append((query, query_results))
                
                # NEW: Add diagnostic queries to approach_raw_results if available
                diagnostic_data = result.get('diagnostic_queries_data', [])
                if diagnostic_data:
                    logger.info(f"🔍 Adding {len(diagnostic_data)} diagnostic queries to approach_raw_results")
                    for diagnostic in diagnostic_data:
                        if diagnostic.get('found_data', False):  # Only add queries that found data
                            diagnostic_query = diagnostic.get('query', '')
                            diagnostic_results = diagnostic.get('sample_data', [])
                            current_approach_tuples.append((diagnostic_query, diagnostic_results))
                            logger.info(f"  🔧 Added diagnostic: {diagnostic.get('purpose', 'Unknown purpose')[:50]}...")
            
            # Store tuples for current approach (now includes diagnostic queries)
            approach_raw_results[current_approach_index] = current_approach_tuples
            
            # Store execution cycle results as raw results for backward compatibility
            cycle_raw_results = self._build_cycle_raw_results(execution_results, current_approach_index + 1)
            existing_raw_results = state.get('raw_query_results', [])
            updated_raw_results = existing_raw_results + cycle_raw_results
            
            # Log results for visibility
            logger.info(f"📊 Stored {len(current_approach_tuples)} query-result tuples for approach {current_approach_index}")
            self._log_cycle_raw_results(cycle_raw_results, current_approach_index + 1)
            
            return {
                **state,
                "current_node": "execute_queries", 
                "execution_results": execution_results,
                "execution_analysis": execution_analysis,
                "execution_status": "success" if all_successful else "partial",
                "total_results_found": total_results_found,
                "query_history": state.get('query_history', []) + execution_results,
                "current_approach_index": current_approach_index,  # Keep current index (Generate handles increment)
                "current_iteration": state.get('current_iteration', 1) + 1,  # Increment iteration
                "discovered_data": updated_discovered_data,  # Add successful results to discovered data
                "raw_query_results": updated_raw_results,  # Store for backward compatibility
                "approach_raw_results": approach_raw_results,  # NEW: Store for rethink analysis
                # Note: generated_queries is NOT cleared - we keep all for development purposes
            }
            
        except Exception as e:
            logger.error(f"❌ Query execution failed: {e}")
            
            # FIXED: Build partial raw_query_results from any successful executions before the failure
            try:
                current_approach_index = state.get('current_approach_index', 0)
                approach_raw_results = state.get('approach_raw_results', {})
                existing_raw_results = state.get('raw_query_results', [])
                
                # If we have approach results for this cycle, build partial raw results
                partial_cycle_results = []
                if current_approach_index in approach_raw_results:
                    # Get any results that were stored before the failure
                    approach_results = approach_raw_results[current_approach_index]
                    if approach_results:
                        # Build execution results from the tuples for partial processing
                        partial_execution_results = []
                        for i, (query, results) in enumerate(approach_results):
                            partial_execution_results.append({
                                'query_number': i + 1,
                                'approach_name': f'Approach {current_approach_index + 1} (Partial)',
                                'cypher_query': query,
                                'status': 'success' if results else 'empty_result',
                                'data': results if isinstance(results, list) else [],
                                'execution_time': 0
                            })
                        
                        # Build partial cycle raw results
                        partial_cycle_results = self._build_cycle_raw_results(
                            partial_execution_results, current_approach_index + 1
                        )
                        logger.info(f"🔄 Built {len(partial_cycle_results)} partial raw results from approach {current_approach_index}")
                
                # Preserve existing raw_query_results and add any partial results
                preserved_raw_results = existing_raw_results + partial_cycle_results
                
            except Exception as preserve_error:
                logger.warning(f"⚠️ Failed to preserve partial raw results: {preserve_error}")
                preserved_raw_results = state.get('raw_query_results', [])
            
            return {
                **state,
                "current_node": "execute_queries",
                "execution_status": "failed",
                "execution_error": str(e),
                "execution_results": [],
                # FIXED: Preserve raw_query_results even on failure
                "raw_query_results": preserved_raw_results
            }

    async def _execute_single_query_with_validation(self, query_data: Dict[str, Any], query_number: int, state: AgentState) -> Dict[str, Any]:
        """
        Execute a single query with comprehensive error handling.
        
        Handles:
        - Syntax errors
        - Empty results with followup analysis
        - Execution failures
        """
        cypher_query = query_data.get('cypher_query', '')
        approach_name = query_data.get('approach_name', f'Query {query_number}')
        
        # Initialize result structure
        result = {
            'query_number': query_number,
            'approach_name': approach_name,
            'cypher_query': cypher_query,
            'status': 'pending',
            'data': [],
            'error': None,
            'syntax_error': False,
            'empty_result': False,
            'followup_analysis': None,
            'execution_time': None
        }
        
        try:
            # Record start time
            import time
            start_time = time.time()
            
            # FIXED: Use unified retry mechanism for primary query execution
            execution_result = await self._execute_query_with_retry(
                cypher_query, 
                approach_name, 
                is_diagnostic=False,  # This is a primary query
                max_retries=3,
                state=state
            )
            
            execution_time = round(time.time() - start_time, 2)
            result['execution_time'] = execution_time
            
            # Handle the unified execution result
            if execution_result['status'] == 'success':
                # Primary query executed successfully (possibly after retries)
                query_data = execution_result.get('data', [])
                result.update({
                    'status': 'success',
                    'data': query_data,
                    'retry_count': execution_result.get('retry_count', 0),
                    'final_query': execution_result.get('final_query', cypher_query)
                })
                
                # Add retry details if corrections were made
                corrections = execution_result.get('corrections_attempted', [])
                if corrections:
                    result.update({
                        'auto_corrected': True,
                        'original_query': cypher_query,
                        'corrections_attempted': corrections,
                        'original_error': corrections[0].get('error') if corrections else None
                    })
                
                # Check for empty results - ONLY trigger diagnostics for primary queries with empty results
                if not query_data or len(query_data) == 0:
                    result.update({
                        'status': 'empty_result',
                        'empty_result': True
                    })
                    logger.warning(f"⚠️ Primary Query {query_number} returned EMPTY RESULTS - initiating diagnostic analysis")
                    logger.warning(f"🔧 This will trigger diagnostic queries to understand why the query was empty")
                    
                    # Perform followup analysis for empty results (ONLY for primary queries)
                    followup_analysis = await self._analyze_empty_result(
                        execution_result.get('final_query', cypher_query), 
                        approach_name, 
                        query_number, 
                        state
                    )
                    result['followup_analysis'] = followup_analysis
                    
                    # Store diagnostic queries for later addition to approach_raw_results
                    result['diagnostic_queries_data'] = followup_analysis.get('diagnostic_results', [])
                    
                    logger.info(f"✅ Empty result analysis completed for Query {query_number}")
                else:
                    logger.info(f"✅ Primary Query {query_number} executed successfully - {len(query_data)} results found")
                    
                return result
                
            else:
                # Primary query failed after all retry attempts
                result.update({
                    'status': execution_result['status'],
                    'error': execution_result.get('error', 'Unknown error'),
                    'retry_count': execution_result.get('retry_count', 0),
                    'final_query': execution_result.get('final_query', cypher_query),
                    'corrections_attempted': execution_result.get('corrections_attempted', [])
                })
                
                # Set additional fields based on failure type
                if execution_result['status'] == 'syntax_error':
                    result.update({
                        'syntax_error': True,
                        'needs_regeneration': True,
                        'error_feedback': self._extract_syntax_error_feedback(execution_result.get('error', 'Unknown error'))
                    })
                
                logger.error(f"❌ Primary Query {query_number} failed after {execution_result.get('retry_count', 0)} attempts: {execution_result.get('error', 'Unknown error')}")
                return result
            
        except Exception as e:
            result.update({
                'status': 'execution_error',
                'error': str(e)
            })
            logger.error(f"❌ Unexpected error in Query {query_number}: {e}")
            return result

    async def _execute_query_with_retry(self, cypher_query: str, approach_name: str, is_diagnostic: bool = False, max_retries: int = 3, state: AgentState = None) -> Dict[str, Any]:
        """
        Execute a query with retry logic for syntax error correction.
        
        Unified method that handles both primary and diagnostic queries with the same
        robust error correction logic.
        
        Args:
            cypher_query: The Cypher query to execute
            approach_name: Name of the approach (for logging)
            is_diagnostic: True if this is a diagnostic query, False for primary
            max_retries: Maximum number of retry attempts (default: 3)
            state: Current workflow state
            
        Returns:
            Dict with execution result including status, data, error info, and retry details
        """
        result = {
            'status': 'pending',
            'data': [],
            'error': None,
            'original_query': cypher_query,
            'retry_count': 0,
            'corrections_attempted': [],
            'is_diagnostic': is_diagnostic
        }
        
        current_query = cypher_query
        
        for attempt in range(max_retries):
            try:
                logger.info(f"{'🔧' if is_diagnostic else '📋'} {'Diagnostic' if is_diagnostic else 'Primary'} Query Attempt {attempt + 1}/{max_retries}")
                if attempt > 0:
                    logger.info(f"   Query: {current_query[:100]}...")
                
                # Execute the query
                execution_result = await self._execute_via_cli(current_query, state)
                
                if execution_result['status'] == 'success':
                    # Success! Return the result
                    query_data = execution_result.get('response', [])
                    result.update({
                        'status': 'success',
                        'data': query_data,
                        'final_query': current_query,
                        'retry_count': attempt
                    })
                    
                    if attempt > 0:
                        logger.info(f"✅ {'Diagnostic' if is_diagnostic else 'Primary'} query succeeded on attempt {attempt + 1}")
                    
                    return result
                    
                elif execution_result['status'] == 'error':
                    # Syntax/execution error - try to fix it
                    error_message = execution_result.get('error', 'Unknown error')
                    logger.warning(f"⚠️ Attempt {attempt + 1} failed: {error_message}")
                    
                    if attempt < max_retries - 1:  # Don't try to fix on the last attempt
                        logger.info(f"🛠️ Attempting to fix {'diagnostic' if is_diagnostic else 'primary'} query...")
                        
                        # Try to fix the query
                        corrected_query = await self._fix_query_syntax(
                            current_query, 
                            error_message, 
                            approach_name, 
                            state,
                            previous_attempts=result['corrections_attempted']
                        )
                        
                        if corrected_query and corrected_query != current_query:
                            logger.info(f"🔧 Generated corrected query for attempt {attempt + 2}")
                            result['corrections_attempted'].append({
                                'attempt': attempt + 1,
                                'original': current_query,
                                'corrected': corrected_query,
                                'error': error_message
                            })
                            current_query = corrected_query
                            continue  # Try the corrected query
                        else:
                            logger.warning(f"⚠️ Could not generate correction for attempt {attempt + 1}")
                    
                    # If we get here, correction failed or this is the last attempt
                    result.update({
                        'status': 'syntax_error',
                        'error': error_message,
                        'final_query': current_query,
                        'retry_count': attempt + 1
                    })
                    
                    if attempt == max_retries - 1:
                        logger.error(f"❌ {'Diagnostic' if is_diagnostic else 'Primary'} query failed after {max_retries} attempts")
                    
                    return result
                    
            except Exception as e:
                logger.error(f"❌ Unexpected error in attempt {attempt + 1}: {e}")
                result.update({
                    'status': 'execution_error',
                    'error': str(e),
                    'final_query': current_query,
                    'retry_count': attempt + 1
                })
                
                if attempt == max_retries - 1:
                    return result
                    
        # Should never reach here, but just in case
        result.update({
            'status': 'max_retries_exceeded',
            'error': f'Failed after {max_retries} attempts',
            'final_query': current_query,
            'retry_count': max_retries
        })
        
        return result

    async def _analyze_empty_result(self, cypher_query: str, approach_name: str, query_number: int, state: AgentState) -> Dict[str, Any]:
        """
        Analyze why a query returned empty results with followup queries and conclusions.
        
        Creates diagnostic queries to understand:
        - Whether target nodes exist in the graph
        - Whether relationships are available
        - Whether query is too restrictive
        """
        logger.info(f"🔍 Starting empty result analysis for Query {query_number}...")
        
        # Extract key components from the original query for analysis
        query_analysis = self._parse_cypher_query_components(cypher_query)
        
        # Generate diagnostic followup queries using LLM
        diagnostic_queries = await self._generate_llm_diagnostic_queries(cypher_query, query_analysis, approach_name, state)
        
        # Execute diagnostic queries with unified retry mechanism
        diagnostic_results = []
        for i, diagnostic_query in enumerate(diagnostic_queries):
            try:
                logger.info(f"🔧 Running diagnostic {i+1}/{len(diagnostic_queries)}: {diagnostic_query['purpose']}")
                
                # FIXED: Use unified retry mechanism for diagnostic queries too
                result = await self._execute_query_with_retry(
                    diagnostic_query['query'],
                    f"Diagnostic for {approach_name}",
                    is_diagnostic=True,  # This is a diagnostic query
                    max_retries=3,
                    state=state
                )
                
                diagnostic_result = {
                    'purpose': diagnostic_query['purpose'],
                    'query': result.get('final_query', diagnostic_query['query']),
                    'original_query': diagnostic_query['query'],
                    'status': result['status'],
                    'found_data': len(result.get('data', [])) > 0,
                    'data_count': len(result.get('data', [])),
                    'sample_data': result.get('data', [])[:3] if result.get('data') else [],
                    'retry_count': result.get('retry_count', 0),
                    'corrections_attempted': result.get('corrections_attempted', [])
                }
                
                diagnostic_results.append(diagnostic_result)
                
                # Enhanced logging with retry information
                retry_info = f" (retries: {diagnostic_result['retry_count']})" if diagnostic_result['retry_count'] > 0 else ""
                logger.info(f"  🔧 {diagnostic_query['purpose']}: {'✅ Found data' if diagnostic_result['found_data'] else '❌ No data'} ({diagnostic_result['data_count']} items){retry_info}")
                
            except Exception as e:
                diagnostic_results.append({
                    'purpose': diagnostic_query['purpose'],
                    'query': diagnostic_query['query'],
                    'status': 'error',
                    'error': str(e),
                    'retry_count': 0,
                    'corrections_attempted': []
                })
                logger.error(f"  ❌ Diagnostic query failed with exception: {e}")
        
        # Generate comprehensive conclusion using LLM
        conclusion = await self._generate_llm_empty_result_conclusion(
            cypher_query, approach_name, query_analysis, diagnostic_results, state
        )
        
        import time
        return {
            'query_number': query_number,
            'approach_name': approach_name,
            'original_query': cypher_query,
            'query_analysis': query_analysis,
            'diagnostic_queries': diagnostic_queries,
            'diagnostic_results': diagnostic_results,
            'conclusion': conclusion,
            'timestamp': time.time()
        }

    def _parse_cypher_query_components(self, cypher_query: str) -> Dict[str, Any]:
        """Parse a Cypher query to extract key components for analysis."""
        query_lower = cypher_query.lower()
        
        # Extract node labels
        import re
        node_patterns = re.findall(r':\s*(\w+)', cypher_query)
        relationship_patterns = re.findall(r'-\[:\s*(\w+)\]->', cypher_query)
        
        # Extract WHERE conditions
        where_conditions = []
        if 'where' in query_lower:
            where_part = cypher_query[query_lower.find('where'):]
            # Basic condition extraction (can be enhanced)
            where_conditions = [cond.strip() for cond in where_part.split('AND') if cond.strip()]
        
        # Extract property references
        property_patterns = re.findall(r'\.(\w+)', cypher_query)
        
        return {
            'node_labels': list(set(node_patterns)),
            'relationships': list(set(relationship_patterns)),
            'where_conditions': where_conditions,
            'properties': list(set(property_patterns)),
            'has_where_clause': 'where' in query_lower,
            'has_limit': 'limit' in query_lower
        }

    async def _generate_llm_diagnostic_queries(self, original_query: str, query_analysis: Dict[str, Any], 
                                             approach_name: str, state: AgentState) -> List[Dict[str, Any]]:
        """Generate diagnostic queries using LLM to understand why original query was empty."""
        
        # Build prompt for LLM diagnostic query generation
        diagnostic_prompt = self._build_empty_result_diagnostic_prompt(
            original_query, query_analysis, approach_name, state
        )
        
        # Generate diagnostic queries using LLM
        llm_service = state.get('llm_service')
        if not llm_service:
            logger.error("❌ LLM service not available - cannot generate diagnostic queries")
            raise Exception("LLM service not available for diagnostic query generation")
            # return self._fallback_static_diagnostic_queries(query_analysis)  # Commented out for debugging
        
        try:
            # Use LLM to generate targeted diagnostic queries with Pydantic validation
            diagnostic_data = await self._retry_llm_with_validation(
                llm_service=llm_service,
                initial_prompt=diagnostic_prompt,
                model_class=DiagnosticQueryGeneration,
                max_retries=2,
                operation_name="diagnostic query generation"
            )
            
            # Extract validated diagnostic queries (diagnostic_data is already a dict from .dict() method)
            diagnostic_queries = []
            for query_dict in diagnostic_data['diagnostic_queries']:
                diagnostic_queries.append({
                    'purpose': query_dict['purpose'],
                    'query': query_dict['query']
                })
            
            logger.info(f"🔧 LLM generated {len(diagnostic_queries)} validated diagnostic queries")
            logger.info(f"📋 Strategy: {diagnostic_data['diagnostic_strategy']}")
            return diagnostic_queries
                
        except Exception as e:
            logger.error(f"❌ LLM diagnostic query generation failed: {e}")
            # logger.warning("🔄 Falling back to static diagnostic queries")  # Commented out for debugging
            # return self._fallback_static_diagnostic_queries(query_analysis)  # Commented out for debugging
            raise Exception(f"Diagnostic query generation failed: {e}")

    def _fallback_static_diagnostic_queries(self, query_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fallback static diagnostic queries when LLM generation fails."""
        diagnostic_queries = []
        
        # 1. Check if target node types exist at all
        for node_label in query_analysis['node_labels']:
            diagnostic_queries.append({
                'purpose': f'Check if {node_label} nodes exist in graph',
                'query': f'MATCH (n:{node_label}) RETURN count(n) as total_count, labels(n)[0] as node_type LIMIT 1'
            })
        
        # 2. Sample data from target nodes without restrictions
        if query_analysis['node_labels']:
            main_node = query_analysis['node_labels'][0]
            diagnostic_queries.append({
                'purpose': f'Sample {main_node} nodes without restrictions',
                'query': f'MATCH (n:{main_node}) RETURN n LIMIT 5'
            })
        
        return diagnostic_queries

    def _build_empty_result_diagnostic_prompt(self, original_query: str, query_analysis: Dict[str, Any], 
                                            approach_name: str, state: AgentState) -> str:
        """Build prompt for LLM to generate diagnostic queries for empty results."""
        
        # Extract key information
        user_query = state.get('user_query', '')
        schema = state.get('schema', {})
        
        return f"""You are an expert Neo4j Cypher query debugger for Code Property Graph (CPG) analysis.

**TASK**: Generate diagnostic queries to understand why the original Cypher query returned empty results.

**USER'S ORIGINAL QUESTION**: {user_query}

**RESEARCH APPROACH CONTEXT**: {approach_name}

**FAILED QUERY**:
```cypher
{original_query}
```

**QUERY ANALYSIS**:
- Target Node Types: {query_analysis.get('node_labels', [])}
- Relationships Used: {query_analysis.get('relationships', [])}
- Properties Referenced: {query_analysis.get('properties', [])}
- Has WHERE Clause: {query_analysis.get('has_where_clause', False)}
- Has LIMIT Clause: {query_analysis.get('has_limit', False)}

**CPG SCHEMA** (for reference):
{json.dumps(schema, indent=2)}

**DIAGNOSTIC STRATEGY**:
Generate 3-5 targeted diagnostic queries to systematically investigate why the original query was empty:

1. **Node Existence**: Check if the target node types exist in the graph
2. **Data Availability**: Sample actual data from target nodes without restrictions  
3. **Relationship Connectivity**: Verify if relationships connect the expected node types
4. **Property Analysis**: Check if referenced properties exist and have values
5. **Constraint Analysis**: Test if WHERE conditions are too restrictive

**REQUIREMENTS**:
- Each diagnostic query should have a clear purpose and be executable
- Queries should progressively narrow down the issue
- Start broad (node existence) and get more specific
- Avoid queries that might also return empty results
- Focus on understanding the specific failure mode

**OUTPUT FORMAT** (JSON):
{{
    "diagnostic_queries": [
        {{
            "purpose": "Clear description of what this query checks",
            "query": "MATCH ... RETURN ... LIMIT ..."
        }},
        ...
    ],
    "diagnostic_strategy": "Brief explanation of the overall diagnostic approach"
}}

Generate the diagnostic queries now:"""

    async def _generate_llm_empty_result_conclusion(self, original_query: str, approach_name: str, 
                                                  query_analysis: Dict[str, Any], 
                                                  diagnostic_results: List[Dict[str, Any]], state: AgentState) -> Dict[str, Any]:
        """Generate LLM-based comprehensive conclusion about why the query returned empty results."""
        
        # Build prompt for LLM conclusion generation
        conclusion_prompt = self._build_empty_result_conclusion_prompt(
            original_query, approach_name, query_analysis, diagnostic_results, state
        )
        
        # Generate conclusion using LLM
        llm_service = state.get('llm_service')
        if not llm_service:
            logger.error("❌ LLM service not available - cannot generate conclusion analysis")
            raise Exception("LLM service not available for conclusion generation")
            # return self._fallback_static_conclusion(query_analysis, diagnostic_results)  # Commented out for debugging
        
        try:
            # Use LLM to generate intelligent conclusion with Pydantic validation
            conclusion_data = await self._retry_llm_with_validation(
                llm_service=llm_service,
                initial_prompt=conclusion_prompt,
                model_class=EmptyResultConclusion,
                max_retries=2,
                operation_name="empty result conclusion generation"
            )
            
            # Return validated conclusion data
            logger.info("🧠 LLM generated intelligent empty result conclusion")
            logger.info(f"🎯 Root Cause: {conclusion_data['root_cause']}")
            logger.info(f"🔍 Confidence: {conclusion_data['confidence_level']}")
            return conclusion_data
                
        except Exception as e:
            logger.error(f"❌ LLM conclusion generation failed: {e}")
            # logger.warning("🔄 Falling back to static conclusion analysis")  # Commented out for debugging
            # return self._fallback_static_conclusion(query_analysis, diagnostic_results)  # Commented out for debugging
            raise Exception(f"Conclusion generation failed: {e}")

    def _fallback_static_conclusion(self, query_analysis: Dict[str, Any], 
                                  diagnostic_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Fallback static conclusion analysis when LLM generation fails."""
        
        # Analyze diagnostic results
        nodes_exist = any(result.get('found_data', False) and 'nodes exist' in result.get('purpose', '').lower() 
                         for result in diagnostic_results)
        
        sample_data_available = any(result.get('found_data', False) and 'sample' in result.get('purpose', '').lower() 
                                  for result in diagnostic_results)
        
        findings = []
        recommendations = []
        
        # Generate basic analysis
        if not nodes_exist:
            root_cause = "missing_nodes"
            conclusion = "The query returned empty because the target node types don't exist in the graph."
            recommendations.extend([
                "Verify that the target node labels are correct",
                "Check if the graph has been populated with the expected data"
            ])
        elif not sample_data_available:
            root_cause = "query_too_restrictive"
            conclusion = "The query conditions may be too restrictive for the available data."
            recommendations.extend([
                "Simplify WHERE conditions or remove restrictive filters",
                "Check if property values match expected patterns"
            ])
        else:
            root_cause = "unknown"
            conclusion = "Query returned empty for unclear reasons based on diagnostic analysis."
            recommendations.append("Manual investigation may be needed")
        
        return {
            "conclusion": conclusion,
            "root_cause": root_cause,
            "findings": findings,
            "recommendations": recommendations,
            "diagnostic_summary": f"Analyzed {len(diagnostic_results)} diagnostic queries",
            "analysis_type": "static_fallback"
        }

    def _build_empty_result_conclusion_prompt(self, original_query: str, approach_name: str, 
                                            query_analysis: Dict[str, Any], diagnostic_results: List[Dict[str, Any]], 
                                            state: AgentState) -> str:
        """Build prompt for LLM to generate intelligent conclusions about empty results."""
        
        # Extract key information
        user_query = state.get('user_query', '')
        schema = state.get('schema', {})
        
        # Format diagnostic results for prompt
        diagnostic_summary = []
        for result in diagnostic_results:
            status = "✅ Found data" if result.get('found_data', False) else "❌ No data"
            count = result.get('data_count', 0)
            diagnostic_summary.append(f"- {result.get('purpose', 'Unknown')}: {status} ({count} items)")
        
        return f"""You are an expert Neo4j Cypher query analyst specializing in Code Property Graph (CPG) debugging.

**TASK**: Analyze diagnostic query results to provide an intelligent conclusion about why the original query returned empty results.

**USER'S ORIGINAL QUESTION**: {user_query}

**RESEARCH APPROACH CONTEXT**: {approach_name}

**FAILED QUERY**:
```cypher
{original_query}
```

**QUERY COMPONENTS**:
- Target Node Types: {query_analysis.get('node_labels', [])}
- Relationships Used: {query_analysis.get('relationships', [])}
- Properties Referenced: {query_analysis.get('properties', [])}
- Has WHERE Clause: {query_analysis.get('has_where_clause', False)}

**DIAGNOSTIC QUERY RESULTS**:
{chr(10).join(diagnostic_summary)}

**FULL DIAGNOSTIC DATA**:
{json.dumps(diagnostic_results, indent=2)}

**YOUR ANALYSIS TASK**:
Based on the diagnostic results, provide an intelligent analysis of why the original query failed:

1. **Root Cause Analysis**: Identify the primary reason for empty results
2. **Evidence-Based Reasoning**: Use the diagnostic query results as evidence
3. **Actionable Recommendations**: Provide specific steps to fix the issue
4. **Query Improvement**: Suggest how to modify the original query

**POSSIBLE ROOT CAUSES TO CONSIDER**:
- Target node types don't exist in the graph
- Required relationships are missing or incorrectly specified
- Property filters are too restrictive or reference non-existent properties
- Data exists but query logic has logical errors
- Graph structure doesn't match the query assumptions

**OUTPUT FORMAT** (JSON):
{{
    "conclusion": "Primary conclusion about why the query was empty",
    "root_cause": "specific_category (e.g., missing_nodes, wrong_relationships, restrictive_filters, logical_error)",
    "evidence": ["Key evidence from diagnostic queries that supports this conclusion"],
    "findings": ["Detailed findings from the diagnostic analysis"],
    "recommendations": ["Specific actionable steps to fix the query"],
    "suggested_query_modifications": ["Concrete suggestions for improving the original query"],
    "confidence_level": "high/medium/low",
    "analysis_type": "llm_intelligent"
}}

Analyze the results now:"""

    async def _analyze_execution_results(self, execution_results: List[Dict[str, Any]], 
                                       state: AgentState) -> Dict[str, Any]:
        """Analyze overall execution results and provide insights."""
        total_queries = len(execution_results)
        successful_queries = sum(1 for r in execution_results if r['status'] == 'success')
        syntax_errors = sum(1 for r in execution_results if r.get('syntax_error', False))
        empty_results = sum(1 for r in execution_results if r.get('empty_result', False))
        execution_errors = sum(1 for r in execution_results if r['status'] == 'execution_error')
        
        total_results = sum(len(r.get('data', [])) for r in execution_results if r['status'] == 'success')
        
        # Analyze empty result patterns
        empty_result_analysis = []
        for result in execution_results:
            if result.get('empty_result') and result.get('followup_analysis'):
                analysis = result['followup_analysis']
                empty_result_analysis.append({
                    'query_number': result['query_number'],
                    'approach_name': result['approach_name'],
                    'root_cause': analysis['conclusion']['root_cause'],
                    'recommendations': analysis['conclusion']['recommendations'][:2]  # Top 2
                })
        
        # Overall assessment
        if successful_queries == total_queries:
            overall_status = 'excellent'
            assessment = 'All queries executed successfully with results found.'
        elif successful_queries > 0:
            overall_status = 'partial_success'
            assessment = f'{successful_queries}/{total_queries} queries succeeded. Review failures for optimization.'
        elif syntax_errors > execution_errors:
            overall_status = 'syntax_issues'
            assessment = 'Multiple syntax errors detected. Query generation needs improvement.'
        else:
            overall_status = 'execution_failed'
            assessment = 'Query execution failed. Check graph connectivity and data availability.'
        
        return {
            'total_queries': total_queries,
            'successful_queries': successful_queries,
            'syntax_errors': syntax_errors,
            'empty_results': empty_results,
            'execution_errors': execution_errors,
            'total_results_found': total_results,
            'overall_status': overall_status,
            'assessment': assessment,
            'empty_result_analysis': empty_result_analysis
        }

    def _log_query_execution_result(self, result: Dict[str, Any], query_number: int):
        """Log individual query execution result."""
        status = result['status']
        
        if status == 'success':
            data_count = len(result.get('data', []))
            exec_time = result.get('execution_time', 0)
            logger.info(f"  ✅ Query {query_number}: SUCCESS - {data_count} results ({exec_time}s)")
        elif status == 'syntax_error':
            logger.warning(f"  ⚠️ Query {query_number}: SYNTAX ERROR - {result.get('error', 'Unknown')}")
        elif status == 'empty_result':
            logger.info(f"  🔍 Query {query_number}: EMPTY RESULT - Followup analysis initiated")
        else:
            logger.error(f"  ❌ Query {query_number}: FAILED - {result.get('error', 'Unknown')}")

    def _log_execution_summary(self, execution_results: List[Dict[str, Any]], 
                             execution_analysis: Dict[str, Any], total_results: int):
        """Log comprehensive execution summary."""
        logger.info("")
        logger.info("=" * 120)
        logger.info("⚡ QUERY EXECUTION COMPLETED")
        logger.info("=" * 120)
        
        analysis = execution_analysis
        
        # Count diagnostic queries
        diagnostic_count = 0
        diagnostic_successful = 0
        for result in execution_results:
            if result.get('diagnostic_queries_data'):
                diagnostic_data = result['diagnostic_queries_data']
                diagnostic_count += len(diagnostic_data)
                diagnostic_successful += sum(1 for d in diagnostic_data if d.get('found_data', False))
        
        logger.info(f"📊 EXECUTION STATISTICS:")
        logger.info(f"  • Primary Queries: {analysis['total_queries']}")
        logger.info(f"  • Diagnostic Queries: {diagnostic_count}")
        logger.info(f"  • Total Queries: {analysis['total_queries'] + diagnostic_count}")
        logger.info(f"  • Successful Primary: {analysis['successful_queries']}")
        logger.info(f"  • Successful Diagnostic: {diagnostic_successful}")
        logger.info(f"  • Syntax Errors: {analysis['syntax_errors']}")
        logger.info(f"  • Empty Results: {analysis['empty_results']}")
        logger.info(f"  • Execution Errors: {analysis['execution_errors']}")
        logger.info(f"  • Total Results Found: {total_results}")
        logger.info("")
        logger.info(f"🎯 OVERALL STATUS: {analysis['overall_status'].upper()}")
        logger.info(f"📝 ASSESSMENT: {analysis['assessment']}")
        
        # Log empty result analysis if any
        if analysis.get('empty_result_analysis'):
            logger.info("")
            logger.info("🔍 EMPTY RESULT ANALYSIS:")
            for empty_analysis in analysis['empty_result_analysis']:
                logger.info(f"  • Query {empty_analysis['query_number']} ({empty_analysis['approach_name']})")
                logger.info(f"    Root Cause: {empty_analysis['root_cause']}")
                logger.info(f"    Key Recommendations: {', '.join(empty_analysis['recommendations'])}")
        
        logger.info("=" * 120)
        logger.info("")

    async def _execute_via_cli(self, cypher_query: str, state: AgentState = None) -> Dict[str, Any]:
        """
        Execute a single Cypher query via project-analyzer CLI.
        
        Returns a standardized result format for the Execute step.
        """
        import subprocess
        import json
        
        try:
            # Get Neo4j config from state or use fallback
            neo4j_config = NEO4J_CONFIG  # Default fallback
            if state:
                neo4j_config = state.get("neo4j_config", neo4j_config)
                # Handle metadata nested config
                if not neo4j_config and state.get("metadata", {}).get("neo4j_config"):
                    neo4j_config = state["metadata"]["neo4j_config"]
            
            # Fix Neo4j 5.x syntax issues
            neo4j_version = ""
            if state:
                neo4j_version = state.get("neo4j_version", "")
            fixed_query = self._fix_neo4j_syntax(cypher_query, neo4j_version)
            
            # Use project-analyzer CLI
            cli_command = [
                GENPOD_GRAPH_INDEXER_BIN,
                "--config-file", neo4j_config,
                "query",
                "--cypher", fixed_query,
                "--limit", "100",
                "--output-format", "json"
            ]
            
            # Execute with timeout
            result = subprocess.run(
                cli_command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False
            )
            
            if result.returncode == 0:
                try:
                    response_data = json.loads(result.stdout)
                    
                    # Handle the actual project-analyzer CLI response format
                    if response_data.get("success") is True:
                        # Successful execution - return results in expected format
                        return {
                            "status": "success",
                            "response": response_data.get("results", []),
                            "raw_output": result.stdout,
                            "count": response_data.get("count", 0),
                            "query": response_data.get("query", cypher_query)
                        }
                    elif response_data.get("success") is False:
                        # Query execution failed (syntax error, etc.)
                        return {
                            "status": "error",
                            "response": [],
                            "error": response_data.get("error", "Query execution failed"),
                            "detailed_message": response_data.get("detailed_message", ""),
                            "raw_output": result.stdout,
                            "query": response_data.get("query", cypher_query)
                        }
                    else:
                        # Unexpected format - fallback
                        return {
                            "status": "success",
                            "response": response_data if isinstance(response_data, list) else [response_data],
                            "raw_output": result.stdout
                        }
                        
                except json.JSONDecodeError as e:
                    return {
                        "status": "error",
                        "response": [],
                        "error": f"JSON parse error: {e}",
                        "raw_output": result.stdout
                    }
            else:
                return {
                    "status": "error",
                    "response": [],
                    "error": result.stderr or "CLI execution failed",
                    "returncode": result.returncode
                }
                
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "response": [],
                "error": "Query execution timed out"
            }
        except Exception as e:
            return {
                "status": "error",
                "response": [],
                "error": str(e)
            }

    async def should_continue_after_execution(self, state: AgentState) -> str:
        """
        Conditional router: Decide whether to continue Think → Generate → Execute cycle or synthesize response.
        
        Decision logic:
        - Route back to "generate_query" if there's a syntax error that needs regeneration
        - Continue to "think" if more approaches need to be analyzed
        - Go to "synthesize_response" if all approaches have been processed or sufficient data found
        """
        current_approach_index = state.get('current_approach_index', 0)
        total_approaches = state.get('total_approaches', 0)
        total_results_found = state.get('total_results_found', 0)
        current_iteration = state.get('current_iteration', 1)
        max_iterations = state.get('max_iterations', 5)
        
        # Check for syntax errors that need regeneration
        execution_results = state.get('execution_results', [])
        has_syntax_error_for_regeneration = False
        syntax_error_count = state.get('syntax_error_count', 0)
        MAX_SYNTAX_RETRIES = 3  # Prevent infinite loops
        
        if execution_results:
            latest_result = execution_results[-1]  # Check the most recent execution result
            if (latest_result.get('status') == 'syntax_error' and 
                latest_result.get('needs_regeneration') and
                syntax_error_count < MAX_SYNTAX_RETRIES):
                has_syntax_error_for_regeneration = True
        
        # Check if we have more approaches to process
        has_more_approaches = (current_approach_index + 1) < total_approaches
        
        # Check if we have sufficient results (threshold: at least 10 results across all queries)
        has_sufficient_results = total_results_found >= 10
        
        # Check iteration limits
        within_iteration_limit = current_iteration < max_iterations
        
        logger.info("")
        logger.info("🤔 CYCLING DECISION ANALYSIS:")
        logger.info(f"  📊 Current approach: {current_approach_index + 1}/{total_approaches}")
        logger.info(f"  📈 Total results found: {total_results_found}")
        logger.info(f"  🔄 Current iteration: {current_iteration}/{max_iterations}")
        logger.info(f"  🔧 Syntax error for regeneration: {has_syntax_error_for_regeneration}")
        logger.info(f"  🔄 Syntax error retry count: {syntax_error_count}/{MAX_SYNTAX_RETRIES}")
        logger.info(f"  ✅ More approaches available: {has_more_approaches}")
        logger.info(f"  📋 Sufficient results: {has_sufficient_results}")
        logger.info(f"  ⏰ Within iteration limit: {within_iteration_limit}")
        
        # Decision logic - prioritize syntax error regeneration
        if has_syntax_error_for_regeneration:
            logger.info("🔧 DECISION: Syntax error detected - regenerating query (generate_query)")
            return "generate_query"
        elif has_more_approaches and within_iteration_limit and not has_sufficient_results:
            logger.info("🔄 DECISION: Continue to next approach (think)")
            return "think"
        else:
            if not has_more_approaches:
                logger.info("🏁 DECISION: All approaches processed - synthesizing response")
            elif has_sufficient_results:
                logger.info("🎯 DECISION: Sufficient results found - synthesizing response")
            elif not within_iteration_limit:
                logger.info("⏰ DECISION: Iteration limit reached - synthesizing response")
            else:
                logger.info("🔚 DECISION: Completing workflow - synthesizing response")
            return "synthesize_response"

    def _extract_syntax_error_feedback(self, error_message: str) -> str:
        """Extract meaningful feedback from syntax errors for query regeneration."""
        # Neo4j provides clear error messages, so we just clean and return them
        error_msg = error_message.strip()
        
        # Remove any stdout/stderr prefixes if present
        if "stdout:" in error_msg:
            error_msg = error_msg.split("stdout:")[-1].strip()
        if "stderr:" in error_msg:
            error_msg = error_msg.split("stderr:")[-1].strip()
        
        # Extract the core error message for the LLM
        return error_msg

    def _build_cycle_raw_results(self, execution_results: List[Dict[str, Any]], cycle_number: int) -> List[Dict[str, Any]]:
        """
        Build raw results for each execution cycle for the rethink step.
        
        Stores query, execution details, results, and error information for each query.
        Now includes both primary and diagnostic queries with client-compatible field names.
        """
        import time
        cycle_raw_results = []
        
        for result in execution_results:
            # Primary query result with client-compatible field names
            raw_result = {
                'cycle_number': cycle_number,
                'query_number': result['query_number'],
                'approach_name': result['approach_name'],
                'cypher_query': result['cypher_query'],
                'execution_status': result['status'],
                'execution_time': result.get('execution_time', 0),
                'results_count': len(result.get('data', [])),
                'data': result.get('data', []),
                'timestamp': time.time(),
                
                # Client-compatible field names (for test_query_cpg_rag_mcp_integration.py)
                'query': result['cypher_query'],  # Client expects 'query' field
                'purpose': result['approach_name'],  # Client expects 'purpose' field
                
                # Error and analysis information
                'error': result.get('error'),
                'syntax_error': result.get('syntax_error', False),
                'empty_result': result.get('empty_result', False),
                'followup_analysis': result.get('followup_analysis'),
                
                # For rethink analysis
                'needs_rethinking': result['status'] != 'success',
                'rethink_priority': self._calculate_rethink_priority(result)
            }
            
            cycle_raw_results.append(raw_result)
            
            # FIXED: Include diagnostic queries in raw results
            diagnostic_queries_data = result.get('diagnostic_queries_data', [])
            if diagnostic_queries_data:
                for i, diagnostic in enumerate(diagnostic_queries_data):
                    diagnostic_raw_result = {
                        'cycle_number': cycle_number,
                        'query_number': f"{result['query_number']}-diag-{i+1}",  # Unique identifier
                        'approach_name': f"{result['approach_name']} (Diagnostic)",
                        'cypher_query': diagnostic.get('query', ''),
                        'execution_status': 'success' if diagnostic.get('found_data', False) else 'empty_result',
                        'execution_time': 0,  # Diagnostic timing not tracked separately
                        'results_count': diagnostic.get('data_count', 0),
                        'data': diagnostic.get('sample_data', []),
                        'timestamp': time.time(),
                        
                        # Client-compatible field names
                        'query': diagnostic.get('query', ''),  # Client expects 'query' field
                        'purpose': diagnostic.get('purpose', 'Diagnostic Query'),  # Client expects 'purpose' field
                        
                        # Diagnostic-specific fields
                        'is_diagnostic': True,
                        'diagnostic_purpose': diagnostic.get('purpose', ''),
                        'found_data': diagnostic.get('found_data', False),
                        'parent_query_number': result['query_number'],
                        
                        # For rethink analysis
                        'needs_rethinking': False,  # Diagnostics don't need rethinking
                        'rethink_priority': 'low'
                    }
                    
                    cycle_raw_results.append(diagnostic_raw_result)
            
        return cycle_raw_results

    def _calculate_rethink_priority(self, result: Dict[str, Any]) -> str:
        """Calculate priority for rethinking based on execution result."""
        status = result['status']
        
        if status == 'success':
            return 'low'  # Successful queries have low rethink priority
        elif status == 'syntax_error':
            return 'high'  # Syntax errors need immediate attention
        elif status == 'empty_result':
            return 'medium'  # Empty results may need query refinement
        else:
            return 'high'  # Other execution errors need investigation

    def _rebuild_comprehensive_raw_query_results(self, state: AgentState) -> List[Dict[str, Any]]:
        """
        Rebuild comprehensive raw_query_results from approach_raw_results.
        
        This ensures ALL executed queries (primary + diagnostic, successful + empty) 
        are included in raw_query_results for client consumption.
        """
        import time
        comprehensive_raw_results = []
        
        approach_raw_results = state.get('approach_raw_results', {})
        discovery_research = state.get('discovery_research', {})
        approaches = discovery_research.get('data_collection_approaches', [])
        
        logger.info(f"🔄 Rebuilding comprehensive raw_query_results from {len(approach_raw_results)} approaches")
        
        for approach_idx in sorted(approach_raw_results.keys()):
            approach_tuples = approach_raw_results[approach_idx]
            cycle_number = approach_idx + 1  # Cycles are 1-based
            
            # Get approach name
            approach_name = f'Approach {cycle_number}'
            if approach_idx < len(approaches):
                approach_name = approaches[approach_idx].get('approach_name', approach_name)
            
            for query_idx, (query, results) in enumerate(approach_tuples):
                # Build primary query result
                primary_result = {
                    'cycle_number': cycle_number,
                    'query_number': query_idx + 1,
                    'approach_name': approach_name,
                    'cypher_query': query,
                    'execution_status': 'success' if results and len(results) > 0 else 'empty_result',
                    'execution_time': 0,  # Not tracked in approach_raw_results
                    'results_count': len(results) if isinstance(results, list) else 0,
                    'data': results if isinstance(results, list) else [],
                    'timestamp': time.time(),
                    
                    # Client-compatible field names
                    'query': query,
                    'purpose': approach_name,
                    
                    # Status fields
                    'error': None,
                    'syntax_error': False,
                    'empty_result': not (results and len(results) > 0),
                    'followup_analysis': None,
                    'is_diagnostic': False,
                    
                    # For rethink analysis
                    'needs_rethinking': not (results and len(results) > 0),
                    'rethink_priority': 'medium' if not (results and len(results) > 0) else 'low'
                }
                
                comprehensive_raw_results.append(primary_result)
                
                # TODO: Add diagnostic queries if they were stored in the tuples
                # Currently diagnostic queries are not stored in approach_raw_results tuples
                # They would need to be extracted from the execution_results if available
        
        logger.info(f"✅ Rebuilt {len(comprehensive_raw_results)} comprehensive raw query results")
        return comprehensive_raw_results

    def _log_cycle_raw_results(self, cycle_raw_results: List[Dict[str, Any]], cycle_number: int):
        """Log raw results from execution cycle for visibility."""
        logger.info("")
        logger.info("=" * 120)
        logger.info(f"🗃️ CYCLE {cycle_number} RAW RESULTS STORED")
        logger.info("=" * 120)
        
        total_results_count = sum(r['results_count'] for r in cycle_raw_results)
        successful_queries = sum(1 for r in cycle_raw_results if r['execution_status'] == 'success')
        failed_queries = len(cycle_raw_results) - successful_queries
        
        # Count diagnostic queries
        diagnostic_count = 0
        diagnostic_successful = 0
        diagnostic_results = 0
        for r in cycle_raw_results:
            if r.get('followup_analysis') and r['followup_analysis'].get('diagnostic_results'):
                diagnostic_data = r['followup_analysis']['diagnostic_results']
                diagnostic_count += len(diagnostic_data)
                for diag in diagnostic_data:
                    if diag.get('found_data', False):
                        diagnostic_successful += 1
                        diagnostic_results += diag.get('data_count', 0)
        
        logger.info(f"📊 CYCLE SUMMARY:")
        logger.info(f"  • Primary Queries: {len(cycle_raw_results)}")
        logger.info(f"  • Diagnostic Queries: {diagnostic_count}")
        logger.info(f"  • Total Queries: {len(cycle_raw_results) + diagnostic_count}")
        logger.info(f"  • Successful Primary: {successful_queries}")
        logger.info(f"  • Successful Diagnostic: {diagnostic_successful}")
        logger.info(f"  • Failed Primary: {failed_queries}")
        logger.info(f"  • Total Data Items: {total_results_count + diagnostic_results}")
        
        logger.info("")
        logger.info("📋 QUERY DETAILS:")
        for raw_result in cycle_raw_results:
            status_emoji = "✅" if raw_result['execution_status'] == 'success' else "❌"
            rethink_emoji = "🔄" if raw_result['needs_rethinking'] else "📌"
            
            logger.info(f"  {status_emoji} Query {raw_result['query_number']}: {raw_result['approach_name']}")
            logger.info(f"    📋 Status: {raw_result['execution_status']}")
            logger.info(f"    📈 Results: {raw_result['results_count']} items")
            logger.info(f"    ⏱️ Time: {raw_result['execution_time']}s")
            logger.info(f"    {rethink_emoji} Rethink Priority: {raw_result['rethink_priority']}")
            logger.info(f"    🎯 Query: {raw_result['cypher_query']}")
            
            # Show actual raw results data
            if raw_result['data'] and raw_result['execution_status'] == 'success':
                logger.info(f"    📊 RAW RESULTS DATA:")
                for i, data_item in enumerate(raw_result['data'][:5], 1):  # Show first 5 items
                    logger.info(f"      {i}. {data_item}")
                if len(raw_result['data']) > 5:
                    logger.info(f"      ... and {len(raw_result['data']) - 5} more items")
            
            if raw_result.get('error'):
                logger.info(f"    ⚠️ Error: {raw_result.get('error', '')[:100]}...")
            
            if raw_result['followup_analysis']:
                root_cause = raw_result['followup_analysis']['conclusion']['root_cause']
                logger.info(f"    🔍 Root Cause: {root_cause}")
                # Show diagnostic queries that were executed
                diagnostic_results = raw_result['followup_analysis'].get('diagnostic_results', [])
                if diagnostic_results:
                    logger.info(f"    🔧 DIAGNOSTIC QUERIES EXECUTED:")
                    for diag in diagnostic_results[:3]:  # Show first 3
                        logger.info(f"      - {diag['purpose']}: {'✅' if diag.get('found_data') else '❌'}")
                        if diag.get('sample_data'):
                            logger.info(f"        Sample: {diag['sample_data'][:2]}")  # Show first 2 samples
        
        logger.info("")
        logger.info(f"🎯 RAW RESULTS AVAILABLE FOR RETHINK ANALYSIS")
        logger.info("=" * 120)
        logger.info("")

    async def _fix_query_syntax(self, original_query: str, error_message: str, 
                               approach_name: str, state: AgentState,
                               previous_attempts: List[Dict] = None) -> str:
        """
        Ad-hoc query fixer: Fix syntax errors in a single query immediately.
        
        This is called right when a query fails with a syntax error.
        Returns the corrected query or None if unable to fix.
        """
        logger.info(f"🔧 Attempting to fix query syntax for: {approach_name}")
        logger.info(f"🔍 Error message to be used in correction prompt: {error_message}")
        
        llm_service = state.get('llm_service')
        if not llm_service:
            logger.warning("⚠️ No LLM service available for query correction")
            return None
        
        # Get schema context
        schema = state.get('schema', {})
        user_query = state.get('user_query', '')
        
        # Build comprehensive schema context
        schema_context = "Unknown"
        if schema and schema.get('nodes'):
            schema_parts = []
            
            # Add node types with their attributes
            nodes_info = []
            for node_type, attributes in schema.get('nodes', {}).items():
                if attributes:
                    attr_list = ', '.join(attributes) if isinstance(attributes, list) else str(attributes)
                    nodes_info.append(f"  • {node_type}: [{attr_list}]")
                else:
                    nodes_info.append(f"  • {node_type}: [no attributes listed]")
            
            if nodes_info:
                schema_parts.append(f"Node Types & Attributes:\n" + '\n'.join(nodes_info))
            
            # Add relationships
            relationships = schema.get('relationships', {})
            if relationships:
                rel_list = list(relationships.keys()) if isinstance(relationships, dict) else list(relationships)
                schema_parts.append(f"Available Relationships: {', '.join(rel_list)}")
            
            schema_context = '\n\n'.join(schema_parts) if schema_parts else "Schema information incomplete"
        
        # Build correction history context
        history_context = ""
        if previous_attempts:
            history_context = "\n\n**Previous Failed Corrections:**\n"
            for i, attempt in enumerate(previous_attempts[-2:], 1):  # Show last 2 attempts
                history_context += f"{i}. Original: {attempt['original']}\n"
                history_context += f"   Corrected: {attempt['corrected']}\n"
                history_context += f"   Error: {attempt['error']}\n\n"
            history_context += "**IMPORTANT**: Avoid making the same corrections that already failed above.\n"
            
            # Log the correction history context for debugging
            logger.info(f"🔍 Correction history context to be added to prompt:")
            logger.info(f"{history_context}")
        else:
            logger.info(f"🔍 No previous correction attempts - first attempt")
        
        correction_prompt = f"""You are a Neo4j Cypher expert. Your task is to fix a specific syntax error in a Cypher query while preserving its complete logic and structure.

**CRITICAL INSTRUCTIONS:**
1. **ANALYZE THE ERROR LOCATION**: The error message shows the exact column/offset of the syntax issue - fix ONLY that specific location
2. **PRESERVE ALL QUERY LOGIC**: Keep ALL MATCH clauses, WITH clauses, WHERE conditions, and RETURN statements intact
3. **NO OVER-SIMPLIFICATION**: Do not remove complex parts of the query to "fix" it - maintain full query structure
4. **LEARN FROM HISTORY**: If previous corrections failed by over-simplifying, try a different targeted approach{history_context}

**QUERY TO FIX:**
```cypher
{original_query}
```

**SYNTAX ERROR:**
{error_message}

**TASK CONTEXT:**
- User Question: {user_query}
- Analysis Approach: {approach_name}

**COMMON FIXES FOR TYPE MISMATCH ERRORS:**
- Variable scoping in ANY/ALL predicates (variables inside predicates aren't available outside)
- Function return type mismatches (check function usage)
- Path vs property access issues
- Missing WITH clauses for variable passing between MATCH statements

**COMMON FIXES FOR STRUCTURAL ERRORS:**
- MATCH patterns must conclude with RETURN, WHERE, or other valid clause
- UNWIND syntax with proper variable handling
- Relationship pattern syntax [:RELATIONSHIP_TYPE]
- WHERE clause syntax and variable references

**OUTPUT REQUIREMENT:**
Return the complete fixed Cypher query as a single statement - no explanations, no markdown formatting, no additional text.

**Available Schema Reference:**
{schema_context}

Corrected Query:"""
        
        try:
            # Disable cache for corrections to allow different approaches
            result = await llm_service.generate_response(correction_prompt, temperature=0.3, use_cache=False)
            if result and not result.error:
                corrected_query = result.content.strip()
                
                # Clean up the response (remove code blocks, extra text)
                if corrected_query.startswith('```'):
                    lines = corrected_query.split('\n')
                    corrected_query = '\n'.join(lines[1:-1] if len(lines) > 2 else lines[1:])
                
                # Take only the first query if multiple are present
                corrected_query = corrected_query.split('\n')[0].strip()
                
                # Basic validation
                if (corrected_query and 
                    any(keyword in corrected_query.upper() for keyword in ['MATCH', 'RETURN', 'CREATE', 'MERGE']) and
                    len(corrected_query) > 10):
                    logger.info(f"✅ Generated corrected query: {corrected_query[:80]}...")
                    return corrected_query
                else:
                    logger.warning("⚠️ Generated correction doesn't look valid")
                    return None
            else:
                logger.warning(f"⚠️ LLM failed to generate correction: {result.error if result else 'No result'}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error in query syntax fix: {e}")
            return None

    # NEW: Parallel execution nodes using LangGraph Send pattern

    async def route_parallel_execution(self, state: AgentState) -> str:
        """
        Router: Determine if we should continue with next batch or synthesize.
        """
        should_continue = state.get('should_continue', False)
        current_batch_index = state.get('current_batch_index', 0)
        total_batches = state.get('total_batches', 1)
        
        if should_continue and current_batch_index < total_batches:
            logger.info(f"🔄 Continuing to batch {current_batch_index + 1}/{total_batches}")
            return "create_approach_batch"
        else:
            logger.info("✅ All batches completed, proceeding to synthesis")
            return "synthesize_response"
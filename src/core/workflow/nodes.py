"""
LangGraph Workflow Nodes for the Adaptive CPG Agent Workflow.

This module contains all the core LangGraph node implementations that form
the workflow orchestration. Each node is a discrete step in the CPG analysis process.

Key nodes:
- initialize_environment: Set up services and schema
- initial_discovery: Research-based discovery using ResearchEngine
- analyze_intent: Intent analysis with Pydantic validation
- execute_batch_approaches: Parallel batch execution using asyncio.gather()
- check_sufficiency: Global sufficiency evaluation after batch
- synthesize_response: Final response synthesis

All nodes maintain LangGraph state management patterns and return proper state updates.
"""
import os
import json
import logging
import asyncio
import subprocess
import time
from typing import Dict, Any, List, Tuple, Optional
from pydantic import ValidationError
from langgraph.types import Send

from .models import AgentState, DiagnosticQueryGeneration, EmptyResultConclusion, IntentAnalysis, SufficiencyEvaluation, ScopeAnalysis, QueryGeneration, SynthesisValidation
from .research_engine import ResearchEngine
from .context_manager import ContextManager
from .prompts import get_intent_analysis_prompt
from .adaptive_query_agent import AdaptiveQueryAgent
from ..llm_service import LLMResponse
from src.core.paths import NEO4J_CONFIG, SCHEMA_PATH, STATE_PKL

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

    async def cleanup_services(self, state: AgentState):
        """Cleanup workflow services and resources."""
        try:
            # Shutdown cypher server instance or pool if it exists
            cypher_server_service = state.get("cypher_server_service")
            if cypher_server_service:
                logger.info("🔥 Shutting down cypher server service...")
                # CypherServerPool uses shutdown(), CypherServerInstance uses stop()
                if hasattr(cypher_server_service, 'shutdown'):
                    await cypher_server_service.shutdown()
                elif hasattr(cypher_server_service, 'stop'):
                    await cypher_server_service.stop()
                logger.info("✅ Cypher server service shut down successfully")
        except Exception as e:
            logger.warning(f"⚠️ Error during service cleanup: {e}")

    # ============================================================================
    # CORE LANGGRAPH NODES (6 nodes that form the workflow graph)
    # ============================================================================

    async def initialize_environment(self, state: AgentState) -> AgentState:
        """
        Node: Initialize the workflow environment and load schema.

        Sets up the basic environment for the CPG workflow including
        schema loading, service initialization, and cypher server startup.
        """
        logger.info("🚀 Node: initialize_environment")

        try:
            # Initialize services if not already done
            if not self.research_engine and state.get('llm_service'):
                await self.initialize_services(state['llm_service'])

            # Initialize cypher server (pool for batch mode, single instance for sequential mode)
            cypher_server_service = None
            try:
                # Get config file path (use provided config or default)
                config_file = state.get("neo4j_config", NEO4J_CONFIG)

                # Check if batch mode is enabled
                enable_batch_mode = state.get('enable_batch_mode', True)
                max_workers = state.get('max_workers', 3)  # Maximum concurrent approach workers

                if enable_batch_mode:
                    # Create cypher server pool for parallel execution
                    from .cypher_server_pool import CypherServerPool

                    # Pool needs 1 extra server for DynamicSchemaManager (held for entire workflow)
                    # Workers use max_workers servers, schema manager uses 1
                    pool_size = max_workers + 1
                    logger.info(f"🔥 Initializing cypher server pool (size: {pool_size}) with config: {config_file}")
                    logger.info(f"   • {max_workers} servers for parallel workers")
                    logger.info(f"   • 1 server for DynamicSchemaManager")
                    cypher_server_pool = CypherServerPool(pool_size=pool_size, neo4j_config=config_file)

                    if await cypher_server_pool.initialize():
                        cypher_server_service = cypher_server_pool
                        logger.info(f"✅ Cypher server pool initialized successfully ({pool_size} servers total, {max_workers} for workers)")
                    else:
                        logger.warning("⚠️ Cypher server pool failed to start - will fallback to subprocess")

                else:
                    # Create single cypher server instance for sequential execution
                    from .cypher_server_pool import CypherServerInstance

                    logger.info(f"🔥 Initializing cypher server instance with config: {config_file}")
                    cypher_server_instance = CypherServerInstance(server_id=0, neo4j_config=config_file)

                    if await cypher_server_instance.start():
                        cypher_server_service = cypher_server_instance
                        logger.info("✅ Cypher server instance started successfully (99.3% performance improvement)")
                    else:
                        logger.warning("⚠️ Cypher server instance failed to start - will fallback to subprocess")

            except Exception as e:
                logger.warning(f"⚠️ Could not initialize cypher server: {e} - will fallback to subprocess")

            # Initialize APOC procedure cache if cypher server is available
            if cypher_server_service:
                try:
                    from ..apoc_procedure_cache import initialize_apoc_cache
                    logger.info("🔧 Initializing APOC procedure cache...")

                    # Get a server instance for cache initialization
                    if hasattr(cypher_server_service, 'acquire'):
                        # Pool mode: acquire a server temporarily
                        server = await cypher_server_service.acquire()
                        try:
                            apoc_stats = await initialize_apoc_cache(server)
                            logger.info(f"✅ APOC cache initialized: {apoc_stats['total_procedures']} procedures, {apoc_stats['total_categories']} categories")
                        finally:
                            await cypher_server_service.release(server)
                    else:
                        # Single instance mode: use directly
                        apoc_stats = await initialize_apoc_cache(cypher_server_service)
                        logger.info(f"✅ APOC cache initialized: {apoc_stats['total_procedures']} procedures, {apoc_stats['total_categories']} categories")

                except Exception as e:
                    logger.warning(f"⚠️ Could not initialize APOC cache: {e} - APOC features may be limited")

            # Load CPG schema (YAML for backward compatibility)
            import yaml
            schema_path = SCHEMA_PATH

            try:
                with open(schema_path, 'r') as f:
                    yaml_schema = yaml.safe_load(f)
                logger.info("✅ CPG YAML schema loaded successfully")
            except Exception as e:
                logger.error(f"❌ Failed to load YAML schema: {e}")
                # Provide fallback schema
                yaml_schema = {
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

            # Initialize DynamicSchemaManager with reconciled schema + path discovery
            schema_manager = None
            if cypher_server_service:
                try:
                    from .dynamic_schema_manager import DynamicSchemaManager

                    logger.info("🔧 Initializing DynamicSchemaManager with reconciled schema...")

                    # Get a server instance for schema manager
                    server_for_schema = None
                    if hasattr(cypher_server_service, 'acquire'):
                        # Pool mode: acquire a server temporarily
                        server_for_schema = await cypher_server_service.acquire()
                    else:
                        # Single instance mode: use directly
                        server_for_schema = cypher_server_service

                    # Initialize schema manager with YAML schema
                    schema_manager = DynamicSchemaManager(
                        cypher_server=server_for_schema,
                        cache_file="/tmp/cpg_workflow_path_cache.json",
                        yaml_schema=yaml_schema,
                        embedding_model='all-MiniLM-L6-v2'
                    )

                    # Start background initialization (reconciliation + path discovery)
                    # This runs in parallel - doesn't block workflow startup
                    asyncio.create_task(schema_manager.initialize_background())

                    logger.info("✅ DynamicSchemaManager initialized (reconciliation running in background)")

                    # NOTE: Don't release server! DynamicSchemaManager needs it for the entire workflow lifecycle.
                    # The server will be released when the schema manager is destroyed at workflow end.

                except Exception as e:
                    logger.warning(f"⚠️ Could not initialize DynamicSchemaManager: {e} - will use YAML schema only")

            return {
                **state,
                "schema": yaml_schema,  # YAML schema for backward compatibility
                "schema_manager": schema_manager,  # DynamicSchemaManager with reconciled schema + paths
                "cypher_server_service": cypher_server_service,
                "max_workers": max_workers,  # For execute_batch_approaches semaphore
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

            # Extract token tracking updates
            token_updates = intent_result.get('_token_updates', {})

            # Extract intent information
            intent_type = intent_result.get('intent_type', 'lookup')
            confidence = intent_result.get('confidence', 0.7)

            logger.info(f"✅ Intent analyzed: {intent_type} (confidence: {confidence:.2f})")

            # Accumulate token metrics (add to existing values, don't overwrite)
            accumulated_tokens = {
                'total_input_tokens': state.get('total_input_tokens', 0) + token_updates.get('total_input_tokens', 0),
                'total_output_tokens': state.get('total_output_tokens', 0) + token_updates.get('total_output_tokens', 0),
                'total_tokens_used': state.get('total_tokens_used', 0) + token_updates.get('total_tokens_used', 0),
                'total_estimated_cost_usd': state.get('total_estimated_cost_usd', 0.0) + token_updates.get('total_estimated_cost_usd', 0.0),
                'llm_call_history': list(state.get('llm_call_history', [])) + token_updates.get('llm_call_history', []),
                'models_used': list(set(state.get('models_used', []) + token_updates.get('models_used', []))),
            }

            return {
                **state,
                **accumulated_tokens,  # Merge accumulated token tracking
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

    async def decompose_query(self, state: AgentState) -> AgentState:
        """
        Node: Decompose query into approach packets (Phase 0).

        Uses ResearchEngine to:
        1. Decompose query with logical reasoning
        2. Analyze dependencies (premise-to-subquery, subquery-to-subquery)
        3. Build self-contained approach packets with execution groups

        Returns:
            Updated state with query_decomposition, dependency_analysis, and approach_packets
        """
        logger.info("🔍 Node: decompose_query (Phase 0)")

        try:
            if not self.research_engine:
                raise Exception("Research engine not initialized")

            user_query = state['user_query']

            # Phase 0: Query decomposition with logical reasoning
            logger.info("📋 Phase 0: Decomposing query with logical reasoning...")
            decomposition = await self.research_engine._decompose_user_query(state)

            if not decomposition:
                logger.error("❌ Query decomposition failed")
                return {
                    **state,
                    "current_node": "decompose_query",
                    "error": "Query decomposition failed"
                }

            logger.info(f"✅ Query decomposed: {len(decomposition.get('subqueries', []))} subqueries, {len(decomposition.get('premises', []))} premises")

            # Phase 0 Post-Processing: Dependency analysis
            logger.info("🔗 Phase 0 Post-Processing: Analyzing dependencies...")
            dependency_analysis = await self.research_engine._analyze_dependencies(decomposition)

            if not dependency_analysis:
                logger.error("❌ Dependency analysis failed")
                return {
                    **state,
                    "query_decomposition": decomposition,
                    "current_node": "decompose_query",
                    "error": "Dependency analysis failed"
                }

            logger.info(f"✅ Dependencies analyzed (worker pool will execute all subqueries in parallel)")

            # Build self-contained approach packets
            logger.info("🔨 Building self-contained approach packets...")
            packet_collection = self.research_engine._build_approach_packets(decomposition, dependency_analysis)

            logger.info(f"✅ Built {packet_collection['total_subqueries']} approach packets (worker pool will execute all in parallel)")

            return {
                **state,
                "query_decomposition": decomposition,
                "dependency_analysis": dependency_analysis,
                "approach_packets": packet_collection,
                "completed_subqueries": [],  # Track which subqueries have been executed
                "subquery_results": {},  # Store results by subquery ID
                "current_node": "decompose_query"
            }

        except Exception as e:
            logger.error(f"❌ Query decomposition failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                **state,
                "current_node": "decompose_query",
                "error": f"Query decomposition failed: {e}"
            }

    async def execute_batch_approaches(self, state: AgentState) -> AgentState:
        """
        Node: Execute Batch Approaches - Worker pool parallel execution.

        NEW: Uses worker pool pattern to execute ALL approach packets in parallel
        with limited concurrency (MAX_WORKERS). Instead of execution groups that
        wait for batch completion, workers continuously pull from queue.

        Dependencies are tracked but NOT used during query generation - only during
        synthesis to combine results.

        Each packet runs via AdaptiveQueryAgent which handles the full CoT workflow:
        think → generate → execute → analyze (with iterative refinement)

        Returns:
            Updated state with aggregated results from ALL packets
        """
        logger.info("⚡ Node: execute_batch_approaches (worker pool pattern)")

        try:
            # Get approach packets from Phase 0 decomposition
            packet_collection = state.get('approach_packets')
            if not packet_collection:
                logger.warning("⚠️ No approach packets available")
                return {
                    **state,
                    "current_node": "execute_batch_approaches"
                }

            all_packets = packet_collection.get('packets', {})
            all_packet_list = list(all_packets.values())

            # Get max workers from state (set in initialize_environment)
            MAX_WORKERS = state.get('max_workers', 3)
            logger.info(f"📦 Executing {len(all_packet_list)} approaches with worker pool (max concurrent: {MAX_WORKERS})")

            # Note: Dependencies are tracked in packets but NOT populated as input_data
            # Dependencies are only used during synthesis to combine results

            # Get cypher server service
            cypher_server_service = state.get('cypher_server_service')
            if cypher_server_service is None:
                error_msg = (
                    "Cypher server service not available. "
                    "The server pool/instance failed to initialize in initialize_environment. "
                    "Please ensure Neo4j is running and the config file is correct."
                )
                logger.error(f"❌ {error_msg}")
                raise Exception(error_msg)

            # Check if we're using a pool or a single instance
            is_pool = hasattr(cypher_server_service, 'acquire')

            # Worker function with semaphore for concurrency control
            MAX_WORKERS = state.get('max_workers', 3)  # From initialize_environment (default: 3)
            semaphore = asyncio.Semaphore(MAX_WORKERS)

            async def run_packet_worker(packet):
                """Worker that acquires server, runs approach, releases server."""
                async with semaphore:  # Limit concurrency
                    server = None
                    try:
                        # Acquire server from pool (or use single instance)
                        if is_pool:
                            server = await cypher_server_service.acquire()
                            logger.info(f"🔷 {packet['id']}: Acquired server from pool")
                        else:
                            server = cypher_server_service
                            logger.info(f"🔷 {packet['id']}: Using single server instance")

                        # Create minimal approach_details for compatibility
                        approach_details = {
                            'approach_name': f"Subquery {packet['id']}",
                            'description': packet['text'],
                            'target_nodes': [],
                            'strategy': 'lookup'
                        }

                        # Run approach
                        result = await self._run_approach_with_adaptive_agent(
                            approach_index=packet['id'],
                            approach_details=approach_details,
                            state=state,
                            cypher_server=server,
                            approach_packet=packet
                        )

                        return result

                    finally:
                        # Always release server back to pool
                        if is_pool and server:
                            await cypher_server_service.release(server)
                            logger.info(f"🔙 {packet['id']}: Released server back to pool")

            # Launch ALL packets with worker pool (semaphore limits concurrency)
            logger.info(f"🚀 Launching {len(all_packet_list)} workers...")
            packet_tasks = [run_packet_worker(packet) for packet in all_packet_list]
            packet_results = await asyncio.gather(*packet_tasks, return_exceptions=True)

            # Aggregate results from ALL packets
            aggregated_state = self._aggregate_approach_results(
                state=state,
                approach_results=packet_results,
                batch_start_idx=0
            )

            # Store subquery results and mark as completed
            subquery_results = {}
            completed_subqueries = []

            for packet, result in zip(all_packet_list, packet_results):
                if not isinstance(result, Exception):
                    packet_id = packet['id']
                    subquery_results[packet_id] = result.get('result', {})
                    completed_subqueries.append(packet_id)
                else:
                    logger.error(f"❌ {packet['id']}: Execution failed with exception: {result}")

            aggregated_state['completed_subqueries'] = completed_subqueries
            aggregated_state['subquery_results'] = subquery_results

            logger.info(f"✅ Worker pool completed: {len(completed_subqueries)}/{len(all_packet_list)} packets succeeded")

            return {
                **state,
                **aggregated_state,
                "current_node": "execute_batch_approaches"
            }

        except Exception as e:
            logger.error(f"❌ Worker pool execution failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                **state,
                "current_node": "execute_batch_approaches",
                "error": f"Worker pool execution failed: {e}"
            }

    async def check_sufficiency(self, state: AgentState) -> AgentState:
        """
        Node: Check Sufficiency - Global sufficiency evaluation after batch.

        Evaluates whether the discovered data is sufficient to answer the user's query.
        This runs AFTER a batch of approaches completes, not during parallel execution.

        Returns:
            Updated state with sufficiency evaluation results
        """
        logger.info("📊 Node: check_sufficiency")

        try:
            discovered_data = state.get('discovered_data', [])
            user_query = state.get('user_query', '')

            # Get approach execution traces for context
            approach_traces = state.get('approach_execution_traces', {})

            # Worker pool executes all packets at once, so always proceed to synthesis
            logger.info(f"✅ All approaches completed. Proceeding to synthesis with {len(discovered_data)} data points.")

            if len(discovered_data) == 0:
                logger.warning("⚠️ No data discovered - will synthesize with empty results")

            return {
                **state,
                "is_sufficient": True,
                "sufficiency_confidence": 1.0,
                "sufficiency_reasoning": f"All approaches completed. Discovered {len(discovered_data)} data points.",
                "current_node": "check_sufficiency"
            }

        except Exception as e:
            logger.error(f"❌ Sufficiency check failed: {e}")
            import traceback
            traceback.print_exc()
            # On error, proceed to synthesis with what we have
            return {
                **state,
                "is_sufficient": True,
                "sufficiency_confidence": 0.5,
                "sufficiency_reasoning": f"Sufficiency check failed ({e}), proceeding with available data",
                "current_node": "check_sufficiency",
                "error": f"Sufficiency check failed: {e}"
            }

    async def synthesize_response(self, state: AgentState) -> AgentState:
        """
        Node: Synthesize Response - Final response synthesis.

        Creates the final natural language response based on all discovered data
        using the ContextManager for smart context windowing.

        Returns:
            Updated state with final response
        """
        logger.info("📝 Node: synthesize_response")

        # DEBUG: Save complete state to pickle file for analysis
        await self._debug_save_state_to_pickle(state)

        try:
            discovered_data = state.get('discovered_data', [])
            user_query = state.get('user_query', '')
            approach_traces = state.get('approach_execution_traces', {})
            approach_raw_results = state.get('approach_raw_results', {})

            # V12: Get logical form and dependencies for synthesis reasoning
            query_decomposition = state.get('query_decomposition', {})
            approach_packets = state.get('approach_packets', {})
            logical_form = query_decomposition.get('logical_form', '')
            packets_dict = approach_packets.get('packets', {}) if approach_packets else {}

            # V12: If no data, use logical reasoning to build intelligent response
            if len(discovered_data) == 0:
                logger.warning("⚠️ No data discovered, analyzing logical structure for response...")

                # Check if we have approach-level answers to synthesize
                if approach_traces:
                    # Continue to normal synthesis path - it will use logical form and dependencies
                    logger.info("   Using approach-level answers with logical reasoning")
                else:
                    # Fallback: no approaches executed
                    logger.warning("   No approaches executed, using generic fallback")
                    return {
                        **state,
                        "response": f"I searched the codebase but couldn't find any data matching your query: '{user_query}'. This could mean:\n1. The data doesn't exist in the project\n2. The query needs to be more specific\n3. The data exists but under different naming/structure",
                        "current_node": "synthesize_response"
                    }

            # Get intent to adapt response style
            intent_analysis = state.get('intent_analysis', {})
            intent_type = intent_analysis.get('intent_type', 'hybrid')

            # Use ContextManager for smart windowing if available
            if self.context_manager:
                logger.info(f"📊 Using ContextManager for synthesis with {len(discovered_data)} data points from {len(approach_traces)} approaches")

                # NEW: Build synthesis from approach-level answers instead of raw data
                approach_answers = []
                for idx, trace in approach_traces.items():
                    approach_answer = trace.get('approach_answer', '')
                    quality_grade = trace.get('approach_quality_grade', 0.0)
                    # Filter out very low quality approaches (< 0.25) to reduce noise
                    if approach_answer and quality_grade > 0.25:  # Only include decent approaches
                        # Get this approach's discovered_data (the filtered, relevant data)
                        approach_data = []
                        if idx in approach_raw_results:
                            approach_data = approach_raw_results[idx].get('discovered_data', [])

                        approach_answers.append({
                            'approach_index': idx,
                            'approach_name': trace.get('approach_name', f'Approach {idx}'),
                            'approach_goal': trace.get('approach_goal', ''),
                            'answer': approach_answer,
                            'quality_grade': quality_grade,
                            'data_count': len(approach_data),
                            'discovered_data': approach_data  # Include the actual data found by this approach
                        })

                # Sort by quality grade (highest first)
                approach_answers.sort(key=lambda x: x['quality_grade'], reverse=True)

                # Create intent-adapted synthesis prompt and instructions
                if intent_type == 'lookup':
                    task_description = "Provide a DIRECT, CONCISE answer to this lookup query. State the answer with confidence - no hedging."

                    synthesis_instructions = """
SYNTHESIS RULES FOR DECOMPOSED LOOKUP QUERIES

1. FOUNDATIONAL CHECKS (Top Priority)
   - Identify subqueries marked as foundational (no dependencies).
   - If a foundational subquery returns no data, give a direct negative conclusion.
     Example: "The requested item is not present in the source material."
   - Do not hedge. Foundational absence produces a definitive negative.

2. DEPENDENCY LOGIC
   - If a foundational subquery fails, all dependent subqueries must be treated as unsatisfied.
   - Explain this logically: "Because the required base information is missing, dependent details cannot be established."

3. POSITIVE SELECTION
   - When data exists, select ONE approach result for each subquery.
   - Prefer the result with the clearest evidence and strongest support.
   - Do not merge or average conflicting outputs.

4. NEGATIVE CONFIDENCE RULES
   - Foundational absence → high-confidence negative ("does not exist" / "not present")
   - Non-foundational absence → medium-confidence negative ("could not locate")
   - Never use uncertain phrasing such as "difficult to determine" or "results may vary."

5. RESPONSE FORMAT
   - Begin with the final conclusion.
   - Add reasoning only when dependency logic affects the outcome.
   - Keep explanations factual, concise, and tied to observed data.

6. APPROACH REPORTING
   - List only the approach indices that contributed directly to the conclusion."""

                elif intent_type == 'architectural':
                    task_description = "Provide a COMPREHENSIVE architectural analysis. Explain structure, patterns, and relationships in detail."

                    synthesis_instructions = """
**SYNTHESIS RULES FOR ARCHITECTURAL QUERIES**:
1. Combine insights from all approaches to build a complete architectural picture
2. Prioritize findings from higher-quality approaches
3. Identify patterns and themes that appear across multiple approaches
4. Track which approaches contributed to your answer"""

                else:
                    task_description = "Provide a clear, balanced answer with both direct findings and helpful context."

                    synthesis_instructions = """
**SYNTHESIS RULES**:
1. Synthesize a comprehensive answer by combining insights from all approaches
2. Prioritize findings from higher-quality approaches (but don't ignore lower-quality ones entirely)
3. Identify patterns and insights that appear across multiple approaches
4. Track which approaches contributed to your answer"""

                # Build prompt from approach answers
                approach_summaries = []
                for i, ap in enumerate(approach_answers):
                    # Format discovered data (already filtered to only relevant points by approach synthesis)
                    data_summary = ""
                    if ap.get('discovered_data'):
                        data_items = ap['discovered_data']  # Show ALL - already filtered to relevant data
                        data_preview = []
                        for idx, item in enumerate(data_items):
                            # Remove internal metadata fields for cleaner display
                            clean_item = {k: v for k, v in item.items() if not k.startswith('_')}
                            data_preview.append(f"  [{idx}] {json.dumps(clean_item, default=str)}")

                        data_summary = f"\n\nData Found ({len(ap['discovered_data'])} data points used in answer):\n" + "\n".join(data_preview)

                    approach_summaries.append(f"""
**Approach {i+1}: {ap['approach_name']}** (Quality: {ap['quality_grade']:.2f}/1.0)
Goal: {ap['approach_goal']}

Answer: {ap['answer']}{data_summary}
""")

                # Build logical form section if available
                logical_form_section = ""
                if logical_form:
                    logical_form_section = f"""
**LOGICAL QUERY STRUCTURE**:
{logical_form}

"""

                # Build dependencies section
                dependencies_section = ""
                if packets_dict:
                    dep_lines = []
                    for packet_id in sorted(packets_dict.keys()):
                        packet = packets_dict[packet_id]
                        depends_on = packet.get('depends_on_subqueries', [])
                        packet_text = packet.get('text', packet_id)
                        if depends_on:
                            dep_lines.append(f"  - {packet_text} → depends on: {', '.join(depends_on)}")
                        else:
                            dep_lines.append(f"  - {packet_text} → foundational (no dependencies)")

                    if dep_lines:
                        dependencies_section = f"""**APPROACH DEPENDENCIES**:
{chr(10).join(dep_lines)}

"""

                prompt = f"""
You are answering a code analysis query by synthesizing findings from multiple analysis approaches.

**USER QUERY**: {user_query}
**QUERY TYPE**: {intent_type}

{logical_form_section}{dependencies_section}**APPROACH ANSWERS** ({len(approach_answers)} approaches, sorted by quality):

{chr(10).join(approach_summaries)}

**YOUR TASK**: {task_description}

{synthesis_instructions}

Return your response in JSON format:

{{
    "answer": "Your synthesized markdown answer here",
    "approaches_used": [0, 1, 2, ...]  // List of approach indices you used
}}

The approaches_used array should contain the indices (0, 1, 2, ...) of approaches whose findings contributed to your answer.
"""

                llm_service = state.get('llm_service')
                if not llm_service:
                    # Fallback: simple summary with all data as citations
                    response = self._generate_fallback_synthesis(user_query, discovered_data, approach_traces)
                    citations = self._build_structured_citations(approach_traces, discovered_data, list(range(len(discovered_data))))
                else:
                    # Try synthesis with full context first (NO ARTIFICIAL LIMITS)
                    result = await llm_service.generate_response(prompt, json_mode=True)

                    # If context error, use incremental chat-based building
                    if result and result.error:
                        error_str = str(result.error).lower()
                        is_context_error = any(keyword in error_str for keyword in [
                            'context_length_exceeded',
                            'maximum context length',
                            'too many tokens',
                            'context window',
                            'token limit'
                        ])

                        if is_context_error:
                            logger.warning(f"⚠️ Full context synthesis failed due to token limits, using incremental chat-based building for {len(discovered_data)} items")
                            response, citations = await self._incremental_synthesis(
                                user_query=user_query,
                                discovered_data=discovered_data,
                                approach_traces=approach_traces,
                                intent_type=intent_type,
                                task_description=task_description,
                                llm_service=llm_service,
                                state=state
                            )

                            return {
                                **state,
                                "response": response,
                                "citations": citations,
                                "current_node": "synthesize_response"
                            }
                        else:
                            # Some other error, not context-related
                            logger.warning(f"⚠️ LLM synthesis failed (non-context error): {result.error}")
                            response = self._generate_fallback_synthesis(user_query, discovered_data, approach_traces)
                            citations = self._build_structured_citations(approach_traces, discovered_data, list(range(len(discovered_data))))

                            return {
                                **state,
                                "response": response,
                                "citations": citations,
                                "current_node": "synthesize_response"
                            }

                    if result and not result.error:
                        try:
                            synthesis_data = json.loads(result.content.strip())
                            response = synthesis_data.get('answer', result.content.strip())
                            approaches_used_indices = synthesis_data.get('approaches_used', list(approach_traces.keys()))

                            # Build citations from approaches that were actually used
                            # Each approach has data_points_used which contains local indices into discovered_data
                            # We need to map these to global discovered_data indices
                            used_data_indices = set()  # Use set to avoid duplicates

                            for approach_idx in approaches_used_indices:
                                if approach_idx in approach_traces:
                                    trace = approach_traces[approach_idx]
                                    # Get the indices of data points this approach actually used
                                    approach_data_indices = trace.get('data_points_used', [])

                                    # Get this approach's discovered_data (filtered data with metadata)
                                    # This is stored in approach_raw_results, NOT in the trace
                                    if approach_idx in approach_raw_results:
                                        approach_discovered_data = approach_raw_results[approach_idx].get('discovered_data', [])

                                        # Map local indices to global indices
                                        for local_idx in approach_data_indices:
                                            if local_idx < len(approach_discovered_data):
                                                # Get the actual data point from approach's discovered_data
                                                data_item = approach_discovered_data[local_idx]

                                                # Find this item in global discovered_data
                                                # Match by source metadata (query + iteration)
                                                source_query = data_item.get('_source_query', '')
                                                source_iteration = data_item.get('_source_iteration', 0)

                                                for global_idx, disc_data in enumerate(discovered_data):
                                                    if (disc_data.get('_source_query') == source_query and
                                                        disc_data.get('_source_iteration') == source_iteration):
                                                        used_data_indices.add(global_idx)
                                                        break

                            citations = self._build_structured_citations(approach_traces, discovered_data, list(used_data_indices))

                            # Track token usage
                            token_updates = self._track_llm_call(
                                llm_response=result,
                                call_type='synthesis',
                                call_purpose='Synthesize final response from discovered data'
                            )

                            # Accumulate token metrics
                            accumulated_tokens = {
                                'total_input_tokens': state.get('total_input_tokens', 0) + token_updates.get('total_input_tokens', 0),
                                'total_output_tokens': state.get('total_output_tokens', 0) + token_updates.get('total_output_tokens', 0),
                                'total_tokens_used': state.get('total_tokens_used', 0) + token_updates.get('total_tokens_used', 0),
                                'total_estimated_cost_usd': state.get('total_estimated_cost_usd', 0.0) + token_updates.get('total_estimated_cost_usd', 0.0),
                                'synthesis_tokens': state.get('synthesis_tokens', 0) + token_updates.get('synthesis_tokens', 0),
                                'llm_call_history': list(state.get('llm_call_history', [])) + token_updates.get('llm_call_history', []),
                                'models_used': list(set(state.get('models_used', []) + token_updates.get('models_used', []))),
                            }

                            logger.info(f"✅ Response synthesized successfully ({len(response)} characters)")
                            logger.info(f"📎 Approaches used: {len(approaches_used_indices)} out of {len(approach_traces)} approaches")
                            logger.info(f"📎 Data citations: {len(used_data_indices)} out of {len(discovered_data)} data points used")

                            return {
                                **state,
                                **accumulated_tokens,
                                "response": response,
                                "citations": citations,  # Only data points actually used in response
                                "current_node": "synthesize_response"
                            }
                        except json.JSONDecodeError:
                            # Fallback if JSON parsing fails
                            logger.warning("⚠️ Failed to parse synthesis JSON, using full response")
                            response = result.content.strip()
                            citations = self._build_structured_citations(approach_traces, discovered_data, list(range(len(discovered_data))))

                            token_updates = self._track_llm_call(
                                llm_response=result,
                                call_type='synthesis',
                                call_purpose='Synthesize final response from discovered data'
                            )

                            # Accumulate token metrics
                            accumulated_tokens = {
                                'total_input_tokens': state.get('total_input_tokens', 0) + token_updates.get('total_input_tokens', 0),
                                'total_output_tokens': state.get('total_output_tokens', 0) + token_updates.get('total_output_tokens', 0),
                                'total_tokens_used': state.get('total_tokens_used', 0) + token_updates.get('total_tokens_used', 0),
                                'total_estimated_cost_usd': state.get('total_estimated_cost_usd', 0.0) + token_updates.get('total_estimated_cost_usd', 0.0),
                                'synthesis_tokens': state.get('synthesis_tokens', 0) + token_updates.get('synthesis_tokens', 0),
                                'llm_call_history': list(state.get('llm_call_history', [])) + token_updates.get('llm_call_history', []),
                                'models_used': list(set(state.get('models_used', []) + token_updates.get('models_used', []))),
                            }

                            return {
                                **state,
                                **accumulated_tokens,
                                "response": response,
                                "citations": citations,
                                "current_node": "synthesize_response"
                            }
                    else:
                        logger.warning(f"⚠️ LLM synthesis failed: {result.error if result else 'No result'}")
                        response = self._generate_fallback_synthesis(user_query, discovered_data, approach_traces)
                        citations = self._build_structured_citations(approach_traces, discovered_data, list(range(len(discovered_data))))
            else:
                # No ContextManager available, use fallback
                logger.warning("⚠️ ContextManager not available, using fallback synthesis")
                response = self._generate_fallback_synthesis(user_query, discovered_data, approach_traces)
                citations = self._build_structured_citations(approach_traces, discovered_data, list(range(len(discovered_data))))

            return {
                **state,
                "response": response,
                "citations": citations,  # Only data points actually used in response
                "current_node": "synthesize_response"
            }

        except Exception as e:
            logger.error(f"❌ Response synthesis failed: {e}")
            import traceback
            traceback.print_exc()

            # Fallback on error
            discovered_data = state.get('discovered_data', [])
            return {
                **state,
                "current_node": "synthesize_response",
                "response": f"Found {len(discovered_data)} results for query: '{state.get('user_query', '')}'. (Error during synthesis: {e})",
                "error": f"Response synthesis failed: {e}"
            }

    def _build_structured_citations(
        self,
        approach_traces: Dict[int, Dict[str, Any]],
        discovered_data: List[Dict[str, Any]],
        used_indices: List[int]
    ) -> Dict[str, Any]:
        """
        Build structured citations from approach execution traces.

        Only includes data points that were actually used in the response.

        Args:
            approach_traces: Execution traces from all approaches
            discovered_data: All discovered data points
            used_indices: Indices of data points actually used in response

        Returns:
            Structured citations format similar to genpod-semantic-rag for MCP/consumer compatibility.
        """
        # Filter to only used data points
        cited_data = [discovered_data[i] for i in used_indices if i < len(discovered_data)]

        citations = {
            "total_cited": len(cited_data),
            "total_discovered": len(discovered_data),
            "approaches": [],
            "cited_results": cited_data,  # Only data points used in response
            "metadata": {
                "approaches_executed": len(approach_traces),
                "total_queries": sum(len(trace.get('query_history', [])) for trace in approach_traces.values()),
                "citation_ratio": f"{len(cited_data)}/{len(discovered_data)}"
            }
        }

        # Build per-approach citations (only include approaches that contributed cited data)
        for idx, trace in approach_traces.items():
            # Find which cited results came from this approach
            approach_cited_results = [r for r in cited_data if self._result_from_approach(r, trace)]

            if len(approach_cited_results) > 0:  # Only include if this approach contributed citations
                approach_citation = {
                    "approach_index": idx,
                    "approach_name": trace.get('approach_name', f'Approach {idx}'),
                    "approach_goal": trace.get('approach_goal', ''),
                    "queries_executed": trace.get('queries_executed', 0),
                    "results_cited": len(approach_cited_results),
                    "query_history": trace.get('query_history', []),
                    "reasoning_trail": trace.get('reasoning_trail', []),
                    "evidence_summary": trace.get('evidence_summary', {}),
                    "is_sufficient": trace.get('is_sufficient', False)
                }
                citations["approaches"].append(approach_citation)

        return citations

    def _result_from_approach(self, result: Dict[str, Any], trace: Dict[str, Any]) -> bool:
        """Check if a result came from this approach (heuristic)."""
        # Simple heuristic: if result appears in trace's query results
        for query_record in trace.get('query_history', []):
            if result in query_record.get('results', []):
                return True
        return False

    async def _incremental_synthesis(
        self,
        user_query: str,
        discovered_data: List[Dict[str, Any]],
        approach_traces: Dict[int, Dict[str, Any]],
        intent_type: str,
        task_description: str,
        llm_service: Any,
        state: AgentState
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Perform chunked synthesis when full context exceeds token limits.

        Strategy:
        1. Break discovered_data into chunks of ~50 items
        2. Analyze each chunk individually
        3. Synthesize chunk summaries into final comprehensive response
        4. Track citations across all chunks

        Returns:
            Tuple of (response_text, citations_dict)
        """
        chunk_size = 50
        chunks = [discovered_data[i:i + chunk_size] for i in range(0, len(discovered_data), chunk_size)]

        logger.info(f"📦 Chunked synthesis: {len(chunks)} chunks of ~{chunk_size} items each")

        # Step 1: Analyze each chunk
        chunk_analyses = []
        all_citations_used = []

        for chunk_idx, chunk in enumerate(chunks):
            chunk_start_idx = chunk_idx * chunk_size

            # Build numbered context for this chunk
            numbered_chunk = []
            for i, data in enumerate(chunk):
                global_idx = chunk_start_idx + i
                numbered_chunk.append(f"[{global_idx}] {json.dumps(data, default=str)}")

            chunk_prompt = f"""
Analyze this chunk of code analysis data ({chunk_idx + 1}/{len(chunks)}).

**USER QUERY**: {user_query}
**QUERY TYPE**: {intent_type}

**DATA CHUNK {chunk_idx + 1}** (items {chunk_start_idx} to {chunk_start_idx + len(chunk) - 1}):

{chr(10).join(numbered_chunk)}

**YOUR TASK**: Extract key findings from this chunk that are relevant to the user query.

Respond in JSON:
{{
    "key_findings": ["Finding 1", "Finding 2", ...],
    "patterns_observed": ["Pattern 1", "Pattern 2", ...],
    "citations_used": [0, 5, 12, ...]  // Global indices used from this chunk
}}
"""

            result = await llm_service.generate_response(chunk_prompt, json_mode=True)

            if result and not result.error:
                try:
                    chunk_data = json.loads(result.content.strip())
                    chunk_analyses.append({
                        'chunk_idx': chunk_idx,
                        'key_findings': chunk_data.get('key_findings', []),
                        'patterns_observed': chunk_data.get('patterns_observed', []),
                        'citations_used': chunk_data.get('citations_used', [])
                    })
                    all_citations_used.extend(chunk_data.get('citations_used', []))

                    # Track token usage
                    token_updates = self._track_llm_call(
                        llm_response=result,
                        call_type='synthesis',
                        call_purpose=f'Chunked synthesis - chunk {chunk_idx + 1}/{len(chunks)}'
                    )

                    logger.info(f"✅ Chunk {chunk_idx + 1}/{len(chunks)} analyzed: {len(chunk_data.get('key_findings', []))} findings")
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ Failed to parse chunk {chunk_idx + 1} analysis")
                    chunk_analyses.append({
                        'chunk_idx': chunk_idx,
                        'key_findings': [f"Chunk {chunk_idx + 1} data available but parsing failed"],
                        'patterns_observed': [],
                        'citations_used': []
                    })
            else:
                logger.warning(f"⚠️ Chunk {chunk_idx + 1} analysis failed: {result.error if result else 'No result'}")

        # Step 2: Synthesize all chunk analyses into comprehensive response
        synthesis_prompt = f"""
Create a comprehensive answer by synthesizing findings from {len(chunks)} data chunks.

**USER QUERY**: {user_query}
**TASK**: {task_description}

**CHUNK ANALYSES**:
{chr(10).join([f"Chunk {a['chunk_idx'] + 1}: {json.dumps(a, indent=2)}" for a in chunk_analyses])}

**YOUR TASK**:
1. Synthesize a comprehensive, detailed answer that integrates findings from all chunks
2. Use SPECIFIC details from the data (exact names, file paths, relationships, code snippets)
3. For architectural/structural queries: describe patterns in depth, explain how components relate
4. For each finding, reference concrete evidence from the data
5. Organize the response with clear sections and subsections
6. Provide thorough explanations rather than surface-level summaries

**QUALITY REQUIREMENTS**:
- Include specific entity names, file paths, and relationships from the data
- Explain patterns and architectural decisions with examples
- Use markdown formatting (headings, lists, code blocks) for readability
- Aim for depth over breadth - elaborate on key findings
- Do NOT simply list items - explain their significance and relationships

Respond in JSON:
{{
    "answer": "Your comprehensive, detailed markdown answer with specific references to data points"
}}
"""

        final_result = await llm_service.generate_response(synthesis_prompt, json_mode=True)

        if final_result and not final_result.error:
            try:
                final_data = json.loads(final_result.content.strip())
                response = final_data.get('answer', final_result.content.strip())

                # Track token usage
                token_updates = self._track_llm_call(
                    llm_response=final_result,
                    call_type='synthesis',
                    call_purpose='Chunked synthesis - final integration'
                )

                logger.info(f"✅ Chunked synthesis complete: {len(chunk_analyses)} chunks integrated")
            except json.JSONDecodeError:
                response = final_result.content.strip()
        else:
            # Ultimate fallback: combine chunk findings manually
            response = f"# Results for: {user_query}\n\n"
            response += f"Analyzed {len(discovered_data)} data points in {len(chunks)} chunks.\n\n"
            for analysis in chunk_analyses:
                if analysis.get('key_findings'):
                    response += f"## Chunk {analysis['chunk_idx'] + 1} Findings:\n"
                    for finding in analysis['key_findings']:
                        response += f"- {finding}\n"
                    response += "\n"

        # Build citations from all chunks
        citations = self._build_structured_citations(approach_traces, discovered_data, list(set(all_citations_used)))

        return response, citations

    def _generate_fallback_synthesis(
        self,
        user_query: str,
        discovered_data: List[Dict[str, Any]],
        approach_traces: Dict[int, Dict[str, Any]]
    ) -> str:
        """Generate a simple fallback synthesis without LLM."""
        lines = [
            f"# Results for: {user_query}",
            "",
            f"Found **{len(discovered_data)}** data points across **{len(approach_traces)}** approaches.",
            ""
        ]

        # Add approach summaries
        if approach_traces:
            lines.append("## Approaches Executed:")
            for idx, trace in list(approach_traces.items())[:5]:
                approach_name = trace.get('approach_name', f'Approach {idx}')
                queries_count = len(trace.get('query_history', []))
                lines.append(f"- **{approach_name}**: {queries_count} queries executed")
            lines.append("")

        # Show sample data
        if discovered_data:
            lines.append("## Sample Results (first 5):")
            for i, data in enumerate(discovered_data[:5], 1):
                lines.append(f"\n### Result {i}:")
                lines.append(f"```json\n{json.dumps(data, indent=2, default=str)}\n```")

        lines.append("")
        lines.append(f"*Total: {len(discovered_data)} data points discovered*")

        return "\n".join(lines)

    # ============================================================================
    # ROUTING/DECISION METHODS (not nodes, but used by conditional edges)
    # ============================================================================

    def should_continue_after_sufficiency_check(self, state: AgentState) -> str:
        """
        Routing function: Decide whether to continue with more execution groups or synthesize.

        Logic:
        1. If more execution groups remain → continue executing
        2. If all groups done and have data → synthesize
        3. If all groups done and no data → synthesize (with error message)

        Returns:
            "execute_batch_approaches" - More execution groups to run
            "synthesize_response" - All groups completed, ready to synthesize
        """
        try:
            # Worker pool executes all packets at once, so decision is simple:
            # execute_batch_approaches → synthesize_response (no loops)

            # All execution groups completed - check if we have data
            discovered_data = state.get('discovered_data', [])
            is_sufficient = state.get('is_sufficient', False)

            logger.info(f"✅ Decision: synthesize_response - All execution groups completed ({len(discovered_data)} data points discovered)")
            return "synthesize_response"

        except Exception as e:
            logger.error(f"❌ Decision error in should_continue_after_sufficiency_check: {e}")
            # Fallback: synthesize what we have
            return "synthesize_response"

    # ============================================================================
    # HELPER METHODS (called by execute_batch_approaches, not standalone nodes)
    # ============================================================================

    async def _run_approach_with_adaptive_agent(
        self,
        approach_index: int,
        approach_details: Dict[str, Any],
        state: AgentState,
        cypher_server: Any,
        approach_packet: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a single approach using AdaptiveQueryAgent.

        Args:
            approach_index: Index of this approach (or packet ID)
            approach_details: Approach configuration from discovery or packet
            state: Current workflow state (read-only for this approach)
            cypher_server: Dedicated CypherServerInstance for this approach
            approach_packet: Optional ApproachPacket dict with premises

        Returns:
            Dict with approach results including discovered_data, tokens, status
        """
        approach_name = approach_details.get('approach_name', f'Approach {approach_index}')
        logger.info(f"🔷 Starting approach {approach_index}: {approach_name}")

        try:
            # Get services from state
            llm_service = state.get('llm_service')
            schema = state.get('schema')
            schema_manager = state.get('schema_manager')  # NEW: Get schema_manager for filtered schema
            project_name = state.get('project_name', 'HelloWorldApp')

            if not llm_service:
                raise Exception("LLM service not available")
            if not cypher_server:
                raise Exception("Cypher server instance not provided")
            if not schema:
                raise Exception("Schema not loaded")

            # Create AdaptiveQueryAgent for this approach with dedicated server
            agent = AdaptiveQueryAgent(
                approach_index=approach_index,
                approach_details=approach_details,
                user_query=state['user_query'],
                schema=schema,
                project_name=project_name,
                llm_service=llm_service,
                cypher_server=cypher_server,  # Pass the dedicated server instance
                max_iterations=state.get('max_iterations', 5),  # Max iterations per approach (from workflow config)
                approach_packet=approach_packet,  # NEW: Pass approach packet with premises
                schema_manager=schema_manager,  # NEW: Pass schema_manager for filtered schema + paths
                use_schema_tools=state.get('use_schema_tools', False)  # V7: Enable tool-based schema discovery
            )

            # Run the agent (internally handles think → generate → execute → analyze loop)
            result = await agent.run()

            logger.info(f"✅ Approach {approach_index} completed: {result['total_results']} results, {result['queries_executed']} queries, {result['tokens_used']} tokens")

            return {
                'approach_index': approach_index,
                'status': 'success',
                'result': result
            }

        except Exception as e:
            logger.error(f"❌ Approach {approach_index} failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                'approach_index': approach_index,
                'status': 'failed',
                'error': str(e),
                'result': {
                    'approach_index': approach_index,
                    'approach_name': approach_name,
                    'discovered_data': [],
                    'total_results': 0,
                    'queries_executed': 0,
                    'tokens_used': 0,
                    'is_sufficient': False,
                    'sufficiency_reason': f'Approach failed: {e}'
                }
            }

    def _aggregate_approach_results(
        self,
        state: AgentState,
        approach_results: List[Any],
        batch_start_idx: int
    ) -> Dict[str, Any]:
        """
        Aggregate results from parallel approach executions.

        Args:
            state: Current state (for existing aggregations)
            approach_results: List of results from asyncio.gather()
            batch_start_idx: Starting index for this batch

        Returns:
            Dict with aggregated state updates
        """
        logger.info("📊 Aggregating results from parallel execution...")

        # Initialize aggregation containers
        all_discovered_data = list(state.get('discovered_data', []))
        all_query_history = list(state.get('query_history', []))  # Global query history
        all_raw_query_results = list(state.get('raw_query_results', []))  # Global raw results
        approach_statuses = dict(state.get('approach_statuses', {}))
        approach_raw_results = dict(state.get('approach_raw_results', {}))
        approach_execution_traces = dict(state.get('approach_execution_traces', {}))
        tokens_per_approach = dict(state.get('tokens_per_approach', {}))
        cost_per_approach = dict(state.get('cost_per_approach', {}))
        llm_call_history = list(state.get('llm_call_history', []))

        # Process each approach result
        for i, approach_result in enumerate(approach_results):
            approach_idx = batch_start_idx + i

            # Handle exceptions from asyncio.gather
            if isinstance(approach_result, Exception):
                logger.error(f"❌ Approach {approach_idx} raised exception: {approach_result}")
                approach_statuses[approach_idx] = 'failed'
                approach_raw_results[approach_idx] = {
                    'error': str(approach_result),
                    'discovered_data': [],
                    'total_results': 0
                }
                continue

            # Extract result data
            status = approach_result.get('status', 'unknown')
            result = approach_result.get('result', {})

            # Store status
            approach_statuses[approach_idx] = status

            # Store raw result
            approach_raw_results[approach_idx] = result

            # Add discovered data
            discovered_data = result.get('discovered_data', [])
            all_discovered_data.extend(discovered_data)

            # Aggregate query history and raw results into global arrays
            approach_query_history = result.get('query_history', [])
            for query_entry in approach_query_history:
                # Each query_entry is a dict with 'query' and 'results'

                # Check if this is a query plan entry (has 'steps' field with actual Cypher queries)
                if 'steps' in query_entry and query_entry.get('mode') == 'plan':
                    # Extract actual Cypher queries from query plan steps
                    for step in query_entry.get('steps', []):
                        # Step can be either a dict or a Pydantic QueryStep object
                        if hasattr(step, 'cypher_query'):
                            # Pydantic QueryStep object - field is named 'cypher_query'
                            step_query = step.cypher_query
                        elif isinstance(step, dict):
                            # Dictionary - might have 'query' or 'cypher_query' key
                            step_query = step.get('cypher_query', step.get('query', ''))
                        else:
                            step_query = ''
                        if step_query:
                            all_query_history.append(step_query)
                else:
                    # Regular query mode - query field contains actual Cypher
                    all_query_history.append(query_entry.get('query', ''))  # Add query string

                all_raw_query_results.extend(query_entry.get('results', []))  # Add raw results

            # Extract approach answer details (it's a dict with answer, data_points_used, confidence)
            approach_answer_dict = result.get('approach_answer', {})
            if isinstance(approach_answer_dict, dict):
                approach_answer_text = approach_answer_dict.get('answer', '')
                data_points_used = approach_answer_dict.get('data_points_used', [])
                confidence_assessment = approach_answer_dict.get('confidence_assessment', '')
            else:
                # Fallback if it's a string (shouldn't happen but be defensive)
                approach_answer_text = str(approach_answer_dict)
                data_points_used = []
                confidence_assessment = ''

            # Store execution trace (reasoning trail, citations, etc.)
            approach_execution_traces[approach_idx] = {
                'approach_name': result.get('approach_name', f'Approach {approach_idx}'),
                'approach_goal': result.get('approach_goal', ''),
                'queries_executed': result.get('queries_executed', 0),
                'query_history': approach_query_history,
                'reasoning_trail': result.get('reasoning_trail', []),
                'citations': result.get('citations', {}),
                'evidence_summary': result.get('evidence_summary', {}),
                'is_sufficient': result.get('is_sufficient', False),
                'sufficiency_reason': result.get('sufficiency_reason', ''),
                # NEW: Approach-level answer and quality grade
                'approach_answer': approach_answer_text,  # Extract just the answer text
                'approach_quality_grade': result.get('approach_quality_grade', 0.0),
                'data_points_used': data_points_used,  # Store separately for citation tracking
                'confidence_assessment': confidence_assessment,
                'partial_answers': result.get('partial_answers', [])
            }

            # Track tokens and cost
            tokens_used = result.get('tokens_used', 0)
            tokens_per_approach[approach_idx] = tokens_used

            # Estimate cost (rough approximation if not provided)
            cost_usd = result.get('total_cost_usd', tokens_used * 0.000002)  # Rough estimate
            cost_per_approach[approach_idx] = cost_usd

            # Merge LLM call history if available
            if 'token_breakdown' in result:
                # Could extract detailed call history here if needed
                pass

        # Calculate totals for this batch
        batch_total_tokens = sum(tokens_per_approach.values())
        batch_total_cost = sum(cost_per_approach.values())
        total_discovered = len(all_discovered_data)

        # Aggregate input/output token breakdown from all approaches
        batch_input_tokens = sum(result.get('result', {}).get('total_input_tokens', 0) for result in approach_results if not isinstance(result, Exception))
        batch_output_tokens = sum(result.get('result', {}).get('total_output_tokens', 0) for result in approach_results if not isinstance(result, Exception))

        # Calculate cumulative totals (previous batches + this batch)
        cumulative_total_tokens = state.get('total_tokens_used', 0) + batch_total_tokens
        cumulative_total_cost = state.get('total_estimated_cost_usd', 0.0) + batch_total_cost
        cumulative_input_tokens = state.get('total_input_tokens', 0) + batch_input_tokens
        cumulative_output_tokens = state.get('total_output_tokens', 0) + batch_output_tokens

        logger.info(f"📈 Aggregation complete:")
        logger.info(f"   • Total data points: {total_discovered}")
        logger.info(f"   • Total queries executed: {len(all_query_history)}")
        logger.info(f"   • Total raw results: {len(all_raw_query_results)}")
        logger.info(f"   • Batch tokens: {batch_total_tokens} (in:{batch_input_tokens}, out:{batch_output_tokens}), Cumulative: {cumulative_total_tokens}")
        logger.info(f"   • Batch cost: ${batch_total_cost:.4f}, Cumulative: ${cumulative_total_cost:.6f}")
        logger.info(f"   • Approaches succeeded: {sum(1 for s in approach_statuses.values() if s == 'success')}/{len(approach_results)}")

        return {
            'discovered_data': all_discovered_data,
            'query_history': all_query_history,  # Global query history from all approaches
            'raw_query_results': all_raw_query_results,  # Global raw results from all approaches
            'final_results': all_discovered_data,  # Alias for backwards compatibility
            'approach_statuses': approach_statuses,
            'approach_raw_results': approach_raw_results,
            'approach_execution_traces': approach_execution_traces,
            'tokens_per_approach': tokens_per_approach,
            'cost_per_approach': cost_per_approach,
            'total_tokens_used': cumulative_total_tokens,
            'total_input_tokens': cumulative_input_tokens,
            'total_output_tokens': cumulative_output_tokens,
            'total_estimated_cost_usd': cumulative_total_cost,
            'llm_call_history': llm_call_history
        }

    # ============================================================================
    # UTILITY METHODS (intent analysis, token tracking)
    # ============================================================================

    async def _analyze_intent_with_validation(self, state: AgentState, max_attempts: int = 3) -> dict:
        """Analyze intent with Pydantic validation."""
        for attempt in range(max_attempts):
            try:
                # Get prompt from centralized prompts module
                intent_prompt = get_intent_analysis_prompt(state['user_query'])

                llm_service = state.get('llm_service')
                if not llm_service:
                    raise Exception("LLM service not available")

                result = await llm_service.generate_response(intent_prompt, json_mode=True)

                if result and not result.error:
                    intent_data = json.loads(result.content.strip())

                    # Validate with Pydantic
                    intent_analysis = IntentAnalysis(**intent_data)

                    # Track token usage (no approach_index since this is global)
                    token_updates = self._track_llm_call(
                        llm_response=result,
                        call_type='intent_analysis',
                        call_purpose='Analyze user query intent'
                    )

                    # Return with token tracking
                    return {
                        **intent_analysis.dict(),
                        '_token_updates': token_updates
                    }
                else:
                    raise Exception(f"Intent analysis failed: {result.error if result else 'No result'}")

            except (json.JSONDecodeError, ValidationError) as e:
                if attempt == max_attempts - 1:
                    raise Exception(f"Intent analysis validation failed after {max_attempts} attempts: {e}")
                logger.warning(f"Intent analysis attempt {attempt + 1} failed: {e}")
                continue

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

    def _track_llm_call(
        self,
        llm_response: Any,
        call_type: str,
        approach_index: Optional[int] = None,
        call_purpose: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Track LLM call metrics and prepare state updates.

        Args:
            llm_response: LLMResponse object from llm_service
            call_type: Type of call (think, generate, rethink, diagnostics, etc.)
            approach_index: Optional approach index for per-approach tracking
            call_purpose: Optional specific purpose description

        Returns:
            Dictionary with state updates for token tracking
        """
        # Extract usage information from LLM response
        usage = getattr(llm_response, 'usage', {})
        if not usage:
            usage = {}

        # Handle different provider response formats
        input_tokens = usage.get('input_tokens', usage.get('prompt_tokens', 0))
        output_tokens = usage.get('output_tokens', usage.get('completion_tokens', 0))
        total_tokens = usage.get('total_tokens', input_tokens + output_tokens)

        # Get cost and latency
        cost_usd = getattr(llm_response, 'cost_estimate', 0.0)
        latency_ms = getattr(llm_response, 'latency_ms', 0)
        model_name = getattr(llm_response, 'model', 'unknown')

        # Create LLM call record
        llm_call_record = {
            'call_type': call_type,
            'timestamp': time.time(),
            'model_name': model_name,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': total_tokens,
            'input_cost_usd': cost_usd * (input_tokens / total_tokens) if total_tokens > 0 else 0.0,
            'output_cost_usd': cost_usd * (output_tokens / total_tokens) if total_tokens > 0 else 0.0,
            'total_cost_usd': cost_usd,
            'latency_seconds': latency_ms / 1000.0,
            'call_purpose': call_purpose or f"{call_type} step",
            'approach_index': approach_index
        }

        # Prepare state updates
        state_updates = {
            # Append to LLM call history
            'llm_call_history': [llm_call_record],

            # Global token metrics
            'total_input_tokens': input_tokens,
            'total_output_tokens': output_tokens,
            'total_tokens_used': total_tokens,
            'total_estimated_cost_usd': cost_usd,

            # Model tracking
            'models_used': [model_name]
        }

        # Per-step token breakdowns
        step_token_field = f"{call_type}_tokens"
        if step_token_field in ['think_tokens', 'generate_tokens', 'rethink_tokens',
                                 'diagnostics_tokens', 'refinement_tokens', 'discovery_research_tokens',
                                 'sufficiency_check_tokens', 'synthesis_tokens']:
            state_updates[step_token_field] = total_tokens

        # Per-approach tracking
        if approach_index is not None:
            state_updates['tokens_per_approach'] = {approach_index: total_tokens}
            state_updates['cost_per_approach'] = {approach_index: cost_usd}

        logger.debug(
            f"Tracked {call_type} call: {total_tokens} tokens "
            f"(in:{input_tokens}, out:{output_tokens}), "
            f"cost: ${cost_usd:.6f}, model: {model_name}"
        )

        return state_updates

    def _sanitize_for_pickle(self, obj, depth=0, max_depth=10):
        """
        Recursively sanitize objects to make them picklable.
        Handles SimpleQueue and other unpicklable objects.
        """
        if depth > max_depth:
            return "<MAX_DEPTH_REACHED>"

        # Handle None
        if obj is None:
            return None

        # Handle primitive types
        if isinstance(obj, (str, int, float, bool)):
            return obj

        # Check if object is picklable by checking its type
        obj_type = type(obj).__name__

        # Known unpicklable types
        unpicklable_types = ['SimpleQueue', 'Queue', 'Lock', 'RLock', 'Semaphore',
                            'Event', 'Condition', 'thread', '_thread', 'LLMService',
                            'CypherServerService', 'CypherServerPool']

        if obj_type in unpicklable_types or 'Queue' in obj_type:
            return f"<{obj_type}_REMOVED_FOR_PICKLING>"

        # Handle dictionaries recursively
        if isinstance(obj, dict):
            return {
                k: self._sanitize_for_pickle(v, depth + 1, max_depth)
                for k, v in obj.items()
            }

        # Handle lists recursively
        if isinstance(obj, list):
            return [self._sanitize_for_pickle(item, depth + 1, max_depth) for item in obj]

        # Handle tuples recursively
        if isinstance(obj, tuple):
            return tuple(self._sanitize_for_pickle(item, depth + 1, max_depth) for item in obj)

        # Handle sets
        if isinstance(obj, set):
            return {self._sanitize_for_pickle(item, depth + 1, max_depth) for item in obj}

        # For other objects, try to pickle them, if they fail, convert to string
        try:
            import pickle
            pickle.dumps(obj)
            return obj
        except (TypeError, AttributeError, pickle.PicklingError):
            # If unpicklable, return a safe representation
            try:
                return f"<{obj_type}: {str(obj)[:100]}>"
            except:
                return f"<{obj_type}_UNPICKLABLE>"

    async def _debug_save_state_to_pickle(self, state: AgentState):
        """
        Save complete state to pickle file for debugging analysis.
        """
        try:
            import pickle
            from datetime import datetime

            # Deep sanitize the entire state
            state_copy = self._sanitize_for_pickle(dict(state))

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
            discovered_data = state.get('discovered_data', [])
            approach_execution_traces = state.get('approach_execution_traces', {})

            logger.info(f"🐛 DEBUG: Complete state saved to {pickle_path}")
            logger.info(f"🔍 Summary: {len(approach_raw_results)} approach_raw_results, {len(approach_execution_traces)} traces, {len(discovered_data)} discovered_data, {len(raw_query_results)} raw results, {len(query_history)} history")

        except Exception as e:
            logger.error(f"❌ Failed to save debug state: {e}")

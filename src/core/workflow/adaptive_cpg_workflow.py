"""
Main Adaptive CPG Agent Workflow Orchestrator.

This is the main entry point for the modularized Adaptive CPG Agent Workflow.
It maintains the LangGraph framework while using the clean modular components:

- models.py: Pydantic data models with validation
- research_engine.py: Intelligent discovery research  
- context_manager.py: Data organization and context management
- nodes.py: LangGraph workflow node implementations

This orchestrator provides the same interface as the original monolithic file
but with much better organization, maintainability, and error handling.
"""
import logging
from langgraph.graph import StateGraph
from typing import Dict, Any

from .models import AgentState
from .nodes import WorkflowNodes

logger = logging.getLogger(__name__)


class AdaptiveCPGAgentWorkflow:
    """
    Modularized Adaptive CPG Agent Workflow using LangGraph.
    
    This class orchestrates the entire CPG analysis workflow using
    clean modular components while maintaining LangGraph as the
    core workflow orchestration framework.
    
    Key Features:
    - Research-based discovery (vs assumption-based)
    - Pydantic validation for all data models
    - Proper error handling and fallback mechanisms
    - Context management for large data processing
    - LangGraph workflow orchestration
    """
    
    def __init__(self, use_schema_tools: bool = False):
        """Initialize the workflow orchestrator.
        
        Args:
            use_schema_tools: Enable tool-based schema discovery in generate step (default: False)
        """
        self.workflow_nodes = WorkflowNodes()
        self.workflow = None
        self.llm_service = None
        self.use_schema_tools = use_schema_tools  # Feature flag for schema tools

    async def initialize_services(self):
        """
        Initialize external services required by the workflow.
        
        This sets up:
        - LLM service for query generation and analysis
        - CLI-based CPG database access via project-analyzer tool
        """
        logger.info("🔧 Initializing workflow services...")
        
        try:
            # Import services
            from ..llm_service import LLMService
            from ..cypher_server_service import create_cypher_server_service
            
            # Initialize LLM service (using same config as original workflow)
            self.llm_service = LLMService({"cache_ttl": 1800})
            
            # Initialize cypher server service for 99.3% performance improvement
            self.cypher_server_service = None  # Will be initialized per-workflow with proper config
            
            # Initialize workflow nodes with services
            await self.workflow_nodes.initialize_services(self.llm_service)
            
            logger.info("✅ All workflow services initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Service initialization failed: {e}")
            raise Exception(f"Failed to initialize workflow services: {e}")

    def build_workflow(self) -> StateGraph:
        """
        Build the LangGraph workflow with all nodes and edges.
        
        This creates the complete workflow graph using LangGraph
        with proper state management and conditional routing.
        """
        logger.info("🏗️ Building LangGraph workflow...")
        
        try:
            # Create StateGraph with AgentState
            workflow = StateGraph(AgentState)
            
            # Add all workflow nodes
            workflow.add_node("initialize_environment", self.workflow_nodes.initialize_environment)
            workflow.add_node("analyze_intent", self.workflow_nodes.analyze_intent)
            workflow.add_node("decompose_query", self.workflow_nodes.decompose_query)  # NEW: Phase 0 decomposition
            # workflow.add_node("initial_discovery", self.workflow_nodes.initial_discovery)  # OLD: Keep for backward compatibility if needed
            # NOTE: Mini CoT agents run internally within execute_batch_approaches
            workflow.add_node("execute_batch_approaches", self.workflow_nodes.execute_batch_approaches)  # Worker pool parallel execution
            workflow.add_node("check_sufficiency", self.workflow_nodes.check_sufficiency)  # Global sufficiency evaluation
            workflow.add_node("synthesize_response", self.workflow_nodes.synthesize_response)

            # Define workflow edges - Phase 0 decomposition → execution groups
            workflow.add_edge("initialize_environment", "analyze_intent")
            workflow.add_edge("analyze_intent", "decompose_query")  # NEW: Decompose into approach packets
            workflow.add_edge("decompose_query", "execute_batch_approaches")  # Execute first execution group

            # Conditional routing after execute_batch_approaches
            # Routes to either check_sufficiency or directly to next batch
            workflow.add_edge("execute_batch_approaches", "check_sufficiency")

            # Conditional routing after check_sufficiency
            # Decides: next batch or synthesize
            workflow.add_conditional_edges(
                "check_sufficiency",
                self.workflow_nodes.should_continue_after_sufficiency_check,  # Returns string: "execute_batch_approaches" or "synthesize_response"
                {
                    "execute_batch_approaches": "execute_batch_approaches",  # More data needed → next batch
                    "synthesize_response": "synthesize_response"  # Sufficient → synthesize
                }
            )
            
            # Conditional edge for continuation decision
            # workflow.add_conditional_edges(
            #     "evaluate_sufficiency",
            #     self.workflow_nodes.should_continue_exploring,
            #     {
            #         "generate_query": "generate_query",
            #         "synthesize_response": "synthesize_response"
            #     }
            # )
            
            # Set entry and exit points (TEST: think self-loop to test all approaches)
            workflow.set_entry_point("initialize_environment")
            workflow.set_finish_point("synthesize_response")  # Will finish after all approaches analyzed
            
            # Compile the workflow with recursion limit  
            compiled_workflow = workflow.compile()
            
            logger.info("✅ LangGraph workflow built successfully")
            return compiled_workflow
            
        except Exception as e:
            logger.error(f"❌ Workflow building failed: {e}")
            raise Exception(f"Failed to build workflow: {e}")

    async def run_workflow(self, user_query: str, project_name: str = "HelloWorldApp", 
                          max_iterations: int = 5, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute the complete CPG analysis workflow.

        Args:
            user_query: The user's question about the codebase
            project_name: Name of the project to analyze
            max_iterations: Maximum iterative query refinement loops per approach (default: 5)

        Returns:
            Dictionary containing the final analysis results
        """
        logger.info(f"🚀 Starting CPG workflow for query: '{user_query}'")
        
        try:
            # Initialize services if not already done
            if not self.llm_service:
                await self.initialize_services()
            
            # Build workflow if not already built
            if not self.workflow:
                self.workflow = self.build_workflow()
            
            # Initialize workflow state - all list fields start as empty lists, never None
            initial_state: AgentState = {
                "user_query": user_query,
                "intent": "",
                # "current_query": None,  # ❌ DEPRECATED: Not used (we have query_history)
                "entities": [],  # Empty list, not None
                "disambiguated_entities": {},
                "discovered_data": [],  # Empty list, not None
                "raw_query_results": [],  # Empty list, not None
                "query_history": [],  # Empty list, not None
                "current_iteration": 1,
                "max_iterations": max_iterations,
                # "should_continue": True,  # ❌ DEPRECATED: Use routing functions instead
                "response": "",
                "current_node": "",
                "schema": {},
                "llm_service": self.llm_service,
                "neo4j_config": metadata.get("neo4j_config") if metadata else None,
                # "neo4j_version": "",  # ❌ DEPRECATED: Output metadata, not state
                "cypher_server_service": None,  # Will be initialized in initialize_environment node
                # "final_results": [],  # ❌ DEPRECATED: Duplicate of discovered_data
                # "body_exploration_candidates": [],  # ❌ DEPRECATED: Old body exploration (not used)
                # "body_exploration_results": [],  # ❌ DEPRECATED: Old body exploration (not used)
                # "vector_results": None,  # ❌ DEPRECATED: Separate feature (vector search)
                # "vector_collection_name": None,  # ❌ DEPRECATED: Separate feature (vector search)
                # "sufficiency_evaluation": None,  # ❌ DEPRECATED: Duplicate fields exist
                "organized_data": None,
                "discovery_research": None,
                # NEW: Phase 0 Query Decomposition and Approach Packet Management
                "query_decomposition": None,  # Phase 0 decomposition result
                "dependency_analysis": None,  # Premise and subquery dependencies
                "approach_packets": None,  # Self-contained approach packets with execution groups
                "completed_subqueries": [],  # List of completed subquery IDs
                "subquery_results": {},  # Dict[subquery_id, result]
                "current_execution_group": 0,  # Current execution group index
                # Think → Generate → Execute → Rethink workflow state
                # "current_approach_index": 0,  # ❌ DEPRECATED: Managed by batcher, not global state
                "total_approaches": 0,  # Will be set after research completes
                # "current_scope": None,  # ❌ DEPRECATED: Not used in batch mode
                # "current_approach_details": None,  # ❌ DEPRECATED: Passed to approaches, not global
                # "thinking_results": None,  # ❌ DEPRECATED: Stored per-approach, not global
                # "rethinking_results": None,  # ❌ DEPRECATED: Stored per-approach, not global
                # "fallback_mode": None,  # ❌ DEPRECATED: Not used
                # "diverse_queries_generated": None,  # ❌ DEPRECATED: Not used
                # "synthesis_context_used": None,  # ❌ DEPRECATED: Output field, not state
                # Execute step workflow state
                # "generated_queries": [],  # ❌ DEPRECATED: Stored per-approach
                # "execution_results": [],  # ❌ DEPRECATED: Use approach_raw_results instead
                # "execution_analysis": None,  # ❌ DEPRECATED: Stored per-approach
                # "execution_status": None,  # ❌ DEPRECATED: Use approach_statuses instead
                # "total_results_found": 0,  # ❌ DEPRECATED: Can calculate from discovered_data length
                # "syntax_error_count": 0,  # ❌ DEPRECATED: Tracked per-approach, not global
                # NEW: Raw results tracking and progressive summarization
                "approach_raw_results": {},  # Dict[approach_index, [(query, results), ...]]
                "iteration_summaries": [],  # Progressive summaries to prevent context explosion
                "cumulative_findings": "",  # Running summary of findings
                # NEW: Rethink step state
                # "rethink_analysis": None,  # ❌ DEPRECATED: Duplicate of rethinking_results
                "sufficiency_check_history": [],  # History of sufficiency checks
                # "should_synthesize": False,  # ❌ DEPRECATED: Use is_sufficient instead
                # NEW: Query refinement tracking
                "failed_approaches": [],  # List of approach indices that failed completely
                "approach_statuses": {},  # Dict[approach_index, 'success'|'partial'|'failed']
                "metadata": metadata or {},  # Store CLI parameter metadata
                # NEW: Parallel batch execution configuration
                # NOTE: Sequential mode = batch mode with batch_size=1 (same code path)
                # "execution_mode": "batch",  # ❌ DEPRECATED: Always batch mode
                "batch_size": 4,  # Execute N approaches per batch (default: 4, sequential mode: 1)
                "current_batch_number": 0,  # Which batch we're on
                "batches_completed": 0,  # Total batches completed
                # "cypher_server_pool": None,  # ❌ DEPRECATED: Duplicate of cypher_server_service
                # NEW: Per-approach execution tracking
                "approach_execution_traces": {},  # Dict[approach_index, ApproachExecutionTrace]
                # "needs_refinement": False,  # ❌ DEPRECATED: Per-approach decision, not global
                "refinement_attempts": {},  # Dict[approach_index, attempt_count]
                # "refined_queries": [],  # ❌ DEPRECATED: Stored in approach results
                # "diagnostics": [],  # ❌ DEPRECATED: Stored per-approach
                # NEW: Sufficiency checking (after batch)
                "is_sufficient": False,  # Is data sufficient?
                "sufficiency_confidence": 0.0,  # LLM confidence in sufficiency
                "sufficiency_reasoning": "",  # Why sufficient/insufficient
                # NEW: Token utilization tracking
                "llm_call_history": [],  # All LLM calls (chronological)
                "total_input_tokens": 0,  # Total input tokens
                "total_output_tokens": 0,  # Total output tokens
                "total_tokens_used": 0,  # Total tokens (input + output)
                "total_estimated_cost_usd": 0.0,  # Total cost
                # Per-step token breakdown
                "discovery_research_tokens": 0,
                "think_tokens": 0,
                "generate_tokens": 0,
                "rethink_tokens": 0,
                "diagnostics_tokens": 0,
                "refinement_tokens": 0,
                "sufficiency_check_tokens": 0,
                "synthesis_tokens": 0,
                # Efficiency metrics
                "tokens_per_approach": {},  # Dict[approach_index, token_count]
                "cost_per_approach": {},  # Dict[approach_index, cost_usd]
                "tokens_per_data_point": None,  # Average tokens per data item
                "cost_per_data_point": None,  # Average cost per data item
                # Model tracking
                "models_used": [],  # List of models used
                "primary_model": "gpt-4-turbo",  # Default model
                # NEW: Schema tools feature flag
                "use_schema_tools": self.use_schema_tools,  # Enable tool-based schema discovery
            }

            # Execute the workflow with recursion limit
            logger.info("⚡ Executing LangGraph workflow...")
            final_state = await self.workflow.ainvoke(
                initial_state,
                config={"recursion_limit": 50}
            )
            
            # Cleanup services after workflow completion
            await self.workflow_nodes.cleanup_services(final_state)
            
            # Process final results - match original format exactly
            results = {
                "status": "success" if not final_state.get("error") else "error",
                "response": final_state.get("response", ""),
                "query_history": final_state.get("query_history", []),
                "iterations_used": final_state.get("current_iteration", 0),
                "final_results": final_state.get("final_results", []),
                "intent": final_state.get("intent", {}),
                "workflow": "langgraph_agent",
                # NEW: Include structure-during-discovery results
                "organized_data": final_state.get("organized_data", {}),
                "architectural_summary": final_state.get("architectural_summary", {}),
                "synthesis_context_used": final_state.get("synthesis_context_used", 0),
                # NEW: Include all raw database query results (internal tracking)
                "raw_query_results": final_state.get("raw_query_results", []),
                "all_executed_queries": final_state.get("query_history", []),  # Use query_history for compatibility
                # NEW: Token utilization tracking
                "total_tokens_used": final_state.get("total_tokens_used", 0),
                "total_input_tokens": final_state.get("total_input_tokens", 0),
                "total_output_tokens": final_state.get("total_output_tokens", 0),
                "total_estimated_cost_usd": final_state.get("total_estimated_cost_usd", 0.0),
                # Per-step token breakdown
                "discovery_research_tokens": final_state.get("discovery_research_tokens", 0),
                "think_tokens": final_state.get("think_tokens", 0),
                "generate_tokens": final_state.get("generate_tokens", 0),
                "rethink_tokens": final_state.get("rethink_tokens", 0),
                "diagnostics_tokens": final_state.get("diagnostics_tokens", 0),
                "refinement_tokens": final_state.get("refinement_tokens", 0),
                "sufficiency_check_tokens": final_state.get("sufficiency_check_tokens", 0),
                "synthesis_tokens": final_state.get("synthesis_tokens", 0),
                # Efficiency metrics
                "tokens_per_approach": final_state.get("tokens_per_approach", {}),
                "cost_per_approach": final_state.get("cost_per_approach", {}),
                "tokens_per_data_point": final_state.get("tokens_per_data_point"),
                "cost_per_data_point": final_state.get("cost_per_data_point"),
                # Model tracking
                "models_used": final_state.get("models_used", []),
                "primary_model": final_state.get("primary_model", "unknown"),
                # LLM call history
                "llm_call_history": final_state.get("llm_call_history", []),
                # MCP compatibility: raw_results contains the filtered discovered data
                "raw_results": final_state.get("discovered_data", []),
                "executed_queries": final_state.get("query_history", []),  # MCP compatibility alias
                # NEW: Query refinement tracking
                "approach_statuses": final_state.get("approach_statuses", {}),
                "failed_approaches": final_state.get("failed_approaches", []),
                # NEW: Per-approach execution traces (query history, citations, reasoning)
                "approach_execution_traces": final_state.get("approach_execution_traces", {}),
                "approach_raw_results": final_state.get("approach_raw_results", {}),
                "agent_metadata": {
                    "neo4j_version": "",  # Will be populated if available
                    "schema_nodes": len(final_state.get("schema", {}).get("nodes", {})),
                    "total_queries_executed": len(final_state.get("query_history", [])),
                    "total_raw_results": len(final_state.get("raw_query_results", [])),
                    "workflow_nodes_executed": 7,
                    "agents_involved": ["environment", "discovery", "intent", "query_generator", "expansion", "synthesis"],
                    # NEW: Enhanced metadata from modular workflow
                    "modular_workflow_version": "2.0.0",
                    "pydantic_validation_enabled": True,
                    "research_based_discovery": bool(final_state.get("discovery_research")),
                    "context_manager_used": bool(final_state.get("synthesis_context_used")),
                    "metadata": final_state.get("metadata", {})
                },
                "error": final_state.get("error")
            }
            
            logger.info(f"✅ Workflow completed successfully in {results['iterations_used']} iterations")
            logger.info(f"📊 Final results: {len(results['raw_results'])} items discovered")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Workflow execution failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "response": f"Workflow execution failed: {e}",
                "query_history": [],
                "iterations_used": 0,
                "final_results": [],
                "intent": {},
                "workflow": "langgraph_agent",
                "organized_data": {},
                "architectural_summary": {},
                "synthesis_context_used": 0,
                "raw_query_results": [],
                "all_executed_queries": [],
                "raw_results": [],  # Empty filtered results on error
                "executed_queries": [],
                "agent_metadata": {
                    "neo4j_version": "",
                    "schema_nodes": 0,
                    "total_queries_executed": 0,
                    "total_raw_results": 0,
                    "workflow_nodes_executed": 0,
                    "agents_involved": []
                }
            }

    async def run_single_query(self, user_query: str, project_name: str = "HelloWorldApp") -> str:
        """
        Convenience method to run a single query and return just the response.
        
        Args:
            user_query: The user's question
            project_name: Project name to analyze
            
        Returns:
            String response to the query
        """
        results = await self.run_workflow(user_query, project_name, max_iterations=3)
        return results.get("response", "No response available")

    def get_workflow_status(self) -> Dict[str, Any]:
        """
        Get current workflow initialization status.
        
        Returns:
            Status information about workflow components
        """
        return {
            "llm_service_initialized": self.llm_service is not None,
            "cli_query_execution_ready": True,  # CLI-based execution is always available
            "workflow_built": self.workflow is not None,
            "workflow_nodes_ready": self.workflow_nodes is not None
        }


# Factory functions for easy instantiation

async def create_adaptive_cpg_workflow(use_schema_tools: bool = False) -> AdaptiveCPGAgentWorkflow:
    """
    Create and initialize an AdaptiveCPGAgentWorkflow instance.
    
    Args:
        use_schema_tools: Enable tool-based schema discovery (default: False)
    
    Returns:
        Fully initialized workflow ready to execute
    """
    workflow = AdaptiveCPGAgentWorkflow(use_schema_tools=use_schema_tools)
    await workflow.initialize_services()
    workflow.workflow = workflow.build_workflow()
    return workflow


async def execute_adaptive_cpg_workflow(user_query: str, project_name: str = "HelloWorldApp", 
                                       max_iterations: int = 5, neo4j_config: str = None,
                                       project_path: str = None, mappings_path: str = None, 
                                       queries_path: str = None, use_schema_tools: bool = False) -> Dict[str, Any]:
    """
    Convenience function to create and execute a workflow in one call.
    
    Args:
        user_query: The user's question about the codebase
        project_name: Name of the project to analyze  
        max_iterations: Maximum exploration iterations
        neo4j_config: Path to Neo4j configuration (for backwards compatibility)
        project_path: Path to project directory (for backwards compatibility)
        mappings_path: Path to mappings directory (for backwards compatibility)
        queries_path: Path to queries directory (for backwards compatibility)
        use_schema_tools: Enable tool-based schema discovery (default: False)
        
    Returns:
        Complete workflow results with 'status' field for backwards compatibility
    """
    workflow = await create_adaptive_cpg_workflow(use_schema_tools=use_schema_tools)
    
    # Store metadata for potential use by agents (paths for future analysis commands)
    metadata = {
        "project_path": project_path,
        "mappings_path": mappings_path,
        "queries_path": queries_path,
        "neo4j_config": neo4j_config
    }
    
    # The run_workflow method already returns the exact format expected by tools.py
    return await workflow.run_workflow(user_query, project_name, max_iterations, metadata)


# Main execution for testing
async def main():
    """Main function for testing the modular workflow."""
    import asyncio
    
    # Test query
    test_query = "What are the key architectural components in this codebase?"
    
    try:
        logger.info("🧪 Testing modular adaptive CPG workflow...")
        results = await execute_adaptive_cpg_workflow(test_query, max_iterations=3)
        
        print(f"\n🎯 Query: {test_query}")
        print(f"📝 Response: {results['response']}")
        print(f"📊 Data Items: {len(results['raw_results'])}")
        print(f"🔄 Iterations: {results['iterations_used']}")
        print(f"✅ Status: {results['status']}")
        
    except Exception as e:
        logger.error(f"❌ Test execution failed: {e}")
        print(f"❌ Test failed: {e}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
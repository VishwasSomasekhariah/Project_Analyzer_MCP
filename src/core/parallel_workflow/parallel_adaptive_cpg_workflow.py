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

from .parallel_models import AgentState
from .parallel_nodes import WorkflowNodes

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
    
    def __init__(self):
        """Initialize the workflow orchestrator."""
        self.workflow_nodes = WorkflowNodes()
        self.workflow = None
        self.llm_service = None

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
            
            # Initialize LLM service (using same config as original workflow)
            self.llm_service = LLMService({"cache_ttl": 1800})
            
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
            workflow.add_node("initial_discovery", self.workflow_nodes.initial_discovery)  
            workflow.add_node("think", self.workflow_nodes.think)  # Think step for approach analysis
            workflow.add_node("analyze_intent", self.workflow_nodes.analyze_intent)
            workflow.add_node("generate_query", self.workflow_nodes.generate_query)
            workflow.add_node("execute_queries", self.workflow_nodes.execute_queries)  # Execute step with comprehensive error handling
            workflow.add_node("rethink", self.workflow_nodes.rethink)  # NEW: Rethink step for sufficiency analysis
            workflow.add_node("evaluate_sufficiency", self.workflow_nodes.evaluate_sufficiency)
            workflow.add_node("synthesize_response", self.workflow_nodes.synthesize_response)
            
            # Define workflow edges - Intent → Think → Generate → Execute → Rethink → (Think|Synthesize) cycle
            workflow.add_edge("initialize_environment", "initial_discovery")
            workflow.add_edge("initial_discovery", "analyze_intent")  # Analyze intent first
            workflow.add_edge("analyze_intent", "think")  # Then go to think after intent analysis
            
            # NEW: Think → Generate → Execute → Rethink cycle
            workflow.add_edge("think", "generate_query")  # Think → Generate (for current approach)
            workflow.add_edge("generate_query", "execute_queries")  # Generate → Execute
            workflow.add_edge("execute_queries", "rethink")  # Execute → Rethink (NEW: Always go to rethink after execution)
            
            # NEW: Conditional edges from rethink: Rethink → Think (continue) or Synthesize (done)
            workflow.add_conditional_edges(
                "rethink",
                self.workflow_nodes.should_continue_after_rethink,
                {
                    "think": "think",  # Continue cycling: Rethink → Think for next approach
                    "synthesize_response": "synthesize_response"  # Or finish if sufficient data found
                }
            )
            
            # Conditional edge for continuation decision
            workflow.add_conditional_edges(
                "evaluate_sufficiency",
                self.workflow_nodes.should_continue_exploring,
                {
                    "generate_query": "generate_query",
                    "synthesize_response": "synthesize_response"
                }
            )
            
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

    def build_parallel_workflow(self) -> StateGraph:
        """
        Build the new parallel LangGraph workflow with batch processing.
        
        This creates a workflow that processes approaches in parallel batches
        instead of sequential execution, significantly improving performance.
        """
        logger.info("🏗️ Building Parallel LangGraph workflow...")
        
        try:
            from langgraph.constants import Send
            
            # Create StateGraph with AgentState  
            workflow = StateGraph(AgentState)
            
            # Add core workflow nodes
            workflow.add_node("initialize_environment", self.workflow_nodes.initialize_environment)
            workflow.add_node("initial_discovery", self.workflow_nodes.initial_discovery)
            workflow.add_node("analyze_intent", self.workflow_nodes.analyze_intent)
            
            # Add NEW parallel execution nodes
            workflow.add_node("initialize_parallel_execution", self.workflow_nodes.initialize_parallel_execution)
            workflow.add_node("create_approach_batch", self.workflow_nodes.create_approach_batch)
            
            # Parallel Think phase nodes
            workflow.add_node("route_parallel_think", self.workflow_nodes.route_parallel_think) 
            workflow.add_node("parallel_think_single", self.workflow_nodes.parallel_think_single)
            
            # Parallel Generate phase nodes
            workflow.add_node("route_parallel_generate", self.workflow_nodes.route_parallel_generate)
            workflow.add_node("parallel_generate_single", self.workflow_nodes.parallel_generate_single)
            
            # Batch Execute phase nodes (sequential due to CLI constraints)
            workflow.add_node("prepare_batch_execution", self.workflow_nodes.prepare_batch_execution)
            workflow.add_node("execute_batch_queries", self.workflow_nodes.execute_batch_queries)
            
            # Parallel Rethink phase nodes
            workflow.add_node("route_parallel_rethink", self.workflow_nodes.route_parallel_rethink)
            workflow.add_node("parallel_rethink_single", self.workflow_nodes.parallel_rethink_single)
            
            # Consolidation and synthesis nodes
            workflow.add_node("consolidate_batch_results", self.workflow_nodes.consolidate_batch_results)
            workflow.add_node("synthesize_response", self.workflow_nodes.synthesize_response)
            
            # Define workflow edges for parallel execution
            
            # Initial setup phase
            workflow.add_edge("initialize_environment", "initial_discovery")
            workflow.add_edge("initial_discovery", "analyze_intent")
            workflow.add_edge("analyze_intent", "initialize_parallel_execution")
            workflow.add_edge("initialize_parallel_execution", "create_approach_batch")
            
            # Parallel Think phase
            workflow.add_edge("create_approach_batch", "route_parallel_think")
            workflow.add_edge("route_parallel_think", "parallel_think_single")  # Send pattern routes to parallel execution
            workflow.add_edge("parallel_think_single", "route_parallel_generate")
            
            # Parallel Generate phase  
            workflow.add_edge("route_parallel_generate", "parallel_generate_single")  # Send pattern routes to parallel execution
            workflow.add_edge("parallel_generate_single", "prepare_batch_execution")
            
            # Sequential Execute phase (CLI constraint)
            workflow.add_edge("prepare_batch_execution", "execute_batch_queries")
            workflow.add_edge("execute_batch_queries", "route_parallel_rethink")
            
            # Parallel Rethink phase
            workflow.add_edge("route_parallel_rethink", "parallel_rethink_single")  # Send pattern routes to parallel execution
            workflow.add_edge("parallel_rethink_single", "consolidate_batch_results")
            
            # Batch continuation or synthesis decision
            workflow.add_conditional_edges(
                "consolidate_batch_results",
                self.workflow_nodes.route_parallel_execution,
                {
                    "create_approach_batch": "create_approach_batch",  # Continue with next batch
                    "synthesize_response": "synthesize_response"  # All batches done, synthesize
                }
            )
            
            # Set entry and exit points
            workflow.set_entry_point("initialize_environment") 
            workflow.set_finish_point("synthesize_response")
            
            # Compile the workflow with higher recursion limit for parallel execution
            compiled_workflow = workflow.compile()
            
            logger.info("✅ Parallel LangGraph workflow built successfully")
            return compiled_workflow
            
        except Exception as e:
            logger.error(f"❌ Parallel workflow building failed: {e}")
            raise Exception(f"Failed to build parallel workflow: {e}")

    async def run_workflow(self, user_query: str, project_name: str = "HelloWorldApp", 
                          max_iterations: int = 5, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute the complete CPG analysis workflow.
        
        Args:
            user_query: The user's question about the codebase
            project_name: Name of the project to analyze
            max_iterations: Maximum number of exploration iterations
            
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
                "current_query": None,
                "entities": [],  # Empty list, not None
                "disambiguated_entities": {},
                "discovered_data": [],  # Empty list, not None
                "raw_query_results": [],  # Empty list, not None
                "query_history": [],  # Empty list, not None
                "current_iteration": 1,
                "max_iterations": max_iterations,
                "should_continue": True,
                "response": "",
                "current_node": "",
                "schema": {},
                "llm_service": self.llm_service,
                "neo4j_config": metadata.get("neo4j_config") if metadata else None,
                "neo4j_version": "",
                "final_results": [],  # Empty list, not None
                "body_exploration_candidates": [],  # Empty list, not None
                "body_exploration_results": [],  # Empty list, not None
                "vector_results": None,
                "vector_collection_name": None,
                "sufficiency_evaluation": None,
                "organized_data": None,
                "discovery_research": None,
                # Think → Generate → Execute → Rethink workflow state
                "current_approach_index": 0,  # Start with first approach
                "total_approaches": 0,  # Will be set after research completes
                "current_scope": None,  # Will be determined by think step
                "current_approach_details": None,  # Will be set by think step
                "thinking_results": None,  # Results from think analysis
                "rethinking_results": None,  # Results from rethink analysis
                "fallback_mode": None,
                "diverse_queries_generated": None,
                "synthesis_context_used": None,
                # Execute step workflow state
                "generated_queries": [],  # Queries ready for execution
                "execution_results": [],  # Results from query execution
                "execution_analysis": None,  # Analysis of execution results
                "execution_status": None,  # Overall execution status
                "total_results_found": 0,  # Total results found across all executions
                "syntax_error_count": 0,  # Track syntax error retries to prevent infinite loops
                # NEW: Raw results tracking and progressive summarization
                "approach_raw_results": {},  # Dict[approach_index, [(query, results), ...]]
                "iteration_summaries": [],  # Progressive summaries to prevent context explosion
                "cumulative_findings": "",  # Running summary of findings
                # NEW: Rethink step state  
                "rethink_analysis": None,  # Current rethink analysis results
                "sufficiency_check_history": [],  # History of sufficiency checks
                "should_synthesize": False,  # Flag from rethink to determine if ready for synthesis
                # NEW: Parallel execution state management
                "current_batch_index": 0,  # Current batch being processed (0-based)
                "total_batches": 0,  # Total number of approach batches
                "batch_size": 2,  # Number of approaches per batch (default: 2-3)
                "current_batch_approaches": [],  # Approach indices in current batch
                "batch_results": {},  # Results by approach index for current batch
                # Parallel approach state tracking
                "parallel_thinking_results": {},  # Think results by approach index
                "parallel_generation_results": {},  # Generate results by approach index  
                "parallel_execution_results": {},  # Execute results by approach index
                "parallel_rethinking_results": {},  # Rethink results by approach index
                # Batch execution tracking
                "batch_query_payload": None,  # Prepared batch queries for CLI execution
                "batch_execution_complete": False,  # Flag indicating if current batch execution is done
                # Cumulative parallel results across all batches
                "all_thinking_results": {},  # All think results across batches
                "all_generation_results": {},  # All generate results across batches
                "all_execution_results": {},  # All execute results across batches
                "all_rethinking_results": {},  # All rethink results across batches
                "metadata": metadata or {}  # Store CLI parameter metadata
            }
            
            # Execute the workflow with recursion limit
            logger.info("⚡ Executing LangGraph workflow...")
            final_state = await self.workflow.ainvoke(
                initial_state,
                config={"recursion_limit": 50}
            )
            
            # Process final results - match original format exactly
            results = {
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
                "all_executed_queries": final_state.get("query_history", []),  # Use query_history for compatibility
                "raw_results": final_state.get("raw_query_results", []),  # MCP compatibility alias
                "executed_queries": final_state.get("query_history", []),  # MCP compatibility alias
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
            logger.info(f"📊 Final results: {len(results['discovered_data'])} items discovered")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Workflow execution failed: {e}")
            return {
                "status": "error", 
                "error": str(e),
                "response": f"Workflow execution failed: {e}",
                "discovered_data": [],
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
                "raw_results": [],
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

    async def run_parallel_workflow(self, user_query: str, project_name: str = "HelloWorldApp", 
                                   max_iterations: int = 5, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute the parallel CPG analysis workflow using batch processing.
        
        This method uses the new parallel workflow for significantly improved performance
        by processing approaches in parallel batches instead of sequential execution.
        
        Args:
            user_query: The user's question about the codebase
            project_name: Name of the project to analyze
            max_iterations: Maximum number of exploration iterations
            metadata: Additional metadata including CLI parameters
            
        Returns:
            Dictionary containing the final analysis results
        """
        logger.info(f"🚀 Starting PARALLEL CPG workflow for query: '{user_query}'")
        
        try:
            # Initialize services if not already done
            if not self.llm_service:
                await self.initialize_services()
            
            # Build parallel workflow
            parallel_workflow = self.build_parallel_workflow()
            
            # Initialize workflow state with parallel execution fields (using same structure as regular workflow)
            initial_state = {
                "user_query": user_query,
                "intent": "",
                "current_query": None,
                "entities": [],
                "disambiguated_entities": {},
                "discovered_data": [],
                "raw_query_results": [],
                "query_history": [],
                "current_iteration": 1,
                "max_iterations": max_iterations,
                "should_continue": True,
                "response": "",
                "current_node": "",
                "schema": {},
                "llm_service": self.llm_service,
                "neo4j_config": metadata.get("neo4j_config") if metadata else None,
                "neo4j_version": "",
                "final_results": [],
                "body_exploration_candidates": [],
                "body_exploration_results": [],
                "vector_results": None,
                "vector_collection_name": None,
                "sufficiency_evaluation": None,
                "organized_data": None,
                "discovery_research": None,
                # Original workflow state (maintained for compatibility)
                "current_approach_index": 0,
                "total_approaches": 0,
                "current_scope": None,
                "current_approach_details": None,
                "thinking_results": None,
                "rethinking_results": None,
                "fallback_mode": None,
                "diverse_queries_generated": None,
                "synthesis_context_used": None,
                "generated_queries": [],
                "execution_results": [],
                "execution_analysis": None,
                "execution_status": None,
                "total_results_found": 0,
                "syntax_error_count": 0,
                "approach_raw_results": {},
                "iteration_summaries": [],
                "cumulative_findings": "",
                "rethink_analysis": None,
                "sufficiency_check_history": [],
                "should_synthesize": False,
                # NEW: Parallel execution state management
                "current_batch_index": 0,
                "total_batches": 0,
                "batch_size": 2,  # Resource-conscious default
                "current_batch_approaches": [],
                "batch_results": {},
                "parallel_thinking_results": {},
                "parallel_generation_results": {},
                "parallel_execution_results": {},
                "parallel_rethinking_results": {},
                "batch_query_payload": None,
                "batch_execution_complete": False,
                "all_thinking_results": {},
                "all_generation_results": {},
                "all_execution_results": {},
                "all_rethinking_results": {},
                "metadata": metadata or {}
            }
            
            # Execute the parallel workflow with higher recursion limit
            logger.info("⚡ Executing PARALLEL LangGraph workflow...")
            final_state = await parallel_workflow.ainvoke(
                initial_state,
                config={"recursion_limit": 100}  # Higher limit for parallel execution
            )
            
            # Process final results - enhanced for parallel execution
            all_execution_results = final_state.get("all_execution_results", {})
            total_approaches_executed = len(all_execution_results)
            total_queries_executed = sum(len(result.get("queries", [])) for result in all_execution_results.values())
            total_results_found = sum(result.get("total_results", 0) for result in all_execution_results.values())
            
            results = {
                "status": "success" if not final_state.get("error") else "error",
                "response": final_state.get("response", ""),
                "discovered_data": final_state.get("discovered_data", []),
                "query_history": final_state.get("query_history", []),
                "iterations_used": final_state.get("current_iteration", 0),
                "final_results": final_state.get("final_results", []),
                "intent": final_state.get("intent", {}),
                "workflow": "parallel_langgraph_agent",  # Distinguish from sequential
                "organized_data": final_state.get("organized_data", {}),
                "architectural_summary": final_state.get("architectural_summary", {}),
                "synthesis_context_used": final_state.get("synthesis_context_used", 0),
                "raw_query_results": final_state.get("raw_query_results", []),
                "all_executed_queries": final_state.get("query_history", []),
                "raw_results": final_state.get("raw_query_results", []),
                "executed_queries": final_state.get("query_history", []),
                # Enhanced metadata for parallel execution
                "agent_metadata": {
                    "neo4j_version": "",
                    "schema_nodes": len(final_state.get("schema", {}).get("nodes", {})),
                    "total_queries_executed": total_queries_executed,
                    "total_raw_results": total_results_found,
                    "workflow_nodes_executed": 12,  # Parallel workflow has more nodes
                    "agents_involved": ["environment", "discovery", "intent", "parallel_executor", "synthesis"],
                    # NEW: Parallel execution metadata
                    "parallel_workflow_version": "1.0.0",
                    "batch_execution_enabled": True,
                    "total_approaches": final_state.get("total_approaches", 0),
                    "approaches_executed": total_approaches_executed,
                    "total_batches": final_state.get("total_batches", 0),
                    "batch_size": final_state.get("batch_size", 2),
                    "parallel_phases": ["think", "generate", "rethink"],
                    "sequential_phases": ["execute"],  # CLI constraint
                    "metadata": final_state.get("metadata", {})
                },
                "error": final_state.get("error")
            }
            
            logger.info(f"✅ PARALLEL Workflow completed: {total_approaches_executed} approaches, {total_queries_executed} queries, {total_results_found} results")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Parallel workflow execution failed: {e}")
            return {
                "status": "error", 
                "error": str(e),
                "response": f"Parallel workflow execution failed: {e}",
                "workflow": "parallel_langgraph_agent",
                "agent_metadata": {
                    "parallel_workflow_version": "1.0.0",
                    "batch_execution_enabled": False,
                    "error": str(e)
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

async def create_adaptive_cpg_workflow() -> AdaptiveCPGAgentWorkflow:
    """
    Create and initialize an AdaptiveCPGAgentWorkflow instance.
    
    Returns:
        Fully initialized workflow ready to execute
    """
    workflow = AdaptiveCPGAgentWorkflow()
    await workflow.initialize_services()
    workflow.workflow = workflow.build_workflow()
    return workflow


async def execute_adaptive_cpg_workflow(user_query: str, project_name: str = "HelloWorldApp", 
                                       max_iterations: int = 5, neo4j_config: str = None,
                                       project_path: str = None, mappings_path: str = None, 
                                       queries_path: str = None) -> Dict[str, Any]:
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
        
    Returns:
        Complete workflow results with 'status' field for backwards compatibility
    """
    workflow = await create_adaptive_cpg_workflow()
    
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
        print(f"📊 Data Items: {len(results['discovered_data'])}")
        print(f"🔄 Iterations: {results['iterations_used']}")
        print(f"✅ Success: {results['success']}")
        
    except Exception as e:
        logger.error(f"❌ Test execution failed: {e}")
        print(f"❌ Test failed: {e}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
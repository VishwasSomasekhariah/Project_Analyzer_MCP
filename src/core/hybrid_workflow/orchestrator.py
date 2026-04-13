"""
Hybrid Workflow Orchestrator

Main LangGraph workflow orchestrator that combines Vector and CPG retrievers
with sophisticated synthesis and validation for comprehensive code analysis.
"""
import logging
import pickle
from langgraph.graph import StateGraph
from typing import Dict, Any

from .models import HybridState
from .nodes import HybridWorkflowNodes

logger = logging.getLogger(__name__)


class HybridRAGWorkflow:
    """
    Hybrid RAG Workflow using LangGraph orchestration.
    
    Combines Vector and CPG retrievers with sophisticated synthesis,
    cross-validation, and critic-based quality assurance for 
    comprehensive code analysis.
    
    Workflow Graph:
    intent_analysis -> [vector_retrieval, cpg_retrieval] -> combine_results -> synthesize_response -> critic_validation
    
    Key Features:
    - Intent-based query routing and weighting
    - Parallel retrieval from Vector and CPG sources  
    - Intelligent result batching for context management
    - Cross-validation between retrievers
    - Chain-of-thought synthesis
    - Critic validation for hallucination/faithfulness checking
    - Smart fallback strategies
    """
    
    def __init__(self):
        """Initialize the hybrid workflow orchestrator."""
        self.workflow_nodes = HybridWorkflowNodes()
        self.workflow = None
        self.is_built = False
    
    def build_workflow(self) -> StateGraph:
        """
        Build the LangGraph workflow with proper node connections.
        
        Returns:
            StateGraph: Configured workflow graph
        """
        logger.info("🏗️ Building Hybrid RAG workflow...")
        
        # Create state graph
        workflow = StateGraph(HybridState)
        
        # Add nodes
        workflow.add_node("intent_analysis", self.workflow_nodes.intent_analysis)
        workflow.add_node("vector_retrieval", self.workflow_nodes.vector_retrieval)  
        workflow.add_node("cpg_retrieval", self.workflow_nodes.cpg_retrieval)
        workflow.add_node("combine_results", self.workflow_nodes.combine_results)
        workflow.add_node("synthesize_response", self.workflow_nodes.synthesize_response)
        workflow.add_node("critic_validation", self.workflow_nodes.critic_validation)
        
        # Set entry point
        workflow.set_entry_point("intent_analysis")
        
        # Add edges for workflow flow
        workflow.add_edge("intent_analysis", "vector_retrieval")
        workflow.add_edge("intent_analysis", "cpg_retrieval")
        workflow.add_edge("vector_retrieval", "combine_results")
        workflow.add_edge("cpg_retrieval", "combine_results") 
        workflow.add_edge("combine_results", "synthesize_response")
        workflow.add_edge("synthesize_response", "critic_validation")
        workflow.add_edge("critic_validation", "__end__")
        
        # Compile workflow
        self.workflow = workflow.compile()
        self.is_built = True
        
        logger.info("✅ Hybrid RAG workflow built successfully")
        return self.workflow
    
    async def run_analysis(
        self, 
        user_query: str, 
        llm_service: Any,
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Run complete hybrid analysis workflow.
        
        Args:
            user_query: User's natural language query
            llm_service: LLM service instance
            config: Optional configuration parameters
            
        Returns:
            Complete analysis result with synthesis and validation
        """
        logger.info(f"🚀 Starting Hybrid RAG analysis for: '{user_query}'")
        
        try:
            # Build workflow if not already built
            if not self.is_built:
                self.build_workflow()
            
            # Initialize state with ALL required fields
            config = config or {}
            initial_state = HybridState(
                # Input (required)
                user_query=user_query,
                llm_service=llm_service,
                
                # Intent Analysis (initialized as None, will be set by intent_analysis node)
                intent_analysis=None,
                
                # Retrieval Results (initialized as None, will be set by retrieval nodes)
                vector_result=None,
                cpg_result=None,
                
                # Combined Results (initialized as empty, will be populated by combine_results node)
                combined_raw_results=[],
                batched_results=[],
                
                # Synthesis (initialized as None, will be set by synthesize_response node)
                synthesis_result=None,
                
                # Validation (initialized as None, will be set by critic_validation node)
                critic_validation=None,
                
                # Context Management (configurable)
                context_size=0,
                batch_size=config.get("batch_size", 5),
                max_context_limit=config.get("max_context_limit", 100000),
                
                # Execution Metadata (tracking)
                execution_metadata={
                    "config": config,
                    "workflow_version": "1.0.0",
                    "start_time": __import__('time').time()
                },
                error_log=[]
            )
            
            # Execute workflow
            logger.info("⚡ Executing Hybrid RAG workflow...")
            final_state = await self.workflow.ainvoke(initial_state)
            
            # Dump state to pickle file for debugging
            try:
                # Create a serializable copy of the state by excluding non-serializable objects
                serializable_state = {}
                for key, value in final_state.items():
                    if key == "llm_service":
                        # Skip the LLM service object as it contains thread locks
                        serializable_state[key] = "<LLM_SERVICE_OBJECT_EXCLUDED>"
                    else:
                        serializable_state[key] = value
                
                with open("HYBRIDSTATE.pkl", "wb") as f:
                    pickle.dump(serializable_state, f)
                logger.info("💾 Final state dumped to HYBRIDSTATE.pkl")
            except Exception as e:
                logger.warning(f"⚠️ Failed to dump state to pickle: {e}")
            
            # Format final result
            result = self._format_final_result(final_state)
            
            logger.info(f"✅ Hybrid RAG analysis completed successfully")
            vector_result = final_state.get("vector_result")
            cpg_result = final_state.get("cpg_result")  
            synthesis_result = final_state.get("synthesis_result")
            
            logger.info(f"📊 Results: Vector={len(vector_result.raw_results) if vector_result else 0}, "
                       f"CPG={len(cpg_result.raw_results) if cpg_result else 0}, "
                       f"Synthesis={synthesis_result.status if synthesis_result else 'none'}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Hybrid RAG analysis failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "user_query": user_query,
                "analysis_type": "hybrid_rag",
                "synthesis": {
                    "answer": "Analysis failed due to system error",
                    "details": f"Error: {str(e)}",
                    "confidence": 0.0,
                    "status": "error"
                }
            }
    
    def _format_final_result(self, final_state: Dict[str, Any]) -> Dict[str, Any]:
        """Format final workflow result for client consumption"""
        
        # Extract synthesis result
        synthesis = {}
        synthesis_result = final_state.get("synthesis_result")
        if synthesis_result:
            synthesis = {
                "answer": synthesis_result.answer,
                "details": synthesis_result.details,
                "confidence": synthesis_result.confidence,
                "status": synthesis_result.status,
                "suggestions": synthesis_result.suggestions,
                "strategy_used": synthesis_result.strategy_used.value,
                "cross_validation": {
                    "vector_validates_cpg": synthesis_result.cross_validation.vector_validates_cpg,
                    "cpg_validates_vector": synthesis_result.cross_validation.cpg_validates_vector,
                    "conflicts_found": synthesis_result.cross_validation.conflicts_found,
                    "consensus_points": synthesis_result.cross_validation.consensus_points,
                    "confidence_score": synthesis_result.cross_validation.confidence_score
                }
            }
        
        # Extract critic validation
        critic_validation = {}
        critic_val_result = final_state.get("critic_validation")
        if critic_val_result:
            critic_validation = {
                "decision": critic_val_result.decision,
                "overall_score": critic_val_result.overall_score,
                "hallucination_score": critic_val_result.hallucination_score,
                "faithfulness_score": critic_val_result.faithfulness_score,
                "accuracy_score": critic_val_result.accuracy_score,
                "validation_issues": critic_val_result.validation_issues,
                "improvement_suggestions": critic_val_result.improvement_suggestions
            }
        
        # Extract retrieval metadata
        vector_result = final_state.get("vector_result")
        cpg_result = final_state.get("cpg_result")
        
        retrieval_results = {
            "vector": {
                "status": vector_result.status.value if vector_result else "not_executed",
                "results_count": len(vector_result.raw_results) if vector_result else 0,
                "execution_time": vector_result.execution_time if vector_result else 0.0,
                "error": vector_result.error if vector_result else None
            },
            "cpg": {
                "status": cpg_result.status.value if cpg_result else "not_executed", 
                "results_count": len(cpg_result.raw_results) if cpg_result else 0,
                "execution_time": cpg_result.execution_time if cpg_result else 0.0,
                "error": cpg_result.error if cpg_result else None
            }
        }
        
        # Calculate total execution time
        total_execution_time = (
            (vector_result.execution_time if vector_result else 0.0) +
            (cpg_result.execution_time if cpg_result else 0.0)
        )
        
        # Extract intent analysis
        intent_analysis = final_state.get("intent_analysis")
        
        return {
            "status": "success",
            "analysis_type": "hybrid_rag", 
            "user_query": final_state.get("user_query"),
            
            # Intent Analysis
            "intent_analysis": {
                "intent": intent_analysis.intent.value if intent_analysis else "unknown",
                "confidence": intent_analysis.confidence if intent_analysis else 0.0,
                "vector_weight": intent_analysis.vector_weight if intent_analysis else 0.5,
                "cpg_weight": intent_analysis.cpg_weight if intent_analysis else 0.5,
                "reasoning": intent_analysis.reasoning if intent_analysis else ""
            },
            
            # Retrieval Results
            "retrieval_results": retrieval_results,
            
            # Combined Results
            "combined_results": {
                "total_results": len(final_state.get("combined_raw_results", [])),
                "batches_created": len(final_state.get("batched_results", [])),
                "context_size": final_state.get("context_size", 0)
            },
            
            # Synthesis Result (main output)
            "synthesis": synthesis,
            
            # Quality Validation
            "critic_validation": critic_validation,
            
            # Full Individual RAG Responses (for benchmarking/evaluation)
            # These contain the complete response from each retriever as if run independently
            "vector_full_response": {
                "status": vector_result.status.value if vector_result else "not_executed",
                "ai_response": vector_result.response_text if vector_result else "",
                "raw_results": vector_result.raw_results if vector_result else [],
                "metadata": vector_result.metadata if vector_result else {},
                "execution_time_ms": int(vector_result.execution_time * 1000) if vector_result else 0,
                "error": vector_result.error if vector_result else ""
            },
            "cpg_full_response": {
                "status": cpg_result.status.value if cpg_result else "not_executed",
                "ai_response": cpg_result.response_text if cpg_result else "",
                "raw_results": cpg_result.raw_results if cpg_result else [],
                "metadata": cpg_result.metadata if cpg_result else {},
                "execution_time_ms": int(cpg_result.execution_time * 1000) if cpg_result else 0,
                "error": cpg_result.error if cpg_result else ""
            },

            # Raw Results for Advanced Use Cases (legacy format)
            "raw_results": {
                "vector_results": vector_result.raw_results if vector_result else [],
                "cpg_results": cpg_result.raw_results if cpg_result else [],
                "combined_results": final_state.get("combined_raw_results", [])
            },
            
            # Performance Metadata
            "performance": {
                "total_execution_time": total_execution_time,
                "vector_execution_time": vector_result.execution_time if vector_result else 0.0,
                "cpg_execution_time": cpg_result.execution_time if cpg_result else 0.0,
                "context_management": {
                    "max_context_limit": final_state.get("max_context_limit", 100000),
                    "actual_context_size": final_state.get("context_size", 0),
                    "batch_size": final_state.get("batch_size", 5),
                    "batches_processed": len(final_state.get("batched_results", []))
                }
            },
            
            # Error Handling
            "errors": final_state.get("error_log", []),
            
            # Execution Metadata
            "metadata": final_state.get("execution_metadata", {})
        }
    
    def get_workflow_status(self) -> Dict[str, Any]:
        """Get current workflow status and configuration"""
        return {
            "workflow_built": self.is_built,
            "nodes_available": [
                "intent_analysis",
                "vector_retrieval", 
                "cpg_retrieval",
                "combine_results",
                "synthesize_response",
                "critic_validation"
            ],
            "workflow_type": "hybrid_rag",
            "version": "1.0.0"
        }
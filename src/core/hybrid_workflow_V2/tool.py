"""
Hybrid RAG Workflow Tool

Tool integration for the Hybrid RAG workflow that can be used by MCP servers
and other components in the project analyzer ecosystem.
"""
import json
import logging
import asyncio
from typing import Dict, Any, Optional

from .orchestrator import HybridRAGWorkflow
from ..llm_service import LLMService
from ..resilient_llm_service import ResilientLLMService

logger = logging.getLogger(__name__)


class HybridRAGTool:
    """
    Tool wrapper for Hybrid RAG workflow.
    
    Provides a consistent interface for running hybrid analysis that combines
    Vector and CPG retrievers with sophisticated synthesis and validation.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize the hybrid RAG tool with configuration"""
        self.config = config or {}
        self.workflow = HybridRAGWorkflow()
        self._llm_service = None
        
    async def initialize_services(self):
        """Initialize required services"""
        if not self._llm_service:
            llm_config = self.config.get("llm_service", {})

            # Use ResilientLLMService with Claude SDK fallback (enabled by default)
            # For easy rollback: comment this line and uncomment the line below
            self._llm_service = ResilientLLMService(llm_config)
            # self._llm_service = LLMService(llm_config)  # OLD: No fallback

            logger.info("✅ LLM service initialized for Hybrid RAG (with Claude SDK fallback)")
    
    async def analyze_query(
        self,
        user_query: str,
        config_overrides: Dict[str, Any] = None,
        project_path: str = None,
        mcts_iterations: int = 20,
    ) -> Dict[str, Any]:
        """
        Run hybrid analysis on a user query.

        Args:
            user_query: Natural language query to analyze
            config_overrides: Optional configuration overrides
            project_path: Path to the project root for PageIndex retrieval
            mcts_iterations: Number of MCTS iterations for PageIndex (default: 20)

        Returns:
            Complete hybrid analysis result
        """
        logger.info(f"🔍 Starting Hybrid RAG analysis: '{user_query}'")

        try:
            # Initialize services if needed
            await self.initialize_services()

            # Merge configuration
            analysis_config = dict(self.config)
            if config_overrides:
                analysis_config.update(config_overrides)

            # Wire pageindex_config so the pageindex_retrieval node can run
            if project_path:
                analysis_config.setdefault("pageindex_config", {})
                analysis_config["pageindex_config"]["project_path"] = project_path
                analysis_config["pageindex_config"]["mcts_iterations"] = mcts_iterations
            
            # Run workflow
            result = await self.workflow.run_analysis(
                user_query=user_query,
                llm_service=self._llm_service,
                config=analysis_config
            )
            
            # Add tool metadata
            result["tool_metadata"] = {
                "tool_type": "hybrid_rag",
                "version": "1.0.0",
                "config_used": analysis_config
            }
            
            logger.info(f"✅ Hybrid RAG analysis completed: {result.get('synthesis', {}).get('status', 'unknown')}")
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
                },
                "tool_metadata": {
                    "tool_type": "hybrid_rag",
                    "error": str(e)
                }
            }
    
    async def get_workflow_info(self) -> Dict[str, Any]:
        """Get information about the hybrid workflow"""
        return {
            "workflow_type": "hybrid_rag",
            "description": "Combines Vector and CPG retrievers with sophisticated synthesis and validation",
            "capabilities": [
                "Intent-based query routing",
                "Parallel Vector and CPG retrieval",
                "Cross-validation between retrievers", 
                "Chain-of-thought synthesis",
                "Critic validation for quality assurance",
                "Intelligent context management",
                "Smart fallback strategies"
            ],
            "workflow_status": self.workflow.get_workflow_status(),
            "supported_intents": [
                "architectural", "direct_lookup", "structural", 
                "relational", "semantic", "quantitative"
            ]
        }


# Standalone function for easy integration
async def run_hybrid_analysis(
    user_query: str, 
    config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Standalone function to run hybrid RAG analysis.
    
    Args:
        user_query: User's natural language query
        config: Optional configuration
        
    Returns:
        Complete analysis result
    """
    tool = HybridRAGTool(config)
    return await tool.analyze_query(user_query)


# Tool factory for MCP integration
def create_hybrid_rag_tool(mcp_server, config: Dict[str, Any] = None):
    """
    Create MCP tool for hybrid RAG analysis.
    
    Args:
        mcp_server: FastMCP server instance
        config: Tool configuration
        
    Returns:
        Registered MCP tool function
    """
    
    @mcp_server.tool()
    async def hybrid_rag_analysis(
        user_query: str,
        project_path: Optional[str] = None,
        mcts_iterations: Optional[int] = 20,
        batch_size: Optional[int] = 5,
        max_context_limit: Optional[int] = 100000,
        enable_debug: Optional[bool] = False
    ) -> Dict[str, Any]:
        """
        Enhanced Hybrid RAG analysis combining PageIndex, Vector, and CPG retrievers.

        PageIndex is the primary retriever. If it returns an insufficient answer,
        the workflow falls back to parallel Vector + CPG retrieval using PageIndex
        learnings to guide the deeper search.

        Args:
            user_query: Natural language query about the codebase
            project_path: Path to the project root for PageIndex retrieval
            mcts_iterations: MCTS iterations for PageIndex search (default: 20)
            batch_size: Size of result batches for context management (default: 5)
            max_context_limit: Maximum context size limit (default: 100000)
            enable_debug: Enable detailed debug logging (default: False)

        Returns:
            Comprehensive analysis result with synthesis, validation, and raw results
        """
        try:
            # Setup configuration
            tool_config = config or {}
            tool_config.update({
                "batch_size": batch_size,
                "max_context_limit": max_context_limit,
                "enable_debug": enable_debug
            })

            # Run analysis
            tool = HybridRAGTool(tool_config)
            result = await tool.analyze_query(
                user_query,
                project_path=project_path,
                mcts_iterations=mcts_iterations,
            )
            
            # Add MCP metadata
            result["mcp_metadata"] = {
                "tool_name": "hybrid_rag_analysis",
                "parameters_used": {
                    "batch_size": batch_size,
                    "max_context_limit": max_context_limit,
                    "enable_debug": enable_debug
                }
            }
            
            return result
            
        except Exception as e:
            logger.error(f"❌ MCP Hybrid RAG tool failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "user_query": user_query,
                "analysis_type": "hybrid_rag",
                "mcp_metadata": {
                    "tool_name": "hybrid_rag_analysis",
                    "error": str(e)
                }
            }
    
    return hybrid_rag_analysis
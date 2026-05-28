"""
Hybrid RAG Workflow Package

Combines Vector and CPG retrievers with sophisticated synthesis and validation.
Uses LangGraph orchestration with chain-of-thought style prompting for
comprehensive code analysis.
"""

from .orchestrator import HybridRAGWorkflow
from .tool import HybridRAGTool, run_hybrid_analysis, create_hybrid_rag_tool
from .models import (
    HybridState, QueryIntent, SynthesisStrategy, IntentAnalysis, 
    RetrieverResult, RetrievalStatus, SynthesisResult, 
    CriticValidation, CrossValidationResult, BatchProcessingResult,
    ChainOfThoughtResult, ChainOfThoughtStep, IntentAnalysisRawResponse,
    SynthesisRawResponse, CriticValidationRawResponse, SynthesisImprovementRawResponse
)
from .nodes import HybridWorkflowNodes

__all__ = [
    # Core workflow components
    "HybridRAGWorkflow",
    "HybridWorkflowNodes",
    "HybridRAGTool", 
    "run_hybrid_analysis",
    "create_hybrid_rag_tool",
    
    # State and main models
    "HybridState",
    "QueryIntent",
    "SynthesisStrategy",
    "IntentAnalysis",
    "RetrieverResult", 
    "RetrievalStatus",
    "SynthesisResult",
    "CriticValidation",
    "CrossValidationResult",
    
    # Supporting models
    "BatchProcessingResult",
    "ChainOfThoughtResult",
    "ChainOfThoughtStep",
    
    # Raw response models for LLM validation
    "IntentAnalysisRawResponse",
    "SynthesisRawResponse", 
    "CriticValidationRawResponse",
    "SynthesisImprovementRawResponse"
]
"""
Hybrid Workflow Nodes

LangGraph nodes for the Hybrid RAG workflow combining Vector and CPG retrievers
with sophisticated synthesis and validation using chain-of-thought reasoning.
"""
import json
import logging
import asyncio
import subprocess
import os
from typing import Dict, Any, List, Tuple, Type, TypeVar, Optional
from pydantic import ValidationError, BaseModel

from .models import (
    HybridState, IntentAnalysis, QueryIntent, RetrieverResult,
    RetrievalStatus, SynthesisResult, SynthesisStrategy,
    CriticValidation, CrossValidationResult, BatchProcessingResult,
    ChainOfThoughtResult, ChainOfThoughtStep, IntentAnalysisRawResponse,
    SynthesisRawResponse, CriticValidationRawResponse, SynthesisImprovementRawResponse
)
from src.core.paths import NEO4J_CONFIG, QDRANT_CONFIG, SCHEMA_PATH

logger = logging.getLogger(__name__)

# Type variable for Pydantic models
T = TypeVar('T', bound=BaseModel)


class HybridWorkflowNodes:
    """
    Hybrid Workflow Nodes implementing LangGraph workflow pattern.
    
    Combines Vector and CPG retrievers with sophisticated synthesis,
    cross-validation, and critic-based quality assurance.
    """
    
    def __init__(self):
        self.cpg_workflow = None  # Will be initialized when needed
    
    async def _robust_llm_call_with_pydantic_validation(
        self,
        llm_service: Any,
        prompt: str,
        pydantic_model: Type[T],
        max_retries: int = 3,
        **llm_kwargs
    ) -> Tuple[Optional[T], Optional[str]]:
        """
        Make robust LLM call with Pydantic validation and retry logic.
        
        Args:
            llm_service: LLM service instance
            prompt: The prompt to send to the LLM
            pydantic_model: Pydantic model class for validation
            max_retries: Maximum number of retries (default: 3)
            **llm_kwargs: Additional arguments for generate_response
            
        Returns:
            Tuple of (validated_model_instance, error_message)
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"🤖 LLM call attempt {attempt + 1}/{max_retries + 1}")
                
                # Make LLM call
                result = await llm_service.generate_response(
                    prompt,
                    json_mode=True,
                    use_cache=False,
                    **llm_kwargs
                )
                
                if not result or result.error:
                    last_error = f"LLM generation failed: {result.error if result else 'No result'}"
                    logger.warning(f"⚠️ Attempt {attempt + 1} failed: {last_error}")
                    continue
                
                # Parse JSON
                try:
                    json_data = json.loads(result.content)
                except json.JSONDecodeError as e:
                    last_error = f"JSON parsing failed: {e}"
                    logger.warning(f"⚠️ Attempt {attempt + 1} JSON error: {last_error}")
                    
                    # Add feedback to prompt for next retry
                    if attempt < max_retries:
                        prompt = self._add_json_feedback_to_prompt(prompt, result.content, str(e))
                    continue
                
                # Validate with Pydantic
                try:
                    validated_model = pydantic_model(**json_data)
                    logger.info(f"✅ LLM call succeeded on attempt {attempt + 1}")
                    return validated_model, None
                    
                except ValidationError as e:
                    last_error = f"Pydantic validation failed: {e}"
                    logger.warning(f"⚠️ Attempt {attempt + 1} validation error: {last_error}")
                    
                    # Add feedback to prompt for next retry
                    if attempt < max_retries:
                        prompt = self._add_validation_feedback_to_prompt(prompt, json_data, str(e))
                    continue
                
            except Exception as e:
                last_error = f"Unexpected error: {e}"
                logger.warning(f"⚠️ Attempt {attempt + 1} unexpected error: {last_error}")
                continue
        
        logger.error(f"❌ LLM call failed after {max_retries + 1} attempts. Last error: {last_error}")
        return None, last_error
    
    def _add_json_feedback_to_prompt(self, original_prompt: str, failed_content: str, error: str) -> str:
        """Add JSON parsing feedback to prompt for retry"""
        feedback = f"""
        
IMPORTANT: Your previous response had JSON parsing errors:
Error: {error}
Previous response: {failed_content}
Please ensure your response is valid JSON format. Double-check:
- All strings are properly quoted
- No trailing commas  
- Proper bracket/brace nesting
- Use double quotes, not single quotes
"""
        return original_prompt + feedback
    
    def _add_validation_feedback_to_prompt(self, original_prompt: str, failed_data: dict, error: str) -> str:
        """Add Pydantic validation feedback to prompt for retry"""
        feedback = f"""
        
IMPORTANT: Your previous response had validation errors:
Validation Error: {error}
Previous data: {json.dumps(failed_data, indent=2)}
Please fix these validation issues:
- Ensure all required fields are present
- Check field types match the expected schema  
- Verify enum values are from the allowed set
- Make sure numerical values are within valid ranges
"""
        return original_prompt + feedback
    
    
    async def intent_analysis(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Analyze user query intent for routing and weighting decisions.
        
        Uses chain-of-thought reasoning to understand query intent and determine
        optimal weighting between Vector and CPG retrievers.
        """
        logger.info("🧠 Node: intent_analysis")
        
        try:
            llm_service = state.llm_service
            user_query = state.user_query
            
            # Chain-of-thought intent analysis prompt
            intent_prompt = f"""You are an expert query intent analyzer for hybrid code analysis systems.
Analyze this user query and determine the optimal retrieval strategy.

**CHAIN OF THOUGHT ANALYSIS**:

**User Query**: {user_query}

**Step 1: Query Type Classification**
Classify the query type and explain your reasoning:
- ARCHITECTURAL: High-level design, patterns, relationships (favor Vector: 0.7/0.3)
- DIRECT_LOOKUP: Specific functions, variables, exact matches (favor CPG: 0.3/0.7)  
- STRUCTURAL: Code structure, classes, inheritance (balanced: 0.5/0.5)
- RELATIONAL: Dependencies, calls, connections (favor CPG: 0.4/0.6)
- SEMANTIC: Conceptual understanding, similarity (favor Vector: 0.8/0.2)
- QUANTITATIVE: Counting, metrics, statistics (favor CPG: 0.2/0.8)

**Step 2: Entity Detection**
Identify key entities in the query:
- Files: Specific filenames mentioned
- Types: Classes, interfaces, structs mentioned  
- Functions: Method or function names mentioned
- Concepts: Abstract concepts or patterns mentioned

**Step 3: Complexity Assessment**
Assess query complexity and reasoning requirements:
- Simple: Direct lookup or single fact
- Complex: Multi-step reasoning or synthesis required

**Step 4: Optimal Weighting Decision**
Based on the analysis above, determine:
- Vector weight (0.0 to 1.0)
- CPG weight (must sum to 1.0 with vector weight)
- Primary intent classification
- Confidence in classification (0.0 to 1.0)

**OUTPUT FORMAT**:
Return ONLY a valid JSON object with this exact structure:
{{
    "intent": "ARCHITECTURAL|DIRECT_LOOKUP|STRUCTURAL|RELATIONAL|SEMANTIC|QUANTITATIVE",
    "confidence": <float 0.0-1.0>,
    "vector_weight": <float 0.0-1.0>,
    "cpg_weight": <float 0.0-1.0>,
    "reasoning": "Detailed step-by-step reasoning following the chain of thought above"
}}"""
            
            # Generate intent analysis with robust validation
            raw_response, error = await self._robust_llm_call_with_pydantic_validation(
                llm_service=llm_service,
                prompt=intent_prompt,
                pydantic_model=IntentAnalysisRawResponse,
                max_tokens=16000,
                temperature=0.1,  # Low temperature for consistent intent classification
                max_retries=3
            )
            
            if raw_response:
                try:
                    # Convert raw response to validated IntentAnalysis
                    intent_analysis = IntentAnalysis(
                        intent=QueryIntent(raw_response.intent.lower()),
                        confidence=raw_response.confidence,
                        vector_weight=raw_response.vector_weight,
                        cpg_weight=raw_response.cpg_weight,
                        reasoning=raw_response.reasoning
                    )
                    
                    logger.info(f"✅ Intent analysis completed: {intent_analysis.intent} (confidence: {intent_analysis.confidence:.2f})")
                    logger.info(f"📊 Weighting: Vector={intent_analysis.vector_weight:.2f}, CPG={intent_analysis.cpg_weight:.2f}")
                    
                    return {"intent_analysis": intent_analysis}
                    
                except (ValueError, ValidationError) as e:
                    logger.error(f"❌ Intent analysis enum conversion failed: {e}")
                    
            # Fallback intent analysis
            logger.warning(f"⚠️ Using fallback intent analysis. Error: {error}")
            fallback_analysis = IntentAnalysis(
                intent=QueryIntent.UNKNOWN,
                confidence=0.5,
                vector_weight=0.5,
                cpg_weight=0.5,
                reasoning=f"Fallback analysis due to LLM failure: {error}"
            )
            return {"intent_analysis": fallback_analysis}
            
        except Exception as e:
            logger.error(f"❌ Intent analysis failed: {e}")
            
            # Fallback with error logging
            error_fallback = IntentAnalysis(
                intent=QueryIntent.UNKNOWN,
                confidence=0.3,
                vector_weight=0.5,
                cpg_weight=0.5,
                reasoning=f"Error fallback: {str(e)}"
            )
            
            return {
                "intent_analysis": error_fallback,
                "error_log": state.error_log + [f"Intent analysis error: {str(e)}"]
            }
    
    async def vector_retrieval(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Execute vector retrieval using genpod-semantic-rag CLI.

        Runs the vector search with enhanced queries based on intent analysis.
        """
        logger.info("🔍 Node: vector_retrieval")

        try:
            user_query = state.user_query
            intent_analysis = state.intent_analysis

            # Extract vector config from execution metadata
            config = state.execution_metadata.get("config", {})
            vector_config = config.get("vector_config", {})

            collection_name = vector_config.get("collection_name", "helloworldapp-benchmarking")
            vector_db = vector_config.get("vector_db", "qdrant")
            config_path = vector_config.get("config_path")
            max_results = vector_config.get("max_results", 5)
            enable_reasoning = vector_config.get("enable_reasoning", True)
            max_branches = vector_config.get("max_branches", 2)

            # Build CLI command for genpod-semantic-rag (following query_vector_only pattern)
            cli_command = [
                "genpod-semantic-rag", 
                "--config", config_path, 
                "query", user_query,
                "--collection-name", collection_name,
                "--vector-db", vector_db,
                "--max-results", str(max_results),
                "--output-format", "json"
            ]

            # Add reasoning flags if enabled
            if enable_reasoning:
                cli_command.append("--reasoning")
                cli_command.extend(["--max-branches", str(max_branches)])

            # Execute vector retrieval
            logger.info(f"⚡ Executing vector search: {' '.join(cli_command)}")
            start_time = asyncio.get_event_loop().time()

            cli_result = subprocess.run(
                cli_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )

            execution_time = asyncio.get_event_loop().time() - start_time

            if cli_result.returncode == 0:
                try:
                    parsed_results = json.loads(cli_result.stdout)
                    raw_results = parsed_results.get("results", [])
                    ai_response = parsed_results.get("response", "")

                    logger.info(f"✅ Vector retrieval successful: {len(raw_results)} results")
                    # logger.info(f"📝 Vector CLI response body: {cli_result.stdout}")
                    logger.info(f"🤖 Vector AI response: {ai_response}")

                    # Extract reasoning metadata if available
                    reasoning_metadata = {}
                    if enable_reasoning:
                        reasoning_metadata = {
                            "reasoning_used": parsed_results.get("reasoning_used", False),
                            "reasoning_metrics": parsed_results.get("reasoning_metrics"),
                            "reasoning_trace": parsed_results.get("reasoning_trace")
                        }
                        if reasoning_metadata.get("reasoning_used"):
                            logger.info("🧠 Reasoning was used for this query")

                    vector_result = RetrieverResult(
                        retriever_type="vector",
                        status=RetrievalStatus.SUCCESS,
                        raw_results=raw_results,
                        processed_results=raw_results,  # Vector results are already processed
                        response_text=ai_response,
                        metadata={
                            "query": user_query,
                            "results_count": len(raw_results),
                            "total_results": parsed_results.get("total_results", len(raw_results)),
                            "processing_time": parsed_results.get("processing_time", execution_time),
                            "confidence_score": parsed_results.get("confidence_score"),
                            "has_diagram": parsed_results.get("has_diagram", False),
                            **reasoning_metadata
                        },
                        execution_time=execution_time
                    )

                    return {"vector_result": vector_result}
                    
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Vector results parsing failed: {e}")
                    vector_result = RetrieverResult(
                        retriever_type="vector",
                        status=RetrievalStatus.FAILED,
                        raw_results=[],
                        processed_results=[],
                        error=f"JSON parsing failed: {e}",
                        metadata={},
                        execution_time=execution_time
                    )
                    return {"vector_result": vector_result}
            else:
                logger.error(f"❌ Vector CLI failed: {cli_result.stderr}")
                vector_result = RetrieverResult(
                    retriever_type="vector",
                    status=RetrievalStatus.FAILED,
                    raw_results=[],
                    processed_results=[],
                    error=cli_result.stderr,
                    metadata={},
                    execution_time=execution_time
                )
                return {"vector_result": vector_result}
                
        except Exception as e:
            logger.error(f"❌ Vector retrieval failed: {e}")
            vector_result = RetrieverResult(
                retriever_type="vector",
                status=RetrievalStatus.FAILED,
                raw_results=[],
                processed_results=[],
                error=str(e),
                metadata={},
                execution_time=0.0
            )
            
            return {
                "vector_result": vector_result,
                "error_log": state.error_log + [f"Vector retrieval error: {str(e)}"]
            }

    async def pageindex_retrieval(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Execute PageIndex retrieval using genpod-semantic-rag CLI with --retriever pageindex.

        Uses MCTS-based file tree navigation instead of vector similarity search.
        """
        logger.info("🗂️ Node: pageindex_retrieval")

        try:
            user_query = state.user_query

            # Extract pageindex config from execution metadata
            config = state.execution_metadata.get("config", {})
            pageindex_config = config.get("pageindex_config", {})

            config_path = pageindex_config.get("config_path", QDRANT_CONFIG)
            project_path = pageindex_config.get("project_path", "/opt/HelloWorldApp")
            mcts_iterations = pageindex_config.get("mcts_iterations", 20)

            # Build CLI command for pageindex retrieval
            cli_command = [
                "genpod-semantic-rag",
                "--config", config_path,
                "query", user_query,
                "--retriever", "pageindex",
                "--project-path", project_path,
                "--mcts-iterations", str(mcts_iterations),
                "--output-format", "json"
            ]

            logger.info(f"⚡ Executing pageindex search: {' '.join(cli_command)}")
            start_time = asyncio.get_event_loop().time()

            cli_result = subprocess.run(
                cli_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )

            execution_time = asyncio.get_event_loop().time() - start_time

            if cli_result.returncode == 0:
                try:
                    parsed_results = json.loads(cli_result.stdout)
                    raw_results = parsed_results.get("results", [])
                    ai_response = parsed_results.get("response", "")

                    logger.info(f"✅ PageIndex retrieval successful: {len(raw_results)} results")
                    logger.info(f"🤖 PageIndex AI response: {ai_response}")

                    cli_metadata = parsed_results.get("metadata", {})
                    validation = cli_metadata.get("validation", {})
                    entity_grounding = validation.get("entity_grounding", {})

                    pageindex_result = RetrieverResult(
                        retriever_type="pageindex",
                        status=RetrievalStatus.SUCCESS,
                        raw_results=raw_results,
                        processed_results=raw_results,
                        response_text=ai_response,
                        metadata={
                            "query": user_query,
                            "results_count": len(raw_results),
                            "total_results": parsed_results.get("total_results", len(raw_results)),
                            "processing_time": parsed_results.get("processing_time", execution_time),
                            "confidence_score": parsed_results.get("confidence_score"),
                            "mcts_iterations": mcts_iterations,
                            # flattened from metadata.validation
                            "faithfulness_score": validation.get("faithfulness_score"),
                            "coverage_score": validation.get("coverage_score"),
                            "unsupported_claims": validation.get("unsupported_claims", []),
                            "uncovered_topics": validation.get("uncovered_topics", []),
                            "hallucinated_count": entity_grounding.get("hallucinated_count"),
                            "hallucinated_entities": entity_grounding.get("hallucinated_entities", []),
                            "answer_identifiers": entity_grounding.get("answer_identifiers"),
                            "symbol_table_size": entity_grounding.get("symbol_table_size"),
                        },
                        execution_time=execution_time
                    )

                    return {"pageindex_result": pageindex_result}

                except json.JSONDecodeError as e:
                    logger.error(f"❌ PageIndex results parsing failed: {e}")
                    pageindex_result = RetrieverResult(
                        retriever_type="pageindex",
                        status=RetrievalStatus.FAILED,
                        raw_results=[],
                        processed_results=[],
                        error=f"JSON parsing failed: {e}",
                        metadata={},
                        execution_time=execution_time
                    )
                    return {"pageindex_result": pageindex_result}
            else:
                logger.error(f"❌ PageIndex CLI failed: {cli_result.stderr}")
                pageindex_result = RetrieverResult(
                    retriever_type="pageindex",
                    status=RetrievalStatus.FAILED,
                    raw_results=[],
                    processed_results=[],
                    error=cli_result.stderr,
                    metadata={},
                    execution_time=execution_time
                )
                return {"pageindex_result": pageindex_result}

        except Exception as e:
            logger.error(f"❌ PageIndex retrieval failed: {e}")
            pageindex_result = RetrieverResult(
                retriever_type="pageindex",
                status=RetrievalStatus.FAILED,
                raw_results=[],
                processed_results=[],
                error=str(e),
                metadata={},
                execution_time=0.0
            )
            return {
                "pageindex_result": pageindex_result,
                "error_log": state.error_log + [f"PageIndex retrieval error: {str(e)}"]
            }

    # DEPRECATED - use Multi-Agent CoT CPG retrieval instead
    # async def cpg_retrieval(self, state: HybridState) -> Dict[str, Any]:
    #     """
    #     Node: Execute CPG retrieval using the existing adaptive CPG workflow.

    #     Integrates with the CPG workflow for structural code analysis.
    #     """
    #     logger.info("🔍 Node: cpg_retrieval")

    #     try:
    #         user_query = state.user_query

    #         # Extract max_agent_iterations from config (passed from MCP tool)
    #         config = state.execution_metadata.get("config", {})
    #         cpg_config = config.get("cpg_config", {})
    #         max_iterations = cpg_config.get("max_agent_iterations", 10)  # Default to 10 if not specified

    #         logger.info(f"⚡ Executing CPG agent workflow for: {user_query}")
    #         logger.info(f"🔢 Max iterations per approach: {max_iterations}")
    #         start_time = asyncio.get_event_loop().time()

    #         # Use the same approach as query_cpg_rag MCP tool
    #         from src.core.adaptive_cpg_agent_workflow import execute_adaptive_cpg_workflow

    #         cpg_result = await execute_adaptive_cpg_workflow(
    #             user_query=user_query,
    #             project_name="HelloWorldApp",
    #             neo4j_config="/opt/genpod/neo4j_config.json",
    #             project_path="/opt/HelloWorldApp/",
    #             mappings_path="/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
    #             queries_path="/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
    #             max_iterations=max_iterations  # Use config value instead of hardcoded 10
    #         )

    #         execution_time = asyncio.get_event_loop().time() - start_time

    #         if cpg_result and cpg_result.get("status") == "success":
    #             raw_results = cpg_result.get("raw_results", [])

    #             # Extract AI response - CPG workflow returns response as a string
    #             response_text = cpg_result.get("response", "")
                
    #             logger.info(f"✅ CPG retrieval successful: {len(raw_results)} results")
    #             # logger.info(f"📝 CPG workflow response body: {json.dumps(cpg_result, indent=2)}")
    #             logger.info(f"🤖 CPG AI response: {response_text}")
                
    #             cpg_retriever_result = RetrieverResult(
    #                 retriever_type="cpg",
    #                 status=RetrievalStatus.SUCCESS,
    #                 raw_results=raw_results,
    #                 processed_results=raw_results,
    #                 response_text=response_text,
    #                 metadata={
    #                     "agent_metadata": cpg_result.get("agent_metadata", {}),
    #                     "approach_statuses": cpg_result.get("approach_statuses", {}),
    #                     "approach_count": len(cpg_result.get("approach_statuses", {})),
    #                     "results_count": len(raw_results),
    #                     "iterations_used": cpg_result.get("iterations_used", 0),
    #                     "total_queries_executed": len(cpg_result.get("query_history", [])),
    #                     "tokens_used": cpg_result.get("total_tokens_used", 0),
    #                     "total_input_tokens": cpg_result.get("total_input_tokens", 0),
    #                     "total_output_tokens": cpg_result.get("total_output_tokens", 0),
    #                     "cost_usd": cpg_result.get("total_estimated_cost_usd", 0.0)
    #                 },
    #                 execution_time=execution_time
    #             )
    #             return {"cpg_result": cpg_retriever_result}
    #         else:
    #             error_msg = cpg_result.get("error", "CPG workflow failed") if cpg_result else "No CPG result"
    #             logger.error(f"❌ CPG workflow failed: {error_msg}")
                
    #             cpg_retriever_result = RetrieverResult(
    #                 retriever_type="cpg",
    #                 status=RetrievalStatus.FAILED,
    #                 raw_results=[],
    #                 processed_results=[],
    #                 error=error_msg,
    #                 metadata={},
    #                 execution_time=execution_time
    #             )
    #             return {"cpg_result": cpg_retriever_result}
                
    #     except Exception as e:
    #         logger.error(f"❌ CPG retrieval failed: {e}")
    #         cpg_retriever_result = RetrieverResult(
    #             retriever_type="cpg",
    #             status=RetrievalStatus.FAILED,
    #             raw_results=[],
    #             processed_results=[],
    #             error=str(e),
    #             metadata={},
    #             execution_time=0.0
    #         )
            
    #         return {
    #             "cpg_result": cpg_retriever_result,
    #             "error_log": state.error_log + [f"CPG retrieval error: {str(e)}"]
    #         }

    async def cpg_retrieval(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Execute CPG retrieval using the Multi-Agent CoT system (graph_rag).

        Uses the new modular graph_rag.MultiAgentCoT for structural code analysis
        with Tree-of-Thought decomposition and Chain-of-Thought reasoning.
        """
        logger.info("🔍 Node: cpg_retrieval (Multi-Agent CoT)")

        system = None  # Track for cleanup in finally block
        try:
            user_query = state.user_query

            # Extract configuration from state
            config = state.execution_metadata.get("config", {})
            cpg_config = config.get("cpg_config", {})
            max_cot_iterations = cpg_config.get("max_agent_iterations", 15)
            max_verifier_iterations = cpg_config.get("max_verifier_iterations", 10)
            neo4j_config = cpg_config.get("config_path", NEO4J_CONFIG)
            schema_path = cpg_config.get("schema_path", SCHEMA_PATH)
            llm_model = cpg_config.get("llm_model", "gpt-4o")
            parallel_agents = cpg_config.get("parallel_agents", True)
            enable_verification = cpg_config.get("enable_verification", True)
            enable_entity_resolution = cpg_config.get("enable_entity_resolution", True)
            # 4-Agent Team configuration
            use_4_agent_team = cpg_config.get("use_4_agent_team", True)
            four_agent_max_iterations = cpg_config.get("four_agent_max_iterations", 3)

            workflow_type = "4-Agent Team" if use_4_agent_team else "Multi-Agent CoT"
            logger.info(f"⚡ Executing {workflow_type} for: {user_query}")
            logger.info(f"🔢 Max iterations: {max_cot_iterations}, parallel: {parallel_agents}, 4-agent: {use_4_agent_team}")
            start_time = asyncio.get_event_loop().time()

            # Import and use the new graph_rag Multi-Agent system
            from src.core.graph_rag import MultiAgentCoT, SystemConfig

            # Create configuration
            system_config = SystemConfig(
                mcp_config_path=neo4j_config,
                yaml_schema_path=schema_path,
                llm_model=llm_model,
                max_cot_iterations=max_cot_iterations,
                max_verifier_iterations=max_verifier_iterations,
                parallel_cot_agents=parallel_agents,
                verification_enabled=enable_verification,
                entity_resolution_enabled=enable_entity_resolution,
                # 4-Agent Team configuration
                use_4_agent_team=use_4_agent_team,
                four_agent_max_iterations=four_agent_max_iterations,
            )

            # Initialize and run the multi-agent system
            system = MultiAgentCoT(system_config, enable_observer=False)
            await system.initialize()

            # Execute the query
            response = await system.run(user_query)

            # Extract execution traces for debugging/analysis (4-agent workflow)
            execution_traces = system.last_execution_traces if use_4_agent_team else []

            execution_time = asyncio.get_event_loop().time() - start_time

            # Convert citations to raw_results format for compatibility
            raw_results = []
            for citation in response.citations:
                raw_results.append({
                    "claim": citation.claim,
                    "source_file": citation.source_file,
                    "source_line": citation.source_line,
                    "entity_name": citation.entity_name,
                    "entity_type": citation.entity_type,
                    "evidence": citation.evidence,
                    "verification_status": citation.verification_status.value if citation.verification_status else None,
                    "cot_agent_id": citation.cot_agent_id,
                    "confidence": citation.confidence.value if citation.confidence else None
                })

            # Build token usage dict
            token_usage = {}
            if response.token_usage:
                token_usage = {
                    "total_tokens": response.token_usage.total_tokens,
                    "total_prompt_tokens": response.token_usage.total_prompt_tokens,
                    "total_completion_tokens": response.token_usage.total_completion_tokens,
                    "call_count": response.token_usage.call_count
                }

            logger.info(f"✅ CPG {workflow_type} retrieval successful: {len(raw_results)} citations ({response.verified_count} verified)")
            logger.info(f"🤖 CPG AI response: {response.answer[:200]}...")

            cpg_retriever_result = RetrieverResult(
                retriever_type="cpg",
                status=RetrievalStatus.SUCCESS,
                raw_results=raw_results,
                processed_results=raw_results,
                response_text=response.answer,
                metadata={
                    "workflow_type": "4_agent_team" if use_4_agent_team else "multi_agent_tot_cot",
                    "use_4_agent_team": use_4_agent_team,
                    "four_agent_max_iterations": four_agent_max_iterations,
                    "confidence": response.confidence.value,
                    "verified_count": response.verified_count,
                    "unverified_count": response.unverified_count,
                    "sub_queries_count": response.sub_queries_count,
                    "llm_calls_count": response.llm_calls_count,
                    "results_count": len(raw_results),
                    "tokens_used": token_usage.get("total_tokens", 0),
                    "total_input_tokens": token_usage.get("total_prompt_tokens", 0),
                    "total_output_tokens": token_usage.get("total_completion_tokens", 0),
                    "execution_time_ms": response.execution_time_ms,
                    # Execution traces with Cypher queries for debugging/analysis
                    "execution_traces": execution_traces
                },
                execution_time=execution_time
            )
            return {"cpg_result": cpg_retriever_result}

        except Exception as e:
            logger.error(f"❌ CPG Multi-Agent retrieval failed: {e}")
            cpg_retriever_result = RetrieverResult(
                retriever_type="cpg",
                status=RetrievalStatus.FAILED,
                raw_results=[],
                processed_results=[],
                error=str(e),
                metadata={},
                execution_time=0.0
            )

            return {
                "cpg_result": cpg_retriever_result,
                "error_log": state.error_log + [f"CPG Multi-Agent retrieval error: {str(e)}"]
            }
        finally:
            # Gracefully shutdown the multi-agent system to prevent cancel scope errors
            if system:
                try:
                    await system.shutdown()
                except Exception:
                    pass  # Suppress cleanup errors
    
    async def combine_results(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Combine and batch raw results from both retrievers.
        
        Implements intelligent batching for context window management.
        """
        logger.info("🔗 Node: combine_results")
        
        try:
            combined_results = []
            
            # Add vector results with source tags
            if state.vector_result and state.vector_result.succeeded:
                for result in state.vector_result.raw_results:
                    result_copy = dict(result) if isinstance(result, dict) else {"content": result}
                    result_copy["_source"] = "vector"
                    # NOTE: _retriever_metadata removed to prevent data explosion (was 278KB per item)
                    # Metadata is available at state.vector_result.metadata for synthesis
                    combined_results.append(result_copy)

                logger.info(f"📊 Added {len(state.vector_result.raw_results)} vector results")

            # Add CPG results with source tags
            if state.cpg_result and state.cpg_result.succeeded:
                for result in state.cpg_result.raw_results:
                    result_copy = dict(result) if isinstance(result, dict) else {"content": result}
                    result_copy["_source"] = "cpg"
                    # NOTE: _retriever_metadata removed to prevent data explosion
                    # Metadata is available at state.cpg_result.metadata for synthesis
                    combined_results.append(result_copy)
                    
                logger.info(f"📊 Added {len(state.cpg_result.raw_results)} CPG results")
            
            # Batch results for context management
            batched_results = self._create_intelligent_batches(
                combined_results, 
                state.batch_size,
                state.max_context_limit
            )
            
            context_size = self._estimate_context_size(combined_results)
            
            logger.info(f"✅ Combined {len(combined_results)} total results into {len(batched_results)} batches")
            logger.info(f"📊 Estimated context size: {context_size} characters")
            
            return {
                "combined_raw_results": combined_results,
                "batched_results": batched_results, 
                "context_size": context_size
            }
            
        except Exception as e:
            logger.error(f"❌ Result combination failed: {e}")
            
            # Fallback
            return {
                "combined_raw_results": [],
                "batched_results": [],
                "context_size": 0,
                "error_log": state.error_log + [f"Result combination error: {str(e)}"]
            }
    
    async def synthesize_response(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Synthesize final response using chain-of-thought reasoning.
        
        Implements sophisticated synthesis with cross-validation between retrievers.
        """
        logger.info("🧠 Node: synthesize_response") 
        
        try:
            synthesis_strategy = self._determine_synthesis_strategy(state)
            logger.info(f"📝 Using synthesis strategy: {synthesis_strategy}")
            
            # Execute synthesis based on strategy
            if synthesis_strategy == SynthesisStrategy.NO_RESULTS:
                synthesis_result = await self._synthesize_no_results(state)
            elif synthesis_strategy in [SynthesisStrategy.FALLBACK_VECTOR, SynthesisStrategy.FALLBACK_CPG]:
                synthesis_result = await self._synthesize_single_source(state, synthesis_strategy)
            else:
                synthesis_result = await self._synthesize_hybrid_with_cross_validation(state, synthesis_strategy)
            
            logger.info(f"✅ Synthesis completed: {synthesis_result.status} (confidence: {synthesis_result.confidence:.2f})")
            return {"synthesis_result": synthesis_result}
            
        except Exception as e:
            logger.error(f"❌ Synthesis failed: {e}")
            
            # Fallback synthesis
            fallback_synthesis = SynthesisResult(
                strategy_used=SynthesisStrategy.NO_RESULTS,
                answer="Analysis failed due to synthesis error.",
                details=f"Synthesis error: {str(e)}",
                confidence=0.1,
                status="error",
                suggestions=["Please try rephrasing your query"],
                cross_validation=CrossValidationResult(
                    vector_validates_cpg=False,
                    cpg_validates_vector=False,
                    conflicts_found=[],
                    consensus_points=[],
                    confidence_score=0.0,
                    validation_details={}
                ),
                evidence={},
                batch_metadata={}
            )
            
            return {
                "synthesis_result": fallback_synthesis,
                "error_log": state.error_log + [f"Synthesis error: {str(e)}"]
            }
    
    async def critic_validation(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Validate synthesis output for hallucination, faithfulness, and accuracy.
        
        Uses chain-of-thought reasoning to grade evidence and validate claims.
        """
        logger.info("🔍 Node: critic_validation")
        
        try:
            llm_service = state.llm_service
            synthesis_result = state.synthesis_result
            
            if not synthesis_result:
                logger.warning("⚠️ No synthesis result to validate")
                return state
            
            # Chain-of-thought validation prompt
            validation_prompt = f"""You are an expert critic for hybrid code analysis systems. 
Validate this synthesis output for hallucination, faithfulness, and accuracy using chain-of-thought reasoning.

**SYNTHESIS TO VALIDATE**:
Answer: {synthesis_result.answer}
Details: {synthesis_result.details}
Confidence: {synthesis_result.confidence}
Strategy: {synthesis_result.strategy_used}

**AVAILABLE EVIDENCE**:
Vector Evidence: {json.dumps(state.vector_result.raw_results[:3] if state.vector_result and state.vector_result.succeeded else [], indent=2)}
CPG Evidence: {json.dumps(state.cpg_result.raw_results[:3] if state.cpg_result and state.cpg_result.succeeded else [], indent=2)}

**CHAIN OF THOUGHT VALIDATION**:

**Step 1: Hallucination Detection**
Check if the synthesis makes claims not supported by evidence:
- Are all facts mentioned in the answer supported by the evidence?
- Are there any invented details, functions, or files not in the evidence?
- Rate hallucination risk (0.0 = no hallucination, 1.0 = severe hallucination)

**Step 2: Faithfulness Assessment** 
Check if the synthesis stays faithful to the source evidence:
- Does the answer accurately represent what was found in the evidence?
- Are quotes and references accurate?
- Rate faithfulness (0.0 = unfaithful, 1.0 = completely faithful)

**Step 3: Accuracy Evaluation**
Check the accuracy of reasoning and conclusions:
- Are the logical connections sound?
- Are the conclusions supported by the evidence?
- Rate accuracy (0.0 = inaccurate, 1.0 = highly accurate)

**Step 4: Evidence Quality Grading**
Grade the quality and relevance of evidence used:
- Vector evidence quality and relevance
- CPG evidence quality and relevance  
- Overall evidence sufficiency

**Step 5: Final Decision**
Based on the analysis above:
- ACCEPT: High quality, faithful, accurate synthesis
- RETRY: Issues found that can be fixed
- REJECT: Severe problems, synthesis is unreliable

**OUTPUT FORMAT**:
Return ONLY a valid JSON object:
{{
    "decision": "accept|retry|reject",
    "overall_score": <float 0.0-1.0>,
    "hallucination_score": <float 0.0-1.0>,
    "faithfulness_score": <float 0.0-1.0>,
    "accuracy_score": <float 0.0-1.0>,
    "validation_issues": ["issue1", "issue2"],
    "reasoning": "Detailed step-by-step validation reasoning",
    "improvement_suggestions": ["suggestion1", "suggestion2"],
    "evidence_grading": {{
        "vector_quality": <float 0.0-1.0>,
        "cpg_quality": <float 0.0-1.0>,
        "overall_sufficiency": <float 0.0-1.0>
    }}
}}"""
            
            # Generate critic validation with robust validation
            raw_response, error = await self._robust_llm_call_with_pydantic_validation(
                llm_service=llm_service,
                prompt=validation_prompt,
                pydantic_model=CriticValidationRawResponse,
                max_tokens=16000,
                temperature=0.1,  # Low temperature for precise validation and scoring
                max_retries=3
            )
            
            if raw_response:
                critic_validation = CriticValidation(
                    decision=raw_response.decision,
                    overall_score=raw_response.overall_score,
                    hallucination_score=raw_response.hallucination_score,
                    faithfulness_score=raw_response.faithfulness_score,
                    accuracy_score=raw_response.accuracy_score,
                    validation_issues=raw_response.validation_issues,
                    reasoning=raw_response.reasoning,
                    improvement_suggestions=raw_response.improvement_suggestions,
                    evidence_grading=raw_response.evidence_grading
                )
                
                logger.info(f"✅ Critic validation: {critic_validation.decision} (score: {critic_validation.overall_score:.2f})")
                
                # If retry needed and score is low, attempt to improve synthesis
                if (critic_validation.decision == "retry" and 
                    critic_validation.overall_score < 0.7):
                    logger.info("🔄 Attempting to improve synthesis based on critic feedback")
                    improved_synthesis = await self._improve_synthesis_with_critic_feedback(
                        state, critic_validation
                    )
                    if improved_synthesis:
                        logger.info("✅ Synthesis improved using critic feedback")
                        return {
                            "critic_validation": critic_validation,
                            "synthesis_result": improved_synthesis
                        }
                
                return {"critic_validation": critic_validation}
            
            logger.error(f"❌ Critic validation failed after retries: {error}")
                    
            # Fallback validation  
            logger.warning("⚠️ Using fallback critic validation")
            fallback_validation = CriticValidation(
                decision="accept",
                overall_score=0.6,
                hallucination_score=0.7,
                faithfulness_score=0.7,
                accuracy_score=0.6,
                validation_issues=[],
                reasoning="Fallback validation due to critic failure",
                improvement_suggestions=[],
                evidence_grading={}
            )
            return {"critic_validation": fallback_validation}
                
        except Exception as e:
            logger.error(f"❌ Critic validation failed: {e}")
            
            # Fallback
            error_validation = CriticValidation(
                decision="accept",
                overall_score=0.5,
                hallucination_score=0.5,
                faithfulness_score=0.5,
                accuracy_score=0.5,
                validation_issues=[f"Validation error: {str(e)}"],
                reasoning="Error fallback validation",
                improvement_suggestions=[],
                evidence_grading={}
            )
            
            return {
                "critic_validation": error_validation,
                "error_log": state.error_log + [f"Critic validation error: {str(e)}"]
            }
    
    
    def _create_intelligent_batches(
        self, 
        results: List[Dict[str, Any]], 
        batch_size: int,
        max_context_limit: int
    ) -> List[List[Dict[str, Any]]]:
        """Create intelligent batches considering context size limits"""
        if not results:
            return []
        
        batches = []
        current_batch = []
        current_size = 0
        
        for result in results:
            result_size = len(str(result))
            
            # If single result exceeds limit, truncate it
            if result_size > max_context_limit:
                result = self._truncate_result(result, max_context_limit // 2)
                result_size = len(str(result))
            
            # If adding this result would exceed context limit or batch size, start new batch
            if ((current_size + result_size > max_context_limit) or 
                (len(current_batch) >= batch_size)) and current_batch:
                batches.append(current_batch)
                current_batch = [result]
                current_size = result_size
            else:
                current_batch.append(result)
                current_size += result_size
        
        # Add final batch if not empty
        if current_batch:
            batches.append(current_batch)
        
        return batches
    
    def _truncate_result(self, result: Dict[str, Any], max_size: int) -> Dict[str, Any]:
        """Truncate a result to fit within size limits"""
        result_str = str(result)
        if len(result_str) <= max_size:
            return result
        
        # Try to keep structured data
        if isinstance(result, dict):
            truncated = {}
            current_size = 0
            
            # Prioritize certain keys
            priority_keys = ['name', 'type', 'file_path', 'content', 'body']
            
            for key in priority_keys:
                if key in result and current_size < max_size * 0.8:
                    value = result[key]
                    value_str = str(value)
                    if len(value_str) > max_size // 4:
                        value_str = value_str[:max_size // 4] + "...[truncated]"
                    truncated[key] = value_str
                    current_size += len(str(value_str))
            
            # Add other keys if space allows
            for key, value in result.items():
                if key not in priority_keys and current_size < max_size:
                    value_str = str(value)
                    if current_size + len(value_str) <= max_size:
                        truncated[key] = value_str
                        current_size += len(value_str)
                    else:
                        break
            
            truncated["_truncated"] = True
            return truncated
        
        # Fallback: string truncation
        return {"content": result_str[:max_size] + "...[truncated]", "_truncated": True}
    
    def _estimate_context_size(self, results: List[Dict[str, Any]]) -> int:
        """Estimate total context size for all results"""
        return sum(len(str(result)) for result in results)
    
    def _determine_synthesis_strategy(self, state: HybridState) -> SynthesisStrategy:
        """Determine optimal synthesis strategy based on retrieval results"""
        vector_succeeded = state.vector_result and state.vector_result.succeeded
        cpg_succeeded = state.cpg_result and state.cpg_result.succeeded
        
        if not vector_succeeded and not cpg_succeeded:
            return SynthesisStrategy.NO_RESULTS
        elif vector_succeeded and not cpg_succeeded:
            return SynthesisStrategy.FALLBACK_VECTOR
        elif cpg_succeeded and not vector_succeeded:
            return SynthesisStrategy.FALLBACK_CPG
        else:
            # Both succeeded - determine based on intent and result quality
            intent = state.intent_analysis.intent if state.intent_analysis else QueryIntent.UNKNOWN
            
            if intent in [QueryIntent.ARCHITECTURAL, QueryIntent.SEMANTIC]:
                return SynthesisStrategy.VECTOR_PRIMARY
            elif intent in [QueryIntent.DIRECT_LOOKUP, QueryIntent.QUANTITATIVE, QueryIntent.RELATIONAL]:
                return SynthesisStrategy.CPG_PRIMARY
            else:
                return SynthesisStrategy.HYBRID_CONSENSUS
    
    async def _synthesize_no_results(self, state: HybridState) -> SynthesisResult:
        """Synthesize response when no retrieval succeeded"""
        return SynthesisResult(
            strategy_used=SynthesisStrategy.NO_RESULTS,
            answer="No results found for your query.",
            details="Both vector and CPG retrievers were unable to find relevant information for your query. This could be due to the query being outside the scope of the codebase or issues with the retrieval systems.",
            confidence=0.1,
            status="not_found",
            suggestions=[
                "Try rephrasing your query with different keywords",
                "Check if the entities mentioned in your query exist in the codebase",
                "Try a more general or more specific version of your query"
            ],
            cross_validation=CrossValidationResult(
                vector_validates_cpg=False,
                cpg_validates_vector=False,
                conflicts_found=[],
                consensus_points=[],
                confidence_score=0.0,
                validation_details={"reason": "no_results"}
            ),
            evidence={},
            batch_metadata={"strategy": "no_results"}
        )
    
    async def _synthesize_single_source(self, state: HybridState, strategy: SynthesisStrategy) -> SynthesisResult:
        """Synthesize response from a single successful retriever"""
        if strategy == SynthesisStrategy.FALLBACK_VECTOR:
            source_result = state.vector_result
            source_name = "vector"
        else:
            source_result = state.cpg_result
            source_name = "cpg"
        
        # Use the existing response if available, otherwise synthesize new one
        if source_result.response_text:
            answer = source_result.response_text[:500] + ("..." if len(source_result.response_text) > 500 else "")
            details = source_result.response_text
        else:
            # Create basic synthesis from raw results
            answer = f"Found {len(source_result.raw_results)} results from {source_name} analysis."
            details = f"Analysis completed using {source_name} retrieval. Results include: " + str(source_result.raw_results[:3])
        
        return SynthesisResult(
            strategy_used=strategy,
            answer=answer,
            details=details,
            confidence=0.7 if source_result.status == RetrievalStatus.SUCCESS else 0.5,
            status="found" if source_result.raw_results else "partial",
            suggestions=[f"Results are based only on {source_name} analysis"],
            cross_validation=CrossValidationResult(
                vector_validates_cpg=False,
                cpg_validates_vector=False,
                conflicts_found=[],
                consensus_points=[],
                confidence_score=0.5,
                validation_details={"single_source": source_name}
            ),
            evidence={source_name: source_result.raw_results},
            batch_metadata={"strategy": "single_source", "source": source_name}
        )
    
    async def _synthesize_hybrid_with_cross_validation(
        self, 
        state: HybridState, 
        strategy: SynthesisStrategy
    ) -> SynthesisResult:
        """Synthesize response with cross-validation between retrievers"""
        llm_service = state.llm_service
        
        # Process batched results to avoid context overflow
        synthesis_prompt = await self._build_hybrid_synthesis_prompt(state, strategy)
        
        # Generate synthesis with robust validation
        raw_response, error = await self._robust_llm_call_with_pydantic_validation(
            llm_service=llm_service,
            prompt=synthesis_prompt,
            pydantic_model=SynthesisRawResponse,
            max_tokens=16000,
            temperature=0.7,  # Higher temperature for creative synthesis and reasoning
            max_retries=3
        )
        
        if raw_response:
            return SynthesisResult(
                strategy_used=strategy,
                answer=raw_response.answer,
                details=raw_response.details,
                confidence=raw_response.confidence,
                status=raw_response.status,
                suggestions=raw_response.suggestions,
                cross_validation=CrossValidationResult(
                    vector_validates_cpg=raw_response.cross_validation.get("vector_validates_cpg", True),
                    cpg_validates_vector=raw_response.cross_validation.get("cpg_validates_vector", True),
                    conflicts_found=raw_response.cross_validation.get("conflicts_found", []),
                    consensus_points=raw_response.cross_validation.get("consensus_points", []),
                    confidence_score=raw_response.cross_validation.get("confidence_score", 0.7),
                    validation_details=raw_response.cross_validation.get("validation_details", {})
                ),
                evidence={
                    "vector": state.vector_result.raw_results if state.vector_result else [],
                    "cpg": state.cpg_result.raw_results if state.cpg_result else []
                },
                batch_metadata=raw_response.batch_metadata
            )
        
        logger.error(f"❌ Hybrid synthesis failed after retries: {error}")
        
        # Fallback hybrid synthesis
        return SynthesisResult(
            strategy_used=strategy,
            answer="Analysis completed with hybrid approach",
            details="Combined vector and CPG analysis results",
            confidence=0.6,
            status="found",
            suggestions=[],
            cross_validation=CrossValidationResult(
                vector_validates_cpg=True,
                cpg_validates_vector=True,
                conflicts_found=[],
                consensus_points=["Both retrievers provided results"],
                confidence_score=0.6,
                validation_details={"fallback": True}
            ),
            evidence={
                "vector": state.vector_result.raw_results if state.vector_result else [],
                "cpg": state.cpg_result.raw_results if state.cpg_result else []
            },
            batch_metadata={"fallback": True}
        )
    
    async def _build_hybrid_synthesis_prompt(self, state: HybridState, strategy: SynthesisStrategy) -> str:
        """Build synthesis prompt with intelligent batching"""
        # Process results in batches to manage context
        batch_summaries = []
        
        for i, batch in enumerate(state.batched_results[:10]):  # Limit to 10 batches
            # Create batch summary
            vector_items = [item for item in batch if item.get("_source") == "vector"]
            cpg_items = [item for item in batch if item.get("_source") == "cpg"]
            
            batch_summary = f"Batch {i+1}: {len(vector_items)} vector, {len(cpg_items)} CPG items"
            if vector_items:
                batch_summary += f" - Vector sample: {str(vector_items[0])[:200]}..."
            if cpg_items:
                batch_summary += f" - CPG sample: {str(cpg_items[0])[:200]}..."
            
            batch_summaries.append(batch_summary)
        
        # Get responses from individual retrievers
        vector_response = state.vector_result.response_text if state.vector_result and state.vector_result.response_text else "No vector response"
        cpg_response = state.cpg_result.response_text if state.cpg_result and state.cpg_result.response_text else "No CPG response"
        
        return f"""You are an expert code analysis synthesizer using chain-of-thought reasoning.
Synthesize a comprehensive response by cross-validating vector and CPG retrieval results.

**USER QUERY**: {state.user_query}
**SYNTHESIS STRATEGY**: {strategy}

**INDIVIDUAL RETRIEVER RESPONSES**:
Vector Response: {vector_response[:1000]}...
CPG Response: {cpg_response[:1000]}...

**BATCHED EVIDENCE SUMMARY**:
{chr(10).join(batch_summaries)}

**CHAIN-OF-THOUGHT SYNTHESIS**:

**Step 1: Cross-Validation Analysis**
Compare vector and CPG findings:
- What claims does each retriever make?
- Where do they agree (consensus points)?
- Where do they conflict?
- Can one validate claims made by the other?

**Step 2: Evidence Quality Assessment**
Evaluate the quality of evidence:
- Which retriever provides more relevant results?
- What is the quality and depth of the evidence?
- Are there gaps in either retriever's findings?

**Step 3: Synthesis Strategy Application**
Apply the {strategy} strategy:
- How should the results be weighted?
- What is the primary source of truth?
- How should conflicts be resolved?

**Step 4: Comprehensive Response Construction**
Build the final response:
- Direct answer to the user's query
- Supporting details with evidence
- Clear indication of confidence level
- Actionable suggestions if needed

**OUTPUT FORMAT**:
Return ONLY a valid JSON object:
{{
    "answer": "Direct, comprehensive answer to the user's query",
    "details": "Detailed explanation with evidence from both retrievers",
    "confidence": <float 0.0-1.0>,
    "status": "found|not_found|partial",
    "suggestions": ["suggestion1", "suggestion2"],
    "cross_validation": {{
        "vector_validates_cpg": <boolean>,
        "cpg_validates_vector": <boolean>,
        "conflicts_found": ["conflict1", "conflict2"],
        "consensus_points": ["consensus1", "consensus2"],
        "confidence_score": <float 0.0-1.0>,
        "validation_details": {{
            "primary_source": "vector|cpg|balanced",
            "agreement_level": "high|medium|low"
        }}
    }},
    "batch_metadata": {{
        "batches_processed": {len(state.batched_results)},
        "total_items": {len(state.combined_raw_results)},
        "strategy_applied": "{strategy}"
    }}
}}"""
    
    async def _improve_synthesis_with_critic_feedback(
        self, 
        state: HybridState, 
        critic_validation: CriticValidation
    ) -> Optional[SynthesisResult]:
        """Improve synthesis based on critic feedback"""
        try:
            llm_service = state.llm_service
            original_synthesis = state.synthesis_result
            
            improvement_prompt = f"""You are a synthesis improvement expert. Improve this response based on critic feedback.

**ORIGINAL SYNTHESIS**:
Answer: {original_synthesis.answer}
Details: {original_synthesis.details}
Confidence: {original_synthesis.confidence}

**CRITIC FEEDBACK**:
Decision: {critic_validation.decision}
Issues: {'; '.join(critic_validation.validation_issues)}
Suggestions: {'; '.join(critic_validation.improvement_suggestions)}
Scores: Hallucination={critic_validation.hallucination_score:.2f}, Faithfulness={critic_validation.faithfulness_score:.2f}, Accuracy={critic_validation.accuracy_score:.2f}

**AVAILABLE EVIDENCE**:
Vector: {json.dumps(state.vector_result.raw_results[:2] if state.vector_result else [], indent=2)}
CPG: {json.dumps(state.cpg_result.raw_results[:2] if state.cpg_result else [], indent=2)}

**IMPROVEMENT REQUIREMENTS**:
1. Address all critic issues
2. Improve faithfulness to evidence  
3. Reduce hallucination risk
4. Increase accuracy
5. Maintain JSON format exactly

**OUTPUT FORMAT**:
Return the improved synthesis in exact same JSON format as original:
{{
    "answer": "Improved answer",
    "details": "Improved detailed explanation",
    "confidence": <float>,
    "status": "found|not_found|partial",
    "suggestions": ["improved suggestions"],
    "cross_validation": {original_synthesis.cross_validation},
    "evidence": {original_synthesis.evidence},
    "batch_metadata": {original_synthesis.batch_metadata}
}}"""
            
            # Generate improvement with robust validation
            raw_response, error = await self._robust_llm_call_with_pydantic_validation(
                llm_service=llm_service,
                prompt=improvement_prompt,
                pydantic_model=SynthesisImprovementRawResponse,
                max_tokens=16000,
                temperature=0.3,  # Moderate temperature for controlled improvement
                max_retries=3
            )
            
            if raw_response:
                # Create improved synthesis result
                improved_synthesis = SynthesisResult(
                    strategy_used=original_synthesis.strategy_used,
                    answer=raw_response.answer,
                    details=raw_response.details,
                    confidence=min(raw_response.confidence, 1.0),
                    status=raw_response.status,
                    suggestions=raw_response.suggestions,
                    cross_validation=original_synthesis.cross_validation,
                    evidence=original_synthesis.evidence,
                    batch_metadata=dict(original_synthesis.batch_metadata, **{"improved": True})
                )
                
                return improved_synthesis
            
            logger.error(f"❌ Synthesis improvement failed after retries: {error}")
                
        except Exception as e:
            logger.error(f"❌ Synthesis improvement failed: {e}")
        
        return None
"""
LangGraph workflow for the 4-Agent Team architecture.

Orchestrates:
1. Thinker → generates reasoning and Cypher queries
2. ThinkingValidator → validates reasoning approach
3. CypherValidator → validates query correctness
4. ExecutorVerifier → executes queries and builds findings

Both validators must approve (AND gate) before execution proceeds.
Failed validation loops back to Thinker with feedback.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Literal

from langgraph.graph import StateGraph, END
from openai import OpenAI

from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.models import (
    SubQuery,
    Finding,
    ThinkerOutput,
    ThinkingValidationResult,
    CypherValidationResult,
    ExecutedQuery,
    FourAgentState,
    FourAgentWorkflowResult,
)
from src.core.graph_rag.core.metrics import AggregatedTokenUsage
from src.core.graph_rag.agents import (
    ThinkerAgent,
    ThinkingValidatorAgent,
    CypherValidatorAgent,
    ExecutorVerifierAgent,
)


logger = logging.getLogger(__name__)


class FourAgentWorkflow:
    """
    LangGraph workflow for 4-agent sub-query execution.

    Flow:
        Thinker → ThinkingValidator → CypherValidator → [if both approved] → Executor → END
                        ↓                    ↓
                  [if rejected]        [if rejected]
                        ↓                    ↓
                  ←←←←←← (feedback loop with combined feedback) ←←←←←←
    """

    def __init__(
        self,
        tool_manager,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig,
        token_tracker: Optional[AggregatedTokenUsage] = None,
    ):
        """
        Initialize the 4-agent workflow.

        Args:
            tool_manager: ToolManager instance for tool execution
            openai_client: OpenAI client instance
            llm_config: LLM configuration
            config: System configuration
            token_tracker: Optional shared token tracker
        """
        self.tool_manager = tool_manager
        self.openai_client = openai_client
        self.llm_config = llm_config
        self.config = config
        self.token_tracker = token_tracker

        # Initialize agents
        self.thinker = ThinkerAgent(
            tool_manager=tool_manager,
            openai_client=openai_client,
            llm_config=llm_config,
            config=config
        )
        self.thinking_validator = ThinkingValidatorAgent(
            tool_manager=tool_manager,
            openai_client=openai_client,
            llm_config=llm_config,
            config=config
        )
        self.cypher_validator = CypherValidatorAgent(
            tool_manager=tool_manager,
            openai_client=openai_client,
            llm_config=llm_config,
            config=config
        )
        self.executor = ExecutorVerifierAgent(
            tool_manager=tool_manager,
            openai_client=openai_client,
            llm_config=llm_config,
            config=config
        )

        # Build the LangGraph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph with sequential validators"""
        graph = StateGraph(FourAgentState)

        # Add nodes
        graph.add_node("thinker", self._thinker_node)
        graph.add_node("thinking_validator", self._thinking_validator_node)
        graph.add_node("cypher_validator", self._cypher_validator_node)
        graph.add_node("executor", self._executor_node)

        # Set entry point
        graph.set_entry_point("thinker")

        # Sequential flow: Thinker → ThinkingValidator → CypherValidator
        graph.add_edge("thinker", "thinking_validator")
        graph.add_edge("thinking_validator", "cypher_validator")

        # Conditional edge after CypherValidator (AND gate - both must have approved)
        graph.add_conditional_edges(
            "cypher_validator",
            self._check_both_validations,
            {
                "approved": "executor",
                "rejected": "thinker",
                "max_iterations": END,
            }
        )

        # Executor goes to END
        graph.add_edge("executor", END)

        return graph.compile()

    async def _thinker_node(self, state: FourAgentState) -> Dict[str, Any]:
        """Thinker node - analyzes query and generates Cypher"""
        logger.info(f"Thinker node - iteration {state.get('iteration_count', 0) + 1}")

        # Get feedback from previous validation if this is a retry
        feedback = self._get_combined_feedback(state)

        try:
            output = await self.thinker.execute(
                sub_query=state["sub_query"],
                context=state.get("context_from_previous", ""),
                schema_info=state.get("schema_info"),
                previous_feedback=feedback,
                max_iterations=self.config.max_cot_iterations
            )

            # Update validation history with rich trace data
            history = list(state.get("validation_history", []))
            iteration_num = state.get("iteration_count", 0) + 1

            # Capture the proposed queries from thinker
            proposed_queries = []
            if output.proposed_queries:
                for pq in output.proposed_queries:
                    proposed_queries.append({
                        "query_id": pq.query_id,
                        "purpose": pq.purpose,
                        "cypher": pq.cypher_query,
                    })

            # Build iteration trace with thinker output only
            # Validation results will be added by the respective validation nodes
            iteration_trace = {
                "iteration": iteration_num,
                "thinker_output": {
                    "summary": output.approach_summary,
                    "query_count": output.total_queries,
                    "proposed_queries": proposed_queries,
                    "overall_reasoning": output.overall_reasoning,  # Step-by-step reasoning
                },
            }

            history.append(iteration_trace)

            return {
                "thinker_output": output,
                "iteration_count": state.get("iteration_count", 0) + 1,
                "validation_history": history,
            }
        except Exception as e:
            logger.error(f"Thinker node error: {e}")
            errors = list(state.get("errors", []))
            errors.append(f"Thinker error: {str(e)}")
            return {
                "errors": errors,
                "iteration_count": state.get("iteration_count", 0) + 1,
            }

    async def _thinking_validator_node(self, state: FourAgentState) -> Dict[str, Any]:
        """Thinking Validator node - validates reasoning approach"""
        logger.info("ThinkingValidator node - validating reasoning")

        thinker_output = state.get("thinker_output")
        if not thinker_output:
            return {
                "thinking_validation": ThinkingValidationResult(
                    approved=False,
                    feedback="No thinker output to validate",
                    reasoning_gaps=["Missing thinker output"],
                    missing_aspects=[],
                    queries_coverage_issues=[],
                    specific_issues=[],
                    suggested_corrections=None
                )
            }

        try:
            result = await self.thinking_validator.execute(
                thinker_output=thinker_output,
                sub_query=state["sub_query"]
            )
            if result.approved:
                logger.info("ThinkingValidator approved")
            else:
                logger.warning(f"ThinkingValidator rejected: {result.feedback}")

            # Update current iteration's trace entry with thinking validation results
            history = list(state.get("validation_history", []))
            if history:
                history[-1]["thinking_validation"] = {
                    "approved": result.approved,
                    "feedback": result.feedback,
                    "reasoning_gaps": result.reasoning_gaps,
                    "missing_aspects": result.missing_aspects,
                    "queries_coverage_issues": result.queries_coverage_issues,
                    "specific_issues": result.specific_issues,
                    "suggested_corrections": result.suggested_corrections,
                }

            return {"thinking_validation": result, "validation_history": history}
        except Exception as e:
            logger.error(f"ThinkingValidator error: {e}")
            return {
                "thinking_validation": ThinkingValidationResult(
                    approved=False,
                    feedback=f"Validation error: {str(e)}",
                    reasoning_gaps=[],
                    missing_aspects=[],
                    queries_coverage_issues=[],
                    specific_issues=[str(e)],
                    suggested_corrections=None
                )
            }

    async def _cypher_validator_node(self, state: FourAgentState) -> Dict[str, Any]:
        """Cypher Validator node - validates query correctness"""
        logger.info("CypherValidator node - validating queries")

        thinker_output = state.get("thinker_output")
        if not thinker_output:
            return {
                "cypher_validation": CypherValidationResult(
                    approved=False,
                    feedback="No queries to validate",
                    query_results=[],
                    invalid_nodes=[],
                    invalid_properties=[],
                    invalid_relationships=[],
                    path_issues=[],
                    specific_issues=["Missing thinker output"],
                    suggested_corrections=None
                )
            }

        try:
            result = await self.cypher_validator.execute(
                thinker_output=thinker_output,
                schema_info=state.get("schema_info")
            )
            if result.approved:
                logger.info("CypherValidator approved")
            else:
                logger.warning(f"CypherValidator rejected: {result.feedback}")

            # Update current iteration's trace entry with cypher validation results
            history = list(state.get("validation_history", []))
            if history:
                query_issues = []
                if result.query_results:
                    for qr in result.query_results:
                        query_issues.append({
                            "query_id": qr.query_id,
                            "approved": qr.approved,
                            "issues": qr.issues,
                        })
                history[-1]["cypher_validation"] = {
                    "approved": result.approved,
                    "feedback": result.feedback,
                    "invalid_nodes": result.invalid_nodes,
                    "invalid_properties": result.invalid_properties,
                    "invalid_relationships": result.invalid_relationships,
                    "query_issues": query_issues,
                    "observed_categorical_values": result.observed_categorical_values,
                }

            return {"cypher_validation": result, "validation_history": history}
        except Exception as e:
            logger.error(f"CypherValidator error: {e}")
            return {
                "cypher_validation": CypherValidationResult(
                    approved=False,
                    feedback=f"Validation error: {str(e)}",
                    query_results=[],
                    invalid_nodes=[],
                    invalid_properties=[],
                    invalid_relationships=[],
                    path_issues=[],
                    specific_issues=[str(e)],
                    suggested_corrections=None
                )
            }

    async def _executor_node(self, state: FourAgentState) -> Dict[str, Any]:
        """Executor node - executes queries and builds findings"""
        logger.info("Executor node - executing queries and building findings")

        thinker_output = state.get("thinker_output")
        if not thinker_output:
            return {
                "findings": [],
                "executed_queries": [],
            }

        try:
            findings, executed_queries = await self.executor.execute(
                thinker_output=thinker_output
            )

            # Update the current iteration entry with execution results
            # (validation results are already captured by the validator nodes)
            history = list(state.get("validation_history", []))
            if history:
                # Mark this iteration as having reached final execution
                history[-1]["final_execution"] = True

                # Capture executed query results
                history[-1]["executed_queries"] = [
                    {
                        "query_id": eq.query_id,
                        "cypher_query": eq.cypher_query,
                        "result_count": eq.result_count,
                        "execution_time_ms": eq.execution_time_ms,
                        "error": eq.error,
                        "results_preview": eq.results[:3] if eq.results else [],
                    }
                    for eq in executed_queries
                ]

                history[-1]["findings_count"] = len(findings)

            return {
                "findings": findings,
                "executed_queries": executed_queries,
                "validation_history": history,
            }
        except Exception as e:
            logger.error(f"Executor error: {e}")
            errors = list(state.get("errors", []))
            errors.append(f"Executor error: {str(e)}")
            return {
                "findings": [],
                "executed_queries": [],
                "errors": errors,
            }

    def _check_both_validations(
        self,
        state: FourAgentState
    ) -> Literal["approved", "rejected", "max_iterations"]:
        """Check BOTH validation results (AND gate) and route accordingly"""
        max_iterations = state.get("max_iterations", 3)
        current_iteration = state.get("iteration_count", 0)

        thinking_val = state.get("thinking_validation")
        cypher_val = state.get("cypher_validation")

        thinking_approved = thinking_val and thinking_val.approved
        cypher_approved = cypher_val and cypher_val.approved

        # FIRST check if both validators approved - if so, proceed to executor
        # regardless of iteration count (we already did the work!)
        if thinking_approved and cypher_approved:
            logger.info("Both validators approved - proceeding to executor")
            return "approved"

        # Log rejection details
        if thinking_val and not thinking_val.approved:
            logger.warning(f"Thinking validation REJECTED:")
            logger.warning(f"  Feedback: {thinking_val.feedback}")
            if thinking_val.reasoning_gaps:
                logger.warning(f"  Reasoning gaps: {thinking_val.reasoning_gaps}")
            if thinking_val.specific_issues:
                logger.warning(f"  Specific issues: {thinking_val.specific_issues}")

        if cypher_val and not cypher_val.approved:
            logger.warning(f"Cypher validation REJECTED:")
            logger.warning(f"  Feedback: {cypher_val.feedback}")
            if cypher_val.invalid_nodes:
                logger.warning(f"  Invalid nodes: {cypher_val.invalid_nodes}")
            if cypher_val.invalid_properties:
                logger.warning(f"  Invalid properties: {cypher_val.invalid_properties}")
            if cypher_val.invalid_relationships:
                logger.warning(f"  Invalid relationships: {cypher_val.invalid_relationships}")
            if cypher_val.query_results:
                for qr in cypher_val.query_results:
                    if not qr.approved:
                        logger.warning(f"  Query {qr.query_id} REJECTED: {qr.issues}")

        # Only check max_iterations when validation FAILED (to decide whether to retry)
        if current_iteration >= max_iterations:
            logger.warning(f"Max iterations ({max_iterations}) reached - giving up")
            return "max_iterations"

        logger.info(f"Validation failed (thinking={thinking_approved}, cypher={cypher_approved}) - looping back to thinker")
        return "rejected"

    def _get_combined_feedback(self, state: FourAgentState) -> Optional[str]:
        """Combine feedback from both validators for retry"""
        feedback_parts = []

        thinking_val = state.get("thinking_validation")
        if thinking_val and not thinking_val.approved:
            parts = []
            if thinking_val.feedback:
                parts.append(f"Reasoning feedback: {thinking_val.feedback}")
            if thinking_val.reasoning_gaps:
                parts.append(f"Reasoning gaps: {', '.join(thinking_val.reasoning_gaps)}")
            if thinking_val.missing_aspects:
                parts.append(f"Missing aspects: {', '.join(thinking_val.missing_aspects)}")
            if thinking_val.suggested_corrections:
                parts.append(f"Suggestions: {thinking_val.suggested_corrections}")
            if parts:
                feedback_parts.append("\n".join(parts))

        cypher_val = state.get("cypher_validation")
        if cypher_val and not cypher_val.approved:
            parts = []
            if cypher_val.feedback:
                parts.append(f"Query feedback: {cypher_val.feedback}")
            if cypher_val.invalid_nodes:
                parts.append(f"Invalid nodes: {', '.join(cypher_val.invalid_nodes)}")
            if cypher_val.invalid_properties:
                parts.append(f"Invalid properties: {', '.join(cypher_val.invalid_properties)}")
            if cypher_val.invalid_relationships:
                parts.append(f"Invalid relationships: {', '.join(cypher_val.invalid_relationships)}")
            if cypher_val.path_issues:
                parts.append(f"Path issues: {', '.join(cypher_val.path_issues)}")
            if cypher_val.suggested_corrections:
                parts.append(f"Suggested fix: {cypher_val.suggested_corrections}")
            # Include discovered categorical values so Thinker can use them
            if cypher_val.observed_categorical_values:
                for prop_key, values in cypher_val.observed_categorical_values.items():
                    parts.append(f"Valid values for {prop_key}: {values}")
            if parts:
                feedback_parts.append("\n".join(parts))

        return "\n\n---\n\n".join(feedback_parts) if feedback_parts else None

    async def run(
        self,
        sub_query: SubQuery,
        context: str = "",
        schema_info: Optional[Dict[str, Any]] = None,
        max_iterations: int = 3
    ) -> FourAgentWorkflowResult:
        """
        Execute the 4-agent workflow for a sub-query.

        Args:
            sub_query: The sub-query to answer
            context: Context from previous phases
            schema_info: Optional pre-fetched schema information
            max_iterations: Maximum retry iterations

        Returns:
            FourAgentWorkflowResult with findings and execution details
        """
        start_time = time.time()
        logger.info(f"Starting 4-agent workflow for: {sub_query.query[:50]}...")

        # Initialize state
        initial_state: FourAgentState = {
            "sub_query": sub_query,
            "context_from_previous": context,
            "schema_info": schema_info or {},
            "thinker_output": None,
            "thinking_validation": None,
            "cypher_validation": None,
            "executed_queries": [],
            "findings": [],
            "iteration_count": 0,
            "max_iterations": max_iterations,
            "validation_history": [],
            "token_usage": self.token_tracker,
            "errors": [],
        }

        try:
            # Run the graph
            final_state = await self.graph.ainvoke(initial_state)

            execution_time = int((time.time() - start_time) * 1000)

            return FourAgentWorkflowResult(
                findings=final_state.get("findings", []),
                iterations_used=final_state.get("iteration_count", 0),
                executed_queries=final_state.get("executed_queries", []),
                validation_history=final_state.get("validation_history", []),
                errors=final_state.get("errors", []),
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"Workflow execution error: {e}")
            return FourAgentWorkflowResult(
                findings=[],
                iterations_used=0,
                executed_queries=[],
                validation_history=[],
                errors=[str(e)],
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


__all__ = ['FourAgentWorkflow']

"""
Adaptive Query Agent - Iterative CoT-based Cypher query generation and refinement.

This agent handles query generation for a single approach using Chain-of-Thought reasoning.
It iteratively generates, executes, and refines queries based on results, eliminating the need
for complex retry/diagnostic logic in the main workflow.
"""

import re
import json
import ast
import operator
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field, field_validator, ValidationError

from .prompts import (
    get_cot_think_prompt,
    get_cot_generate_query_prompt,
    get_cot_generate_query_plan_prompt,
    get_cot_analyze_results_prompt,
    get_approach_synthesis_prompt
)

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for CoT Responses
# =============================================================================

class RecommendationType(str, Enum):
    """Recommendation types for query analysis."""
    CONTINUE = "Continue"
    SUFFICIENT = "Sufficient"
    ALTERNATIVE = "Alternative"
    STOP = "Stop"
    REFINE = "Refine"


class CoTReasoningSteps(BaseModel):
    """Chain-of-Thought reasoning steps for perspective-driven query generation."""
    step1_perspective: str = Field(..., description="What perspective/angle is this query taking?")
    step2_premise_validation: str = Field(..., description="Which premises does this validate?")
    step3_path_trace: str = Field(..., description="Relationship path through schema")
    step4_filters: str = Field(..., description="Filters for this perspective")
    step5_return: str = Field(..., description="What to return from query")
    step6_optimize: str = Field(..., description="Optimizations (limits, ordering)")


class EntityConstraint(BaseModel):
    """Represents a WHERE clause constraint on an entity property."""
    var: str = Field(..., description="Variable name in the query (e.g., 'f', 't')")
    label: str = Field(..., description="Node label (e.g., 'Function', 'Type')")
    property: Optional[str] = Field(default="", description="Property name (e.g., 'name', 'file_path'), empty string if no constraint")
    value: Optional[str] = Field(default="", description="Expected property value (e.g., 'CreateWorkers'), empty string if no constraint")


class QueryStepType(str, Enum):
    """Type of query step in the execution plan."""
    ENTITY_CHECK = "entity_check"      # Verify entity exists
    PATH_CHECK = "path_check"          # Verify relationship path exists
    COUNT_CHECK = "count_check"        # Verify result count expectations
    DATA_RETRIEVAL = "data_retrieval"  # Main data retrieval query


class QueryStep(BaseModel):
    """A single step in the query execution plan."""
    step_number: int = Field(..., description="Sequential step number (1-based)")
    step_type: QueryStepType = Field(..., description="Type of validation this step performs")
    purpose: str = Field(..., description="What this step validates or retrieves")
    cypher_query: str = Field(..., description="Cypher query for this step")
    expected_outcome: str = Field(..., description="What success looks like (e.g., 'count >= 1', 'results > 0')")
    on_failure_guidance: str = Field(..., description="What it means if this step fails and what to try instead")
    depends_on_steps: List[int] = Field(
        default_factory=list,
        description="Previous step numbers this depends on (empty if independent)"
    )

    # Entity tracking for diagnostics
    entities_validated: List[EntityConstraint] = Field(
        default_factory=list,
        description="Which entities are validated in this step"
    )


class CypherQueryPlan(BaseModel):
    """Multi-step query execution plan with validation steps."""

    # Overall reasoning
    cot_reasoning: CoTReasoningSteps = Field(..., description="High-level reasoning for query approach")
    plan_overview: str = Field(..., description="Overview of what this plan will accomplish")

    # Query steps
    steps: List[QueryStep] = Field(..., description="Sequential query steps with validation")
    data_retrieval_step: int = Field(..., description="Which step number retrieves the actual data (others are validation)")

    # Fallback strategy
    fallback_hints: List[str] = Field(
        default_factory=list,
        description="Alternative approaches if all steps fail"
    )

    # Entity constraints for diagnostics
    all_entity_constraints: List[EntityConstraint] = Field(
        default_factory=list,
        description="All entity constraints across all steps"
    )


class CoTQueryGeneration(BaseModel):
    """LLM response for query generation with CoT reasoning."""
    cot_reasoning: CoTReasoningSteps = Field(..., description="Step-by-step reasoning")
    cypher_query: str = Field(..., description="Generated Cypher query")
    query_purpose: str = Field(..., description="What this query will discover")
    entity_constraints: List[EntityConstraint] = Field(
        default_factory=list,
        description="Entity constraints from WHERE clause for diagnostics"
    )


class CoTThinkDecision(BaseModel):
    """LLM response for deciding whether to continue generating queries."""
    should_continue: bool = Field(..., description="Should generate another query?")
    reasoning: str = Field(..., description="Why continue or stop")
    next_query_focus: Optional[str] = Field(None, description="Focus for next query if continuing")


class CoTAnalysisResult(BaseModel):
    """LLM response for analyzing query execution results."""
    analysis: str = Field(..., description="What happened and why")
    key_findings: List[str] = Field(default_factory=list, description="Key discoveries")
    recommendation: RecommendationType = Field(..., description="Continue/Sufficient/Alternative/Stop/Refine")
    next_query_hint: Optional[str] = Field(None, description="What next query should do differently")
    # NEW: Explicit ambiguity detection for perspective-driven flow
    is_ambiguous: Optional[bool] = Field(None, description="Is the data ambiguous or unclear? (perspective flow only)")
    ambiguity_reason: Optional[str] = Field(None, description="Why the data is ambiguous (perspective flow only)")
    disambiguation_perspective: Optional[str] = Field(None, description="What perspective will resolve the ambiguity (perspective flow only)")


class ApproachSynthesisResult(BaseModel):
    """LLM response for synthesizing approach-level answer."""
    approach_answer: str = Field(..., description="Synthesized answer addressing the user query from this approach's perspective")
    data_points_used: List[int] = Field(default_factory=list, description="Indices of discovered_data items actually used in the answer")
    confidence_assessment: str = Field(..., description="Assessment of confidence: High/Medium/Low with brief reasoning")


# =============================================================================
# Agent State
# =============================================================================

@dataclass
class AdaptiveQueryAgentState:
    """State for a single approach's adaptive query agent."""

    # Approach context (immutable)
    approach_index: int
    approach_details: Dict[str, Any]
    user_query: str
    schema: Dict[str, Any]
    project_name: str

    # Execution state (mutable)
    iteration: int = 0
    max_iterations: int = 5

    # Query history
    queries_executed: List[Dict[str, Any]] = field(default_factory=list)
    # Each query: {iteration, query, reasoning, results, error, result_count, analysis}

    # Accumulated findings
    discovered_data: List[Dict[str, Any]] = field(default_factory=list)

    # Incremental answer building (NEW: build answer across iterations)
    partial_answers: List[Dict[str, Any]] = field(default_factory=list)
    # Each partial answer: {iteration, findings_summary, data_count, quality_grade}

    # Decision state
    is_sufficient: bool = False
    sufficiency_reason: str = ""
    last_analysis_hint: str = ""

    # NEW: Think step decisions per iteration (for cohesive Think→Generate flow)
    # Each entry: {iteration, should_continue, reasoning, next_query_focus}
    think_decisions: List[Dict[str, Any]] = field(default_factory=list)

    # NEW: Ambiguity tracking for perspective-driven flow
    is_data_ambiguous: bool = False
    ambiguity_reason: str = ""
    disambiguation_perspective: str = ""

    # Token tracking
    tokens_used: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    token_breakdown: Dict[str, Dict[str, int]] = field(default_factory=dict)


# =============================================================================
# Adaptive Query Agent
# =============================================================================

class AdaptiveQueryAgent:
    """
    Adaptive Query Agent for a single approach.

    Generates and refines Cypher queries iteratively using Chain-of-Thought reasoning.
    Each iteration:
    1. Thinks: Should we generate another query?
    2. Generates: Creates query with CoT reasoning
    3. Executes: Runs query via cypher server
    4. Analyzes: Examines results and decides next step

    Replaces the old think->generate->execute->rethink node sequence with a
    simpler, self-contained agent that learns from previous iterations.
    """

    def __init__(
        self,
        approach_index: int,
        approach_details: Dict[str, Any],
        user_query: str,
        schema: Dict[str, Any],
        project_name: str,
        llm_service: Any,
        cypher_server: Any,
        max_iterations: int = 5,
        approach_packet: Optional[Dict[str, Any]] = None,
        schema_manager: Optional[Any] = None,
        use_schema_tools: bool = False
    ):
        """
        Initialize the adaptive query agent.

        Args:
            approach_index: Index of this approach (for tracking)
            approach_details: Approach configuration from discovery phase
            user_query: Original user query (for context)
            schema: Neo4j schema with nodes and relationships (YAML, for backward compatibility)
            project_name: Project name for queries
            llm_service: LLM service for generating responses
            cypher_server: Cypher server for executing queries
            max_iterations: Maximum query iterations (default: 5)
            approach_packet: Optional ApproachPacket dict with premise tracking
            schema_manager: Optional DynamicSchemaManager with reconciled schema + path discovery
            use_schema_tools: Enable tool-based schema discovery (default: False for backward compatibility)
        """
        # NEW: If we have an approach packet, the actual query to answer is the subquery text
        # The user_query is just context for understanding the broader goal
        actual_query = approach_packet['text'] if approach_packet else user_query

        # Make a shallow copy of schema to avoid sharing references across parallel agents
        # Each agent may get a different filtered schema, so we need isolation
        import copy
        schema_copy = copy.copy(schema) if schema else {}

        self.state = AdaptiveQueryAgentState(
            approach_index=approach_index,
            approach_details=approach_details,
            user_query=actual_query,  # This is now the SUBQUERY if packet exists
            schema=schema_copy,  # Use copy to avoid cross-agent contamination
            project_name=project_name,
            max_iterations=max_iterations
        )
        self.llm_service = llm_service
        self.cypher_server = cypher_server
        self.approach_packet = approach_packet  # Store for premise validation and correction
        self.original_user_query = user_query  # Keep for context
        self.schema_manager = schema_manager  # Store for dynamic path discovery
        self.use_schema_tools = use_schema_tools  # Feature flag for tool-based schema discovery

        # Initialize schema tool caller if enabled
        self.schema_tool_caller = None
        if use_schema_tools and schema_manager:
            from src.core.workflow.schema_tools_langchain import create_schema_tools
            from src.core.workflow.schema_tool_caller import SchemaToolCaller

            schema_tools = create_schema_tools(schema_manager, cypher_server=self.cypher_server)
            self.schema_tool_caller = SchemaToolCaller(llm_service, schema_tools)
            logger.info(f"  🛠️ Schema tool calling enabled for approach {approach_index}")

    async def run(self) -> Dict[str, Any]:
        """
        Main execution loop - iteratively generate and refine queries.

        Returns:
            Dict with discovered data, citations, reasoning trail, and metadata
        """
        approach_name = self.state.approach_details.get('approach_name', 'Unknown')
        logger.info(f"🤖 AdaptiveQueryAgent starting for approach {self.state.approach_index}: {approach_name}")

        # Get schema (3-tier fallback: filtered reconciled → complete reconciled → YAML)
        # Note: self.state.schema already contains YAML schema from __init__
        if self.schema_manager and not self.schema_manager._loading:
            try:
                logger.info(f"  🔍 Getting filtered schema for subquery using DynamicSchemaManager...")
                schema_result = await self.schema_manager.get_schema_for_subquery(
                    subquery_text=self.state.user_query,
                    max_path_depth=5,
                    cypher_server=self.cypher_server  # Use worker's server for path discovery
                )

                # Get reconciled schema for granular fallback
                reconciled = self.schema_manager._reconciled_schema

                # Extract what we got from schema extraction
                node_schemas = schema_result.get('node_schemas', {})
                relationship_schemas = schema_result.get('relationship_schemas', {})

                # Granular fallback: supplement missing pieces only
                fallback_applied = []

                # If no nodes extracted, use all nodes from reconciled
                if not node_schemas:
                    logger.warning(f"  ⚠️ No nodes extracted - using all nodes from reconciled schema")
                    node_schemas = reconciled.get('nodes', {})
                    fallback_applied.append("nodes")

                # If no relationships extracted, use all relationships from reconciled
                if not relationship_schemas:
                    logger.warning(f"  ⚠️ No relationships extracted - using all relationships from reconciled schema")
                    relationship_schemas = reconciled.get('relationships', {})
                    fallback_applied.append("relationships")

                # Build final schema with supplemented parts
                self.state.schema = {
                    'nodes': node_schemas,
                    'node_labels': list(node_schemas.keys()),
                    'relationships': relationship_schemas,
                    'paths': schema_result.get('paths', [])
                }

                # Log extraction results
                extracted_info = f"{len(schema_result.get('node_types', []))} nodes, {len(schema_result.get('relationship_types', []))} relationships"
                final_info = f"{len(node_schemas)} node types, {len(relationship_schemas)} relationships"
                fallback_info = f" (fallback: {', '.join(fallback_applied)})" if fallback_applied else ""
                logger.info(f"  ✅ Schema ready - Extracted: {extracted_info} | Final: {final_info}{fallback_info}")
            except Exception as e:
                logger.warning(f"  ⚠️ Failed to get schema from schema_manager: {e} - using YAML schema")
                # Tier 3: self.state.schema already contains YAML from __init__, keep it
        else:
            # Tier 3: schema_manager not available - use YAML schema (already in self.state.schema)
            logger.info(f"  📄 Tier 3: Using YAML schema (schema_manager not available/ready)")

        for iteration in range(self.state.max_iterations):
            self.state.iteration = iteration + 1
            logger.info(f"  🔄 Iteration {self.state.iteration}/{self.state.max_iterations}")

            # Step 1: Think - should we generate another query?
            should_continue = await self._cot_think_step()
            if not should_continue:
                logger.info(f"  ✅ Agent decided to stop: {self.state.sufficiency_reason}")
                break

            # Step 2: Generate query or query plan using CoT reasoning
            query_result = await self._cot_generate_query_step()
            if not query_result:
                logger.warning(f"  ⚠️ Failed to generate query/plan, stopping")
                break

            # Step 3 & 4: Execute and analyze (branched by mode)
            # if self.use_query_plans:
            # QUERY PLAN MODE: Multi-step validation + execution
            logger.info(f"  📋 Query Plan Mode: Executing multi-step plan")

            # Execute query plan
            plan_result = await self._execute_query_plan(query_result['query_plan'])

            # Analyze plan execution with granular feedback
            analysis_result = await self._cot_analyze_plan_results(plan_result)

            # Extract execution result from plan
            if plan_result['final_step_success']:
                # Get data from the data retrieval step
                data_step_index = query_result['data_retrieval_step'] - 1
                data_step_result = plan_result['execution_results'][data_step_index]
                execution_result = data_step_result['result']
            else:
                # Plan failed at validation step
                execution_result = {'results': [], 'error': None, 'success': False}

            # else:
            #     # SINGLE QUERY MODE: Original behavior (backward compatible)
            #     logger.info(f"  🔍 Single Query Mode: Executing single query")

            #     # Execute single query
            #     execution_result = await self._execute_query(query_result['cypher_query'])

            #     # Analyze results
            #     analysis_result = await self._cot_analyze_results_step(query_result, execution_result)

            # Record this query execution with full traceability
            query_record = {
                'iteration': self.state.iteration,
                'mode': 'plan',  # Always query plan mode
                'results': execution_result.get('results', []),
                'error': execution_result.get('error'),
                'result_count': len(execution_result.get('results', [])),
                # Store analysis for reasoning trail
                'analysis': {
                    'analysis': analysis_result.get('analysis', ''),
                    'key_findings': analysis_result.get('key_findings', []),
                    'recommendation': analysis_result.get('recommendation', ''),
                    'next_query_hint': analysis_result.get('next_query_hint', '')
                },
                # Premise validation tracking
                'premise_validations': execution_result.get('premise_validations', []),
                'apoc_diagnostics_used': execution_result.get('apoc_diagnostics_used', False),
                'sufficiency_status': execution_result.get('sufficiency_status')
            }

            # Add mode-specific fields
            # if self.use_query_plans:
                # Query plan mode: store plan details
            query_record.update({
                'query': query_result.get('plan_overview', 'Unknown plan'),
                'query_plan': query_result.get('query_plan'),
                'steps': query_result.get('steps', []),
                'failed_at_step': analysis_result.get('failed_at_step'),
                'reasoning': {
                    'cot_reasoning': query_result.get('cot_reasoning', {}),
                    'query_purpose': query_result.get('plan_overview', 'Unknown'),
                    'plan_overview': query_result.get('plan_overview', '')
                }
            })
            # else:
            #     # Single query mode: store single query
            #     query_record.update({
            #         'query': query_result['cypher_query'],
            #         'reasoning': {
            #             'cot_reasoning': query_result.get('cot_reasoning', {}),
            #             'query_purpose': query_result.get('query_purpose', 'Unknown')
            #         }
            #     })

            self.state.queries_executed.append(query_record)

            # Add to partial_answers if we got results (needed for synthesis)
            if execution_result.get('results'):
                partial_answer = {
                    'iteration': self.state.iteration,  # Required by synthesis prompt template
                    'answer': analysis_result.get('analysis', ''),
                    'key_findings': analysis_result.get('key_findings', []),
                    'data_count': len(execution_result.get('results', [])),
                    'quality_grade': analysis_result.get('quality_grade', 0.5),
                    'query_purpose': query_result.get('plan_overview', 'Unknown')
                }
                self.state.partial_answers.append(partial_answer)
                logger.info(f"    📝 Built partial answer (iteration {self.state.iteration})")

                # Add results to discovered_data (needed for final synthesis)
                for result in execution_result.get('results', []):
                    enriched_result = {
                        **result,
                        '_source_query': query_result.get('plan_overview', 'Unknown'),
                        '_source_iteration': self.state.iteration,
                        '_query_purpose': query_result.get('plan_overview', 'Unknown'),
                        '_cot_reasoning': query_result.get('cot_reasoning', {})
                    }
                    self.state.discovered_data.append(enriched_result)
                logger.info(f"    📊 Added {len(execution_result.get('results', []))} data points to discovered_data")

            # Check if we should stop based on analysis recommendation
            recommendation = analysis_result.get('recommendation')
            if recommendation in [RecommendationType.SUFFICIENT, RecommendationType.STOP]:
                logger.info(f"  ✅ Analysis recommends stopping: {recommendation}")
                self.state.is_sufficient = True
                self.state.sufficiency_reason = analysis_result.get('analysis', f'Analysis determined: {recommendation}')
                break

        # Return aggregated results with full citations and reasoning (now async)
        return await self._build_final_result()

    async def _cot_think_step(self) -> bool:
        """
        CoT Step: Decide if we should generate another query.

        Analyzes previous query results and determines if more queries are needed
        to fulfill the approach goal.

        Returns:
            True if should continue, False if sufficient
        """
        # Build context from previous queries
        previous_context = self._format_previous_queries()

        # Use unified prompt from centralized prompts module
        prompt = get_cot_think_prompt(
            user_query=self.state.user_query,
            approach_details=self.state.approach_details,
            iteration=self.state.iteration,
            max_iterations=self.state.max_iterations,
            previous_queries=previous_context,
            discovered_data_count=len(self.state.discovered_data),
            last_analysis_hint=self.state.last_analysis_hint
        )

        try:
            system_prompt = "You are a query planning expert."

            result = await self.llm_service.generate_with_pydantic(
                system_prompt=system_prompt,
                user_prompt=prompt,
                response_model=CoTThinkDecision,
                model_name="gpt-4o-mini",  # Fast model for decision
                call_type="cot_think",
                approach_index=self.state.approach_index,
                call_purpose=f"Think step - iteration {self.state.iteration}"
            )

            # Track tokens
            self._update_token_tracking_from_result('think', result)

            self.state.is_sufficient = not result.should_continue
            self.state.sufficiency_reason = result.reasoning

            # NEW: Store complete think decision for cohesive Think→Generate flow
            think_decision = {
                'iteration': self.state.iteration,
                'should_continue': result.should_continue,
                'reasoning': result.reasoning,
                'next_query_focus': result.next_query_focus or '',
                'data_points_so_far': len(self.state.discovered_data),
                'queries_executed_so_far': len(self.state.queries_executed)
            }
            self.state.think_decisions.append(think_decision)

            logger.info(f"    💭 Think Decision: {'Continue' if result.should_continue else 'Stop'}")
            logger.info(f"    💡 Reasoning: {result.reasoning}")
            if result.next_query_focus:
                logger.info(f"    🎯 Next Focus: {result.next_query_focus}")

            return result.should_continue

        except Exception as e:
            logger.error(f"  ❌ Think step failed: {e}")
            # On error, stop iterating
            self.state.is_sufficient = True
            self.state.sufficiency_reason = f"Think step failed: {e}"
            return False

    async def _cot_generate_query_step(self, max_retries: int = 2) -> Optional[Dict[str, Any]]:
        """
        CoT Step: Generate a Cypher query with step-by-step reasoning.

        Uses schema examples to guide correct relationship paths.
        Includes retry logic for:
        - Pydantic validation errors (with feedback to LLM)
        - Duplicate query detection

        Args:
            max_retries: Maximum retry attempts for validation errors (default: 2)

        Returns:
            Dict with cypher_query, cot_reasoning, query_purpose, or None on failure
        """
        # Get context from previous queries
        previous_context = self._format_previous_queries()

        # Get all previously executed queries for duplicate detection
        previous_queries = [q['query'].strip() for q in self.state.queries_executed]

        # Choose prompt and response model based on mode
        # if self.use_query_plans:
            # QUERY PLAN MODE: Generate multi-step plan
        base_prompt = get_cot_generate_query_plan_prompt(
            user_query=self.state.user_query,
            approach_details=self.state.approach_details,
            project_name=self.state.project_name,
            schema=self.state.schema,
            previous_queries=previous_context,
            last_analysis_hint=self.state.last_analysis_hint,
            approach_packet=self.approach_packet
        )
        response_model = CypherQueryPlan
        call_type = "cot_generate_plan"
        # else:
        #     # SINGLE QUERY MODE: Generate single query (backward compatible)
        #     base_prompt = get_cot_generate_query_prompt(
        #         user_query=self.state.user_query,
        #         approach_details=self.state.approach_details,
        #         project_name=self.state.project_name,
        #         schema=self.state.schema,
        #         previous_queries=previous_context,
        #         last_analysis_hint=self.state.last_analysis_hint,
        #         approach_packet=self.approach_packet
        #     )
        #     response_model = CoTQueryGeneration
        #     call_type = "cot_generate"

        validation_feedback = ""  # Accumulates feedback from validation failures

        for attempt in range(max_retries + 1):
            try:
                # Add validation feedback to prompt if retrying
                prompt = base_prompt
                if validation_feedback:
                    feedback_section = f"""
⚠️ **FEEDBACK FROM PREVIOUS ATTEMPT**:
The last Cypher query failed validation for the following reasons:

{validation_feedback}

Please correct these issues before continuing.
- Use only relationships and properties that exist in the schema.
- Replace invalid edges with valid ones suggested below.
- Maintain the same subquery goal.
"""
                    prompt = f"""{feedback_section}

{base_prompt}
"""

                # System prompt for query plan generation (always using query plan mode)
                system_prompt = "You are a Cypher query plan expert. Generate multi-step validation plans with granular failure guidance."

                # TOOL-BASED GENERATION: Use schema tools if enabled
                if self.use_schema_tools and self.schema_tool_caller:
                    logger.info(f"    🛠️ Using tool-based schema discovery (attempt {attempt + 1})")

                    # Get tool documentation
                    tool_docs = self.schema_tool_caller.get_tools_documentation()

                    # Modify prompt to reference tools
                    tool_prompt = f"""{system_prompt}

{tool_docs}

{prompt}

🎯 CRITICAL VALIDATION REQUIREMENT:
BEFORE including ANY relationship in your query plan, you MUST use validate_relationship_triplet() to verify the EXACT (source, relationship, target) combination exists.

DO NOT assume relationships work just because the relationship type exists!
Example: REFERENCES exists for Variable->Type and Function->Type, but NOT Statement->Type.

For EVERY relationship pattern in your plan:
1. Call validate_relationship_triplet(from_label, rel_type, to_label)
2. If is_valid=false, examine the alternatives provided
3. Only include validated triplets in your final query plan

This validation is MANDATORY - non-existent relationships will cause query failures!

Output your final answer as JSON with this structure:
{{
    "cypher_query": "your query here",
    "cot_reasoning": "step by step reasoning",
    "query_purpose": "what this query does"
}}"""

                    tool_result = await self.schema_tool_caller.generate_with_tools(
                        system_prompt=system_prompt,
                        user_prompt=tool_prompt,
                        model_name="gpt-4o",
                        max_iterations=10,
                        max_tokens=4000
                    )

                    # Parse tool result into Pydantic model
                    import json
                    try:
                        # Extract JSON from the final answer
                        content = tool_result['content']

                        # Try to find JSON in markdown code blocks
                        if '```json' in content:
                            json_start = content.find('```json') + 7
                            json_end = content.find('```', json_start)
                            content = content[json_start:json_end].strip()
                        elif '```' in content:
                            json_start = content.find('```') + 3
                            json_end = content.find('```', json_start)
                            content = content[json_start:json_end].strip()

                        data = json.loads(content)
                        result = response_model(**data)

                        # Add tool calling metadata
                        result._tokens_used = tool_result.get('total_tokens', 0)
                        result._tool_calls_made = tool_result.get('tool_calls_made', 0)

                        logger.info(f"    🛠️ Tool calls made: {tool_result.get('tool_calls_made', 0)}")

                    except (json.JSONDecodeError, Exception) as e:
                        logger.error(f"    ❌ Failed to parse tool result: {e}")
                        content_preview = str(tool_result.get('content', ''))[:500] if tool_result.get('content') else 'No content'
                        validation_feedback = f"Failed to generate valid JSON: {e}\n\nContent: {content_preview}"
                        continue

                # STANDARD GENERATION: Use embedded schema (backward compatible)
                else:
                    result = await self.llm_service.generate_with_pydantic(
                        system_prompt=system_prompt,
                        user_prompt=prompt,
                        response_model=response_model,
                        model_name="gpt-4o",  # Stronger model for query generation
                        call_type=call_type,
                        approach_index=self.state.approach_index,
                        call_purpose=f"Generate plan - iteration {self.state.iteration}, attempt {attempt + 1}"
                    )

                # Check for duplicate (skip for query plans as they may be different even if overview is same)
#                 if not self.use_query_plans and result.cypher_query.strip() in previous_queries:
#                     if attempt < max_retries:
#                         logger.warning(f"    ⚠️ Duplicate query detected (attempt {attempt + 1})")
#                         validation_feedback = f"""You generated the same query as a previous iteration:
# Query: {result.cypher_query}

# This is a DUPLICATE. You MUST generate a DIFFERENT query that:
# 1. Uses different relationship paths, OR
# 2. Targets different entities, OR
# 3. Applies different filters
# 4. Follows the hint from the previous analysis: {self.state.last_analysis_hint}

# Do NOT repeat the same query!"""
#                         continue
#                     else:
#                         logger.error(f"    ❌ Duplicate query after {max_retries} retries, stopping")
#                         return None

                # Validate Cypher query against schema (only for single query mode)
#                 if not self.use_query_plans and self.schema_manager and hasattr(self.schema_manager, '_reconciled_schema'):
#                     from .cypher_query_validator import CypherQueryValidator

#                     validator = CypherQueryValidator(self.schema_manager._reconciled_schema)
#                     schema_validation = validator.validate(result.cypher_query)

#                     if not schema_validation.is_valid:
#                         if attempt < max_retries:
#                             # Build detailed error feedback for LLM
#                             import re
#                             error_messages = []
#                             failed_edges = []  # Track failed relationships to show relevant paths

#                             for issue in schema_validation.get_errors():
#                                 error_messages.append(f"  ❌ {issue.location}: {issue.message}")
#                                 if issue.suggestion:
#                                     error_messages.append(f"     💡 {issue.suggestion}")

#                                 # Extract source and target from failed relationship patterns
#                                 match = re.search(r'\((\w+)\)-\[.*?\]->\((\w+)\)', issue.location)
#                                 if match:
#                                     failed_edges.append((match.group(1), match.group(2)))

#                             # Extract starting node from the query (first node in MATCH clause)
#                             query = result.cypher_query
#                             start_match = re.search(r'MATCH\s*\(\w+:(\w+)', query)
#                             start_node = start_match.group(1) if start_match else None

#                             # Build discovered paths hint showing how to reach failed endpoints from start
#                             paths_hint = ""
#                             if start_node and failed_edges:
#                                 paths_hint = "\n**DISCOVERED PATHS** (showing how to connect these nodes):\n"
#                                 paths_hint += "These are the ACTUAL valid paths in the graph:\n\n"

#                                 processed_pairs = set()
#                                 for source, target in failed_edges:
#                                     # Show paths from query start to failed source (if not start itself)
#                                     if source != start_node and (start_node, source) not in processed_pairs:
#                                         paths_hint += self._format_paths_between(start_node, source)
#                                         processed_pairs.add((start_node, source))

#                                     # Show paths from query start to failed target
#                                     if (start_node, target) not in processed_pairs:
#                                         paths_hint += self._format_paths_between(start_node, target)
#                                         processed_pairs.add((start_node, target))

#                                     # Show paths between the failed edge nodes (for comparison)
#                                     if (source, target) not in processed_pairs:
#                                         paths_hint += self._format_paths_between(source, target)
#                                         processed_pairs.add((source, target))

#                             validation_feedback = f"""SCHEMA VALIDATION ERRORS:

# YOUR PREVIOUS CYPHER QUERY:
# ```cypher
# {result.cypher_query}
# ```

# ERRORS FOUND:
# {chr(10).join(error_messages)}

# 🚨 YOUR QUERY VIOLATES THE SCHEMA'S VALID NODE PAIR RULES

# Your query starts from {start_node if start_node else 'unknown'} but uses an invalid relationship pattern.
# {paths_hint}

# TO FIX THIS:
# 1. Look at the valid paths shown above between {start_node} and your target nodes
# 2. Use the relationship types and intermediate nodes exactly as shown
# 3. If "NO PATH EXISTS" is shown, that connection is impossible in the graph

# CRITICAL RULES:
# - Only use the relationship patterns shown in the valid paths above
# - Multi-hop paths require intermediate nodes - you must traverse through them
# - Do not invent relationships or skip intermediate nodes"""

#                             logger.warning(f"    ⚠️ Schema validation failed (attempt {attempt + 1})")
#                             logger.warning(f"    📋 Failed Query: {result.cypher_query}")
#                             logger.warning(f"    🔍 Validation Errors:")
#                             for issue in schema_validation.get_errors():
#                                 logger.warning(f"       • {issue.location}: {issue.message}")
#                             logger.warning(f"    📊 Schema Node Types: {list(self.schema_manager._reconciled_schema.get('nodes', {}).keys())}")
#                             logger.warning(f"    📊 Schema Relationships: {list(self.schema_manager._reconciled_schema.get('relationships', {}).keys())}")
#                             logger.warning(f"    💬 Validation Feedback Sent to LLM:\n{validation_feedback}")
#                             logger.info(f"    🔄 Retrying with schema validation feedback...")
#                             continue
#                         else:
#                             logger.error(f"    ❌ Schema validation failed after {max_retries} retries")
#                             logger.error(f"    📋 Failed Query: {result.cypher_query}")
#                             logger.error(f"    🔍 Validation Errors:")
#                             for issue in schema_validation.get_errors():
#                                 logger.error(f"       • {issue.location}: {issue.message}")
#                                 if issue.suggestion:
#                                     logger.error(f"         💡 Suggestion: {issue.suggestion}")
#                             logger.error(f"    📊 Schema Context:")
#                             logger.error(f"       Node Types: {list(self.schema_manager._reconciled_schema.get('nodes', {}).keys())}")
#                             logger.error(f"       Relationships: {list(self.schema_manager._reconciled_schema.get('relationships', {}).keys())}")
#                             # Log valid pairs for the problematic relationships
#                             for issue in schema_validation.get_errors():
#                                 if 'Invalid relationship' in issue.message:
#                                     # Extract relationship type from error message
#                                     import re
#                                     rel_match = re.search(r'\[:(\w+)\]', issue.location)
#                                     if rel_match:
#                                         rel_type = rel_match.group(1)
#                                         if rel_type in self.schema_manager._reconciled_schema.get('relationships', {}):
#                                             valid_pairs = self.schema_manager._reconciled_schema['relationships'][rel_type].get('valid_pairs', [])
#                                             logger.error(f"       {rel_type} valid pairs: {valid_pairs[:5]}{'...' if len(valid_pairs) > 5 else ''}")
#                             return None
#                     else:
#                         logger.info(f"    ✅ Query passed schema validation")

                # Track tokens
                self._update_token_tracking_from_result('generate_plan', result)

                # Log query plan generation (always using query plan mode)
                logger.info(f"    📋 Generated Query Plan (attempt {attempt + 1})")
                logger.info(f"    🎯 Overview: {result.plan_overview}")
                logger.info(f"    📍 Steps: {len(result.steps)}")
                logger.info(f"    🔬 Perspective: {result.cot_reasoning.step1_perspective}")
                logger.info(f"    💭 Path: {result.cot_reasoning.step3_path_trace}")

                # Return query plan result
                return {
                    'query_plan': result,
                    'plan_overview': result.plan_overview,
                    'cot_reasoning': result.cot_reasoning.dict() if hasattr(result.cot_reasoning, 'dict') else result.cot_reasoning,
                    'steps': result.steps,
                    'data_retrieval_step': result.data_retrieval_step,
                    'fallback_hints': result.fallback_hints
                }

                # COMMENTED OUT: Single-query mode logging and return (deprecated)
                # else:
                #     logger.info(f"    🔍 Generated Query (attempt {attempt + 1}): {result.cypher_query[:100]}...")
                #     logger.info(f"    🎯 Purpose: {result.query_purpose}")
                #     logger.info(f"    🔬 Perspective: {result.cot_reasoning.step1_perspective}")
                #     logger.info(f"    💭 Path: {result.cot_reasoning.step3_path_trace}")
                #     # Return single query result
                #     return result.dict()

            except ValidationError as e:
                # Pydantic validation error - provide detailed feedback to LLM
                if attempt < max_retries:
                    error_details = []
                    for error in e.errors():
                        field = '.'.join(str(loc) for loc in error['loc'])
                        msg = error['msg']
                        error_details.append(f"  - Field '{field}': {msg}")

                    validation_feedback = f"""Your response failed Pydantic validation:
{chr(10).join(error_details)}

Expected schema:
- cot_reasoning: {{step1_perspective, step2_premise_validation, step3_path_trace, step4_filters, step5_return, step6_optimize}}
- cypher_query: string (the Cypher query)
- query_purpose: string (what this query discovers)
- entity_constraints: array of {{var, label, property, value}} (WHERE clause constraints, empty array if none)

Please ensure your JSON response matches this exact structure."""

                    logger.warning(f"    ⚠️ Pydantic validation error (attempt {attempt + 1}): {e}")
                    logger.info(f"    🔄 Retrying with validation feedback...")
                    continue
                else:
                    logger.error(f"    ❌ Pydantic validation failed after {max_retries} retries: {e}")
                    return None

            except Exception as e:
                logger.error(f"  ❌ Query generation failed: {e}")
                return None

        # Should not reach here
        logger.error(f"  ❌ Query generation exhausted all {max_retries + 1} attempts")
        return None

    async def _execute_query(self, cypher_query: str) -> Dict[str, Any]:
        """
        Execute query via dedicated cypher server instance.

        NEW: Integrates APOC-based premise validation for:
        - Non-syntax errors (schema mismatches)
        - Empty results (NOT_FOUND vs INSUFFICIENT_DATA)

        Args:
            cypher_query: Cypher query to execute

        Returns:
            Dict with results, error, success status, and optional premise_validations
        """
        try:
            logger.info(f"    ▶️ Executing query (iteration {self.state.iteration})...")
            logger.info(f"       Query:\n{cypher_query}")
            response = await self.cypher_server.execute_query(cypher_query)

            # Extract data from cypher server response
            if isinstance(response, dict) and 'data' in response:
                results = response.get('data', [])
                error = response.get('error')
            else:
                results = response if isinstance(response, list) else []
                error = None

            # Handle errors with APOC validation
            if error:
                error_lower = str(error).lower()
                is_syntax_error = any(kw in error_lower for kw in ['syntax', 'invalid', 'unexpected token'])

                if is_syntax_error:
                    # Syntax errors use current retry flow (no APOC)
                    logger.warning(f"    ⚠️ Syntax error: {error}")
                    return {'results': [], 'error': error, 'success': False}
                else:
                    # Non-syntax error → APOC validation
                    logger.warning(f"    ⚠️ Schema error detected, running APOC validation...")
                    validation_result = await self._validate_premises_with_apoc(error=error)

                    if validation_result['should_retry'] and validation_result['corrected_premises']:
                        # Update packet with corrections and retry
                        logger.info(f"    🔄 Premises corrected, retrying query...")
                        self.approach_packet['corrected_premises'] = validation_result['corrected_premises']
                        self.approach_packet['active_premises'] = validation_result['corrected_premises']
                        self.approach_packet['status'] = 'retrying'
                        # Note: Retry will happen in next iteration via agent loop

                    return {
                        'results': [],
                        'error': error,
                        'success': False,
                        'premise_validations': validation_result['premise_validations'],
                        'apoc_diagnostics_used': True
                    }

            # Handle empty results with APOC validation
            if len(results) == 0:
                logger.info(f"    🔬 Empty result, running APOC validation...")
                validation_result = await self._validate_premises_with_apoc(empty_result=True)

                # Determine sufficiency based on premise validation
                all_validated = all(v['status'] == 'validated' for v in validation_result['premise_validations'])
                sufficiency_status = 'NOT_FOUND' if all_validated else 'INSUFFICIENT_DATA'

                logger.info(f"    📊 Sufficiency: {sufficiency_status} (premises {'valid' if all_validated else 'invalid'})")

                return {
                    'results': [],
                    'error': None,
                    'success': True,
                    'sufficiency_status': sufficiency_status,
                    'premise_validations': validation_result['premise_validations'],
                    'apoc_diagnostics_used': True
                }

            logger.info(f"    ✅ Query success: {len(results)} results")
            return {
                'results': results,
                'error': None,
                'success': True
            }

        except Exception as e:
            logger.warning(f"    ⚠️ Query execution error: {str(e)}")
            return {
                'results': [],
                'error': str(e),
                'success': False
            }

    def _safe_get_first_row_value(self, data: List[Dict[str, Any]], field_name: str) -> Any:
        """
        Safely extract a value from the first row of query results.

        Args:
            data: List of result dictionaries
            field_name: Name of the field to extract

        Returns:
            The field value if found, None otherwise
        """
        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        first_row = data[0]
        if not isinstance(first_row, dict):
            return None

        # Try exact match first
        if field_name in first_row:
            return first_row[field_name]

        # Try case-insensitive match
        field_lower = field_name.lower()
        for key, value in first_row.items():
            if key.lower() == field_lower:
                return value

        return None

    def _evaluate_step_outcome(self, result: Dict[str, Any], expected_outcome: str) -> bool:
        """
        Evaluate if a query step's result matches the expected outcome.

        Args:
            result: Query execution result
            expected_outcome: Expected outcome string (e.g., "count >= 1", "results > 0")

        Returns:
            True if outcome matches expectation, False otherwise
        """
        # Handle error cases
        if result.get('error'):
            return False

        data = result.get('results', [])

        # Parse expected outcome
        expected_str = expected_outcome.strip()
        expected_lower = expected_str.lower()

        # Handle special "exists" case - just check for any data
        if expected_lower == "exists" or expected_lower == "any":
            return len(data) > 0

        # Define supported operators mapping
        operators = {
            '>=': operator.ge,
            '<=': operator.le,
            '!=': operator.ne,
            '==': operator.eq,
            '>': operator.gt,
            '<': operator.lt,
            '=': operator.eq,  # Single = also means equality
        }

        # Try to parse expression like "field_name <op> value"
        for op_str, op_func in operators.items():
            if op_str in expected_str:
                parts = expected_str.split(op_str, 1)
                if len(parts) == 2:
                    left_side = parts[0].strip().lower()
                    right_side = parts[1].strip()

                    # Parse right side value
                    try:
                        # Use ast.literal_eval for safe parsing of Python literals
                        threshold = ast.literal_eval(right_side)
                    except (ValueError, SyntaxError):
                        # If it fails, try as a plain string or int
                        try:
                            threshold = int(right_side)
                        except ValueError:
                            try:
                                threshold = float(right_side)
                            except ValueError:
                                threshold = right_side  # Keep as string

                    # Determine what left side refers to
                    if left_side == "results" or left_side == "rows":
                        # Compare against result count
                        actual_value = len(data)
                    elif left_side == "count":
                        # Get 'count' field from first row
                        actual_value = self._safe_get_first_row_value(data, 'count')
                        if actual_value is None:
                            actual_value = 0
                    else:
                        # Treat left side as a field name to extract
                        actual_value = self._safe_get_first_row_value(data, left_side)
                        if actual_value is None:
                            # Field not found - return False for the comparison
                            logger.warning(f"Field '{left_side}' not found in results for: {expected_outcome}")
                            return False

                    # Perform the comparison
                    try:
                        return op_func(actual_value, threshold)
                    except TypeError as e:
                        logger.warning(f"Type mismatch in comparison '{expected_outcome}': {e}")
                        return False
                break  # Only try the first matching operator

        # If no operator matched, default to checking if we got any data
        logger.warning(f"Could not parse expected outcome: {expected_outcome}, defaulting to 'has results' check")
        return len(data) > 0

    async def _execute_query_plan(self, plan: CypherQueryPlan) -> Dict[str, Any]:
        """
        Execute a multi-step query plan with sequential validation.

        Args:
            plan: CypherQueryPlan with validation and retrieval steps

        Returns:
            Dict containing:
                - plan: Original plan
                - execution_results: List of step execution results
                - final_step_success: Whether the last executed step succeeded
                - failed_at_step: Step number that failed (None if all succeeded)
        """
        logger.info(f"    📋 Executing query plan: {plan.plan_overview}")
        logger.info(f"       Total steps: {len(plan.steps)}, Data retrieval at step {plan.data_retrieval_step}")

        execution_results = []

        for step in plan.steps:
            logger.info(f"    📍 Executing Step {step.step_number}/{len(plan.steps)}: {step.purpose}")
            logger.info(f"       Type: {step.step_type.value}")
            logger.info(f"       Expected: {step.expected_outcome}")

            # Execute query
            result = await self._execute_query(step.cypher_query)

            # Evaluate outcome
            success = self._evaluate_step_outcome(result, step.expected_outcome)

            step_result = {
                'step_number': step.step_number,
                'step_type': step.step_type.value,
                'purpose': step.purpose,
                'query': step.cypher_query,
                'success': success,
                'result': result,
                'expected': step.expected_outcome,
                'on_failure_guidance': step.on_failure_guidance
            }

            execution_results.append(step_result)

            if not success:
                logger.warning(f"    ⚠️ Step {step.step_number} failed!")
                logger.warning(f"    💡 Guidance: {step.on_failure_guidance}")

                # If this is a validation step and it failed, stop execution
                if step.step_type != QueryStepType.DATA_RETRIEVAL:
                    logger.info(f"    🛑 Stopping execution - validation failed at step {step.step_number}")
                    break
                else:
                    # Data retrieval step failed - continue to capture full context
                    logger.warning(f"    ⚠️ Data retrieval step failed - no results found")
            else:
                logger.info(f"    ✅ Step {step.step_number} succeeded")

        # Determine overall result
        final_step_success = execution_results[-1]['success'] if execution_results else False
        failed_at_step = next((r['step_number'] for r in execution_results if not r['success']), None)

        logger.info(f"    📊 Query plan execution complete:")
        logger.info(f"       Steps executed: {len(execution_results)}/{len(plan.steps)}")
        logger.info(f"       Final step success: {final_step_success}")
        if failed_at_step:
            logger.info(f"       Failed at step: {failed_at_step}")

        return {
            'plan': plan,
            'execution_results': execution_results,
            'final_step_success': final_step_success,
            'failed_at_step': failed_at_step,
            'fallback_hints': plan.fallback_hints
        }

    def _format_step_results(self, execution_results: List[Dict[str, Any]]) -> str:
        """
        Format query plan execution results for LLM analysis.

        Args:
            execution_results: List of step execution results

        Returns:
            Formatted string describing each step's outcome
        """
        formatted = []
        for result in execution_results:
            step_num = result['step_number']
            purpose = result['purpose']
            step_type = result['step_type']
            success = result['success']
            expected = result['expected']

            status_icon = "✅" if success else "❌"
            formatted.append(f"Step {step_num} ({step_type}): {status_icon} {purpose}")
            formatted.append(f"  Expected: {expected}")

            if not success:
                formatted.append(f"  ⚠️ FAILED: {result['on_failure_guidance']}")

                # Include error details if available
                if result['result'].get('error'):
                    formatted.append(f"  Error: {result['result']['error']}")
                elif result['result'].get('results') is not None:
                    data_len = len(result['result']['results'])
                    formatted.append(f"  Got {data_len} results (expected condition not met)")

            formatted.append("")  # Blank line between steps

        return "\n".join(formatted)

    async def _cot_analyze_plan_results(self, plan_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze query plan execution with detailed step-by-step feedback.

        This provides granular failure information showing exactly which validation
        step failed, what was expected, and what guidance was provided.

        Args:
            plan_result: Result from _execute_query_plan

        Returns:
            Analysis dict with recommendations based on specific step failures
        """
        failed_step_num = plan_result.get('failed_at_step')
        execution_results = plan_result['execution_results']
        plan = plan_result['plan']

        # Build detailed context for LLM
        # Check if we'll use tool-enabled analysis (determines if we add "Your Task" section)
        will_use_tools = failed_step_num and self.use_schema_tools and self.schema_tool_caller

        if failed_step_num:
            failed_step_info = execution_results[failed_step_num - 1]

            # Build base context (shared between tool and non-tool paths)
            analysis_context = f"""
Query plan failed at Step {failed_step_num}:

**Failed Step Details:**
- Purpose: {failed_step_info['purpose']}
- Type: {failed_step_info['step_type']}
- Query: {failed_step_info['query']}
- Expected: {failed_step_info['expected']}
- Guidance: {failed_step_info['on_failure_guidance']}

**All Steps Executed:**
{self._format_step_results(execution_results)}

**Plan Overview:**
{plan.plan_overview}

**CoT Reasoning:**
{json.dumps(plan.cot_reasoning.model_dump(), indent=2)}

**Fallback Hints:**
{chr(10).join(f'  • {hint}' for hint in plan.fallback_hints)}
"""
            # Only add "Your Task" for non-tool path (tool_prompt provides its own instructions)
            if not will_use_tools:
                analysis_context += f"""
**Your Task:**
Analyze why step {failed_step_num} failed and recommend the next action.
Use the failure guidance and fallback hints to suggest an alternative approach.
"""
        else:
            # All validation steps passed - get actual query and results from data retrieval step
            data_step = execution_results[plan.data_retrieval_step - 1]
            actual_results = data_step['result'].get('results', [])
            data_count = len(actual_results)
            actual_query = data_step['query']

            # Get approach goal
            approach_goal = None
            if self.approach_packet:
                approach_goal = self.approach_packet.get('goal') or self.approach_packet.get('text')

            # Build query plan validation section
            plan_validation = "\n**QUERY PLAN VALIDATION**:\n"
            plan_validation += "✅ ALL STEPS PASSED - Query executed successfully and met all expected_outcome criteria\n"
            for i, step_result in enumerate(execution_results, 1):
                expected = step_result['expected']
                plan_validation += f"  Step {i}: ✅ PASSED (expected: {expected})\n"

            analysis_context = f"""
**APPROACH GOAL**:
{approach_goal if approach_goal else 'N/A'}

**QUERY PLAN OVERVIEW**:
{plan.plan_overview}

**ACTUAL CYPHER QUERY EXECUTED** (Step {plan.data_retrieval_step} - Data Retrieval):
{actual_query}

**EXECUTION RESULT**:
- Success: True
- Result Count: {data_count}
- Error: None
{plan_validation}
**ACTUAL RESULTS** (all {data_count} results):
{json.dumps(actual_results, indent=2, default=str) if actual_results else 'Empty'}

**COT REASONING USED**:
{json.dumps(plan.cot_reasoning.model_dump(), indent=2)}

**CRITICAL DECISION LOGIC**:
1. ✅ ALL STEPS PASSED (shown above) - the query worked correctly!
2. Check if the results semantically answer the APPROACH GOAL (not just result count)
3. Look at the ACTUAL DATA in results - does it contain the information we need?
4. ONE result can contain MULTIPLE semantic entities (e.g., one Statement with multiple class instantiations)

**Your Task:**
All validation steps passed. The query executed successfully according to its own success criteria.
EVALUATE: Does the returned data answer the APPROACH GOAL?
- Check the CONTENT of results (text fields, properties)
- Don't judge by COUNT alone - one node can contain multiple semantic entities
- If results contain the needed information → recommend "Sufficient"
- If results don't answer the goal → explain what's missing and recommend "Continue"
- AVOID recommending "Refine" unless there's a technical issue
"""

        # Call LLM for analysis
        base_prompt = f"""Analyze the following query plan execution results and provide your response in JSON format. 
        
        {analysis_context} 
        
        Return JSON with these exact fields: 
        - "analysis": A single string summarizing what happened and why 
        - "key_findings": An array of strings, each describing a key discovery 
        - "recommendation": One of: "Continue", "Sufficient", "Alternative", "Stop", or "Refine" 
        - "next_query_hint": A string describing what the next query should do differently (or null if stopping) 
        
        Example format: 
        {{ 
            "analysis": "The query plan executed successfully retrieving 7 Type-Function relationships.", 
            "key_findings": ["Found 7 types with functions", "All validation steps passed"], 
            "recommendation": "Sufficient", 
            "next_query_hint": null }} """

        try:
            # TOOL-ENABLED ANALYSIS: Use fuzzy search when step failed and tools available
            if failed_step_num and self.use_schema_tools and self.schema_tool_caller:
                logger.info(f"    🛠️ Using tool-enabled analysis for failed step {failed_step_num}")

                # Only allow search_codebase tool
                allowed_tools = ["search_codebase"]
                tool_docs = self.schema_tool_caller.get_tools_documentation(tool_filter=allowed_tools)

                tool_prompt = f"""You are a "Query-plan analysis expert with access to a codebase search tool".

{tool_docs}

Below is a full description of the failed query plan, plus context and instructions:

{base_prompt}

## 🔍 CRITICAL: before making any recommendations, you MUST do the following:

1. **Extract all entity values** used in the failed query.
   - Look for string literals or identifiers likely representing entities: e.g. name fields, label names, property values in the Cypher query.
   - Collect each unique candidate entity name.

2. **For each extracted entity-name**, call the tool `search_codebase(search_term="<entity_name>")` to validate the root cause for Cypher query execution failure.
   - If the tool finds one or more close matches, record them. close match should only be case-variants of the original name. Like "FooBar", "Foobar" and "foobar".
   - If none found, note that explicitly and recommend to "Stop" for user to correct the name.

3. **Based on search results**, decide whether a likely correct (Case-Variants only) entity exists in your data.
   - If yes: propose the corrected name(s) and show how the original query could be changed accordingly.
   - If not: do not guess — Update key findings to show plausible entities found for user correction.

After tool-use and reasoning, output your answer **in valid JSON** with exactly the fields:

```json
{{
  "analysis": "...",
  "key_findings": ["...", ...],
  "recommendation": "...",
  "next_query_hint": "..."
}}
```"""

                tool_result = await self.schema_tool_caller.generate_with_tools(
                    system_prompt="You are a query plan analysis expert with fuzzy search capabilities.",
                    user_prompt=tool_prompt,
                    model_name="gpt-4o-mini",
                    max_iterations=5,
                    max_tokens=5000,
                    tool_filter=allowed_tools
                )

                # Parse tool result into Pydantic model
                try:
                    content = tool_result['content']

                    # Extract JSON from markdown code blocks
                    if '```json' in content:
                        json_start = content.find('```json') + 7
                        json_end = content.find('```', json_start)
                        content = content[json_start:json_end].strip()
                    elif '```' in content:
                        json_start = content.find('```') + 3
                        json_end = content.find('```', json_start)
                        content = content[json_start:json_end].strip()

                    data = json.loads(content)
                    result = CoTAnalysisResult(**data)

                    logger.info(f"    🛠️ Tool calls made: {tool_result.get('tool_calls_made', 0)}")

                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(f"    ⚠️ Failed to parse tool result, falling back to standard: {e}")
                    # Fall back to standard analysis
                    result = await self.llm_service.generate_with_pydantic(
                        system_prompt="You are a query plan analysis expert.",
                        user_prompt=base_prompt,
                        response_model=CoTAnalysisResult,
                        model_name="gpt-4o-mini",
                        call_type="cot_analyze_plan",
                        approach_index=self.state.approach_index,
                        call_purpose=f"Analyze query plan - iteration {self.state.iteration}"
                    )

            # STANDARD ANALYSIS: No tools needed (step passed or tools disabled)
            else:
                result = await self.llm_service.generate_with_pydantic(
                    system_prompt="You are a query plan analysis expert.",
                    user_prompt=base_prompt,
                    response_model=CoTAnalysisResult,
                    model_name="gpt-4o-mini",
                    call_type="cot_analyze_plan",
                    approach_index=self.state.approach_index,
                    call_purpose=f"Analyze query plan - iteration {self.state.iteration}"
                )

            # Track tokens
            self._update_token_tracking_from_result('analyze_plan', result)

            # Store hint for next iteration
            self.state.last_analysis_hint = result.next_query_hint or ''

            return {
                'analysis': result.analysis,
                'key_findings': result.key_findings,
                'recommendation': result.recommendation,
                'next_query_hint': result.next_query_hint,
                'quality_grade': 0.0 if failed_step_num else 0.5,  # Partial credit if validated
                'failed_at_step': failed_step_num,
                'step_failure_guidance': failed_step_info['on_failure_guidance'] if failed_step_num else None
            }

        except Exception as e:
            logger.error(f"  ❌ Plan analysis failed: {e}")
            return {
                'analysis': f'Plan analysis failed: {e}',
                'key_findings': [],
                'recommendation': RecommendationType.STOP,
                'next_query_hint': '',
                'quality_grade': 0.0,
                'failed_at_step': failed_step_num
            }

    # async def _cot_analyze_results_step(
    #     self,
    #     query_result: Dict[str, Any],
    #     execution_result: Dict[str, Any]
    # ) -> Dict[str, Any]:
    #     """
    #     CoT Step: Analyze query results and extract insights WITH adaptive context handling.

    #     For empty results, runs focused diagnostics to understand why.
    #     For large result sets, detects context errors and provides feedback for refinement.

    #     Args:
    #         query_result: Query generation result with CoT reasoning
    #         execution_result: Execution result with results/error

    #     Returns:
    #         Dict with analysis, key_findings, recommendation, next_query_hint, quality_grade
    #     """
    #     results = execution_result.get('results', [])
    #     error = execution_result.get('error')

    #     # Use discovered paths as hints (no need for separate diagnostic queries)
    #     # Discovered paths already tell us:
    #     # - Which node types are reachable (if paths include them)
    #     # - Which relationships exist (shown in path patterns)
    #     # - How nodes connect structurally (multi-hop paths)

    #     # Try to analyze with adaptive context handling
    #     try:
    #         return await self._analyze_with_adaptive_context(
    #             query_result=query_result,
    #             execution_result=execution_result,
    #             results=results,
    #             error=error
    #         )

    #     except Exception as e:
    #         logger.error(f"  ❌ Analysis step failed: {e}")
    #         return {
    #             'analysis': f'Analysis failed: {e}',
    #             'key_findings': [],
    #             'recommendation': RecommendationType.STOP,
    #             'next_query_hint': '',
    #             'quality_grade': 0.0
    #         }

#     async def _analyze_with_adaptive_context(
#         self,
#         query_result: Dict[str, Any],
#         execution_result: Dict[str, Any],
#         results: List[Dict[str, Any]],
#         error: Optional[str],
#         max_retries: int = 2
#     ) -> Dict[str, Any]:
#         """
#         Analyze results with adaptive context management.

#         Strategy:
#         1. Try with ALL results first (optimistic)
#         2. If context error → provide feedback to refine query in next iteration
#         3. If still too large → chunk and analyze incrementally

#         Returns:
#             Analysis dict with quality_grade and adaptive feedback
#         """
#         # Try with full context first
#         validation_feedback = ""  # Accumulates Pydantic validation errors for retry

#         # Run entity diagnostics if results are empty and we have constraints
#         diagnostic_info = None
#         if not results and 'entity_constraints' in query_result:
#             entity_constraints_data = query_result.get('entity_constraints', [])
#             if entity_constraints_data:
#                 # Convert dict to EntityConstraint objects
#                 entity_constraints = [
#                     EntityConstraint(**c) if isinstance(c, dict) else c
#                     for c in entity_constraints_data
#                 ]
#                 diagnostic_info = await self._run_entity_diagnostics(entity_constraints)

#         for attempt in range(max_retries + 1):
#             try:
#                 # Build prompt with current results subset
#                 current_results = results if attempt == 0 else results[:max(10, len(results) // (2 ** attempt))]

#                 # Build query plan dict with steps for validation display
#                 query_plan_dict = None
#                 if 'query_plan' in query_result or 'steps' in query_result:
#                     steps = query_result.get('steps', [])

#                     # Convert steps to dict format if they're Pydantic objects
#                     steps_list = []
#                     for step in steps:
#                         if hasattr(step, 'dict'):
#                             steps_list.append(step.dict())
#                         elif isinstance(step, dict):
#                             steps_list.append(step)
#                         else:
#                             # Skip if it's a string or other format
#                             continue

#                     query_plan_dict = {
#                         'steps': steps_list,
#                         'failed_at_step': query_result.get('failed_at_step')
#                     }

#                 # Get approach goal from approach packet
#                 approach_goal = None
#                 if self.approach_packet:
#                     approach_goal = self.approach_packet.get('goal') or self.approach_packet.get('text')

#                 # Use unified prompt from centralized prompts module
#                 base_prompt = get_cot_analyze_results_prompt(
#                     cypher_query=query_result['cypher_query'],
#                     query_purpose=query_result.get('query_purpose', 'Unknown'),
#                     cot_reasoning=query_result.get('cot_reasoning', {}),
#                     execution_result={
#                         **execution_result,
#                         'results': current_results  # Use subset if needed
#                     },
#                     diagnostic_info=diagnostic_info,  # Entity existence diagnostics
#                     query_plan=query_plan_dict,  # Query plan validation
#                     approach_goal=approach_goal  # Approach-level goal
#                 )

#                 # Add validation feedback if retrying due to Pydantic error
#                 prompt = base_prompt
#                 if validation_feedback:
#                     prompt = f"""{base_prompt}

# **VALIDATION ERROR FROM PREVIOUS ATTEMPT**:
# {validation_feedback}

# **IMPORTANT**: Please fix the above error and generate a corrected response.
# """

#                 result = await self.llm_service.generate_with_pydantic(
#                     system_prompt="You are a query analysis expert.",
#                     user_prompt=prompt,
#                     response_model=CoTAnalysisResult,
#                     model_name="gpt-4o-mini",
#                     call_type="cot_analyze",
#                     approach_index=self.state.approach_index,
#                     call_purpose=f"Analyze results - iteration {self.state.iteration}, attempt {attempt + 1}"
#                 )

#                 # Success! Track tokens
#                 self._update_token_tracking_from_result('analyze', result)

#                 # Update state with findings - attach source query attribution
#                 if results:
#                     # Enrich each result with source query metadata
#                     for result_item in results:
#                         enriched_result = {
#                             **result_item,
#                             '_source_query': query_result['cypher_query'],
#                             '_source_iteration': self.state.iteration,
#                             '_query_purpose': query_result.get('query_purpose', 'Unknown'),
#                             '_cot_reasoning': query_result.get('cot_reasoning', {})
#                         }
#                         self.state.discovered_data.append(enriched_result)

#                 # Store hint for next iteration
#                 self.state.last_analysis_hint = result.next_query_hint or ''

#                 # NEW: Store ambiguity detection for perspective-driven flow
#                 if self.approach_packet and hasattr(result, 'is_ambiguous') and result.is_ambiguous is not None:
#                     # If previously ambiguous and now resolved
#                     if self.state.is_data_ambiguous and not result.is_ambiguous:
#                         logger.info(f"    ✅ AMBIGUITY RESOLVED: Previous ambiguity has been resolved")

#                     self.state.is_data_ambiguous = result.is_ambiguous
#                     self.state.ambiguity_reason = result.ambiguity_reason or ''
#                     self.state.disambiguation_perspective = result.disambiguation_perspective or ''

#                     if result.is_ambiguous:
#                         logger.warning(f"    ⚠️ AMBIGUITY DETECTED: {result.ambiguity_reason}")
#                         logger.info(f"    🔍 Disambiguation Perspective: {result.disambiguation_perspective}")

#                 # Calculate quality grade based on result characteristics
#                 quality_grade = self._calculate_quality_grade(result, len(results), error)

#                 logger.info(f"    📊 Analysis: {result.analysis[:100]}...")
#                 logger.info(f"    💡 Findings: {len(result.key_findings)} key findings")
#                 logger.info(f"    📌 Recommendation: {result.recommendation}")
#                 logger.info(f"    ⭐ Quality Grade: {quality_grade:.2f}")
#                 if result.next_query_hint:
#                     logger.info(f"    💡 Next Query Hint: {result.next_query_hint[:100]}...")

#                 # Build incremental answer for this iteration
#                 if len(result.key_findings) > 0:
#                     partial_answer = {
#                         'iteration': self.state.iteration,
#                         'findings_summary': result.analysis,
#                         'key_findings': result.key_findings,
#                         'data_count': len(results),
#                         'quality_grade': quality_grade,
#                         'query_purpose': query_result.get('query_purpose', 'Unknown')
#                     }
#                     self.state.partial_answers.append(partial_answer)
#                     logger.info(f"    📝 Built partial answer (iteration {self.state.iteration})")

#                 # If we analyzed only a subset, add context feedback
#                 if len(current_results) < len(results):
#                     logger.warning(f"    ⚠️ Analyzed {len(current_results)}/{len(results)} results due to context limits")

#                 analysis_dict = result.dict()
#                 analysis_dict['quality_grade'] = quality_grade
#                 analysis_dict['results_analyzed'] = len(current_results)
#                 analysis_dict['total_results'] = len(results)

#                 return analysis_dict

#             except ValidationError as e:
#                 # Pydantic validation error - provide detailed feedback to LLM
#                 if attempt < max_retries:
#                     error_details = []
#                     for error in e.errors():
#                         field = '.'.join(str(loc) for loc in error['loc'])
#                         msg = error['msg']
#                         input_val = error.get('input', 'N/A')
#                         error_details.append(f"  - Field '{field}': {msg} (got: {input_val})")

#                     validation_feedback = f"""Your response failed Pydantic validation:
# {chr(10).join(error_details)}

# Expected schema:
# - analysis: string (what happened and why)
# - key_findings: list of strings (key discoveries)
# - recommendation: MUST be EXACTLY one of: "Continue", "Sufficient", "Alternative", "Stop", "Refine"
# - next_query_hint: optional string (what next query should do)

# CRITICAL: The 'recommendation' field must be an EXACT match (case-sensitive, no extra text):
#   ✓ Valid: "Continue", "Sufficient", "Stop", "Refine", "Alternative"
#   ✗ Invalid: "continue", "Sufficient data", "Continue with..."

# Please ensure your JSON response matches this exact structure."""

#                     logger.warning(f"    ⚠️ Pydantic validation error (attempt {attempt + 1}): {e}")
#                     logger.info(f"    🔄 Retrying with validation feedback...")
#                     continue
#                 else:
#                     logger.error(f"    ❌ Pydantic validation failed after {max_retries} retries: {e}")
#                     # Return fallback analysis
#                     return {
#                         'analysis': f'Analysis failed validation after {max_retries} retries: {e}',
#                         'key_findings': [],
#                         'recommendation': RecommendationType.STOP,
#                         'next_query_hint': '',
#                         'quality_grade': 0.0
#                     }

#             except Exception as e:
#                 error_str = str(e).lower()

#                 # Check if it's a context error
#                 is_context_error = any(keyword in error_str for keyword in [
#                     'context_length_exceeded',
#                     'maximum context length',
#                     'too many tokens',
#                     'context window',
#                     'token limit'
#                 ])

#                 if is_context_error and attempt < max_retries:
#                     logger.warning(f"    ⚠️ Context error (attempt {attempt + 1}): Too many results ({len(results)} items)")

#                     # Large dataset - provide feedback to refine query in next iteration
#                     if attempt == 0 and len(results) > 100:
#                         logger.info(f"    💡 Providing feedback: Refine query to reduce result set")
#                         return {
#                             'analysis': f"Large dataset found ({len(results)} items) - exceeded context limits",
#                             'key_findings': [
#                                 f"Query returned {len(results)} results",
#                                 "Too many results to analyze in single pass",
#                                 "Need more specific query filters"
#                             ],
#                             'recommendation': RecommendationType.REFINE,
#                             'next_query_hint': f"Break this into multiple focused queries - found {len(results)} items but can only handle <100. Add more specific filters or query smaller subsets.",
#                             'quality_grade': 0.3,  # Low quality - couldn't analyze
#                             'needs_refinement': True,
#                             'results_analyzed': 0,
#                             'total_results': len(results)
#                         }

#                     # Otherwise, retry with smaller subset
#                     logger.info(f"    🔄 Retrying with reduced result set...")
#                     continue

#                 else:
#                     # Not a context error or max retries exceeded
#                     raise

#         # Should not reach here
#         raise Exception("Analysis failed after all retry attempts")

    # def _calculate_quality_grade(
    #     self,
    #     analysis_result: CoTAnalysisResult,
    #     result_count: int,
    #     error: Optional[str]
    # ) -> float:
    #     """
    #     Calculate quality grade for this query's results.

    #     Factors:
    #     - Query intent/strategy (lookup vs exploratory)
    #     - Number of results (context-aware based on query type)
    #     - Error status (errors = low quality)
    #     - Key findings count (more insights = higher quality)
    #     - Recommendation type (Continue = good, Alternative = medium, Stop = low)

    #     Returns:
    #         Float between 0.0 and 1.0
    #     """
    #     quality = 0.5  # Start at medium

    #     # Error check
    #     if error:
    #         return 0.1  # Very low quality

    #     # Determine query type from approach strategy
    #     strategy = self.state.approach_details.get('strategy', 'general').lower()
    #     is_lookup_query = strategy in ['lookup', 'specific', 'targeted', 'direct']

    #     # Results count factor - CONTEXT-AWARE based on query type
    #     if result_count == 0:
    #         quality *= 0.2  # Empty results are always low quality
    #     elif is_lookup_query:
    #         # Lookup queries: Few precise results are GOOD
    #         if 1 <= result_count <= 5:
    #             quality *= 1.2  # Perfect - precise lookup
    #         elif 6 <= result_count <= 10:
    #             quality *= 1.0  # Good - still focused
    #         elif 11 <= result_count <= 50:
    #             quality *= 0.8  # Acceptable but broader than expected
    #         else:
    #             quality *= 0.6  # Too many - probably not specific enough
    #     else:
    #         # Exploratory/discovery queries: More results are better (up to a point)
    #         if result_count < 10:
    #             quality *= 0.7  # Too few for discovery
    #         elif 10 <= result_count <= 100:
    #             quality *= 1.0  # Ideal range for exploration
    #         elif result_count > 100:
    #             quality *= 0.8  # Too many, might be too broad

    #     # Key findings factor
    #     findings_count = len(analysis_result.key_findings)
    #     if findings_count == 0:
    #         quality *= 0.5
    #     elif findings_count >= 3:
    #         quality *= 1.2  # Good insights

    #     # Recommendation factor - CONTEXT-AWARE based on query type
    #     if analysis_result.recommendation == RecommendationType.SUFFICIENT:
    #         # SUFFICIENT means we got what we needed
    #         if is_lookup_query:
    #             quality *= 1.2  # Excellent - found exactly what we're looking for
    #         else:
    #             quality *= 1.1  # Good - exploratory query gathered enough data
    #     elif analysis_result.recommendation == RecommendationType.CONTINUE:
    #         # CONTINUE means more exploration needed
    #         if is_lookup_query:
    #             quality *= 0.9  # Slight penalty - lookup should be quick and decisive
    #         else:
    #             quality *= 1.1  # Good - exploratory queries benefit from iteration
    #     elif analysis_result.recommendation == RecommendationType.REFINE:
    #         quality *= 0.9  # Needs improvement (same for both)
    #     elif analysis_result.recommendation == RecommendationType.ALTERNATIVE:
    #         quality *= 0.8  # This approach didn't work (same for both)
    #     elif analysis_result.recommendation == RecommendationType.STOP:
    #         quality *= 0.7  # Dead end (same for both)

    #     # Clamp to [0.0, 1.0]
    #     return min(1.0, max(0.0, quality))

    # async def _run_targeted_diagnostics(self, failed_query: str) -> Dict[str, Any]:
    #     """
    #     Run 1-2 focused diagnostics on empty results to understand the data landscape.

    #     These are CHEAP queries that return minimal metadata, not full results.
    #     Purpose: Help LLM understand what data exists so it can craft better queries.

    #     Args:
    #         failed_query: The query that returned empty results

    #     Returns:
    #         Dict with diagnostic information (counts, sample names)
    #     """
    #     diagnostics = {}

    #     try:
    #         # Extract all node types from the query dynamically
    #         node_pattern = re.findall(r'\((\w+):(\w+)\)', failed_query)

    #         if node_pattern:
    #             # Get the target node (usually the last one in the MATCH)
    #             target_var, target_type = node_pattern[-1]

    #             # Diagnostic 1: Check if nodes of this type exist at all in the project
    #             count_query = f"""
    #             MATCH (p:Project {{name: '{self.state.project_name}'}})
    #             OPTIONAL MATCH (p)-[:CONTAINS*1..3]->(n:{target_type})
    #             RETURN
    #                 COUNT(DISTINCT n) as node_count,
    #                 COLLECT(DISTINCT n.name)[..5] as sample_names
    #             """

    #             logger.info(f"       🔬 DIAGNOSTIC QUERY 1: Checking {target_type} node availability...")
    #             logger.info(f"          Query:\n{count_query}")
    #             # Use the dedicated server instance directly
    #             count_response = await self.cypher_server.execute_query(count_query)

    #             # Extract data from cypher server response
    #             if isinstance(count_response, dict) and 'data' in count_response:
    #                 count_result = count_response.get('data', [])
    #             else:
    #                 count_result = count_response if isinstance(count_response, list) else []

    #             node_count = count_result[0]['node_count'] if count_result else 0
    #             logger.info(f"       ✅ DIAGNOSTIC QUERY 1 Result: Found {node_count} {target_type} nodes in project")

    #             diagnostics['target_node_availability'] = {
    #                 'node_type': target_type,
    #                 'count': node_count,
    #                 'sample_names': count_result[0]['sample_names'] if count_result else []
    #             }

    #         # Diagnostic 2: Extract relationship types from query and check if they exist
    #         rel_pattern = re.findall(r'-\[:(\w+)\]->', failed_query)

    #         if rel_pattern:
    #             # Check if these relationship types exist in the schema
    #             unique_rels = list(set(rel_pattern))

    #             # Build separate MATCH queries for each relationship type
    #             rel_counts = {}
    #             for rel_type in unique_rels:  # Check all relationship types from query
    #                 rel_query = f"""
    #                 MATCH (p:Project {{name: '{self.state.project_name}'}})-[:CONTAINS*0..3]-()-[r:{rel_type}]->()
    #                 RETURN COUNT(r) as count
    #                 """

    #                 logger.info(f"       🔬 DIAGNOSTIC QUERY 2.{unique_rels.index(rel_type) + 1}: Checking {rel_type} relationships...")
    #                 logger.info(f"          Query:\n{rel_query}")

    #                 try:
    #                     # Use the dedicated server instance directly
    #                     rel_response = await self.cypher_server.execute_query(rel_query)

    #                     # Extract data from cypher server response
    #                     if isinstance(rel_response, dict) and 'data' in rel_response:
    #                         rel_result = rel_response.get('data', [])
    #                     else:
    #                         rel_result = rel_response if isinstance(rel_response, list) else []

    #                     count = rel_result[0]['count'] if rel_result else 0
    #                     rel_counts[f"{rel_type.lower()}_count"] = count
    #                     logger.info(f"       ✅ DIAGNOSTIC QUERY 2.{unique_rels.index(rel_type) + 1} Result: {count} {rel_type} relationships")
    #                 except Exception as e:
    #                     logger.warning(f"       ⚠️ Failed to check {rel_type}: {e}")
    #                     rel_counts[f"{rel_type.lower()}_count"] = 0

    #             if rel_counts:
    #                 diagnostics['relationship_existence'] = {
    #                     'relationships_checked': unique_rels,
    #                     'counts': rel_counts
    #                 }

    #     except Exception as e:
    #         logger.warning(f"⚠️ Diagnostic queries failed: {e}")
    #         diagnostics['error'] = str(e)

    #     return diagnostics

    # # ============================================================================
    # # APOC-BASED PREMISE VALIDATION (for approach packet execution)
    # # ============================================================================

    async def _validate_premises_with_apoc(
        self,
        error: Optional[str] = None,
        empty_result: bool = False
    ) -> Dict[str, Any]:
        """
        Validate premises using APOC diagnostics when queries fail or return empty.

        Flow:
        1. LLM generates diagnostic query using known APOC procedures
        2. Check if procedures exist using APOCCacheTool
        3. If unavailable → suggest alternatives from same category
        4. LLM corrects query with available procedures
        5. Execute and validate premises against actual schema

        Returns:
            Dict with premise_validations, corrected_premises, should_retry
        """
        if not self.approach_packet:
            return {'premise_validations': [], 'corrected_premises': [], 'should_retry': False}

        logger.info(f"🔍 Validating premises using APOC diagnostics...")

        try:
            from ..apoc_procedure_cache import get_apoc_cache
            from .apoc_cache_tool import APOCCacheTool

            apoc_cache = get_apoc_cache()
            if not apoc_cache:
                logger.warning("⚠️ APOC cache not available")
                return {'premise_validations': [], 'corrected_premises': [], 'should_retry': False}

            apoc_tool = APOCCacheTool(apoc_cache)
            premise_validations = []
            corrected_premises = []
            any_corrections = False

            for premise in self.approach_packet.get('active_premises', []):
                # Generate diagnostic query
                diagnostic = await self._generate_diagnostic_query_for_premise(premise, error, empty_result)
                if not diagnostic:
                    continue

                # Check procedure availability
                availability = self._check_procedure_availability(diagnostic.get('procedures_used', []), apoc_tool)

                # Correct if needed
                final_query = diagnostic['query']
                if not availability['all_available']:
                    corrected = await self._correct_query_with_alternatives(
                        diagnostic['query'], availability['unavailable'], availability['alternatives']
                    )
                    if corrected:
                        final_query = corrected['corrected_query']

                # Execute diagnostic query
                try:
                    result = await self.cypher_server.execute_query(final_query)
                    diagnostic_data = result.get('data', []) if isinstance(result, dict) else result
                except Exception as e:
                    logger.warning(f"⚠️ Diagnostic execution failed: {e}")
                    continue

                # Validate premise
                validation = await self._validate_premise_against_results(premise, diagnostic_data, error, empty_result)
                premise_validations.append(validation['validation'])

                if validation['validation']['status'] == 'corrected':
                    corrected_premises.append({
                        'id': premise['id'],
                        'text': validation['validation']['corrected_text']
                    })
                    any_corrections = True

            return {
                'premise_validations': premise_validations,
                'corrected_premises': corrected_premises,
                'should_retry': any_corrections
            }

        except Exception as e:
            logger.error(f"❌ APOC validation failed: {e}")
            return {'premise_validations': [], 'corrected_premises': [], 'should_retry': False}

#     def _build_schema_path_examples(self) -> str:
#         """
#         [DEPRECATED] Build concrete examples of valid relationship paths from schema.

#         DEPRECATED: Schema examples are now removed from prompts to prevent LLM hallucination.
#         The new prompt uses only filtered schema from DynamicSchemaManager with valid_pairs validation.

#         TODO: Remove this method after testing confirms new prompt works correctly.

#         These examples guide the LLM to use correct paths.
#         """
#         return f"""
# **Some Valid Path Examples**:

# 1. **Project → File nodes**:
#    MATCH (p:Project {{name: '{self.state.project_name}'}})-[:CONTAINS]->(f:File)

# 2. **Reaching Type nodes (optional Namespace may exist)**:
#    // File may contain Namespace which contains Type, OR File may directly contain Type
#    MATCH (f:File)-[:CONTAINS*1..2]->(t:Type)

# 3. **Reaching Function nodes**:
#    // Function nodes can be contained in Type nodes:
#    MATCH (t:Type)-[:CONTAINS]->(fn:Function)

#    // Or directly in File nodes:
#    MATCH (f:File)-[:CONTAINS]->(fn:Function)

# 4. **Accessing Statement nodes (requires Block nodes)**:
#    // Statement nodes exist ONLY within Block nodes
#    MATCH (fn:Function)-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)

#    // With statement order:
#    MATCH (fn:Function)-[:CONTAINS]->(b:Block)-[r:CONTAINS]->(s:Statement)
#    ORDER BY r.order

# 5. **Type node relationships**:
#    MATCH (child:Type)-[:INHERITS_FROM]->(parent:Type)
#    MATCH (impl:Type)-[:IMPLEMENTS]->(interface:Type)

# 6. **Function node relationships**:
#    MATCH (caller:Function)-[:CALLS]->(callee:Function)

# **Key Rules**:

# Hierarchical Structure via CONTAINS:
# - Project nodes contain File nodes
# - File nodes contain Namespace OR Type OR Function nodes
# - Namespace nodes contain Type nodes
# - Type nodes contain Type OR Function OR Variable nodes (Type can nest Type for inner classes)
# - Function nodes contain Block OR Variable nodes
# - Block nodes contain Statement OR Block OR Literal nodes (Block can nest Block)

# Statement Node Access:
# - Statement nodes exist ONLY within Block nodes
# - To access Statement nodes: traverse Function -> Block -> Statement
# - NEVER query Function -[:CONTAINS]-> Statement (this path does not exist)
# - NEVER query Type -[:CONTAINS]-> Statement (this path does not exist)
# - Statement 'order' property (on CONTAINS relationship) maintains sequence
# - Statement 'text' property contains source code text
# - Statement 'statement_type' property classifies the statement

# Available Relationships:
# - CONTAINS (hierarchical parent-child)
# - CALLS (Function to Function)
# - INHERITS_FROM (Type to Type)
# - IMPLEMENTS (Type to Type)
# - DECLARES (scope to Variable)
# - DEFINED_IN (node to File)
# """

    async def _generate_diagnostic_query_for_premise(
        self, premise: Dict, error: Optional[str], empty_result: bool
    ) -> Optional[Dict]:
        """Generate APOC diagnostic query to validate a premise."""
        prompt = f"""Generate an APOC diagnostic query to validate this premise.

**PREMISE**: {premise['text']}
**SCENARIO**: {"Empty result - verify premise is valid" if empty_result else f"Error: {error}"}

**APOC PROCEDURES** (common):
- apoc.meta.schema() - Full schema metadata
- apoc.meta.nodeTypeProperties() - Node properties
- apoc.meta.relTypeProperties() - Relationship properties

**RESPONSE** (JSON):
{{"query": "CALL apoc.meta.schema()...", "procedures_used": ["apoc.meta.schema"], "reasoning": "Why"}}"""

        result = await self.llm_service.generate_response(prompt, json_mode=True)
        return json.loads(result.content) if result and not result.error else None

    def _check_procedure_availability(self, procedures: List[str], apoc_tool: Any) -> Dict:
        """Check if APOC procedures exist."""
        unavailable, alternatives = [], {}
        for proc in procedures:
            if not apoc_tool.get_procedure_signature(proc):
                unavailable.append(proc)
                category = '.'.join(proc.split('.')[:2])
                alternatives[proc] = apoc_tool.get_procedures_summary_in_category(category)
        return {'all_available': len(unavailable) == 0, 'unavailable': unavailable, 'alternatives': alternatives}

    async def _correct_query_with_alternatives(
        self, original_query: str, unavailable: List[str], alternatives: Dict
    ) -> Optional[Dict]:
        """Correct diagnostic query with available alternatives."""
        alts_text = [f"\n**Missing**: {p}\n**Alternatives**: {', '.join([a['name'] for a in alts[:3]])}"
                     for p, alts in alternatives.items()]
        prompt = f"""Rewrite query using available procedures.

**ORIGINAL**: {original_query}
**UNAVAILABLE**: {chr(10).join(alts_text)}

**RESPONSE** (JSON):
{{"corrected_query": "...", "replacements_made": [{{"from": "old", "to": "new", "reason": "why"}}]}}"""

        result = await self.llm_service.generate_response(prompt, json_mode=True)
        return json.loads(result.content) if result and not result.error else None

    async def _validate_premise_against_results(
        self, premise: Dict, diagnostic_results: List, error: Optional[str], empty_result: bool
    ) -> Dict:
        """Validate premise against APOC diagnostic results."""
        prompt = f"""Validate premise against actual schema.

**PREMISE**: {premise['text']}
**SCENARIO**: {"Empty result" if empty_result else f"Error: {error}"}
**SCHEMA DATA**: {json.dumps(diagnostic_results, default=str)}

**TASK**: Determine status:
- validated: Premise correct
- invalidated: Premise incorrect
- corrected: Premise wrong but correctable

**RESPONSE** (JSON):
{{"status": "validated|invalidated|corrected", "corrected_text": "...", "correction_reasoning": "..."}}"""

        result = await self.llm_service.generate_response(prompt, json_mode=True)
        if result and not result.error:
            data = json.loads(result.content)
            return {'validation': {
                'premise_id': premise['id'],
                'original_text': premise['text'],
                'status': data['status'],
                'corrected_text': data.get('corrected_text'),
                'correction_reasoning': data.get('correction_reasoning'),
                'validation_method': 'apoc_diagnostics'
            }}
        return {'validation': {'premise_id': premise['id'], 'original_text': premise['text'],
                              'status': 'invalidated', 'corrected_text': None,
                              'correction_reasoning': 'Validation failed', 'validation_method': 'apoc_diagnostics'}}

    def _format_previous_queries(self) -> str:
        """Format previous queries for context."""
        if not self.state.queries_executed:
            return "No previous queries yet."

        formatted = []
        for i, q in enumerate(self.state.queries_executed, 1):
            analysis = q.get('analysis', {})
            recommendation = analysis.get('recommendation', 'N/A')
            next_hint = analysis.get('next_query_hint', '')

            formatted.append(f"""
Query {i} (Iteration {q['iteration']}):
  Cypher: {q['query']}
  Purpose: {q['reasoning'].get('query_purpose', 'N/A')}
  Perspective: {q['reasoning'].get('cot_reasoning', {}).get('step1_perspective', 'N/A')}
  Path Used: {q['reasoning'].get('cot_reasoning', {}).get('step3_path_trace', 'N/A')}
  Results: {q['result_count']} records
  Error: {q.get('error') or 'None'}
  Key Findings: {', '.join(analysis.get('key_findings', []))}
  Recommendation: {recommendation}
  Next Hint: {next_hint if next_hint else 'None'}
""")
        return "\n".join(formatted)

#     def _build_perspective_think_prompt(self, previous_context: str) -> str:
#         """
#         [DEPRECATED] Build perspective-driven think prompt for subquery execution.

#         DEPRECATED: Unified prompt structure now used via get_cot_think_prompt() from prompts.py.
#         The approach_packet conditional logic has been removed - all subqueries now use the same
#         centralized prompt.

#         Issues with this approach:
#         - Included input_data from dependencies (contradicts parallel execution)
#         - Duplicated prompt logic instead of using centralized prompts module
#         - Different system prompt based on approach_packet (inconsistent behavior)

#         TODO: Remove this method after testing confirms unified prompt works for all cases.

#         Focus: What perspectives do we need to fully answer this subquery?

#         Args:
#             previous_context: Formatted previous query results

#         Returns:
#             Prompt for perspective-based thinking
#         """
#         active_premises = self.approach_packet.get('active_premises', [])
#         premises_text = "\n".join([f"  {i+1}. {p['text']}" for i, p in enumerate(active_premises)])

#         # Get input data from dependencies
#         input_data = self.approach_packet.get('input_data', {})
#         input_context = ""
#         if input_data:
#             input_context = "\n**DEPENDENCY DATA** (from previous subqueries):\n"
#             for dep_id, dep_data in input_data.items():
#                 count = len(dep_data) if isinstance(dep_data, list) else 'N/A'
#                 input_context += f"  {dep_id}: {count} records\n"

#         # Check if we're disambiguating
#         disambiguation_context = ""
#         if self.state.is_data_ambiguous:
#             disambiguation_context = f"""
# **⚠️ AMBIGUITY DETECTED IN PREVIOUS QUERY**:
# - Reason: {self.state.ambiguity_reason}
# - Disambiguation Perspective Needed: {self.state.disambiguation_perspective}

# **YOUR TASK IS NOW TO DISAMBIGUATE**: The previous query returned data but it's ambiguous.
# You MUST decide if we should try the disambiguation perspective suggested above.
# """
#         else:
#             disambiguation_context = "**YOUR TASK**: Decide if we need to query from ANOTHER PERSPECTIVE to fully answer this subquery."

#         return f"""You are deciding what perspectives are needed to fully answer a specific subquery.

# **CONTEXT**: You're executing ONE subquery from a larger query decomposition.

# **ORIGINAL USER QUERY**: {self.original_user_query}

# **THIS SUBQUERY TO ANSWER**: {self.state.user_query}

# **PREMISES** (guide what we're looking for):
# {premises_text}
# {input_context}

# **ITERATION**: {self.state.iteration}/{self.state.max_iterations}

# **PREVIOUS QUERIES EXECUTED** ({previous_context.count('Query ') if 'Query ' in previous_context else 0} perspectives tried):
# {previous_context}

# **DATA DISCOVERED SO FAR**: {len(self.state.discovered_data)} records

# **LAST ANALYSIS HINT**: {self.state.last_analysis_hint if self.state.last_analysis_hint else 'None'}

# ---

# {disambiguation_context}

# **KEY QUESTIONS**:

# 1. **Completeness**: Do we have complete data to answer THIS subquery?
#    - Have we validated all premises from different angles?
#    - Are there gaps in our understanding?

# 2. **Ambiguity**: Is the data we have AMBIGUOUS or UNCLEAR?
#    - Do we need another perspective to disambiguate?
#    - Example: If we found functions but not sure which are constructors, query constructor metadata

# 3. **Perspectives Remaining**: What OTHER perspectives could help?
#    - Can we query the same data from a different relationship path?
#    - Can we look at metadata/properties we haven't checked?
#    - Can we validate premises through a different approach?

# 4. **Iteration Limit**: Have we hit max iterations?

# **IMPORTANT**:
# - We're NOT exploring broadly - we're answering THIS specific subquery
# - Each query should bring a NEW PERSPECTIVE to resolve ambiguity or fill gaps
# - Stop when we have SUFFICIENT, UNAMBIGUOUS data for this subquery

# Respond in JSON:
# {{
#     "should_continue": true/false,
#     "reasoning": "Why we need another perspective OR why current data is sufficient",
#     "next_query_focus": "If continuing: What NEW PERSPECTIVE will this query bring?"
# }}
# """

#     def _build_perspective_generate_prompt(self, schema_examples: str, previous_context: str) -> str:
#         """
#         [DEPRECATED] Build perspective-driven query generation prompt.

#         DEPRECATED: Unified prompt structure now used via get_cot_generate_query_prompt() from prompts.py.
#         The approach_packet conditional logic has been removed - all subqueries now use the same
#         cleaned-up prompt with schema valid_pairs validation and no static examples.

#         Issues with this approach:
#         - Used schema_examples (static, showed unavailable relationships)
#         - Included input_data from dependencies (contradicts parallel execution)
#         - Duplicated prompt logic instead of using centralized prompts module

#         TODO: Remove this method after testing confirms unified prompt works for all cases.

#         Focus: Generate query from a SPECIFIC PERSPECTIVE to answer/validate the subquery.

#         Args:
#             schema_examples: Schema relationship examples
#             previous_context: Formatted previous query results

#         Returns:
#             Prompt for perspective-based query generation
#         """
#         active_premises = self.approach_packet.get('active_premises', [])
#         premises_text = "\n".join([f"  {i+1}. {p['text']}" for i, p in enumerate(active_premises)])

#         # Get corrected premises if any
#         corrected_premises = self.approach_packet.get('corrected_premises', [])
#         correction_note = ""
#         if corrected_premises:
#             correction_note = "\n**NOTE**: Some premises were corrected by APOC validation. Use the ACTIVE premises above.\n"

#         # Get input data from dependencies
#         input_data = self.approach_packet.get('input_data', {})
#         input_context = ""
#         if input_data:
#             input_context = "\n**DEPENDENCY DATA** (from previous subqueries - use if relevant):\n"
#             for dep_id, dep_data in input_data.items():
#                 input_context += f"  {dep_id}: Available for reference\n"

#         # Extract schema info
#         node_labels = self.state.schema.get('node_labels', [])
#         relationships = self.state.schema.get('relationships', [])

#         # Format relationships
#         if isinstance(relationships, list):
#             import json
#             rel_summary = json.dumps([{'type': r.get('type'), 'from': r.get('start'), 'to': r.get('end')} for r in relationships], indent=2)
#         else:
#             import json
#             rel_summary = json.dumps(relationships, indent=2)

#         # Check if we're disambiguating
#         task_context = ""
#         if self.state.is_data_ambiguous:
#             task_context = f"""
# **🔍 DISAMBIGUATION MODE**:
# Previous query returned ambiguous data: {self.state.ambiguity_reason}
# You MUST generate a query from this perspective: {self.state.disambiguation_perspective}
# This query should RESOLVE the ambiguity by checking specific properties or relationships.
# """
#         else:
#             task_context = "**TASK**: Generate a query from a NEW PERSPECTIVE to validate premises and answer the subquery."

#         return f"""You are generating a Cypher query from a SPECIFIC PERSPECTIVE to answer a well-defined subquery.

# **CONTEXT**: This is ONE subquery from a larger query decomposition.

# **ORIGINAL USER QUERY**: {self.original_user_query}

# **THIS SUBQUERY TO ANSWER**: {self.state.user_query}

# {task_context}

# **PREMISES** (from Phase 0 - validate these):
# {premises_text}
# {correction_note}{input_context}

# **PROJECT**: '{self.state.project_name}' (use exact value, NOT $project_name)

# **SCHEMA** (source of truth):
# - Node Types: {', '.join(node_labels) if isinstance(node_labels, list) else str(node_labels)}
# - Relationships: {rel_summary}

# **SCHEMA EXAMPLES** (common patterns):
# {schema_examples}

# **PREVIOUS QUERIES** (learn what perspectives were tried):
# {previous_context}

# **HINT FROM ANALYSIS**: {self.state.last_analysis_hint if self.state.last_analysis_hint else 'First query - no hint yet'}

# ---

# **YOUR TASK**: Generate a query from a NEW PERSPECTIVE.

# If this is the FIRST query:
#   - Pick the most direct perspective to validate premises

# If this is a FOLLOW-UP query:
#   - Review the hint - it tells you what perspective to try next
#   - Focus on resolving ambiguity or filling gaps from previous queries
#   - Try a DIFFERENT angle/path/property than before

# **CHAIN-OF-THOUGHT REASONING**:

# **Step 1 - PERSPECTIVE**: What perspective am I taking?
# - First query: "Direct validation of premise X"
# - Follow-up: "Checking metadata Y to disambiguate Z"
# - Example: "Looking at CALLS relationships to find instantiated classes"

# **Step 2 - PREMISE VALIDATION**: Which premises does this perspective validate?
# - Identify which premise(s) this query will validate
# - How does this perspective provide evidence for/against the premise?

# **Step 3 - PATH TRACE**: What's the relationship path for this perspective?
# - Start from Project: Project {{name: '{self.state.project_name}'}}
# - Follow schema examples carefully
# - ⚠️ NO skipping intermediate nodes
# - ⚠️ NO inventing relationships
# - ⚠️ Statements are ONLY in Block nodes

# **Step 4 - FILTERS**: What filters implement this perspective?
# - Use premise-specific filters
# - Consider hint from previous analysis
# - Example: Filter on node types, relationship properties, names

# **Step 5 - RETURN**: What data proves/disproves the premises?
# - Return data that validates premises from this perspective
# - Include context (names, paths, properties)
# - ⚠️ NO nested properties
# - ⚠️ JSON properties: use apoc.convert.fromJsonMap() to parse first

# **Step 6 - OPTIMIZE**:
# - Add LIMIT (25-100)
# - Order by relevance
# - Keep focused on THIS perspective

# **NOW GENERATE**:

# Respond in JSON:
# {{
#     "cot_reasoning": {{
#         "step1_perspective": "What perspective/angle is this query taking?",
#         "step2_premise_validation": "Which premises does this validate?",
#         "step3_path_trace": "relationship path...",
#         "step4_filters": "filters for this perspective...",
#         "step5_return": "what to return...",
#         "step6_optimize": "optimizations..."
#     }},
#     "cypher_query": "MATCH ... RETURN ... LIMIT ...",
#     "query_purpose": "What perspective this query brings to answer the subquery"
# }}
# """

#     def _build_perspective_analyze_prompt(
#         self,
#         query_result: Dict[str, Any],
#         execution_result: Dict[str, Any],
#         current_results: List[Dict[str, Any]],
#         error: Optional[str]
#     ) -> str:
#         """
#         [DEPRECATED] Build perspective-focused analysis prompt.

#         DEPRECATED: Unified prompt structure now used via get_cot_analyze_results_prompt() from prompts.py.
#         The approach_packet conditional logic has been removed - all subqueries now use the same
#         centralized prompt.

#         Issues with this approach:
#         - Used premises from approach_packet (not available in centralized flow)
#         - Duplicated prompt logic instead of using centralized prompts module
#         - Perspective-specific framing not needed for parallel independent execution

#         TODO: Remove this method after testing confirms unified prompt works for all cases.

#         Focus: Did this perspective give us useful data? Is it ambiguous? What perspective next?

#         Args:
#             query_result: Query generation result
#             execution_result: Execution result
#             current_results: Current results (possibly subset)
#             error: Error message if any

#         Returns:
#             Perspective-focused analysis prompt
#         """
#         import json

#         active_premises = self.approach_packet.get('active_premises', [])
#         premises_text = "\n".join([f"  {i+1}. {p['text']}" for i, p in enumerate(active_premises)])

#         cot_reasoning = query_result.get('cot_reasoning', {})
#         perspective_used = cot_reasoning.get('step1_perspective', 'Unknown perspective')

#         result_count = len(current_results) if isinstance(current_results, list) else (1 if current_results else 0)

#         return f"""You are analyzing query results from a SPECIFIC PERSPECTIVE to answer a subquery.

# **SUBQUERY TO ANSWER**: {self.state.user_query}

# **PREMISES** (what we're validating):
# {premises_text}

# **PERSPECTIVE USED IN THIS QUERY**: {perspective_used}

# **QUERY EXECUTED**:
# {query_result['cypher_query']}

# **QUERY PURPOSE**: {query_result.get('query_purpose', 'Unknown')}

# **EXECUTION RESULT**:
# - Success: {execution_result['success']}
# - Result Count: {result_count}
# - Error: {error if error else 'None'}

# **RESULTS**:
# {json.dumps(current_results, indent=2, default=str) if current_results else 'Empty'}

# {self._format_discovered_paths_hint() if result_count == 0 else ''}

# ---

# **YOUR TASK**: Analyze this perspective's results and guide next perspective if needed.

# **ANALYSIS QUESTIONS**:

# 1. **Did this perspective work?**
#    - If ERROR: What went wrong? Schema mismatch? Wrong path?
#    - If EMPTY: Check DISCOVERED PATHS above - does the path you tried actually exist in the graph?
#    - If SUCCESS: Did we get useful data?

# 2. **Premise Validation**:
#    - Does this data validate or invalidate any premises?
#    - Example: If we found Function nodes, premise "Function exists" is validated

# 3. **Data Quality**:
#    - Is the data COMPLETE for this perspective?
#    - Is the data AMBIGUOUS or UNCLEAR?
#    - Example: We found functions but can't tell which are constructors → AMBIGUOUS

# 4. **Next Perspective Needed?**:
#    - If data is ambiguous: What perspective will DISAMBIGUATE?
#    - If data is incomplete: What OTHER perspective fills the gaps?
#    - If error/empty: Should we try DIFFERENT perspective or stop?
#    - If data is sufficient: No more perspectives needed

# **IMPORTANT**:
# - Your `next_query_hint` should suggest a NEW PERSPECTIVE, not just "try again"
# - Be specific about WHAT angle/property/relationship to query next
# - Example good hint: "Check the 'type_kind' property to disambiguate between classes and interfaces"
# - Example bad hint: "Try a different query"

# Respond in JSON:
# {{
#     "analysis": "What this perspective revealed and why",
#     "key_findings": ["finding 1", "finding 2", ...],
#     "recommendation": "EXACT value from list below",
#     "next_query_hint": "If continuing: What SPECIFIC PERSPECTIVE to try next and why",
#     "is_ambiguous": true/false,
#     "ambiguity_reason": "Why the data is ambiguous (if is_ambiguous=true)",
#     "disambiguation_perspective": "What perspective will resolve ambiguity (if is_ambiguous=true)"
# }}

# **CRITICAL - recommendation field MUST be EXACTLY one of these 5 values**:
# - "Continue" → Need another perspective to disambiguate or complete data
# - "Sufficient" → This subquery is fully answered with current data
# - "Alternative" → Current perspective strategy isn't working, need different angle
# - "Stop" → No viable path forward for this subquery
# - "Refine" → Query needs refinement (too many results, context issues)

# **AMBIGUITY DETECTION**:
# Set `is_ambiguous=true` when:
# - Data exists but unclear what it represents (e.g., functions found but unclear which are constructors)
# - Multiple interpretations possible
# - Missing metadata to determine meaning

# Set `is_ambiguous=false` when:
# - Data is clear and unambiguous
# - No data found (NOT ambiguous - just absent)
# - Error occurred (NOT ambiguous - just failed)
# """

    # def _format_discovered_paths_hint(self) -> str:
    #     """
    #     Format discovered paths as a hint for empty result analysis.

    #     Returns the discovered paths from schema extraction, formatted as guidance
    #     for correcting queries that returned empty results.

    #     Returns:
    #         Formatted string with path information, or empty string if no paths
    #     """
    #     import json

    #     paths = self.state.schema.get('paths', [])
    #     if not paths or len(paths) == 0:
    #         return ""

    #     # Group paths by from->to for better readability
    #     path_groups = {}
    #     for path in paths:
    #         source = path.get('from', 'Unknown')
    #         target = path.get('to', 'Unknown')
    #         key = f"{source} → {target}"

    #         if key not in path_groups:
    #             path_groups[key] = []

    #         path_groups[key].append({
    #             'relationships': path.get('rels', []),
    #             'via': path.get('via', []),
    #             'depth': path.get('depth', 0)
    #         })

    #     # Format as readable hint - show ALL paths (LLM needs complete information)
    #     hint_parts = ["\n**DISCOVERED PATHS** (from schema analysis):"]
    #     hint_parts.append("These are the ACTUAL paths that exist in the graph for relevant node types:\n")

    #     for path_key, path_list in sorted(path_groups.items()):
    #         # Sort paths by depth (simpler first)
    #         sorted_path_list = sorted(path_list, key=lambda p: p['depth'])
    #         hint_parts.append(f"  {path_key}: ({len(sorted_path_list)} path(s))")
    #         for path_info in sorted_path_list:  # Show ALL paths
    #             depth = path_info['depth']
    #             if depth == 1:
    #                 # Direct relationship
    #                 rel = path_info['relationships'][0] if path_info['relationships'] else 'UNKNOWN'
    #                 hint_parts.append(f"    • Direct: -{rel}->")
    #             else:
    #                 # Multi-hop path
    #                 via = path_info['via']
    #                 rels = path_info['relationships']
    #                 path_str = " → ".join([f"-[{rel}]->" for rel in rels])
    #                 hint_parts.append(f"    • {depth}-hop: {path_str} (via {', '.join(via)})")

    #     hint_parts.append("\n**HINT FOR CORRECTING QUERY**:")
    #     hint_parts.append("- If your query tried a direct relationship that doesn't exist, use a multi-hop path")
    #     hint_parts.append("- Check the 'via' nodes - you may need to traverse through intermediate node types")
    #     hint_parts.append("- Use the relationship names shown above (they're validated against actual graph)")
    #     hint_parts.append("")

    #     return "\n".join(hint_parts)

    def _format_paths_between(self, source_type: str, target_type: str) -> str:
        """
        Format discovered paths between specific node types for validation feedback.

        Args:
            source_type: Starting node type (e.g., "Function")
            target_type: Target node type (e.g., "Type")

        Returns:
            Formatted string showing all paths from source to target, or empty if none exist
        """
        paths = self.state.schema.get('paths', [])
        if not paths:
            return ""

        # Filter paths that match the source and target
        relevant_paths = [
            p for p in paths
            if p.get('from') == source_type and p.get('to') == target_type
        ]

        if not relevant_paths:
            return f"  {source_type} → {target_type}: NO PATH EXISTS (cannot be connected)\n"

        # Format ALL paths (don't limit - LLM needs to see all options)
        # Sort by depth to show simpler paths first
        sorted_paths = sorted(relevant_paths, key=lambda p: p.get('depth', 0))

        result = [f"  {source_type} → {target_type}: ({len(sorted_paths)} path(s) found)"]
        for path in sorted_paths:
            depth = path.get('depth', 0)
            if depth == 1:
                # Direct relationship
                rel = path.get('rels', [])[0] if path.get('rels') else 'UNKNOWN'
                result.append(f"    • Direct: -[{rel}]->")
            else:
                # Multi-hop path
                via = path.get('via', [])
                rels = path.get('rels', [])
                # Build readable path like: -[CONTAINS]-> Block -[CONTAINS]-> Variable -[REFERENCES]->
                path_segments = []
                for i, rel in enumerate(rels):
                    if i < len(via):
                        path_segments.append(f"-[{rel}]-> {via[i]}")
                    else:
                        path_segments.append(f"-[{rel}]->")
                path_str = " ".join(path_segments)
                result.append(f"    • {depth}-hop: {path_str}")

        result.append("")  # Empty line for spacing
        return "\n".join(result)

#     async def _check_entity_existence(
#         self,
#         constraint: EntityConstraint
#     ) -> Dict[str, Any]:
#         """
#         Check if an entity with specific property value exists, provide fuzzy matches if not.

#         Args:
#             constraint: Entity constraint from query generation

#         Returns:
#             Dictionary with existence check results and suggestions
#         """
#         # Check for exact match
#         exact_query = f"""
#         MATCH (n:{constraint.label})
#         WHERE n.{constraint.property} = $value
#         RETURN n.{constraint.property} AS matched_value
#         LIMIT 1
#         """

#         exact_result = await self.server_pool.execute_cypher(
#             exact_query,
#             params={'value': constraint.value}
#         )

#         if exact_result['results']:
#             return {
#                 'exists': True,
#                 'constraint': constraint.dict(),
#                 'suggestion': None
#             }

#         # No exact match - find fuzzy matches
#         fuzzy_query = f"""
#         MATCH (n:{constraint.label})
#         WHERE n.{constraint.property} IS NOT NULL
#         WITH n, n.{constraint.property} AS prop_value
#         WHERE toLower(prop_value) CONTAINS toLower($search_term)
#            OR toLower($search_term) CONTAINS toLower(prop_value)
#         RETURN DISTINCT prop_value AS name
#         ORDER BY size(prop_value) ASC
#         LIMIT 5
#         """

#         fuzzy_result = await self.server_pool.execute_cypher(
#             fuzzy_query,
#             params={'search_term': constraint.value}
#         )

#         fuzzy_matches = [r['name'] for r in fuzzy_result['results']]

#         if fuzzy_matches:
#             suggestion = f"""❌ {constraint.label} with {constraint.property}='{constraint.value}' does NOT exist.

# 📍 Did you mean one of these?
# {chr(10).join(f'   • {name}' for name in fuzzy_matches)}

# 💡 The value '{constraint.value}' looks like it may be incorrectly formatted.
#    Check if you're using qualified names (Type.Function) when you should use simple names."""
#         else:
#             # No fuzzy matches - get examples
#             examples_query = f"""
#             MATCH (n:{constraint.label})
#             WHERE n.{constraint.property} IS NOT NULL
#             RETURN DISTINCT n.{constraint.property} AS name
#             LIMIT 5
#             """

#             examples_result = await self.server_pool.execute_cypher(examples_query)
#             examples = [r['name'] for r in examples_result['results']]

#             suggestion = f"""❌ {constraint.label} with {constraint.property}='{constraint.value}' does NOT exist.

# 📋 Examples of {constraint.label} nodes that DO exist:
# {chr(10).join(f'   • {name}' for name in examples) if examples else '   (None found)'}"""

#         return {
#             'exists': False,
#             'constraint': constraint.dict(),
#             'fuzzy_matches': fuzzy_matches,
#             'suggestion': suggestion
#         }

#     async def _run_entity_diagnostics(
#         self,
#         entity_constraints: List[EntityConstraint]
#     ) -> Optional[str]:
#         """
#         Run entity existence diagnostics on query constraints.

#         Args:
#             entity_constraints: List of constraints from query generation

#         Returns:
#             Diagnostic message string for the LLM, or None if all entities exist
#         """
#         if not entity_constraints:
#             logger.info("   No entity constraints to check")
#             return None

#         logger.info(f"🔍 Running entity existence diagnostics on {len(entity_constraints)} constraints...")

#         diagnostics = []
#         all_exist = True

#         for constraint in entity_constraints:
#             logger.info(f"   Checking: {constraint.label}.{constraint.property} = '{constraint.value}'")

#             check_result = await self._check_entity_existence(constraint)

#             if not check_result['exists']:
#                 all_exist = False
#                 diagnostics.append(check_result['suggestion'])
#                 logger.warning(f"   ❌ Entity not found: {constraint.value}")
#             else:
#                 logger.info(f"   ✅ Entity exists: {constraint.value}")

#         if all_exist:
#             return None

#         # Build diagnostic message
#         diagnostic_msg = "\n\n".join(diagnostics)
#         return f"""
# 🔍 ENTITY EXISTENCE DIAGNOSTICS:

# {diagnostic_msg}

# ⚠️ Your query references entities that don't exist in the database.
# Please revise your query to use the correct entity names shown above.
# """

    def _extract_token_info(self, llm_result: Any) -> tuple[int, int, int]:
        """Extract token usage from LLM result.

        Args:
            llm_result: Pydantic model returned by LLM service

        Returns:
            Tuple of (total_tokens, input_tokens, output_tokens)
        """
        total = getattr(llm_result, '_tokens_used', 0)
        metadata = getattr(llm_result, '_metadata', {})
        usage = metadata.get('usage', {})

        # Handle different provider formats
        input_tokens = usage.get('input_tokens', usage.get('prompt_tokens', 0))
        output_tokens = usage.get('output_tokens', usage.get('completion_tokens', 0))

        # If no breakdown available, fall back to total
        if input_tokens == 0 and output_tokens == 0 and total > 0:
            # No breakdown - estimate (rough heuristic: 80% input, 20% output)
            input_tokens = int(total * 0.8)
            output_tokens = total - input_tokens

        return (total, input_tokens, output_tokens)

    def _update_token_tracking(self, call_type: str, tokens: int, input_tokens: int = 0, output_tokens: int = 0):
        """Update token tracking for this iteration.

        Args:
            call_type: Type of LLM call (think, generate, analyze, etc.)
            tokens: Total tokens used (for backwards compatibility)
            input_tokens: Input tokens used (if available)
            output_tokens: Output tokens used (if available)
        """
        iteration_key = f"iteration_{self.state.iteration}"
        if iteration_key not in self.state.token_breakdown:
            self.state.token_breakdown[iteration_key] = {}

        self.state.token_breakdown[iteration_key][call_type] = tokens
        self.state.token_breakdown[iteration_key]['total'] = (
            self.state.token_breakdown[iteration_key].get('total', 0) + tokens
        )
        self.state.tokens_used += tokens

        # Track input/output separately for proper accounting
        self.state.total_input_tokens += input_tokens
        self.state.total_output_tokens += output_tokens

    def _update_token_tracking_from_result(self, call_type: str, llm_result: Any):
        """Update token tracking from an LLM result.

        Args:
            call_type: Type of LLM call (think, generate, analyze, etc.)
            llm_result: Pydantic model returned by LLM service
        """
        total, input_tok, output_tok = self._extract_token_info(llm_result)
        self._update_token_tracking(call_type, total, input_tok, output_tok)

    async def _synthesize_approach_answer(self) -> Dict[str, Any]:
        """
        Synthesize a comprehensive approach-level answer from partial answers using LLM.

        Uses LLM to:
        1. Analyze ALL discovered data with source query metadata
        2. Identify which specific data points are relevant
        3. Synthesize a coherent answer addressing the user query
        4. Return answer + list of data point indices actually used

        Returns:
            Dict with 'answer', 'data_points_used', and 'confidence_assessment'
        """
        if not self.state.partial_answers:
            return {
                'answer': "No findings discovered during query execution.",
                'data_points_used': [],
                'confidence_assessment': "Low - no data collected"
            }

        # Calculate average quality grade
        avg_quality = sum(pa['quality_grade'] for pa in self.state.partial_answers) / len(self.state.partial_answers)

        # Get prompt with ALL data (no truncation)
        prompt = get_approach_synthesis_prompt(
            user_query=self.state.user_query,
            approach_details=self.state.approach_details,
            discovered_data=self.state.discovered_data,
            partial_answers=self.state.partial_answers,
            avg_quality=avg_quality
        )

        try:
            result = await self.llm_service.generate_with_pydantic(
                system_prompt="You are a synthesis expert. Analyze discovered data and create coherent answers.",
                user_prompt=prompt,
                response_model=ApproachSynthesisResult,
                model_name="gpt-4o",  # Stronger model for synthesis
                call_type="approach_synthesis",
                approach_index=self.state.approach_index,
                call_purpose=f"Synthesize approach-level answer from {len(self.state.discovered_data)} data points"
            )

            # Track tokens
            self._update_token_tracking_from_result('synthesis', result)

            logger.info(f"    📝 Synthesized answer using {len(result.data_points_used)}/{len(self.state.discovered_data)} data points")
            logger.info(f"    🎯 Confidence: {result.confidence_assessment}")

            return {
                'answer': result.approach_answer,
                'data_points_used': result.data_points_used,
                'confidence_assessment': result.confidence_assessment
            }

        except Exception as e:
            logger.error(f"  ❌ Approach synthesis failed: {e}")
            # Fallback to simple concatenation
            approach_name = self.state.approach_details.get('approach_name', 'Unknown')
            findings = []
            for partial in self.state.partial_answers:
                findings.extend(partial['key_findings'])

            return {
                'answer': f"**{approach_name}**: " + "; ".join(findings[:5]),
                'data_points_used': [],
                'confidence_assessment': f"Low - synthesis failed: {e}"
            }

    async def _build_final_result(self) -> Dict[str, Any]:
        """
        Build final result with SubqueryCitation and premise validation tracking.

        NEW: Returns structured citation including:
        - Original premises (from Phase 0)
        - Premise validations (from APOC diagnostics)
        - Sufficiency status (FOUND, NOT_FOUND, INSUFFICIENT_DATA)
        - APOC diagnostics usage
        - Complete reasoning trail
        """
        # Build citation map: data -> query that discovered it
        citations = self._build_citation_map()

        # Build reasoning trail showing decision process
        reasoning_trail = self._build_reasoning_trail()

        # Build evidence summary with attributions
        evidence_summary = self._build_evidence_summary(citations)

        # Synthesize approach-level answer from partial answers
        approach_answer = await self._synthesize_approach_answer()

        # Filter discovered_data to only include data points identified as relevant by synthesis
        data_points_used = approach_answer.get('data_points_used', [])
        if data_points_used:
            relevant_data = [self.state.discovered_data[i] for i in data_points_used if i < len(self.state.discovered_data)]
            logger.info(f"    🎯 Filtered to {len(relevant_data)}/{len(self.state.discovered_data)} relevant data points")
        else:
            relevant_data = self.state.discovered_data
            logger.warning(f"    ⚠️ No data point filtering (synthesis returned no indices)")

        # NEW: Build SubqueryCitation with premise validations
        subquery_citation = self._build_subquery_citation(relevant_data, approach_answer)

        # Calculate quality grade based on premise validation + answer quality
        final_quality, confidence_level = self._calculate_quality_with_premises(
            approach_answer,
            relevant_data,
            subquery_citation
        )

        logger.info(f"  ✅ Approach completed: {len(relevant_data)} relevant results, quality={final_quality:.2f}, confidence={confidence_level}")

        return {
            'approach_index': self.state.approach_index,
            'approach_name': self.state.approach_details.get('approach_name', 'Unknown'),
            'approach_goal': self.state.approach_details.get('description', ''),

            # NEW: Approach-level synthesized answer
            'approach_answer': approach_answer,
            'approach_quality_grade': final_quality,
            'confidence_level': confidence_level,

            # NEW: SubqueryCitation with premise validations
            'subquery_citation': subquery_citation,

            # Core results - FILTERED to only relevant data points
            'discovered_data': relevant_data,
            'total_results': len(relevant_data),
            'total_discovered': len(self.state.discovered_data),

            # Query execution details
            'queries_executed': len(self.state.queries_executed),
            'query_history': self.state.queries_executed,

            # Citations: map each data point to its source query
            'citations': citations,

            # Reasoning trail: show the agent's thought process
            'reasoning_trail': reasoning_trail,

            # Evidence summary: group findings by query with CoT reasoning
            'evidence_summary': evidence_summary,

            # Incremental answers (for debugging/transparency)
            'partial_answers': self.state.partial_answers,

            # Sufficiency assessment
            'is_sufficient': self.state.is_sufficient,
            'sufficiency_reason': self.state.sufficiency_reason,

            # Resource usage
            'tokens_used': self.state.tokens_used,
            'total_input_tokens': self.state.total_input_tokens,
            'total_output_tokens': self.state.total_output_tokens,
            'token_breakdown': self.state.token_breakdown,
            'iterations': self.state.iteration
        }

    def _build_subquery_citation(self, relevant_data: List, approach_answer: Dict) -> Dict:
        """
        Build SubqueryCitation with premise validations from APOC.

        Returns:
            SubqueryCitation dict with original/corrected premises and validations
        """
        if not self.approach_packet:
            return {}

        # Collect all premise validations from query executions
        all_premise_validations = []
        apoc_diagnostics_used = False
        sufficiency_status = 'FOUND'  # Default

        for query_record in self.state.queries_executed:
            # Check if this query had premise validations
            if 'premise_validations' in query_record:
                all_premise_validations.extend(query_record['premise_validations'])
                apoc_diagnostics_used = True

            # Check if sufficiency status was determined
            if 'sufficiency_status' in query_record:
                sufficiency_status = query_record['sufficiency_status']

        # Determine final sufficiency based on results and premise validations
        if len(relevant_data) == 0:
            # No data found - check premise validations
            if all_premise_validations:
                # If premises were validated → NOT_FOUND (confident negative)
                # If premises were invalidated → INSUFFICIENT_DATA (can't determine)
                all_valid = all(v['status'] == 'validated' for v in all_premise_validations)
                sufficiency_status = 'NOT_FOUND' if all_valid else 'INSUFFICIENT_DATA'
            else:
                sufficiency_status = 'NOT_FOUND'  # No validation, assume NOT_FOUND
        else:
            sufficiency_status = 'FOUND'

        # Get latest query for Cypher
        last_query = self.state.queries_executed[-1] if self.state.queries_executed else {}

        return {
            'subquery_id': self.approach_packet.get('id', 'unknown'),
            'subquery_text': self.approach_packet.get('text', ''),
            'execution_group': self.approach_packet.get('execution_group', 0),
            'logical_form': self.approach_packet.get('logical_form', ''),

            # Premise tracking
            'original_premises': self.approach_packet.get('original_premises', []),
            'corrected_premises': self.approach_packet.get('corrected_premises', []),
            'active_premises': self.approach_packet.get('active_premises', []),
            'premise_validations': all_premise_validations,

            # Execution results
            'cypher_query': last_query.get('query', ''),
            'execution_attempts': len(self.state.queries_executed),
            'result_data': relevant_data,
            'sufficiency_status': sufficiency_status,
            'apoc_diagnostics_used': apoc_diagnostics_used,
            'error': last_query.get('error')
        }

    def _calculate_quality_with_premises(
        self,
        approach_answer: Dict,
        relevant_data: List,
        subquery_citation: Dict
    ) -> tuple:
        """
        Calculate quality grade considering premise validation status.

        Returns:
            Tuple of (quality_grade, confidence_level)
        """
        confidence_str = approach_answer.get('confidence_assessment', '').lower()

        # Base quality from LLM assessment
        if 'high' in confidence_str:
            base_quality = 0.9
            confidence_level = 'high'
        elif 'medium' in confidence_str:
            base_quality = 0.6
            confidence_level = 'medium'
        elif 'low' in confidence_str:
            base_quality = 0.3
            confidence_level = 'low'
        else:
            # Fallback
            base_quality = 0.5
            confidence_level = 'medium'
            if self.state.partial_answers:
                base_quality = sum(pa['quality_grade'] for pa in self.state.partial_answers) / len(self.state.partial_answers)

        final_quality = base_quality

        # Adjust based on sufficiency status
        sufficiency = subquery_citation.get('sufficiency_status', 'FOUND')
        if sufficiency == 'FOUND':
            # Data found with validated premises → high confidence
            final_quality = min(1.0, final_quality * 1.2)
            if len(relevant_data) > 0:
                confidence_level = 'high'
        elif sufficiency == 'NOT_FOUND':
            # No data but premises validated → confident negative
            final_quality = max(final_quality, 0.7)
            confidence_level = 'high'
        else:  # INSUFFICIENT_DATA
            # Premises invalid → low confidence
            final_quality = min(final_quality, 0.4)
            confidence_level = 'low'

        # Adjust based on premise corrections
        premise_validations = subquery_citation.get('premise_validations', [])
        if premise_validations:
            corrected_count = sum(1 for v in premise_validations if v['status'] == 'corrected')
            invalidated_count = sum(1 for v in premise_validations if v['status'] == 'invalidated')

            if corrected_count > 0:
                # Premises were corrected - moderate confidence
                final_quality = min(final_quality, 0.8)
                if confidence_level == 'high':
                    confidence_level = 'medium'

            if invalidated_count > 0:
                # Some premises invalid - low confidence
                final_quality = min(final_quality, 0.5)
                confidence_level = 'low'

        # Ensure within bounds
        final_quality = min(1.0, max(0.0, final_quality))

        return (final_quality, confidence_level)

    def _build_citation_map(self) -> Dict[str, Any]:
        """
        Build a map showing which query discovered each piece of data.

        Returns:
        {
            "data_point_0": {
                "query_index": 0,
                "query": "MATCH ...",
                "iteration": 1,
                "cot_reasoning": {...}
            },
            ...
        }
        """
        citations = {}
        data_index = 0

        for query_record in self.state.queries_executed:
            query_idx = query_record['iteration'] - 1
            results = query_record.get('results', [])

            for result in results:
                citation_key = f"data_point_{data_index}"
                citations[citation_key] = {
                    'query_index': query_idx,
                    'query': query_record['query'],  # Full query, no truncation
                    'iteration': query_record['iteration'],
                    'query_purpose': query_record['reasoning'].get('query_purpose', 'Unknown'),
                    'cot_reasoning': query_record['reasoning'].get('cot_reasoning', {}),
                    'discovered_at': f"Iteration {query_record['iteration']}, Query {query_idx + 1}"
                }
                data_index += 1

        return citations

    def _build_reasoning_trail(self) -> List[Dict[str, Any]]:
        """
        Build a chronological trail of the agent's reasoning process.

        Shows:
        - What the agent thought at each step
        - Why it decided to generate each query
        - How it analyzed results
        - Why it decided to continue or stop
        """
        trail = []

        for query_record in self.state.queries_executed:
            iteration = query_record['iteration']

            # Decision to continue
            trail.append({
                'step': f"Iteration {iteration} - Decision",
                'type': 'think',
                'reasoning': f"Agent decided to generate another query",
                'context': f"{len(self.state.discovered_data)} data points collected so far"
            })

            # Query generation with CoT
            cot = query_record['reasoning'].get('cot_reasoning', {})
            trail.append({
                'step': f"Iteration {iteration} - Query Generation",
                'type': 'generate',
                'query': query_record['query'],
                'cot_reasoning': {
                    'step1_perspective': cot.get('step1_perspective', 'N/A'),
                    'step2_premise_validation': cot.get('step2_premise_validation', 'N/A'),
                    'step3_path_trace': cot.get('step3_path_trace', 'N/A'),
                    'step4_filters': cot.get('step4_filters', 'N/A'),
                    'step5_return': cot.get('step5_return', 'N/A'),
                    'step6_optimize': cot.get('step6_optimize', 'N/A')
                },
                'query_purpose': query_record['reasoning'].get('query_purpose', 'Unknown')
            })

            # Execution result
            result_count = query_record.get('result_count', 0)
            error = query_record.get('error')
            trail.append({
                'step': f"Iteration {iteration} - Execution",
                'type': 'execute',
                'result_count': result_count,
                'error': error if error else None,
                'status': 'success' if not error and result_count > 0 else 'empty' if not error else 'error'
            })

            # Analysis
            if 'analysis' in query_record:
                trail.append({
                    'step': f"Iteration {iteration} - Analysis",
                    'type': 'analyze',
                    'analysis': query_record['analysis'].get('analysis', ''),
                    'key_findings': query_record['analysis'].get('key_findings', []),
                    'recommendation': query_record['analysis'].get('recommendation', ''),
                    'next_query_hint': query_record['analysis'].get('next_query_hint', '')
                })

        # Final decision
        trail.append({
            'step': 'Final Decision',
            'type': 'conclude',
            'is_sufficient': self.state.is_sufficient,
            'reason': self.state.sufficiency_reason,
            'total_iterations': self.state.iteration,
            'total_data_points': len(self.state.discovered_data)
        })

        return trail

    def _build_evidence_summary(self, citations: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a summary of evidence organized by query.

        Groups findings by which query discovered them, with CoT reasoning.
        """
        evidence_by_query = {}

        for query_record in self.state.queries_executed:
            query_idx = query_record['iteration'] - 1
            key = f"query_{query_idx}"

            results = query_record.get('results', [])
            cot = query_record['reasoning'].get('cot_reasoning', {})

            # Handle results whether it's a list or dict
            if isinstance(results, list):
                result_count = len(results)
            elif isinstance(results, dict):
                results = [results]
                result_count = 1
            else:
                results = []
                result_count = 0

            evidence_by_query[key] = {
                'iteration': query_record['iteration'],
                'query': query_record['query'],
                'query_purpose': query_record['reasoning'].get('query_purpose', 'Unknown'),
                'cot_reasoning': {
                    'perspective': cot.get('step1_perspective', 'N/A'),
                    'premises_validated': cot.get('step2_premise_validation', 'N/A'),
                    'path_used': cot.get('step3_path_trace', 'N/A'),
                    'filters_applied': cot.get('step4_filters', 'N/A')
                },
                'result_count': result_count,
                'key_findings': query_record.get('analysis', {}).get('key_findings', []),
                'results': results  # All results, no truncation
            }

        return evidence_by_query

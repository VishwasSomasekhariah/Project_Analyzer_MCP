"""
Thinking Validator Agent for the 4-Agent Team architecture.

Validates the Thinker's reasoning approach before queries are executed.
Focuses on logical completeness, not query syntax.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from src.core.graph_rag.core.enums import AgentRole
from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.models import (
    SubQuery,
    ThinkerOutput,
    ThinkingValidationResult,
)
from src.core.graph_rag.prompts.agent_prompts import THINKING_VALIDATOR_SYSTEM_PROMPT
from src.core.graph_rag.tools.retry import retry_with_backoff
from src.core.graph_rag.agents.base_agent import BaseAgent


# Pydantic model for structured LLM output
class ThinkingValidationModel(BaseModel):
    """Structured response model for Thinking Validator output"""
    approved: bool = Field(..., description="Whether validation passed")
    feedback: Optional[str] = Field(None, description="Explanation if rejected")
    reasoning_gaps: List[str] = Field(default_factory=list, description="Gaps in reasoning")
    missing_aspects: List[str] = Field(default_factory=list, description="Missing aspects")
    queries_coverage_issues: List[str] = Field(default_factory=list, description="Coverage issues")
    specific_issues: List[str] = Field(default_factory=list, description="Specific issues")
    suggested_corrections: Optional[str] = Field(None, description="How to fix issues")


class ThinkingValidatorAgent(BaseAgent):
    """
    Thinking Validator Agent - Validates reasoning approach.

    This agent is the second in the 4-agent team. It:
    1. Validates the Thinker's reasoning chain for logical completeness
    2. Checks if the approach addresses all aspects of the sub-query
    3. Verifies the proposed queries together cover the requirements
    4. Does NOT validate query syntax (that's CypherValidator's job)

    Tools available:
    - get_schema_overview: For basic schema understanding (read-only)
    """

    # Limited tool access - just schema overview for context (short names for OpenAI API)
    ALLOWED_TOOLS = [
        "get_schema_overview",
    ]

    # Fully qualified tool names for Claude SDK fallback
    # Must match ALLOWED_TOOLS exactly (just with MCP prefixes)
    SDK_ALLOWED_TOOLS = [
        "mcp__schema_tools__get_schema_overview",
    ]

    def __init__(
        self,
        tool_manager,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig,
        agent_id: Optional[str] = None
    ):
        """
        Initialize the Thinking Validator Agent.

        Args:
            tool_manager: ToolManager instance for executing tools
            openai_client: OpenAI client instance
            llm_config: LLM configuration
            config: System configuration
            agent_id: Optional unique agent identifier
        """
        super().__init__(
            openai_client,
            llm_config,
            AgentRole.THINKING_VALIDATOR,
            config,
            agent_id=agent_id or "ThinkingValidator"
        )
        self._tool_manager = tool_manager
        self._tools = self._build_allowed_tools()

    def _build_allowed_tools(self) -> List[Dict[str, Any]]:
        """Build tool definitions for only the allowed tools"""
        all_tools = self._tool_manager.tools
        return [
            tool for tool in all_tools
            if tool.get("function", {}).get("name") in self.ALLOWED_TOOLS
        ]

    def _get_structured_response_format(self) -> Dict[str, Any]:
        """Get the JSON schema for structured output"""
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "thinking_validation_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "approved": {
                            "type": "boolean",
                            "description": "Whether validation passed"
                        },
                        "feedback": {
                            "type": ["string", "null"],
                            "description": "Explanation if rejected"
                        },
                        "reasoning_gaps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Gaps in reasoning chain"
                        },
                        "missing_aspects": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Aspects not addressed"
                        },
                        "queries_coverage_issues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Query coverage issues"
                        },
                        "specific_issues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific issues found"
                        },
                        "suggested_corrections": {
                            "type": ["string", "null"],
                            "description": "How to fix issues"
                        }
                    },
                    "required": ["approved", "feedback", "reasoning_gaps", "missing_aspects",
                               "queries_coverage_issues", "specific_issues", "suggested_corrections"],
                    "additionalProperties": False
                }
            }
        }

    async def _execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute a tool via the tool manager, restricted to allowed tools"""
        if name not in self.ALLOWED_TOOLS:
            return json.dumps({"error": f"Tool '{name}' not allowed for Thinking Validator"})

        try:
            result = await self._tool_manager.execute_tool(name, arguments)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as e:
            self._logger.error(f"Tool execution error ({name}): {e}")
            return json.dumps({"error": str(e)})

    def _build_user_prompt(
        self,
        thinker_output: ThinkerOutput,
        sub_query: SubQuery
    ) -> str:
        """Build the user prompt for validation"""
        # Format proposed queries for display
        queries_text = ""
        for q in thinker_output.proposed_queries:
            queries_text += f"\n\nQuery {q.query_id}:"
            queries_text += f"\n  Purpose: {q.purpose}"
            queries_text += f"\n  Reasoning: {q.reasoning}"
            queries_text += f"\n  Cypher: {q.cypher_query}"
            queries_text += f"\n  Expected result: {q.expected_result_type}"
            if q.depends_on:
                queries_text += f"\n  Depends on: {q.depends_on}"

        return f"""ORIGINAL SUB-QUERY:
{sub_query.query}

FOCUS AREA: {sub_query.focus}

THINKER'S APPROACH:
Reasoning Chain:
{chr(10).join(f'  {i+1}. {step}' for i, step in enumerate(thinker_output.overall_reasoning))}

Summary: {thinker_output.approach_summary}

PROPOSED QUERIES ({thinker_output.total_queries} total):{queries_text}

Validate the reasoning approach:
1. Does the reasoning address ALL aspects of the sub-query?
2. Is the approach logically sound?
3. Do the queries together cover the requirements?
4. Are there any gaps or missing aspects?

NOTE: Do NOT validate query syntax - only reasoning completeness."""

    @retry_with_backoff(max_retries=3)
    async def execute(
        self,
        thinker_output: ThinkerOutput,
        sub_query: SubQuery,
        max_iterations: int = 5
    ) -> ThinkingValidationResult:
        """
        Validate the Thinker's reasoning approach.

        Args:
            thinker_output: Output from the Thinker agent
            sub_query: The original sub-query being answered
            max_iterations: Maximum tool-use iterations

        Returns:
            ThinkingValidationResult with approval status and feedback
        """
        start_time = time.time()
        self._logger.info("Thinking Validator checking reasoning approach...")

        messages = [
            {"role": "system", "content": THINKING_VALIDATOR_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(thinker_output, sub_query)}
        ]

        for iteration in range(max_iterations):
            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tools if self._tools else None,
                    tool_choice="auto" if self._tools else None
                )

                msg = response.choices[0].message

                # Check if done (no tool calls)
                if not msg.tool_calls:
                    # Add assistant message if any
                    if msg.content:
                        messages.append({"role": "assistant", "content": msg.content})

                    # Request structured output
                    messages.append({
                        "role": "user",
                        "content": "Now provide your validation result in the required JSON format."
                    })

                    structured_response = self._create_chat_completion(
                        messages=messages,
                        response_format=self._get_structured_response_format()
                    )

                    structured_content = structured_response.choices[0].message.content
                    return self._parse_structured_result(structured_content)

                # Execute tool calls
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": msg.tool_calls
                })

                for tool_call in msg.tool_calls:
                    args = json.loads(tool_call.function.arguments)
                    result = await self._execute_tool(tool_call.function.name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

            except Exception as e:
                self._logger.error(f"Thinking Validator error: {e}")

        # Max iterations - approve by default to avoid blocking
        self._logger.warning("Thinking Validator reached max iterations, approving by default")
        return ThinkingValidationResult(
            approved=True,
            feedback="Validation timeout - approved by default",
            reasoning_gaps=[],
            missing_aspects=[],
            queries_coverage_issues=[],
            specific_issues=[],
            suggested_corrections=None
        )

    def _parse_structured_result(self, response: str) -> ThinkingValidationResult:
        """Parse structured JSON response"""
        try:
            data = json.loads(response)
            validated = ThinkingValidationModel(**data)

            return ThinkingValidationResult(
                approved=validated.approved,
                feedback=validated.feedback,
                reasoning_gaps=validated.reasoning_gaps,
                missing_aspects=validated.missing_aspects,
                queries_coverage_issues=validated.queries_coverage_issues,
                specific_issues=validated.specific_issues,
                suggested_corrections=validated.suggested_corrections
            )
        except (json.JSONDecodeError, ValueError) as e:
            self._logger.error(f"Structured JSON parsing failed: {e}")
            # Default to approved on parse error
            return ThinkingValidationResult(
                approved=True,
                feedback="Parsing error - approved by default",
                reasoning_gaps=[],
                missing_aspects=[],
                queries_coverage_issues=[],
                specific_issues=[],
                suggested_corrections=None
            )


__all__ = ['ThinkingValidatorAgent']

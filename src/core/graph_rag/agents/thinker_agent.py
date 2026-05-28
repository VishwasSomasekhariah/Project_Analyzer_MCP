"""
Thinker Agent for the 4-Agent Team architecture.

Analyzes sub-queries, reasons about the approach, and generates
one or more Cypher queries to retrieve needed information.
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
    ProposedQuery,
)
from src.core.graph_rag.prompts.agent_prompts import THINKER_SYSTEM_PROMPT
from src.core.graph_rag.tools.retry import retry_with_backoff
from src.core.graph_rag.agents.base_agent import BaseAgent


# Pydantic models for structured LLM output
class ProposedQueryModel(BaseModel):
    """Model for a single proposed query"""
    query_id: int = Field(..., description="Unique ID for this query")
    purpose: str = Field(..., description="What this query retrieves")
    reasoning: str = Field(..., description="Why this query is needed")
    cypher_query: str = Field(..., description="The Cypher query to execute")
    target_entities: List[str] = Field(default_factory=list, description="Target entities")
    expected_result_type: str = Field(default="list", description="Expected result type")
    depends_on: List[int] = Field(default_factory=list, description="Query dependencies")


class ThinkerOutputModel(BaseModel):
    """Structured response model for Thinker agent output"""
    overall_reasoning: List[str] = Field(..., description="Step-by-step reasoning")
    approach_summary: str = Field(..., description="Summary of approach")
    proposed_queries: List[ProposedQueryModel] = Field(..., description="Proposed queries")
    total_queries: int = Field(default=1, description="Number of queries")


class ThinkerAgent(BaseAgent):
    """
    Thinker Agent - Analyzes queries and generates Cypher with reasoning.

    This agent is the first in the 4-agent team. It:
    1. Analyzes the sub-query to understand what information is needed
    2. Uses schema tools to understand available node types and properties
    3. Reasons step-by-step about the best approach
    4. Generates one or more Cypher queries to retrieve the needed information

    Tools available:
    - get_node_labels: Get all valid node labels in schema
    - get_node_properties: Properties for a node type
    - get_valid_pairs: Get valid (from, to) pairs for a relationship type
    - validate_relationship_triplet: Check if (from)-[rel]->(to) is valid
    - get_outgoing_relationships: What relationships go out from a node type
    - neo4j_execute_query: For exploration only (limited use)
    """

    # Tools the Thinker is allowed to use (short names for OpenAI API)
    ALLOWED_TOOLS = [
        "get_node_labels",
        "get_node_properties",
        "get_valid_pairs",
        "validate_relationship_triplet",
        "get_outgoing_relationships",
        "neo4j_execute_query",  # For exploration, not final queries
    ]

    # Fully qualified tool names for Claude SDK fallback
    # Must match ALLOWED_TOOLS exactly (just with MCP prefixes)
    SDK_ALLOWED_TOOLS = [
        # In-process schema tools (use schema_manager directly)
        "mcp__schema_tools__get_node_labels",
        "mcp__schema_tools__get_node_properties",
        "mcp__schema_tools__get_valid_pairs",
        "mcp__schema_tools__validate_relationship_triplet",
        "mcp__schema_tools__get_outgoing_relationships",
        # External MCP tools (via neo4j_memory server)
        "mcp__neo4j_memory__neo4j_execute_query",  # For exploration only
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
        Initialize the Thinker Agent.

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
            AgentRole.THINKER,
            config,
            agent_id=agent_id or "Thinker"
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
                "name": "thinker_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "overall_reasoning": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Step-by-step reasoning chain"
                        },
                        "approach_summary": {
                            "type": "string",
                            "description": "Brief summary of approach"
                        },
                        "proposed_queries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "query_id": {"type": "integer", "description": "Query ID"},
                                    "purpose": {"type": "string", "description": "Purpose"},
                                    "reasoning": {"type": "string", "description": "Reasoning"},
                                    "cypher_query": {"type": "string", "description": "Cypher query"},
                                    "target_entities": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Target entities"
                                    },
                                    "expected_result_type": {"type": "string", "description": "Result type"},
                                    "depends_on": {
                                        "type": "array",
                                        "items": {"type": "integer"},
                                        "description": "Dependencies"
                                    }
                                },
                                "required": ["query_id", "purpose", "reasoning", "cypher_query",
                                           "target_entities", "expected_result_type", "depends_on"],
                                "additionalProperties": False
                            },
                            "description": "Proposed Cypher queries"
                        },
                        "total_queries": {
                            "type": "integer",
                            "description": "Number of queries"
                        }
                    },
                    "required": ["overall_reasoning", "approach_summary", "proposed_queries", "total_queries"],
                    "additionalProperties": False
                }
            }
        }

    async def _execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute a tool via the tool manager, restricted to allowed tools"""
        if name not in self.ALLOWED_TOOLS:
            return json.dumps({"error": f"Tool '{name}' not allowed for Thinker agent"})

        try:
            result = await self._tool_manager.execute_tool(name, arguments)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as e:
            self._logger.error(f"Tool execution error ({name}): {e}")
            return json.dumps({"error": str(e)})

    def _build_user_prompt(
        self,
        sub_query: SubQuery,
        context: str,
        previous_feedback: Optional[str] = None
    ) -> str:
        """Build the user prompt for the Thinker agent"""
        prompt_parts = [
            f"SUB-QUERY TO ANSWER:\n{sub_query.query}",
            f"\nFOCUS AREA: {sub_query.focus}",
        ]

        if context:
            prompt_parts.append(f"\nCONTEXT FROM PREVIOUS PHASES:\n{context}")

        if previous_feedback:
            prompt_parts.append(
                f"\n\nPREVIOUS ATTEMPT FEEDBACK (address these issues):\n{previous_feedback}"
            )

        prompt_parts.append(
            "\n\nAnalyze this sub-query and generate one or more Cypher queries to retrieve the needed information. "
            "Use schema tools to understand what nodes, properties, and relationships are available."
        )

        return "\n".join(prompt_parts)

    @retry_with_backoff(max_retries=3)
    async def execute(
        self,
        sub_query: SubQuery,
        context: str = "",
        schema_info: Optional[Dict[str, Any]] = None,
        previous_feedback: Optional[str] = None,
        max_iterations: int = 15  # Increased to allow thorough schema discovery
    ) -> ThinkerOutput:
        """
        Execute the Thinker agent to analyze a sub-query and generate Cypher queries.

        Args:
            sub_query: The sub-query to answer
            context: Context from previous phases
            schema_info: Optional pre-fetched schema information
            previous_feedback: Feedback from validators if this is a retry
            max_iterations: Maximum tool-use iterations

        Returns:
            ThinkerOutput with reasoning and proposed queries
        """
        start_time = time.time()
        self._logger.info(f"Thinker analyzing sub-query: {sub_query.query[:50]}...")

        messages = [
            {"role": "system", "content": THINKER_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(sub_query, context, previous_feedback)}
        ]

        for iteration in range(max_iterations):
            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tools,
                    tool_choice="auto"
                )

                msg = response.choices[0].message

                # Log iteration progress
                if msg.tool_calls:
                    tool_names = [tc.function.name for tc in msg.tool_calls]
                    self._logger.info(f"Thinker iteration {iteration + 1}: calling tools {tool_names}")

                # Check if done (no tool calls) - get structured output
                if not msg.tool_calls:
                    # Add the LLM's analysis to messages
                    if msg.content:
                        messages.append({"role": "assistant", "content": msg.content})

                    # Request structured output
                    messages.append({
                        "role": "user",
                        "content": "Now provide your final output with reasoning and proposed Cypher queries in the required JSON format."
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
                self._logger.error(f"Thinker agent error: {e}")

        # Max iterations reached - return empty output
        self._logger.warning(f"Thinker reached max iterations without completing")
        return ThinkerOutput(
            overall_reasoning=["Max iterations reached without completion"],
            approach_summary="Failed to complete analysis",
            proposed_queries=[],
            total_queries=0
        )

    def _parse_structured_result(self, response: str) -> ThinkerOutput:
        """Parse structured JSON response"""
        try:
            data = json.loads(response)
            validated = ThinkerOutputModel(**data)

            # Convert to domain model
            proposed_queries = []
            for q in validated.proposed_queries:
                proposed_queries.append(ProposedQuery(
                    query_id=q.query_id,
                    purpose=q.purpose,
                    reasoning=q.reasoning,
                    cypher_query=q.cypher_query,
                    target_entities=q.target_entities,
                    expected_result_type=q.expected_result_type,
                    depends_on=q.depends_on
                ))

            return ThinkerOutput(
                overall_reasoning=validated.overall_reasoning,
                approach_summary=validated.approach_summary,
                proposed_queries=proposed_queries,
                total_queries=validated.total_queries
            )
        except (json.JSONDecodeError, ValueError) as e:
            self._logger.error(f"Structured JSON parsing failed: {e}")
            return ThinkerOutput(
                overall_reasoning=["Failed to parse output"],
                approach_summary="Parsing error",
                proposed_queries=[],
                total_queries=0
            )


__all__ = ['ThinkerAgent']

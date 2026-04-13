"""
Cypher Validator Agent for the 4-Agent Team architecture.

Validates Cypher query correctness using schema tools and validation queries.
Can execute queries to verify node types, properties, and relationships exist.
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
    ThinkerOutput,
    CypherValidationResult,
    QueryValidationResult,
)
from src.core.graph_rag.prompts.agent_prompts import CYPHER_VALIDATOR_SYSTEM_PROMPT
from src.core.graph_rag.tools.retry import retry_with_backoff
from src.core.graph_rag.agents.base_agent import BaseAgent


# Pydantic models for structured LLM output
class QueryValidationModel(BaseModel):
    """Validation result for a single query"""
    query_id: int = Field(..., description="Query ID")
    approved: bool = Field(..., description="Whether this query passed")
    issues: List[str] = Field(default_factory=list, description="Issues found")
    suggested_fix: Optional[str] = Field(None, description="Suggested fix")


class ObservedCategoricalValueModel(BaseModel):
    """Observed values for a categorical property"""
    property: str = Field(..., description="Property name in format NodeLabel.propertyName")
    values: List[str] = Field(default_factory=list, description="Discovered valid values")


class CypherValidationModel(BaseModel):
    """Structured response model for Cypher Validator output"""
    approved: bool = Field(..., description="Whether all queries passed")
    feedback: Optional[str] = Field(None, description="Overall feedback")
    query_results: List[QueryValidationModel] = Field(default_factory=list, description="Per-query results")
    invalid_nodes: List[str] = Field(default_factory=list, description="Invalid node types")
    invalid_properties: List[str] = Field(default_factory=list, description="Invalid properties")
    invalid_relationships: List[str] = Field(default_factory=list, description="Invalid relationships")
    path_issues: List[str] = Field(default_factory=list, description="Path issues")
    specific_issues: List[str] = Field(default_factory=list, description="Specific issues")
    suggested_corrections: Optional[str] = Field(None, description="How to fix all issues")
    observed_categorical_values: List[ObservedCategoricalValueModel] = Field(default_factory=list, description="Discovered valid values for categorical properties")


class CypherValidatorAgent(BaseAgent):
    """
    Cypher Validator Agent - Validates query correctness using schema and validation queries.

    This agent is the third in the 4-agent team. It:
    1. Validates each proposed query against the schema
    2. Checks node types exist in the schema
    3. Verifies properties are valid for their node types
    4. Validates each relationship triplet (from)-[rel]->(to) exists in schema
    5. Can run validation queries to verify schema elements exist

    Tools available:
    - get_node_labels: Get all valid node labels in schema
    - get_node_properties: Properties for a node type
    - get_valid_pairs: Get valid (from, to) pairs for a relationship type
    - validate_relationship_triplet: Check if (from)-[rel]->(to) is valid (CRITICAL!)
    - get_outgoing_relationships: What relationships go out from a node type
    - get_incoming_relationships: What relationships come into a node type
    - neo4j_execute_query: For running validation queries
    - neo4j_execute_batch_cypher: For running batch validation queries
    """

    # Schema tools + query execution for validation (short names for OpenAI API)
    ALLOWED_TOOLS = [
        "get_node_labels",
        "get_node_properties",
        "get_valid_pairs",
        "validate_relationship_triplet",  # Critical for validating (from)-[rel]->(to) paths
        "get_outgoing_relationships",
        "get_incoming_relationships",
        "neo4j_execute_query",
        "neo4j_execute_batch_cypher",
    ]

    # Fully qualified tool names for Claude SDK fallback
    # Must match ALLOWED_TOOLS exactly (just with MCP prefixes)
    SDK_ALLOWED_TOOLS = [
        # In-process schema tools
        "mcp__schema_tools__get_node_labels",
        "mcp__schema_tools__get_node_properties",
        "mcp__schema_tools__get_valid_pairs",
        "mcp__schema_tools__validate_relationship_triplet",
        "mcp__schema_tools__get_outgoing_relationships",
        "mcp__schema_tools__get_incoming_relationships",
        # External MCP tools
        "mcp__neo4j_memory__neo4j_execute_query",
        "mcp__neo4j_memory__neo4j_execute_batch_cypher",
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
        Initialize the Cypher Validator Agent.

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
            AgentRole.CYPHER_VALIDATOR,
            config,
            agent_id=agent_id or "CypherValidator"
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
                "name": "cypher_validation_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "approved": {
                            "type": "boolean",
                            "description": "Whether all queries passed validation"
                        },
                        "feedback": {
                            "type": ["string", "null"],
                            "description": "Overall feedback"
                        },
                        "query_results": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "query_id": {"type": "integer"},
                                    "approved": {"type": "boolean"},
                                    "issues": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    },
                                    "suggested_fix": {"type": ["string", "null"]}
                                },
                                "required": ["query_id", "approved", "issues", "suggested_fix"],
                                "additionalProperties": False
                            },
                            "description": "Per-query validation results"
                        },
                        "invalid_nodes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Invalid node types found"
                        },
                        "invalid_properties": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Invalid properties found"
                        },
                        "invalid_relationships": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Invalid relationships found"
                        },
                        "path_issues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Path connectivity issues"
                        },
                        "specific_issues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Other specific issues"
                        },
                        "suggested_corrections": {
                            "type": ["string", "null"],
                            "description": "How to fix all issues"
                        },
                        "observed_categorical_values": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "property": {"type": "string", "description": "Property name in format NodeLabel.propertyName"},
                                    "values": {"type": "array", "items": {"type": "string"}, "description": "Discovered valid values"}
                                },
                                "required": ["property", "values"],
                                "additionalProperties": False
                            },
                            "description": "Discovered valid values for categorical properties"
                        }
                    },
                    "required": ["approved", "feedback", "query_results", "invalid_nodes",
                               "invalid_properties", "invalid_relationships", "path_issues",
                               "specific_issues", "suggested_corrections", "observed_categorical_values"],
                    "additionalProperties": False
                }
            }
        }

    async def _execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute a tool via the tool manager, restricted to allowed tools"""
        if name not in self.ALLOWED_TOOLS:
            return json.dumps({"error": f"Tool '{name}' not allowed for Cypher Validator"})

        try:
            result = await self._tool_manager.execute_tool(name, arguments)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as e:
            self._logger.error(f"Tool execution error ({name}): {e}")
            return json.dumps({"error": str(e)})

    def _build_user_prompt(self, thinker_output: ThinkerOutput) -> str:
        """Build the user prompt for validation"""
        queries_text = ""
        for q in thinker_output.proposed_queries:
            queries_text += f"\n\nQuery {q.query_id}:"
            queries_text += f"\n  Purpose: {q.purpose}"
            queries_text += f"\n  Cypher:\n  {q.cypher_query}"
            queries_text += f"\n  Target entities: {q.target_entities}"

        return f"""PROPOSED QUERIES TO VALIDATE ({thinker_output.total_queries} total):{queries_text}

VALIDATION PROCESS:
1. For EACH query above, extract the node labels, properties, and relationships used
2. Use schema tools to verify:
   - All node types exist (e.g., Type, Function, File, Project)
   - All properties are valid for their node types (e.g., Type.name, Function.body)
   - All relationships exist with correct direction (e.g., (Type)-[:CONTAINS]->(Function))
   - Query paths are reachable
3. You can use neo4j_execute_query to run validation queries if needed (e.g., check if labels exist)
4. Approve ONLY if ALL queries pass validation

Validate each query thoroughly using schema tools and validation queries as needed."""

    @retry_with_backoff(max_retries=3)
    async def execute(
        self,
        thinker_output: ThinkerOutput,
        schema_info: Optional[Dict[str, Any]] = None,
        max_iterations: int = 10
    ) -> CypherValidationResult:
        """
        Validate the proposed Cypher queries against the schema.

        Args:
            thinker_output: Output from the Thinker agent containing queries
            schema_info: Optional pre-fetched schema information
            max_iterations: Maximum tool-use iterations

        Returns:
            CypherValidationResult with validation status for each query
        """
        start_time = time.time()
        self._logger.info(f"Cypher Validator checking {thinker_output.total_queries} queries...")

        messages = [
            {"role": "system", "content": CYPHER_VALIDATOR_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(thinker_output)}
        ]

        for iteration in range(max_iterations):
            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tools,
                    tool_choice="auto"
                )

                msg = response.choices[0].message

                # Check if done (no tool calls)
                if not msg.tool_calls:
                    if msg.content:
                        messages.append({"role": "assistant", "content": msg.content})

                    # Request structured output
                    messages.append({
                        "role": "user",
                        "content": "Now provide your validation results for all queries in the required JSON format."
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
                self._logger.error(f"Cypher Validator error: {e}")

        # Max iterations - reject to be safe
        self._logger.warning("Cypher Validator reached max iterations, rejecting by default")
        return CypherValidationResult(
            approved=False,
            feedback="Validation timeout - could not complete validation",
            query_results=[],
            invalid_nodes=[],
            invalid_properties=[],
            invalid_relationships=[],
            path_issues=["Validation did not complete"],
            specific_issues=["Max iterations reached"],
            suggested_corrections="Try simplifying the queries"
        )

    def _parse_structured_result(self, response: str) -> CypherValidationResult:
        """Parse structured JSON response"""
        try:
            data = json.loads(response)
            validated = CypherValidationModel(**data)

            # Convert query results
            query_results = []
            for qr in validated.query_results:
                query_results.append(QueryValidationResult(
                    query_id=qr.query_id,
                    approved=qr.approved,
                    issues=qr.issues,
                    suggested_fix=qr.suggested_fix
                ))

            # Convert array format to dict format for observed_categorical_values
            observed_values_dict = {}
            for item in validated.observed_categorical_values:
                observed_values_dict[item.property] = item.values

            return CypherValidationResult(
                approved=validated.approved,
                feedback=validated.feedback,
                query_results=query_results,
                invalid_nodes=validated.invalid_nodes,
                invalid_properties=validated.invalid_properties,
                invalid_relationships=validated.invalid_relationships,
                path_issues=validated.path_issues,
                specific_issues=validated.specific_issues,
                suggested_corrections=validated.suggested_corrections,
                observed_categorical_values=observed_values_dict
            )
        except (json.JSONDecodeError, ValueError) as e:
            self._logger.error(f"Structured JSON parsing failed: {e}")
            # Reject on parse error to be safe
            return CypherValidationResult(
                approved=False,
                feedback=f"Parsing error: {e}",
                query_results=[],
                invalid_nodes=[],
                invalid_properties=[],
                invalid_relationships=[],
                path_issues=[],
                specific_issues=["Response parsing failed"],
                suggested_corrections=None,
                observed_categorical_values={}
            )


__all__ = ['CypherValidatorAgent']

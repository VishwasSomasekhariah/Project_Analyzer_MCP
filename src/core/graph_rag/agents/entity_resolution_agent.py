"""
Entity Resolution Agent for the Graph RAG Multi-Agent system.

Detects case sensitivity issues and misspellings in entity names
before CoT agents execute, preventing wasted iterations on wrong names.
"""

import json
import logging
import time
from typing import Any, Dict, List, Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from src.core.graph_rag.core.enums import AgentRole
from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.models import (
    EntityCorrection,
    EntityResolutionResult,
    ResolvedEntity,
    SubQuery,
)
from src.core.graph_rag.tools.retry import retry_with_backoff
from src.core.graph_rag.agents.base_agent import BaseAgent


# Pydantic models for structured LLM output
class CorrectionModel(BaseModel):
    """Model for entity correction"""
    original_term: str = Field(..., description="Term from query")
    suggested_name: str = Field(..., description="Correct name or alternatives")
    entity_type: str = Field(..., description="Entity type: class/function/variable/etc")
    file_path: Optional[str] = Field(None, description="File path if available")
    confidence_score: float = Field(default=0.0, description="Confidence score 0.0-1.0")
    issue_type: str = Field(..., description="Issue type: case_sensitivity, misspelling, not_found_similar_exists")


class ResolvedEntityModel(BaseModel):
    """Model for resolved entity"""
    name: str = Field(..., description="Entity name")
    entity_type: str = Field(..., description="Type: Project, Namespace, Class, Function, etc")
    file_path: Optional[str] = Field(None, description="File path if available")
    query_hint: str = Field(..., description="Cypher hint for querying this entity")
    domain_explanation: Optional[str] = Field(None, description="Domain-specific explanation based on schema discovery")


class EntityResolutionResponseModel(BaseModel):
    """Structured response model for entity resolution output"""
    corrections: List[CorrectionModel] = Field(default_factory=list, description="Entity corrections found")
    resolved_entities: List[ResolvedEntityModel] = Field(default_factory=list, description="Resolved entities with context")
    has_issues: bool = Field(default=False, description="Whether any issues were found")
    corrected_query: Optional[str] = Field(None, description="Query with corrections applied or null")


class EntityResolutionAgent(BaseAgent):
    """
    Entity Resolution Agent - ONLY has access to neo4j_fuzzy_search.

    Purpose:
    - Detect case sensitivity issues (e.g., 'workerz' vs 'WorkerZ')
    - Detect misspellings (e.g., 'Hellper' vs 'Helper')
    - Suggest corrections WITHOUT answering the query

    This agent runs after query decomposition to validate entity names
    before CoT agents execute. It prevents wasted iterations on wrong names.
    """

    # Tools allowed for this agent (short names for OpenAI API)
    ALLOWED_TOOLS = [
        "neo4j_fuzzy_search",
        "neo4j_execute_query",
        "get_node_properties",
    ]

    # Fully qualified tool names for Claude SDK fallback
    SDK_ALLOWED_TOOLS = [
        "mcp__neo4j_memory__neo4j_fuzzy_search",
        "mcp__neo4j_memory__neo4j_execute_query",
        "mcp__schema_tools__get_node_properties",
    ]

    SYSTEM_PROMPT = """You are an Entity Resolution Agent. Your job is to:
1. Verify entity names from queries
2. DISCOVER and EXPLAIN domain concepts by querying the schema

CRITICAL RULES:
1. You have THREE tools:
   - neo4j_fuzzy_search: For finding classes, functions, variables (indexed nodes)
   - neo4j_execute_query: For checking Project, Namespace, File nodes
   - get_node_properties: For discovering what properties exist on node types - USE THIS for domain concepts!
2. Use these tools to check if mentioned entities exist in the codebase
3. **MANDATORY**: When the query mentions ANY technical concept (complexity, dependencies, methods, etc.),
   you MUST call get_node_properties to discover what properties exist for that concept
4. Report issues for name problems: case_sensitivity, misspelling, not_found_similar_exists
5. ALWAYS provide domain_explanation explaining what you discovered from the schema
6. DO NOT answer the user's question - only identify name issues and provide schema context

PROCESS:
1. Extract entity names from the query (HelloWorldApp, WorkerA, etc.)
2. **IDENTIFY TECHNICAL CONCEPTS** - words like: complexity, methods, functions, dependencies, inheritance, calls, types
3. For each entity name: check if it's a Project/Namespace/File using neo4j_execute_query
4. **FOR EACH TECHNICAL CONCEPT** - YOU MUST call get_node_properties:
   - "methods" or "functions" → call get_node_properties("Function") to see what properties exist
   - "complexity" → call get_node_properties("Function") to find cyclomatic_complexity property
   - "types" or "classes" → call get_node_properties("Type") to see class properties
   - "dependencies" or "calls" → explain the CALLS relationship
5. Include domain_explanation with what you discovered (e.g., "Function nodes have cyclomatic_complexity property")

EXAMPLE - For query "What are the methods and their cyclomatic complexity?":
- MUST call: get_node_properties("Function") to discover cyclomatic_complexity exists
- domain_explanation: "Function nodes have 'cyclomatic_complexity' property storing the complexity value"

OUTPUT FORMAT (JSON):
{
  "corrections": [...],
  "resolved_entities": [
    {
      "name": "<entity name>",
      "entity_type": "<Project|Namespace|Class|Function|etc>",
      "file_path": "<path if available>",
      "query_hint": "<Cypher hint for querying this entity>",
      "domain_explanation": "<REQUIRED: What you discovered from get_node_properties about relevant properties>"
    }
  ],
  "has_issues": <true|false>,
  "corrected_query": null
}"""

    def __init__(
        self,
        mcp_session,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig
    ):
        """
        Initialize the Entity Resolution Agent.

        Args:
            mcp_session: Active MCP session for tool execution
            openai_client: OpenAI client instance
            llm_config: LLM configuration
            config: System configuration
        """
        super().__init__(openai_client, llm_config, AgentRole.COT_AGENT, config, agent_id="EntityResolver")
        self._session = mcp_session
        self._build_tools()

    def _build_tools(self):
        """Build tool definitions - fuzzy search, cypher, and schema discovery"""
        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": "neo4j_fuzzy_search",
                    "description": "Fuzzy search for code entities (classes, functions, variables). Does NOT include Project, Namespace, or File nodes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "Name to search for (e.g., 'workerz', 'Helper.FormatMessage')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results (default: 15)",
                                "default": 15
                            },
                            "min_score": {
                                "type": "number",
                                "description": "Minimum relevance score (default: 0.5)",
                                "default": 0.5
                            }
                        },
                        "required": ["search_term"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "neo4j_execute_query",
                    "description": "Execute a Cypher query to check for Project, Namespace, or File nodes. Use this FIRST to check if entity is a project/namespace/file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Cypher query to execute. Use for checking Project/Namespace/File nodes."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_node_properties",
                    "description": "Get all properties available on a node type. Use this to discover what properties exist (e.g., check if Function has 'cyclomatic_complexity' property).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "Node label to get properties for (e.g., 'Function', 'Type', 'File')"
                            }
                        },
                        "required": ["label"]
                    }
                }
            }
        ]

    def _get_structured_response_format(self) -> Dict[str, Any]:
        """Get the JSON schema for structured output"""
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "entity_resolution_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "corrections": {
                            "type": "array",
                            "description": "Entity corrections found",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "original_term": {"type": "string", "description": "Term from query"},
                                    "suggested_name": {"type": "string", "description": "Correct name or alternatives"},
                                    "entity_type": {"type": "string", "description": "Entity type"},
                                    "file_path": {"type": ["string", "null"], "description": "File path if available"},
                                    "confidence_score": {"type": "number", "description": "Confidence 0.0-1.0"},
                                    "issue_type": {"type": "string", "description": "Issue type"}
                                },
                                "required": ["original_term", "suggested_name", "entity_type", "file_path", "confidence_score", "issue_type"],
                                "additionalProperties": False
                            }
                        },
                        "resolved_entities": {
                            "type": "array",
                            "description": "Resolved entities with context",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "Entity name"},
                                    "entity_type": {"type": "string", "description": "Type: Project, Namespace, Class, Function, etc"},
                                    "file_path": {"type": ["string", "null"], "description": "File path if available"},
                                    "query_hint": {"type": "string", "description": "Cypher hint for querying this entity"},
                                    "domain_explanation": {"type": ["string", "null"], "description": "Domain-specific explanation based on schema discovery"}
                                },
                                "required": ["name", "entity_type", "file_path", "query_hint", "domain_explanation"],
                                "additionalProperties": False
                            }
                        },
                        "has_issues": {"type": "boolean", "description": "Whether any issues were found"},
                        "corrected_query": {"type": ["string", "null"], "description": "Query with corrections or null"}
                    },
                    "required": ["corrections", "resolved_entities", "has_issues", "corrected_query"],
                    "additionalProperties": False
                }
            }
        }

    async def _execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute fuzzy search, cypher query, or schema discovery tool via MCP"""
        allowed_tools = ("neo4j_fuzzy_search", "neo4j_execute_query", "get_node_properties")
        if name not in allowed_tools:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            # For cypher queries, validate it's a safe read-only query
            if name == "neo4j_execute_query":
                query = arguments.get("query", "").upper()
                # Only allow read queries for entity resolution
                if any(kw in query for kw in ["DELETE", "CREATE", "SET", "MERGE", "REMOVE", "DROP"]):
                    return json.dumps({"error": "Only read queries allowed for entity resolution"})

            result = await self._session.call_tool(name, arguments)
            if hasattr(result, 'content') and result.content:
                return result.content[0].text
            return json.dumps({"error": "Empty MCP response"})
        except Exception as e:
            self._logger.error(f"Tool execution error ({name}): {e}")
            return json.dumps({"error": str(e)})

    @retry_with_backoff(max_retries=3)
    async def execute(self, query: str, sub_queries: Optional[List[SubQuery]] = None) -> EntityResolutionResult:
        """
        Check for entity name issues in query and sub-queries.

        Args:
            query: Original user query
            sub_queries: Optional decomposed sub-queries to also check

        Returns:
            EntityResolutionResult with any corrections found
        """
        start_time = time.time()
        self._logger.info("Entity Resolution Agent checking query...")

        # Build prompt with query and sub-queries
        query_text = f"Original query: {query}"
        if sub_queries:
            query_text += "\n\nDecomposed sub-queries:"
            for i, sq in enumerate(sub_queries):
                query_text += f"\n{i+1}. {sq.query}"

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"Check for entity name issues in:\n\n{query_text}"}
        ]

        # Limited iterations - this should be quick
        max_iterations = 5
        for iteration in range(max_iterations):
            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tools,
                    tool_choice="auto"
                )

                msg = response.choices[0].message

                # Check if done (no tool calls) - get structured output
                if not msg.tool_calls:
                    # Add the LLM's analysis to messages
                    if msg.content:
                        messages.append({"role": "assistant", "content": msg.content})

                    # Request structured output
                    messages.append({
                        "role": "user",
                        "content": "Now provide your final entity resolution result in the required JSON format."
                    })

                    structured_response = self._create_chat_completion(
                        messages=messages,
                        response_format=self._get_structured_response_format()
                    )

                    structured_content = structured_response.choices[0].message.content
                    result = self._parse_structured_result(structured_content)
                    result_dict = result.model_dump()
                    result_dict['execution_time_ms'] = int((time.time() - start_time) * 1000)
                    return EntityResolutionResult(**result_dict)

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
                self._logger.error(f"Entity resolution error: {e}")

        execution_time = int((time.time() - start_time) * 1000)
        return EntityResolutionResult(
            corrections=[],
            has_issues=False,
            corrected_query=None,
            resolved_entities=[],
            execution_time_ms=execution_time
        )

    def _parse_structured_result(self, response: str) -> EntityResolutionResult:
        """Parse structured JSON response from Pydantic-validated output"""
        try:
            # Parse the structured JSON response
            data = json.loads(response)

            # Validate with Pydantic model
            validated = EntityResolutionResponseModel(**data)

            # Convert to EntityResolutionResult
            corrections = []
            for c in validated.corrections:
                corrections.append(EntityCorrection(
                    original_term=c.original_term,
                    suggested_name=c.suggested_name,
                    entity_type=c.entity_type,
                    file_path=c.file_path,
                    confidence_score=c.confidence_score,
                    issue_type=c.issue_type
                ))

            resolved_entities = []
            for r in validated.resolved_entities:
                resolved_entities.append(ResolvedEntity(
                    name=r.name,
                    entity_type=r.entity_type,
                    file_path=r.file_path,
                    query_hint=r.query_hint,
                    domain_explanation=r.domain_explanation
                ))

            return EntityResolutionResult(
                corrections=corrections,
                has_issues=validated.has_issues,
                corrected_query=validated.corrected_query,
                resolved_entities=resolved_entities,
                execution_time_ms=0  # Set by caller
            )
        except (json.JSONDecodeError, ValueError) as e:
            self._logger.error(f"Structured JSON parsing failed: {e}")
            # Return empty result if parsing fails (should not happen with structured output)
            return EntityResolutionResult(
                corrections=[],
                has_issues=False,
                corrected_query=None,
                resolved_entities=[],
                execution_time_ms=0
            )


__all__ = ['EntityResolutionAgent']

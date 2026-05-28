"""
Executor & Verifier Agent for the 4-Agent Team architecture.

Executes validated Cypher queries, builds findings from results,
verifies claims against evidence, and constructs citations.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from src.core.graph_rag.core.enums import AgentRole, ConfidenceLevel
from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.models import (
    ThinkerOutput,
    ProposedQuery,
    Finding,
    CodeEntity,
    ExecutedQuery,
)
from src.core.graph_rag.prompts.agent_prompts import EXECUTOR_VERIFIER_SYSTEM_PROMPT
from src.core.graph_rag.tools.retry import retry_with_backoff
from src.core.graph_rag.agents.base_agent import BaseAgent


# Pydantic models for structured LLM output
class EntityModel(BaseModel):
    """Model for a code entity"""
    name: str = Field(..., description="Entity name")
    entity_type: str = Field(..., description="Entity type: class, function, etc")
    file_path: Optional[str] = Field(None, description="File path")


class FindingModel(BaseModel):
    """Model for a single finding"""
    claim: str = Field(..., description="Claim about actual code")
    entities: List[EntityModel] = Field(default_factory=list, description="Entities involved")
    evidence_summary: str = Field(default="", description="Summary of evidence from queries")
    confidence: str = Field(default="medium", description="Confidence: high/medium/low")
    source_query: str = Field(..., description="Query that produced this finding")


class ExecutorOutputModel(BaseModel):
    """Structured response model for Executor output"""
    findings: List[FindingModel] = Field(default_factory=list, description="Verified findings")


class ExecutorVerifierAgent(BaseAgent):
    """
    Executor & Verifier Agent - Executes queries and builds verified findings.

    This agent is the fourth (final) in the 4-agent team. It:
    1. Executes ALL validated Cypher queries in order
    2. Collects and analyzes results
    3. Builds claims about ACTUAL code entities
    4. Verifies each claim has supporting evidence
    5. Constructs proper citations with file paths and entity details

    Tools available:
    - neo4j_execute_query: Execute Cypher queries
    - neo4j_execute_batch_cypher: Execute multiple queries
    - neo4j_fuzzy_search: Search for entities by name
    """

    # Execution tools only (short names for OpenAI API)
    ALLOWED_TOOLS = [
        "neo4j_execute_query",
        "neo4j_execute_batch_cypher",
        "neo4j_fuzzy_search",
    ]

    # Fully qualified tool names for Claude SDK fallback
    # Must match ALLOWED_TOOLS exactly (just with MCP prefixes)
    SDK_ALLOWED_TOOLS = [
        "mcp__neo4j_memory__neo4j_execute_query",
        "mcp__neo4j_memory__neo4j_execute_batch_cypher",
        "mcp__neo4j_memory__neo4j_fuzzy_search",
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
        Initialize the Executor & Verifier Agent.

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
            AgentRole.EXECUTOR_VERIFIER,
            config,
            agent_id=agent_id or "ExecutorVerifier"
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
                "name": "executor_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "claim": {
                                        "type": "string",
                                        "description": "Statement about actual code"
                                    },
                                    "entities": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string"},
                                                "entity_type": {"type": "string"},
                                                "file_path": {"type": ["string", "null"]}
                                            },
                                            "required": ["name", "entity_type", "file_path"],
                                            "additionalProperties": False
                                        },
                                        "description": "Code entities involved"
                                    },
                                    "evidence_summary": {
                                        "type": "string",
                                        "description": "Summary of evidence from query results supporting this claim"
                                    },
                                    "confidence": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                        "description": "Confidence level"
                                    },
                                    "source_query": {
                                        "type": "string",
                                        "description": "Query that produced this"
                                    }
                                },
                                "required": ["claim", "entities", "evidence_summary", "confidence", "source_query"],
                                "additionalProperties": False
                            },
                            "description": "List of verified findings"
                        }
                    },
                    "required": ["findings"],
                    "additionalProperties": False
                }
            }
        }

    async def _execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute a tool via the tool manager, restricted to allowed tools"""
        if name not in self.ALLOWED_TOOLS:
            return json.dumps({"error": f"Tool '{name}' not allowed for Executor"})

        try:
            result = await self._tool_manager.execute_tool(name, arguments)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as e:
            self._logger.error(f"Tool execution error ({name}): {e}")
            return json.dumps({"error": str(e)})

    async def _execute_queries(
        self,
        proposed_queries: List[ProposedQuery]
    ) -> List[ExecutedQuery]:
        """Execute all proposed queries and collect results"""
        executed = []

        # Sort by dependencies (queries with no dependencies first)
        sorted_queries = sorted(proposed_queries, key=lambda q: len(q.depends_on))

        for query in sorted_queries:
            start_time = time.time()
            try:
                result = await self._execute_tool(
                    "neo4j_execute_query",
                    {"query": query.cypher_query}
                )

                # Parse result
                try:
                    parsed = json.loads(result) if isinstance(result, str) else result
                    if isinstance(parsed, dict) and "error" in parsed:
                        executed.append(ExecutedQuery(
                            query_id=query.query_id,
                            cypher_query=query.cypher_query,
                            results=[],
                            result_count=0,
                            execution_time_ms=int((time.time() - start_time) * 1000),
                            error=parsed.get("error")
                        ))
                    else:
                        results_list = parsed if isinstance(parsed, list) else [parsed]
                        executed.append(ExecutedQuery(
                            query_id=query.query_id,
                            cypher_query=query.cypher_query,
                            results=results_list,
                            result_count=len(results_list),
                            execution_time_ms=int((time.time() - start_time) * 1000),
                            error=None
                        ))
                except json.JSONDecodeError:
                    # Raw string result
                    executed.append(ExecutedQuery(
                        query_id=query.query_id,
                        cypher_query=query.cypher_query,
                        results=[{"raw": result}],
                        result_count=1,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                        error=None
                    ))
            except Exception as e:
                self._logger.error(f"Query {query.query_id} failed: {e}")
                executed.append(ExecutedQuery(
                    query_id=query.query_id,
                    cypher_query=query.cypher_query,
                    results=[],
                    result_count=0,
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    error=str(e)
                ))

        return executed

    def _build_user_prompt(
        self,
        thinker_output: ThinkerOutput,
        executed_queries: List[ExecutedQuery]
    ) -> str:
        """Build the user prompt with query results"""
        results_text = ""
        for eq in executed_queries:
            results_text += f"\n\nQuery {eq.query_id}:"
            results_text += f"\n  Cypher: {eq.cypher_query}"
            if eq.error:
                results_text += f"\n  ERROR: {eq.error}"
            else:
                results_text += f"\n  Results ({eq.result_count} rows):"
                # Show first few results
                for i, row in enumerate(eq.results[:5]):
                    results_text += f"\n    {json.dumps(row, default=str)[:200]}"
                if len(eq.results) > 5:
                    results_text += f"\n    ... and {len(eq.results) - 5} more rows"

        return f"""THINKER'S APPROACH:
{thinker_output.approach_summary}

QUERY EXECUTION RESULTS:{results_text}

BUILD VERIFIED FINDINGS:
1. Analyze the query results above
2. Build claims about ACTUAL code entities (use real names from results)
3. For each claim, include:
   - Specific entities with names, types, and file paths from the results
   - Evidence directly from the query results
   - Confidence level based on evidence strength
   - The query that produced this finding
4. Only include claims SUPPORTED by the results
5. If a query returned no results, note this but don't make up data"""

    @retry_with_backoff(max_retries=3)
    async def execute(
        self,
        thinker_output: ThinkerOutput,
        max_iterations: int = 5
    ) -> tuple[List[Finding], List[ExecutedQuery]]:
        """
        Execute validated queries and build verified findings.

        Args:
            thinker_output: Output from Thinker containing validated queries
            max_iterations: Maximum LLM iterations for building findings

        Returns:
            Tuple of (List[Finding], List[ExecutedQuery])
        """
        start_time = time.time()
        self._logger.info(f"Executor running {thinker_output.total_queries} queries...")

        # Step 1: Execute all queries
        executed_queries = await self._execute_queries(thinker_output.proposed_queries)
        self._logger.info(f"Executed {len(executed_queries)} queries")

        # Step 2: Build findings from results
        messages = [
            {"role": "system", "content": EXECUTOR_VERIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(thinker_output, executed_queries)}
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
                    if msg.content:
                        messages.append({"role": "assistant", "content": msg.content})

                    # Request structured output
                    messages.append({
                        "role": "user",
                        "content": "Now provide your findings in the required JSON format."
                    })

                    structured_response = self._create_chat_completion(
                        messages=messages,
                        response_format=self._get_structured_response_format()
                    )

                    structured_content = structured_response.choices[0].message.content
                    findings = self._parse_structured_result(structured_content)
                    return findings, executed_queries

                # Execute tool calls (for additional verification if needed)
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
                self._logger.error(f"Executor error: {e}")

        # Max iterations - return empty findings
        self._logger.warning("Executor reached max iterations")
        return [], executed_queries

    def _parse_structured_result(self, response: str) -> List[Finding]:
        """Parse structured JSON response into Finding objects"""
        try:
            data = json.loads(response)
            validated = ExecutorOutputModel(**data)

            findings = []
            for f in validated.findings:
                # Convert entities
                entities = []
                for e in f.entities:
                    entities.append(CodeEntity(
                        name=e.name,
                        entity_type=e.entity_type,
                        file_path=e.file_path
                    ))

                # Map confidence string to enum
                confidence_map = {
                    "high": ConfidenceLevel.HIGH,
                    "medium": ConfidenceLevel.MEDIUM,
                    "low": ConfidenceLevel.LOW
                }
                confidence = confidence_map.get(f.confidence.lower(), ConfidenceLevel.MEDIUM)

                findings.append(Finding(
                    claim=f.claim,
                    entities=entities,
                    evidence={"summary": f.evidence_summary} if f.evidence_summary else {},
                    confidence=confidence,
                    source_query=f.source_query,
                    cot_agent_id=self._agent_id
                ))

            return findings
        except (json.JSONDecodeError, ValueError) as e:
            self._logger.error(f"Structured JSON parsing failed: {e}")
            return []


__all__ = ['ExecutorVerifierAgent']

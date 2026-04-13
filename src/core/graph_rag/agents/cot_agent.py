"""
Chain-of-Thought (CoT) Agent for the Graph RAG Multi-Agent system.

Executes sub-queries using step-by-step reasoning and returns findings
about ACTUAL code entities from the codebase.
"""

import json
import logging
import time
from typing import Any, Dict, List

from openai import OpenAI

from src.core.graph_rag.core.enums import AgentRole, ConfidenceLevel
from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.models import (
    CodeEntity,
    Finding,
    SubQuery,
    WorkerResponse,
)
from src.core.graph_rag.tools.manager import ToolManager
from src.core.graph_rag.tools.retry import retry_with_backoff
from src.core.graph_rag.agents.base_agent import BaseAgent


class CoTAgent(BaseAgent):
    """
    Chain-of-Thought Agent - Has schema tools access.
    Executes sub-queries using step-by-step reasoning and returns findings about ACTUAL code entities.

    NOTE: This is a LEGACY agent used when use_4_agent_team=False.
    The 4-Agent Team workflow uses ThinkerAgent instead.
    """

    # Tools allowed for this agent (short names for OpenAI API)
    # Matches tools provided by ToolManager
    ALLOWED_TOOLS = [
        # Neo4j/MCP tools
        "neo4j_execute_query",
        "neo4j_get_version",
        # Schema tools (langchain)
        "get_node_labels",
        "get_valid_pairs",
        "validate_relationship_triplet",
        "get_outgoing_relationships",
        "get_node_properties",
        "get_children_types",
        "get_incoming_relationships",
        "get_leaf_nodes",
    ]

    # Fully qualified tool names for Claude SDK fallback
    SDK_ALLOWED_TOOLS = [
        # Neo4j/MCP tools
        "mcp__neo4j_memory__neo4j_execute_query",
        "mcp__neo4j_memory__neo4j_get_version",
        # Schema tools (in-process MCP)
        "mcp__schema_tools__get_node_labels",
        "mcp__schema_tools__get_valid_pairs",
        "mcp__schema_tools__validate_relationship_triplet",
        "mcp__schema_tools__get_outgoing_relationships",
        "mcp__schema_tools__get_node_properties",
        "mcp__schema_tools__get_children_types",
        "mcp__schema_tools__get_incoming_relationships",
        "mcp__schema_tools__get_leaf_nodes",
    ]

    SYSTEM_PROMPT = """You are a Data Retrieval Agent for code analysis. Your job is to find ACTUAL code entities from the codebase stored in a Neo4j Code Property Graph.

CRITICAL RULES:
1. Return information about ACTUAL code in the codebase:
   - Real class names (e.g., "WorkerA", "Helper", "WorkerFactory")
   - Real function names (e.g., "CreateWorkers", "FormatMessage")
   - Real file paths (e.g., "HelloWorldApp/WorkerA.cs")
   - Real code snippets from the 'body' property
   - Real relationships between actual code entities

2. DO NOT describe the graph schema structure. Never say:
   - "Type nodes contain Function nodes" [WRONG]
   - "The CALLS relationship connects Function to Function" [WRONG]

3. INSTEAD say things like:
   - "The WorkerFactory class contains the CreateWorkers method" [CORRECT]
   - "WorkerA.DoWork calls Helper.FormatMessage" [CORRECT]

4. Use schema tools to write correct Cypher queries, but findings must be about actual code.

5. NEO4J VERSION & SYNTAX: Before writing complex queries, call neo4j_get_version for correct syntax guidance.
   - Use schema tools to discover the actual graph structure before querying
   - If a query fails with syntax error, read the error and fix the query accordingly

6. ENTITY CONTEXT: You may receive hints about entity types. Use them for correct queries:
   - If told "HelloWorldApp is a PROJECT", query: WHERE x.file_path STARTS WITH 'HelloWorldApp/'
   - If told "Manager is a CLASS", query: MATCH (t:Type {name: 'Manager'})
   - If told "FormatMessage is a FUNCTION", query: MATCH (f:Function {name: 'FormatMessage'})
   - Project/Namespace names are NOT class names - filter by file_path instead!

OUTPUT FORMAT (JSON):
{
  "findings": [
    {
      "claim": "Clear statement about actual code",
      "entities": [
        {"name": "EntityName", "entity_type": "class/function/etc", "file_path": "path/to/file.cs"}
      ],
      "evidence": {"property_name": "value from graph"},
      "confidence": "high/medium/low",
      "source_query": "MATCH query used"
    }
  ]
}"""

    def __init__(
        self,
        tool_manager: ToolManager,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig,
        cot_agent_id: str
    ):
        """
        Initialize the CoT Agent.

        Args:
            tool_manager: ToolManager for executing tools
            openai_client: OpenAI client instance
            llm_config: LLM configuration
            config: System configuration
            cot_agent_id: Unique identifier for this CoT agent
        """
        super().__init__(openai_client, llm_config, AgentRole.COT_AGENT, config, agent_id=cot_agent_id)
        self._tool_manager = tool_manager
        self._cot_agent_id = cot_agent_id

    @retry_with_backoff(max_retries=3)
    async def execute(self, subquery: SubQuery, entity_context: str = "") -> WorkerResponse:
        """Execute a sub-query using chain-of-thought reasoning

        Args:
            subquery: The sub-query to execute
            entity_context: Optional context about resolved entities (e.g., "HelloWorldApp is a Project,
                          query by file_path not Type.name")
        """
        start_time = time.time()
        self._logger.info(f"CoT Agent {self._cot_agent_id} executing: {subquery.query[:50]}...")

        # Build user message with entity context if available
        user_content = f"Find information for: {subquery.query}\n\nFocus area: {subquery.focus}"
        if entity_context:
            user_content += f"\n\n{entity_context}"

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        findings = []
        errors = []
        iterations = 0

        for iteration in range(self._config.max_cot_iterations):
            iterations = iteration + 1
            self._logger.info(f"  [{self._cot_agent_id}] Iteration {iterations}")

            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tool_manager.tools,
                    tool_choice="auto"
                )

                msg = response.choices[0].message

                # Check if done
                if not msg.tool_calls:
                    if msg.content:
                        self._logger.info(f"  [{self._cot_agent_id}] Final response (first 500 chars):\n{msg.content[:500]}")
                        findings = self._parse_findings(msg.content)
                        self._logger.info(f"  [{self._cot_agent_id}] Parsed {len(findings)} findings")
                    break

                # Log assistant thinking if present
                if msg.content:
                    self._logger.info(f"  [{self._cot_agent_id}] Thinking: {msg.content[:200]}...")

                # Execute tool calls
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": msg.tool_calls
                })

                for tool_call in msg.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                        # Log tool call
                        args_str = json.dumps(args, indent=2)[:300]
                        self._logger.info(f"  [{self._cot_agent_id}] TOOL CALL: {tool_name}\n    Args: {args_str}")
                        
                        result = await self._tool_manager.execute_tool(tool_name, args)
                        
                        # Log tool response (truncated)
                        result_preview = result[:500] if len(result) > 500 else result
                        self._logger.info(f"  [{self._cot_agent_id}] TOOL RESULT ({len(result)} chars): {result_preview}...")
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                    except Exception as e:
                        error_msg = f"Tool error ({tool_name}): {str(e)}"
                        self._logger.error(f"  [{self._cot_agent_id}] {error_msg}")
                        errors.append(error_msg)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": str(e)})
                        })

            except Exception as e:
                errors.append(f"Iteration {iteration} error: {str(e)}")
                self._logger.error(f"CoT Agent error: {e}")

        execution_time = int((time.time() - start_time) * 1000)
        self._logger.info(f"  [{self._cot_agent_id}] Completed: {len(findings)} findings, {len(errors)} errors, {execution_time}ms")

        # Add cot_agent_id to findings
        for finding in findings:
            finding_dict = finding.model_dump()
            finding_dict['cot_agent_id'] = self._cot_agent_id
            findings[findings.index(finding)] = Finding(**finding_dict)

        return WorkerResponse(
            findings=findings,
            errors=errors,
            iterations_used=iterations,
            execution_time_ms=execution_time
        )

    def _parse_findings(self, response: str) -> List[Finding]:
        """Parse LLM response into structured findings with guardrails"""
        findings = []

        # Try JSON parsing first
        try:
            # Find JSON in response
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                data = json.loads(json_str)

                if 'findings' in data:
                    for f in data['findings']:
                        entities = []
                        for e in f.get('entities', []):
                            entities.append(CodeEntity(
                                name=e.get('name', 'unknown'),
                                entity_type=e.get('entity_type', 'unknown'),
                                file_path=e.get('file_path'),
                                node_id=e.get('node_id'),
                                properties=e.get('properties', {})
                            ))

                        findings.append(Finding(
                            claim=f.get('claim', ''),
                            entities=entities,
                            evidence=f.get('evidence', {}),
                            confidence=ConfidenceLevel(f.get('confidence', 'medium')),
                            source_query=f.get('source_query'),
                            cot_agent_id=self._cot_agent_id
                        ))
                    return findings
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._logger.warning(f"JSON parsing failed: {e}")

        # Fallback: create single finding from response
        if response.strip():
            findings.append(Finding(
                claim=response,
                entities=[],
                evidence={"raw_response": response},
                confidence=ConfidenceLevel.LOW,
                source_query=None,
                cot_agent_id=self._cot_agent_id
            ))

        return findings


__all__ = ['CoTAgent']

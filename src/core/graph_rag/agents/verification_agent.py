"""
Verification Agent for the Graph RAG Multi-Agent system.

Independently verifies claims by querying the graph.
Works collaboratively with CoT agents by providing feedback when queries are incorrect.
"""

import json
import logging
import time
from typing import Any, Dict, List, Literal, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from src.core.graph_rag.core.enums import AgentRole, VerificationStatus
from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.models import (
    Finding,
    VerificationResult,
    VerifierResponse,
)
from src.core.graph_rag.tools.manager import ToolManager
from src.core.graph_rag.tools.retry import retry_with_backoff
from src.core.graph_rag.agents.base_agent import BaseAgent


# Pydantic model for structured LLM output
class VerificationResponseModel(BaseModel):
    """Structured response model for verification agent output"""
    status: Literal["verified", "not_verified", "partially_verified", "needs_correction"] = Field(
        ..., description="Verification status"
    )
    explanation: str = Field(
        ..., description="Detailed explanation of the analysis"
    )
    verified_evidence_json: str = Field(
        default="{}", description="JSON string containing verification data/evidence from query results"
    )
    verification_query: Optional[str] = Field(
        None, description="Cypher query used for verification"
    )
    correction_feedback: Optional[str] = Field(
        None, description="If needs_correction: What is wrong and how to fix it"
    )
    suggested_query: Optional[str] = Field(
        None, description="If needs_correction: The corrected Cypher query"
    )


class VerificationAgent(BaseAgent):
    """
    Verification Agent - Has schema tools access.
    Works collaboratively with CoT agents:
    1. Validates query logic against the claim
    2. Provides correction feedback if query is wrong
    3. Verifies data only when query logic is correct

    NOTE: This is a LEGACY agent used when use_4_agent_team=False.
    The 4-Agent Team workflow uses ExecutorVerifierAgent instead.
    """

    # Tools allowed for this agent (short names for OpenAI API)
    # Minimal set needed for verification: query execution + schema validation
    ALLOWED_TOOLS = [
        "neo4j_execute_query",  # Run verification queries
        "get_node_properties",  # Check node properties exist
        "get_outgoing_relationships",  # Check relationship directions
        "get_incoming_relationships",  # Check relationship directions
        "validate_relationship_triplet",  # Validate (from)-[rel]->(to) paths
    ]

    # Fully qualified tool names for Claude SDK fallback
    SDK_ALLOWED_TOOLS = [
        "mcp__neo4j_memory__neo4j_execute_query",
        "mcp__schema_tools__get_node_properties",
        "mcp__schema_tools__get_outgoing_relationships",
        "mcp__schema_tools__get_incoming_relationships",
        "mcp__schema_tools__validate_relationship_triplet",
    ]

    SYSTEM_PROMPT = """You are a Verification Agent working as a TEAM with the CoT (Chain-of-Thought) Agent.

YOUR TWO-PHASE JOB:

## PHASE 1: VALIDATE QUERY LOGIC
First, analyze whether the SOURCE_QUERY correctly answers the CLAIM:
- Does the query retrieve the right data for what's being claimed?
- Is the graph schema being used correctly?
- Are the correct node types, relationships, and properties being queried?

Use schema tools to understand the graph structure:
- get_node_properties: What properties exist on nodes
- get_outgoing_relationships / get_incoming_relationships: What relationships connect nodes
- validate_relationship_triplet: Verify (from)-[rel]->(to) paths are valid

## PHASE 2: VERIFY OR PROVIDE FEEDBACK
If query logic is CORRECT:
- Execute verification query to confirm the data
- Return status: "verified" | "not_verified" | "partially_verified"

If query logic is WRONG:
- Return status: "needs_correction"
- Provide specific correction_feedback explaining what's wrong
- Provide suggested_query with the corrected Cypher query

EXAMPLES OF QUERY LOGIC ISSUES:
- Counting all Statement nodes when only decision points (if/for/while) should be counted
- Using wrong property name (e.g., 'type' instead of 'statement_type')
- Missing WHERE clause filters
- Wrong relationship direction or type
- Incorrect node label

OUTPUT FORMAT (JSON):
{
  "status": "verified" | "not_verified" | "partially_verified" | "needs_correction",
  "explanation": "Detailed explanation of your analysis",
  "verified_evidence": {"data from verification query if applicable"},
  "verification_query": "MATCH query you used for verification",
  "correction_feedback": "If needs_correction: What is wrong and how to fix it",
  "suggested_query": "If needs_correction: The corrected Cypher query"
}

IMPORTANT: Be a helpful teammate! If the CoT agent's query is wrong, help them understand exactly what to fix."""

    def __init__(
        self,
        tool_manager: ToolManager,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig
    ):
        """
        Initialize the Verification Agent.

        Args:
            tool_manager: ToolManager for executing tools
            openai_client: OpenAI client instance
            llm_config: LLM configuration
            config: System configuration
        """
        super().__init__(openai_client, llm_config, AgentRole.VERIFIER, config)
        self._tool_manager = tool_manager

    def _get_structured_response_format(self) -> Dict[str, Any]:
        """Get the JSON schema for structured output"""
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "verification_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["verified", "not_verified", "partially_verified", "needs_correction"],
                            "description": "Verification status"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Detailed explanation of the analysis"
                        },
                        "verified_evidence_json": {
                            "type": "string",
                            "description": "JSON string containing verification data/evidence from query results"
                        },
                        "verification_query": {
                            "type": ["string", "null"],
                            "description": "Cypher query used for verification"
                        },
                        "correction_feedback": {
                            "type": ["string", "null"],
                            "description": "If needs_correction: What is wrong and how to fix it"
                        },
                        "suggested_query": {
                            "type": ["string", "null"],
                            "description": "If needs_correction: The corrected Cypher query"
                        }
                    },
                    "required": ["status", "explanation", "verified_evidence_json", "verification_query", "correction_feedback", "suggested_query"],
                    "additionalProperties": False
                }
            }
        }

    @retry_with_backoff(max_retries=3)
    async def execute(self, finding: Finding) -> VerifierResponse:
        """Verify a finding with collaborative feedback"""
        start_time = time.time()

        # Detailed logging - INPUT
        self._logger.info(f"[VERIFIER INPUT]")
        self._logger.info(f"  Claim: {finding.claim}")
        self._logger.info(f"  Source Query: {finding.source_query if finding.source_query else 'None'}")
        self._logger.info(f"  Evidence: {json.dumps(finding.evidence, indent=2)}")
        self._logger.info(f"  Entities: {[e.name for e in finding.entities] if finding.entities else []}")

        # Build user message with source query for validation
        user_content = f"""Verify this claim from the CoT Agent:

CLAIM: {finding.claim}

SOURCE QUERY USED BY COT AGENT:
{finding.source_query if finding.source_query else "No query provided"}

PROVIDED EVIDENCE:
{json.dumps(finding.evidence, indent=2)}

ENTITIES MENTIONED:
{json.dumps([e.model_dump() for e in finding.entities], indent=2)}

INSTRUCTIONS:
1. First, use schema tools to understand how this information should be queried
2. Analyze if the SOURCE QUERY correctly answers the CLAIM
3. If query logic is wrong, return "needs_correction" with helpful feedback
4. If query logic is correct, verify the data independently"""

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        for iteration in range(self._config.max_verifier_iterations):
            self._logger.info(f"  [Verifier Iteration {iteration + 1}]")
            try:
                response = self._create_chat_completion(
                    messages=messages,
                    tools=self._tool_manager.tools,
                    tool_choice="auto"
                )

                msg = response.choices[0].message

                if not msg.tool_calls:
                    # LLM is done with tool calls, now get structured output
                    self._logger.info(f"  [VERIFIER ANALYSIS COMPLETE] Getting structured response...")

                    # Add the LLM's analysis to messages
                    if msg.content:
                        self._logger.info(f"  [VERIFIER ANALYSIS]:\n{msg.content}")
                        messages.append({"role": "assistant", "content": msg.content})

                    # Request structured output
                    messages.append({
                        "role": "user",
                        "content": "Now provide your final verification result in the required JSON format."
                    })

                    structured_response = self._create_chat_completion(
                        messages=messages,
                        response_format=self._get_structured_response_format()
                    )

                    structured_content = structured_response.choices[0].message.content
                    self._logger.info(f"  [VERIFIER STRUCTURED RESPONSE]:\n{structured_content}")

                    result = self._parse_structured_verification(finding.claim, structured_content)
                    execution_time = int((time.time() - start_time) * 1000)

                    # Detailed logging - OUTPUT
                    self._logger.info(f"[VERIFIER OUTPUT]")
                    self._logger.info(f"  Status: {result.status.value}")
                    self._logger.info(f"  Explanation: {result.explanation}")
                    self._logger.info(f"  Correction Feedback: {result.correction_feedback}")
                    self._logger.info(f"  Suggested Query: {result.suggested_query}")
                    self._logger.info(f"  Verification Query: {result.verification_query}")

                    return VerifierResponse(result=result, execution_time_ms=execution_time)

                # Log assistant thinking
                if msg.content:
                    self._logger.info(f"  Verifier thinking: {msg.content}")

                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": msg.tool_calls
                })

                for tool_call in msg.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                        args_str = json.dumps(args, indent=2)
                        self._logger.info(f"  [Verifier TOOL CALL]: {tool_name}\n    Args: {args_str}")

                        result = await self._tool_manager.execute_tool(tool_name, args)

                        self._logger.info(f"  [Verifier TOOL RESULT]: {result}")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                    except Exception as e:
                        self._logger.error(f"  Tool error ({tool_name}): {e}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps({"error": str(e)})
                        })

            except Exception as e:
                self._logger.error(f"Verification error: {e}")

        # Max iterations reached
        execution_time = int((time.time() - start_time) * 1000)
        return VerifierResponse(
            result=VerificationResult(
                claim=finding.claim,
                status=VerificationStatus.ERROR,
                verified_evidence={},
                explanation="Max iterations reached",
                verification_query=None,
                correction_feedback=None,
                suggested_query=None
            ),
            execution_time_ms=execution_time
        )

    def _parse_structured_verification(self, claim: str, response: str) -> VerificationResult:
        """Parse structured JSON verification response from Pydantic-validated output"""
        try:
            # Parse the structured JSON response
            data = json.loads(response)

            # Validate with Pydantic model
            validated = VerificationResponseModel(**data)

            # Map status string to enum
            status = VerificationStatus(validated.status)

            # Parse the verified_evidence_json string back to dict
            verified_evidence = {}
            if validated.verified_evidence_json:
                try:
                    verified_evidence = json.loads(validated.verified_evidence_json)
                except json.JSONDecodeError:
                    # If it's not valid JSON, store it as a string value
                    verified_evidence = {"raw": validated.verified_evidence_json}

            return VerificationResult(
                claim=claim,
                status=status,
                verified_evidence=verified_evidence,
                explanation=validated.explanation,
                verification_query=validated.verification_query,
                correction_feedback=validated.correction_feedback,
                suggested_query=validated.suggested_query
            )
        except (json.JSONDecodeError, ValueError) as e:
            self._logger.error(f"Structured JSON parsing failed: {e}")
            # Return error result if parsing fails (should not happen with structured output)
            return VerificationResult(
                claim=claim,
                status=VerificationStatus.ERROR,
                verified_evidence={},
                explanation=f"Failed to parse structured response: {e}",
                verification_query=None,
                correction_feedback=None,
                suggested_query=None
            )


__all__ = ['VerificationAgent']

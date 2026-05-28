"""
Tree-of-Thought Orchestrator for the Graph RAG Multi-Agent system.

Decomposes queries using tree-of-thought reasoning, orchestrates CoT agents,
and synthesizes final answers from verified findings.
"""

import json
import logging
from typing import List, Tuple

from openai import OpenAI

from src.core.graph_rag.core.enums import AgentRole, ConfidenceLevel, VerificationStatus
from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.models import (
    Finding,
    FinalAnswer,
    QueryDecomposition,
    SubQuery,
    VerificationResult,
)
from src.core.graph_rag.agents.base_agent import BaseAgent


class ToTOrchestrator(BaseAgent):
    """
    Tree-of-Thought Orchestrator - NO schema access.
    Decomposes queries using tree-of-thought reasoning, orchestrates CoT agents, synthesizes answers.
    """

    DECOMPOSITION_PROMPT = """You are a Query Decomposition Agent. Break down the user's question into specific sub-queries.

Each sub-query should:
1. Be specific and answerable
2. Focus on finding ACTUAL code entities (classes, functions, files, relationships)
3. Together cover all aspects of the original question
4. Use the CORRECT entity types based on any provided entity context

IMPORTANT: If entity context is provided, use it to create accurate sub-queries:
- If an entity is identified as a PROJECT, create sub-queries that find entities WITHIN that project (not the project as a class)
- If an entity is identified as a CLASS, create sub-queries that examine that class
- If an entity is identified as a NAMESPACE, create sub-queries that explore that namespace

DEPENDENCY TRACKING: Some sub-queries may depend on findings from other sub-queries.
- Discovery/exploration sub-queries (finding what data exists) are usually INDEPENDENT
- Calculation/analysis sub-queries that USE discovered data are DEPENDENT on the discovery queries
- Mark dependencies using the "depends_on" field with the IDs of prerequisite sub-queries
- Sub-queries with no dependencies can run in parallel; dependent ones run after their prerequisites

Example: For "calculate cyclomatic complexity":
- Sub-query 1 (id:1): "Find what statement types exist" → depends_on: [] (independent)
- Sub-query 2 (id:2): "Calculate complexity using discovered statement types" → depends_on: [1] (needs #1's findings)

OUTPUT FORMAT (JSON):
{
  "sub_queries": [
    {"id": 1, "query": "specific question", "focus": "what aspect this covers", "priority": 1-5, "depends_on": []},
    {"id": 2, "query": "another question", "focus": "aspect", "priority": 1, "depends_on": [1]}
  ],
  "reasoning": "why you decomposed it this way and identified these dependencies"
}"""

    SYNTHESIS_PROMPT = """You are a Code Analysis Expert synthesizing findings about a codebase.

RULES:
1. Only include VERIFIED information
2. Talk about ACTUAL code entities (real class names, function names, files)
3. DO NOT describe graph schema or database structure
4. Be specific with names, file paths, and code details
5. Mention uncertainty for unverified claims

OUTPUT FORMAT (JSON):
{
  "answer": "comprehensive answer about the actual codebase",
  "verified_claims": ["list of verified facts"],
  "unverified_claims": ["list of unverified claims"],
  "confidence": "high/medium/low"
}"""

    def __init__(self, openai_client: OpenAI, llm_config: LLMConfig, config: SystemConfig):
        """
        Initialize the ToT Orchestrator.

        Args:
            openai_client: OpenAI client instance
            llm_config: LLM configuration
            config: System configuration
        """
        super().__init__(openai_client, llm_config, AgentRole.TOT_ORCHESTRATOR, config)

    async def execute(self, *args, **kwargs):
        """Not used directly - orchestrator has specific methods"""
        pass

    def decompose_query(self, user_query: str, entity_context: str = "") -> QueryDecomposition:
        """
        Decompose user query into sub-queries using tree-of-thought reasoning.

        Args:
            user_query: Original user question
            entity_context: Optional context about resolved entities (e.g., "HelloWorldApp is a Project")

        Returns:
            QueryDecomposition with sub-queries and reasoning
        """
        self._logger.info("Decomposing query...")

        # Build user message with entity context if available
        user_message = user_query
        if entity_context:
            user_message = f"{user_query}\n\n{entity_context}"

        try:
            response = self._create_chat_completion(
                messages=[
                    {"role": "system", "content": self.DECOMPOSITION_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content

            # Parse JSON
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                data = json.loads(content[start_idx:end_idx])

                # Handle nested structure from Claude SDK's StructuredOutput tool
                # The JSON might be {"type": {"sub_queries": [...]}} instead of {"sub_queries": [...]}
                if 'type' in data and isinstance(data['type'], dict):
                    self._logger.debug(f"Found nested 'type' structure, extracting sub_queries from it")
                    data = data['type']

                sub_queries = []
                for idx, sq in enumerate(data.get('sub_queries', [])):
                    # Use provided id or default to 1-indexed position
                    sq_id = sq.get('id', idx + 1)
                    sub_queries.append(SubQuery(
                        id=sq_id,
                        query=sq.get('query', ''),
                        focus=sq.get('focus', ''),
                        priority=sq.get('priority', 1),
                        depends_on=sq.get('depends_on', [])
                    ))

                decomposition = QueryDecomposition(
                    original_query=user_query,
                    sub_queries=sub_queries,
                    reasoning=data.get('reasoning', '')
                )

                # Log decomposition with dependencies for debugging
                self._logger.info(f"Decomposition created {len(sub_queries)} sub-queries:")
                for sq in sub_queries:
                    self._logger.info(f"  SQ-{sq.id}: depends_on={sq.depends_on} | {sq.query[:60]}...")

                return decomposition

        except Exception as e:
            self._logger.error(f"Decomposition error: {e}")

        # Fallback - single independent sub-query
        return QueryDecomposition(
            original_query=user_query,
            sub_queries=[SubQuery(id=1, query=user_query, focus="entire question", priority=1, depends_on=[])],
            reasoning="Fallback - using original query"
        )

    def synthesize_answer(
        self,
        user_query: str,
        verified_findings: List[Tuple[Finding, VerificationResult]]
    ) -> FinalAnswer:
        """
        Synthesize final answer from verified findings.

        Args:
            user_query: Original user question
            verified_findings: List of (Finding, VerificationResult) tuples

        Returns:
            FinalAnswer with synthesized response and claim lists
        """
        self._logger.info("Synthesizing final answer...")

        # Build findings summary
        findings_text = ""
        verified_claims = []
        unverified_claims = []

        for finding, verification in verified_findings:
            if verification.status == VerificationStatus.VERIFIED:
                status_icon = "[OK]"
                verified_claims.append(finding.claim)
            elif verification.status == VerificationStatus.PARTIALLY_VERIFIED:
                status_icon = "~"
                verified_claims.append(f"(partial) {finding.claim}")
            else:
                status_icon = "[X]"
                unverified_claims.append(finding.claim)

            findings_text += f"\n{status_icon} {finding.claim}\n"
            findings_text += f"  Evidence: {json.dumps(finding.evidence)}\n"
            findings_text += f"  Entities: {[e.name for e in finding.entities]}\n"

        try:
            response = self._create_chat_completion(
                messages=[
                    {"role": "system", "content": self.SYNTHESIS_PROMPT},
                    {"role": "user", "content": f"""Original Question: {user_query}

Findings:
{findings_text}

Synthesize a comprehensive answer."""}
                ],
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content

            # Parse JSON
            try:
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                if start_idx != -1 and end_idx > start_idx:
                    data = json.loads(content[start_idx:end_idx])

                    # Handle nested structure from Claude SDK's StructuredOutput tool
                    # The JSON might be {"type": {"answer": ...}} instead of {"answer": ...}
                    if 'type' in data and isinstance(data['type'], dict):
                        self._logger.debug(f"Found nested 'type' structure in synthesis, extracting from it")
                        data = data['type']

                    return FinalAnswer(
                        answer=data.get('answer', content),
                        verified_claims=data.get('verified_claims', verified_claims),
                        unverified_claims=data.get('unverified_claims', unverified_claims),
                        confidence=ConfidenceLevel(data.get('confidence', 'medium')),
                        total_findings=len(verified_findings),
                        verified_count=len(verified_claims)
                    )
            except (json.JSONDecodeError, ValueError):
                pass

            return FinalAnswer(
                answer=content,
                verified_claims=verified_claims,
                unverified_claims=unverified_claims,
                confidence=ConfidenceLevel.MEDIUM,
                total_findings=len(verified_findings),
                verified_count=len(verified_claims)
            )

        except Exception as e:
            self._logger.error(f"Synthesis error: {e}")
            return FinalAnswer(
                answer=f"Error synthesizing answer: {e}",
                verified_claims=[],
                unverified_claims=[],
                confidence=ConfidenceLevel.LOW,
                total_findings=len(verified_findings),
                verified_count=0
            )


__all__ = ['ToTOrchestrator']

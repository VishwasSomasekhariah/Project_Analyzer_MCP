"""
.. deprecated::
    Not used by any active MCP tools. See ``src/core/graph_rag/workflows/four_agent_workflow.py``
    for the active multi-agent pipeline.

MultiAgentIRCoT Orchestrator - IR-based Multi-Agent Chain-of-Thought.

This orchestrator integrates IR-based query generation into the existing
multi-agent architecture, replacing the CoT+Verifier loop with deterministic
IR validation and compilation.

Architecture:
    ┌──────────────────────────────────────────────────────────────────────┐
    │                       MultiAgentIRCoT Orchestrator                    │
    └──────────────────────────────────────────────────────────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
    ┌───────────────┐        ┌────────────────┐        ┌───────────────┐
    │EntityResolver │        │QueryDecomposer │        │ SchemaManager │
    │  (existing)   │        │  (existing)    │        │  (existing)   │
    └───────────────┘        └────────────────┘        └───────────────┘
                                       │
                                       ▼
                            ┌────────────────────┐
                            │   IRPlannerAgent   │  ← NEW: Generates IR only
                            │  (Schema-aware)    │
                            └────────────────────┘
                                       │
                                       ▼
                            ┌────────────────────┐
                            │   IRValidator      │  ← NEW: Validates IR against schema
                            │ (No LLM needed)    │     (deterministic checks)
                            └────────────────────┘
                                       │
                                       ▼
                            ┌────────────────────┐
                            │  CypherCompiler    │  ← NEW: IR → Cypher (deterministic)
                            │ (Template-based)   │     (No LLM needed)
                            └────────────────────┘
                                       │
                                       ▼
                            ┌────────────────────┐
                            │  ExecutionEngine   │  ← Executes, handles errors
                            └────────────────────┘
                                       │
                                       ▼
                            ┌────────────────────┐
                            │ SynthesizerAgent   │  ← Existing ToT synthesizer
                            └────────────────────┘

Key Benefits:
- Reuses existing EntityResolver for entity disambiguation
- Reuses existing QueryDecomposer (ToT) for query breakdown
- Eliminates CoT/Verifier loops through validated IR
- Deterministic Cypher generation (no LLM hallucinations in queries)
- Uses existing ToT synthesizer for final answer
"""

import asyncio
import json
import logging
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from openai import OpenAI

from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.models import (
    ProductionResponse,
    ConfidenceLevel,
    Citation,
    Finding,
    SubQuery,
)
from src.core.graph_rag.core.enums import VerificationStatus
from src.core.graph_rag.core.metrics import AggregatedTokenUsage, TokenUsage
from src.core.graph_rag.validators.input_validator import InputPromptValidator, CypherSecurityError
from src.core.graph_rag.agents.base_agent import BaseAgent
from src.core.graph_rag.agents.entity_resolution_agent import EntityResolutionAgent
from src.core.graph_rag.orchestrators.tot_orchestrator import ToTOrchestrator
from src.core.graph_rag.tools.manager import ToolManager

from .planner_agent import IRPlannerAgent, IRPlanningResult
from .models import QueryIR
from .context import SchemaInfo
from .validators import IRValidator, IntentRuleEngine
from .compiler import CypherCompiler

if TYPE_CHECKING:
    from src.core.graph_rag.schema import DynamicSchemaManager
    from mcp_use import MCPClient


logger = logging.getLogger(__name__)


class MultiAgentIRCoT:
    """
    IR-based Multi-Agent Chain-of-Thought Orchestrator.

    This orchestrator integrates with the existing multi-agent system:
    - EntityResolver: For entity disambiguation (existing)
    - ToTOrchestrator: For query decomposition and synthesis (existing)
    - IRPlannerAgent: For generating validated IR (new)
    - IRValidator: For schema validation (new)
    - CypherCompiler: For deterministic Cypher generation (new)

    The key improvement is replacing the CoT+Verifier feedback loop with
    deterministic IR validation, eliminating LLM hallucinations in Cypher.

    Usage:
        orchestrator = MultiAgentIRCoT(config)
        await orchestrator.initialize()

        response = await orchestrator.run(
            "Find functions with cyclomatic complexity > 5 in HelloWorldApp"
        )
    """

    def __init__(
        self,
        config: Optional[SystemConfig] = None,
        enable_entity_resolution: bool = True,
        strict_validation: bool = True
    ):
        """
        Initialize the Multi-Agent IR CoT Orchestrator.

        Args:
            config: System configuration (uses defaults if not provided)
            enable_entity_resolution: Whether to run entity resolution
            strict_validation: If True, unknown properties are errors
        """
        self._config = config or SystemConfig()
        self._enable_entity_resolution = enable_entity_resolution
        self._strict_validation = strict_validation

        # Existing components (initialized in initialize())
        self._mcp_client: Optional['MCPClient'] = None
        self._mcp_session = None
        self._schema_manager: Optional['DynamicSchemaManager'] = None
        self._tool_manager: Optional[ToolManager] = None
        self._tot_orchestrator: Optional[ToTOrchestrator] = None
        self._entity_resolver: Optional[EntityResolutionAgent] = None

        # New IR components
        self._ir_planner: Optional[IRPlannerAgent] = None
        self._compiler = CypherCompiler()

        # OpenAI client
        self._openai: Optional[OpenAI] = None
        self._llm_config: Optional[LLMConfig] = None

        # Input validation
        self._input_validator = InputPromptValidator(strict_mode=True)

        # State
        self._initialized = False
        self._logger = logging.getLogger(f"{__name__}.orchestrator")

        # Token tracking
        self._token_tracker = AggregatedTokenUsage()
        BaseAgent.set_token_tracker(self._token_tracker)

    async def initialize(self) -> None:
        """Initialize the orchestrator and all components."""
        if self._initialized:
            self._logger.info("Orchestrator already initialized")
            return

        self._logger.info("Initializing MultiAgentIRCoT Orchestrator...")

        # Initialize OpenAI client from config
        self._llm_config = self._config.get_llm_config()
        self._openai = OpenAI(
            api_key=self._llm_config.api_key,
            base_url=self._llm_config.base_url
        )

        # Initialize MCP client
        from mcp_use import MCPClient
        mcp_config_dict = self._config.get_mcp_config_dict()
        server_name = list(mcp_config_dict.get('mcpServers', {}).keys())[0]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(mcp_config_dict, f)
            temp_config_path = f.name

        self._mcp_client = MCPClient.from_config_file(temp_config_path)
        self._mcp_session = await self._mcp_client.create_session(server_name)

        # Initialize DynamicSchemaManager - must use MCPCypherAdapter and yaml_schema
        from src.core.graph_rag.schema import DynamicSchemaManager
        from src.core.graph_rag.adapters.mcp_adapter import MCPCypherAdapter
        cypher_adapter = MCPCypherAdapter(self._mcp_session)
        yaml_schema = self._config.get_yaml_schema()
        self._schema_manager = DynamicSchemaManager(
            cypher_server=cypher_adapter,
            yaml_schema=yaml_schema
        )
        await self._schema_manager.initialize_background()
        self._logger.info(f"Schema loaded: {len(self._schema_manager._reconciled_schema.get('nodes', {}))} node types")

        # Initialize ToolManager (for execution)
        self._tool_manager = ToolManager(
            self._mcp_session,
            self._schema_manager,
            agent_id="ir_orchestrator"
        )

        # Initialize existing ToTOrchestrator (for decomposition and synthesis)
        self._tot_orchestrator = ToTOrchestrator(
            self._openai,
            self._llm_config,
            self._config
        )

        # Initialize EntityResolver (existing, optional)
        if self._enable_entity_resolution and self._config.entity_resolution_enabled:
            self._entity_resolver = EntityResolutionAgent(
                self._mcp_session,  # Needs MCP session with call_tool method
                self._openai,
                self._llm_config,
                self._config
            )

        # Initialize IR Planner Agent (NEW)
        self._ir_planner = IRPlannerAgent(
            openai_client=self._openai,
            llm_config=self._llm_config,
            config=self._config,
            schema_manager=self._schema_manager,
            tool_manager=self._tool_manager,  # Enable tool-driven exploration
            strict_validation=self._strict_validation,
            use_tool_exploration=True
        )

        self._initialized = True
        self._logger.info("MultiAgentIRCoT Orchestrator initialized successfully")

    async def run(self, user_query: str) -> ProductionResponse:
        """
        Run the multi-agent IR system on a query.

        Flow:
        1. Input validation & sanitization
        2. Entity resolution (existing)
        3. Query decomposition (existing ToT)
        4. For each sub-query:
           a. IRPlannerAgent generates IR
           b. IRValidator validates IR (built into planner)
           c. CypherCompiler compiles to Cypher
           d. Execute Cypher
        5. Synthesize final answer (existing ToT)

        Args:
            user_query: User's natural language question

        Returns:
            ProductionResponse with answer, citations, and metadata
        """
        if not self._initialized:
            await self.initialize()

        start_time = time.time()

        # SECURITY: Validate user input
        try:
            self._input_validator.validate_or_raise(user_query)
        except CypherSecurityError as e:
            self._logger.warning(f"User query rejected: {e}")
            return ProductionResponse(
                answer=f"Query rejected for security reasons: {e}",
                confidence=ConfidenceLevel.LOW,
                citations=[],
                verified_count=0,
                unverified_count=0,
                token_usage=self._token_tracker,
                execution_time_ms=0,
                sub_queries_count=0,
                llm_calls_count=0,
                original_query=user_query
            )

        # Sanitize input
        sanitized_query = self._input_validator.sanitize(user_query)
        if sanitized_query != user_query:
            self._logger.info("User input was sanitized")

        print(f"\n{'='*70}")
        print("MULTI-AGENT IR COT SYSTEM")
        print(f"{'='*70}")
        print(f"Query: {sanitized_query}")

        # Step 1: Entity Resolution (existing)
        effective_query = sanitized_query
        resolved_entity_context = ""

        if self._entity_resolver:
            print(f"\n[RESOLVE] STEP 1: Resolving entity types...")
            resolution_result = await self._entity_resolver.execute(sanitized_query)

            if resolution_result.has_issues:
                print(f"   Found {len(resolution_result.corrections)} entity name issues")
                if resolution_result.corrected_query:
                    effective_query = resolution_result.corrected_query
                    print(f"   Corrected query: {effective_query}")

            if resolution_result.resolved_entities:
                context_lines = ["ENTITY CONTEXT:"]
                for entity in resolution_result.resolved_entities:
                    context_lines.append(f"- {entity.name} is a {entity.entity_type}")
                resolved_entity_context = "\n".join(context_lines)
        else:
            print(f"\n[RESOLVE] STEP 1: Entity resolution skipped")

        # Step 2: Query Decomposition (existing ToT)
        print(f"\n[DECOMPOSE] STEP 2: Decomposing query...")
        decomposition = self._tot_orchestrator.decompose_query(
            effective_query,
            resolved_entity_context
        )

        # Limit sub-queries
        if len(decomposition.sub_queries) > self._config.max_sub_queries:
            decomposition.sub_queries = sorted(
                decomposition.sub_queries, key=lambda sq: sq.priority
            )[:self._config.max_sub_queries]

        print(f"   Sub-queries: {len(decomposition.sub_queries)}")
        for i, sq in enumerate(decomposition.sub_queries):
            print(f"   {i+1}. [{sq.focus}] {sq.query}")

        # Step 3: Execute sub-queries using IR pipeline
        print(f"\n[EXECUTE] STEP 3: Executing sub-queries with IR pipeline...")
        findings: List[Finding] = []
        verified_findings: List[Tuple[Finding, Any]] = []

        for i, subquery in enumerate(decomposition.sub_queries):
            print(f"\n   Sub-query {i+1}: {subquery.query}")

            # 3a. IRPlannerAgent generates and validates IR
            print(f"      [IR] Generating QueryIR...")
            planning_result = await self._ir_planner.execute(
                query=subquery.query,
                project_name=None,  # Optional - not needed for most queries
                additional_context={"entity_context": resolved_entity_context}
            )

            if not planning_result.success:
                print(f"      [IR] Failed: {planning_result.error_message}")
                # Create a finding with the error
                finding = Finding(
                    claim=f"Could not answer: {subquery.query}",
                    evidence={},
                    source_query=None,
                    confidence=ConfidenceLevel.LOW,
                    source_subquery=subquery.query
                )
                findings.append(finding)
                continue

            print(f"      [IR] Success after {planning_result.attempts} attempt(s)")

            # 3b. Cypher already compiled by planner
            cypher = planning_result.cypher
            print(f"      [CYPHER] {cypher[:100]}...")

            # 3c. Execute Cypher via ToolManager
            print(f"      [EXEC] Executing query...")
            try:
                result_json = await self._tool_manager.execute_tool(
                    'neo4j_execute_query',
                    {'query': cypher}
                )
                result = json.loads(result_json) if isinstance(result_json, str) else result_json

                if result.get("error"):
                    print(f"      [EXEC] Error: {result.get('error')}")
                    finding = Finding(
                        claim=f"Query execution error for: {subquery.query}",
                        evidence={"error": result.get("error")},
                        source_query=cypher,
                        confidence=ConfidenceLevel.LOW,
                        source_subquery=subquery.query
                    )
                else:
                    # Support both 'results' (neo4j MCP format) and 'data' keys
                    data = result.get("results") or result.get("data") or []
                    print(f"      [EXEC] Success: {len(data)} rows")

                    # Build finding from results
                    finding = Finding(
                        claim=self._summarize_results(subquery.query, data),
                        evidence={"data": data, "row_count": len(data)},
                        source_query=cypher,
                        confidence=ConfidenceLevel.HIGH if data else ConfidenceLevel.MEDIUM,
                        source_subquery=subquery.query
                    )

                findings.append(finding)

                # IR-validated queries are considered verified
                from src.core.graph_rag.core.models import VerificationResult
                ver_result = VerificationResult(
                    claim=finding.claim,
                    status=VerificationStatus.VERIFIED,
                    verified_evidence=finding.evidence,
                    explanation="IR-validated query executed successfully"
                )
                verified_findings.append((finding, ver_result))

            except Exception as e:
                print(f"      [EXEC] Exception: {e}")
                finding = Finding(
                    claim=f"Execution failed for: {subquery.query}",
                    evidence={"error": str(e)},
                    source_query=cypher,
                    confidence=ConfidenceLevel.LOW,
                    source_subquery=subquery.query
                )
                findings.append(finding)

        # Step 4: Synthesize Answer (existing ToT synthesizer)
        print(f"\n[SYNTHESIS] STEP 4: Synthesizing final answer...")
        final_answer = self._tot_orchestrator.synthesize_answer(
            sanitized_query,
            verified_findings
        )

        # Build citations
        citations = self._build_citations(verified_findings)

        elapsed = time.time() - start_time
        execution_time_ms = int(elapsed * 1000)

        # Build production response
        verified_count = sum(
            1 for _, v in verified_findings
            if v.status == VerificationStatus.VERIFIED
        )

        response = ProductionResponse(
            answer=final_answer.answer,
            confidence=final_answer.confidence,
            citations=citations,
            verified_count=verified_count,
            unverified_count=len(findings) - verified_count,
            token_usage=self._token_tracker,
            execution_time_ms=execution_time_ms,
            sub_queries_count=len(decomposition.sub_queries),
            llm_calls_count=self._token_tracker.call_count,
            original_query=sanitized_query
        )

        self._print_results(response)
        return response

    def _summarize_results(self, query: str, data: List[Dict[str, Any]]) -> str:
        """Create a summary claim from query results."""
        if not data:
            return f"No results found for: {query}"

        row_count = len(data)

        # Try to extract meaningful summary
        if row_count == 1:
            return f"Found 1 result for: {query}"
        else:
            return f"Found {row_count} results for: {query}"

    def _build_citations(
        self,
        verified_findings: List[Tuple[Finding, Any]]
    ) -> List[Citation]:
        """Build citations from verified findings."""
        citations = []

        for finding, verification in verified_findings:
            # Citation expects evidence as dict, not JSON string
            evidence_dict = finding.evidence if finding.evidence else {}

            citation = Citation(
                claim=finding.claim,
                evidence=evidence_dict,
                source_query=finding.source_query or "",
                verification_status=verification.status,
                confidence=finding.confidence
            )
            citations.append(citation)

        return citations

    def _print_results(self, response: ProductionResponse) -> None:
        """Print results for CLI output."""
        print(f"\n{'='*70}")
        print("RESULTS")
        print(f"{'='*70}")
        print(f"\nANSWER: {response.answer}")
        print(f"\nConfidence: {response.confidence.value}")
        print(f"Citations: {len(response.citations)}")
        print(f"Verified: {response.verified_count}, Unverified: {response.unverified_count}")
        print(f"Execution time: {response.execution_time_ms}ms")
        print(f"Token usage: {response.token_usage.total_tokens} tokens")

    async def shutdown(self) -> None:
        """Clean up resources."""
        if self._schema_manager:
            await self._schema_manager.shutdown()

        if self._mcp_client:
            try:
                await self._mcp_client.close_all_sessions()
            except Exception as e:
                self._logger.debug(f"Session cleanup: {e}")

        self._initialized = False
        self._logger.info("MultiAgentIRCoT Orchestrator shut down")


__all__ = ['MultiAgentIRCoT']

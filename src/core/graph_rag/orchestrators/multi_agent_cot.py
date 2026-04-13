"""
Multi-Agent CoT Orchestrator for the Graph RAG system.

Coordinates ToT Orchestrator, CoT Agents, Verification Agent, Entity Resolution,
and CPG Observer for comprehensive code analysis.
"""

import asyncio
import json
import logging
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from mcp_use import MCPClient

from src.core.graph_rag.core.enums import ConfidenceLevel, VerificationStatus
from src.core.graph_rag.core.config import SystemConfig
from src.core.graph_rag.core.models import (
    Citation,
    Finding,
    ProductionResponse,
    QueryDecomposition,
    SubQuery,
    VerificationResult,
)
from src.core.graph_rag.core.metrics import AggregatedTokenUsage
from src.core.graph_rag.core.exceptions import CypherSecurityError
from src.core.graph_rag.validators.input_validator import InputPromptValidator
from src.core.graph_rag.adapters.mcp_adapter import MCPCypherAdapter
from src.core.graph_rag.adapters.session_pool import MCPSessionPool
from src.core.graph_rag.schema.dynamic_schema_manager import DynamicSchemaManager
from src.core.graph_rag.tools.manager import ToolManager
from src.core.graph_rag.agents.base_agent import BaseAgent
from src.core.graph_rag.agents.cot_agent import CoTAgent
from src.core.graph_rag.agents.verification_agent import VerificationAgent
from src.core.graph_rag.agents.entity_resolution_agent import EntityResolutionAgent
from src.core.graph_rag.agents.cpg_observer import CPGObserverAgent, ObserverReport
from src.core.graph_rag.orchestrators.tot_orchestrator import ToTOrchestrator
from src.core.graph_rag.workflows.four_agent_workflow import FourAgentWorkflow


class MultiAgentCoT:
    """
    Multi-Agent Tree-of-Thought / Chain-of-Thought System.
    Coordinates ToT Orchestrator, CoT Agents, and Verification Agent.
    """

    def __init__(self, config: Optional[SystemConfig] = None, enable_observer: bool = True):
        """
        Initialize the Multi-Agent CoT system.

        Args:
            config: System configuration (uses defaults if not provided)
            enable_observer: Whether to enable CPG Observer Agent
        """
        self._config = config or SystemConfig()
        self._mcp_client: Optional[MCPClient] = None
        self._mcp_session = None
        self._session_pool: Optional[MCPSessionPool] = None  # Pool for parallel CoT agents
        self._schema_manager: Optional[DynamicSchemaManager] = None
        self._tool_manager: Optional[ToolManager] = None
        self._tot_orchestrator: Optional[ToTOrchestrator] = None
        self._verifier: Optional[VerificationAgent] = None
        self._entity_resolver: Optional[EntityResolutionAgent] = None
        self._cpg_observer: Optional[CPGObserverAgent] = None  # CPG Quality Observer
        self._enable_observer = enable_observer  # Flag to enable/disable observer
        self._input_validator = InputPromptValidator(strict_mode=True)
        self._initialized = False
        self._logger = logging.getLogger(f"{__name__}.orchestrator")
        self._openai: Optional[OpenAI] = None  # Created during initialize() from LLM config
        self._llm_config = None
        self._cot_llm_config = None  # CoT-specific config with higher temperature

        # Initialize token tracker for transparency
        self._token_tracker = AggregatedTokenUsage()
        BaseAgent.set_token_tracker(self._token_tracker)

        # Store execution traces for debugging/analysis (populated by run())
        self._last_execution_traces: List[Dict[str, Any]] = []

    async def initialize(self):
        """Initialize all components"""
        if self._initialized:
            return

        self._logger.info("Initializing Multi-Agent System...")

        # Get effective LLM config and create client
        self._llm_config = self._config.get_llm_config()
        self._openai = self._llm_config.create_client()

        # Enable per-agent SDK mode for Claude SDK fallback
        # This provides per-agent tool restrictions and parallel-safe sessions
        self._openai.enable_per_agent_mode()

        # Create CoT-specific LLM config with higher temperature for more exploration
        self._cot_llm_config = self._llm_config.model_copy(update={"temperature": 0.3})

        # Initialize MCP - supports both direct config dict and file path
        mcp_config_dict = self._config.get_mcp_config_dict()
        server_name = list(mcp_config_dict.get('mcpServers', {}).keys())[0]
        server_config = mcp_config_dict['mcpServers'][server_name]

        # Create connector with custom SSE timeout (1 hour for long workflows)
        from mcp_use import MCPSession
        from mcp_use.connectors.http import HttpConnector

        connector = HttpConnector(
            base_url=server_config['url'],
            headers=server_config.get('headers'),
            auth_token=server_config.get('auth_token'),
            timeout=10,
            sse_read_timeout=3600,  # 1 hour for long-running workflows
        )

        self._mcp_session = MCPSession(connector)
        await self._mcp_session.initialize()
        self._logger.info(f"MCP session established: {server_name} (SSE timeout: 3600s)")

        # Initialize schema manager - supports both direct dict and file path
        cypher_adapter = MCPCypherAdapter(self._mcp_session)
        yaml_schema = self._config.get_yaml_schema()

        self._schema_manager = DynamicSchemaManager(
            cypher_server=cypher_adapter,
            yaml_schema=yaml_schema
        )
        await self._schema_manager.initialize_background()
        self._logger.info(f"Schema loaded: {len(self._schema_manager._reconciled_schema.get('nodes', {}))} node types")

        # Set tool context for Claude SDK fallback (enables in-process tools)
        # This must be done after schema_manager and mcp_session are initialized
        if hasattr(self._openai, 'set_tool_context'):
            self._openai.set_tool_context(self._schema_manager, self._mcp_session)
            self._logger.info("Tool context set for Claude SDK fallback")

        # Initialize CPG Observer Agent (if enabled) - monitors queries to identify CPG improvements
        if self._enable_observer:
            self._cpg_observer = CPGObserverAgent(
                mcp_session=self._mcp_session,
                openai_client=self._openai,
                llm_config=self._llm_config,
                memory_file="cpg_observer_memory.json"
            )
            self._logger.info("CPG Observer Agent initialized")

        # Initialize tool manager (for verification agent - uses main session)
        # Observer is passed to enable non-blocking query tracking
        self._tool_manager = ToolManager(
            self._mcp_session,
            self._schema_manager,
            observer=self._cpg_observer,
            agent_id="Verifier"
        )

        # Initialize session pool for parallel CoT agents
        # Use 1 hour SSE timeout for long-running workflows (default 5min is too short)
        self._session_pool = MCPSessionPool(mcp_config_dict, sse_timeout=3600)

        # Initialize agents with LLM config
        self._tot_orchestrator = ToTOrchestrator(
            self._openai, self._llm_config, self._config
        )
        self._verifier = VerificationAgent(
            self._tool_manager, self._openai, self._llm_config, self._config
        )

        # Initialize entity resolution agent (uses main session - only has fuzzy search)
        if self._config.entity_resolution_enabled:
            self._entity_resolver = EntityResolutionAgent(
                self._mcp_session, self._openai, self._llm_config, self._config
            )
            self._logger.info("Entity Resolution Agent initialized")

        self._initialized = True
        self._logger.info(f"Multi-Agent System initialized! (model: {self._llm_config.model}, temp: {self._llm_config.temperature}, cot_temp: {self._cot_llm_config.temperature})")

    def _create_cot_agent(self, cot_agent_id: str) -> CoTAgent:
        """Create a Chain-of-Thought agent with higher temperature for exploration"""
        return CoTAgent(
            self._tool_manager,
            self._openai,
            self._cot_llm_config,  # Use CoT-specific config with temp=0.3
            self._config,
            cot_agent_id
        )

    def _build_execution_phases(self, sub_queries: List[SubQuery]) -> List[List[SubQuery]]:
        """
        Build execution phases based on sub-query dependencies.

        Sub-queries with no dependencies go in Phase 1.
        Sub-queries that depend on Phase 1 queries go in Phase 2, etc.

        Returns:
            List of phases, where each phase is a list of SubQuery objects
        """
        # Build lookup by id
        query_by_id = {sq.id: sq for sq in sub_queries}
        remaining = set(sq.id for sq in sub_queries)
        completed = set()
        phases = []

        while remaining:
            # Find queries whose dependencies are all completed
            ready = []
            for sq_id in remaining:
                sq = query_by_id[sq_id]
                deps = set(sq.depends_on)
                if deps.issubset(completed):
                    ready.append(sq)

            if not ready:
                # Circular dependency or missing dependency - add remaining as final phase
                self._logger.warning(
                    f"Could not resolve dependencies for queries: {remaining}. "
                    "Adding to final phase."
                )
                ready = [query_by_id[sq_id] for sq_id in remaining]

            phases.append(ready)
            for sq in ready:
                completed.add(sq.id)
                remaining.discard(sq.id)

        return phases

    async def _execute_with_4_agent_workflow(
        self,
        subquery: SubQuery,
        context: str,
        resolved_entity_context: str
    ) -> Dict[str, Any]:
        """
        Execute a sub-query using the 4-agent LangGraph workflow.

        This method creates a temporary MCP session and runs the FourAgentWorkflow
        (Thinker → ThinkingValidator → CypherValidator → ExecutorVerifier).

        Args:
            subquery: The sub-query to execute
            context: Context from previous phases
            resolved_entity_context: Entity resolution context

        Returns:
            Dictionary with execution results compatible with the legacy format
        """
        workflow_id = f"4Agent-{subquery.id}"
        client = None

        try:
            # Create MCPClient for this workflow
            mcp_config_dict = self._config.get_mcp_config_dict()
            server_name = list(mcp_config_dict.get('mcpServers', {}).keys())[0]

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(mcp_config_dict, f)
                temp_config_path = f.name

            client = MCPClient.from_config_file(temp_config_path)
            session = await client.create_session(server_name)

            # Create tool manager with dedicated session
            tool_manager = ToolManager(
                session,
                self._schema_manager,
                observer=self._cpg_observer,
                agent_id=workflow_id
            )
            tool_manager.set_context(sub_query=subquery.query)

            # Build full context
            full_context = resolved_entity_context
            if context:
                full_context = f"{resolved_entity_context}\n\n{context}" if resolved_entity_context else context

            self._logger.info(f"{workflow_id}: Starting 4-agent workflow")

            # Create and run the 4-agent workflow
            workflow = FourAgentWorkflow(
                tool_manager=tool_manager,
                openai_client=self._openai,
                llm_config=self._cot_llm_config,  # Use same temp as CoT
                config=self._config,
                token_tracker=self._token_tracker
            )

            result = await workflow.run(
                sub_query=subquery,
                context=full_context,
                schema_info=None,  # Let workflow fetch as needed
                max_iterations=self._config.four_agent_max_iterations
            )

            # Convert findings to (Finding, VerificationResult) tuples
            # All findings from 4-agent workflow are considered verified since they
            # passed both validators
            verified_findings = []
            for finding in result.findings:
                verification = VerificationResult(
                    claim=finding.claim,
                    status=VerificationStatus.VERIFIED,
                    verified_evidence=finding.evidence,
                    explanation="Validated by 4-agent workflow (ThinkingValidator + CypherValidator)",
                    verification_query=finding.source_query,
                    correction_feedback=None,
                    suggested_query=None
                )
                verified_findings.append((finding, verification))

            return {
                'subquery_id': subquery.id,
                'findings_count': len(result.findings),
                'verified_findings': verified_findings,
                'execution_time_ms': result.execution_time_ms,
                'errors': result.errors,
                'iterations_used': result.iterations_used,
                # Trace data for debugging/analysis
                'validation_history': result.validation_history,
                'executed_queries': [
                    {
                        'query_id': eq.query_id,
                        'cypher_query': eq.cypher_query,
                        'result_count': eq.result_count,
                        'execution_time_ms': eq.execution_time_ms,
                        'error': eq.error
                    }
                    for eq in result.executed_queries
                ],
            }

        except Exception as e:
            self._logger.error(f"{workflow_id} error: {e}")
            return {
                'subquery_id': subquery.id,
                'findings_count': 0,
                'verified_findings': [],
                'execution_time_ms': 0,
                'errors': [str(e)],
                'iterations_used': 0,
                'validation_history': [],
                'executed_queries': [],
            }

        finally:
            if client:
                try:
                    await client.close_all_sessions()
                except Exception as e:
                    self._logger.debug(f"Session cleanup for {workflow_id}: {e}")

    def _extract_relevant_context(
        self,
        verified_findings: List[Tuple[Finding, VerificationResult]],
        next_phase_queries: List[SubQuery]
    ) -> str:
        """
        Use LLM to extract relevant context from verified findings for the next phase.

        Instead of blindly passing all evidence, we use LLM to extract only the
        specific information that the next phase's queries need.

        Args:
            verified_findings: Verified findings from the current phase
            next_phase_queries: Sub-queries that will execute in the next phase

        Returns:
            Extracted context string with relevant information
        """
        if not verified_findings or not next_phase_queries:
            return ""

        # Build a summary of findings with their evidence
        findings_summary = []
        for finding, verification in verified_findings:
            if verification.status == VerificationStatus.VERIFIED:
                finding_info = {
                    "claim": finding.claim,
                    "entities": [{"name": e.name, "type": e.entity_type} for e in finding.entities] if finding.entities else [],
                    "evidence": finding.evidence if finding.evidence else {}
                }
                findings_summary.append(finding_info)

        if not findings_summary:
            return ""

        # Build next phase queries summary
        next_queries = [{"id": sq.id, "query": sq.query, "focus": sq.focus} for sq in next_phase_queries]

        extraction_prompt = """You are a context extraction agent. Your job is to extract SPECIFIC, ACTIONABLE information
from verified findings that will help answer the next set of queries.

VERIFIED FINDINGS FROM PREVIOUS PHASE:
{findings_json}

NEXT PHASE QUERIES THAT NEED THIS CONTEXT:
{queries_json}

INSTRUCTIONS:
1. Analyze what specific information each next query needs
2. Extract ONLY the relevant data from the findings (specific names, values, relationships)
3. Format the extracted context so it's directly usable by the next phase
4. Include actual entity names, file paths, method names, property values - not generic descriptions
5. If a query needs numerical data (like counts, complexity values), include the actual numbers

OUTPUT FORMAT:
Return a structured context that the next phase can use. Be specific and include actual values.
Example: "Files found: Manager.cs, Program.cs, Worker.cs. Classes found: Manager, Program, WorkerA, WorkerB."
NOT: "Several files were found in the project."

EXTRACTED CONTEXT:"""

        try:
            response = self._openai.chat.completions.create(
                model=self._llm_config.model,
                temperature=0.0,  # Deterministic extraction
                messages=[
                    {"role": "system", "content": "You extract precise, specific information from findings for dependent queries."},
                    {"role": "user", "content": extraction_prompt.format(
                        findings_json=json.dumps(findings_summary, indent=2, default=str),
                        queries_json=json.dumps(next_queries, indent=2)
                    )}
                ]
            )
            extracted_context = response.choices[0].message.content.strip()
            self._logger.info(f"Extracted context for next phase:\n{extracted_context}")
            return extracted_context

        except Exception as e:
            self._logger.error(f"Context extraction failed: {e}")
            # Fallback to simple claims
            return "\n".join([f"- {f.claim}" for f, v in verified_findings if v.status == VerificationStatus.VERIFIED])

    async def run(self, user_query: str) -> ProductionResponse:
        """
        Run the multi-agent system on a query.

        Args:
            user_query: User's natural language question about the codebase

        Returns:
            ProductionResponse with answer, citations, and metadata
        """
        if not self._initialized:
            await self.initialize()

        # Clear previous execution traces
        self._last_execution_traces = []

        # SECURITY: Validate user input before processing
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

        # Sanitize input (remove hidden instructions, etc.)
        sanitized_query = self._input_validator.sanitize(user_query)
        if sanitized_query != user_query:
            self._logger.info("User input was sanitized")

        start_time = time.time()

        # OBSERVER: Set the current user query context for observation tracking
        if self._cpg_observer:
            self._cpg_observer.set_current_query(sanitized_query)

        print(f"\n{'='*70}")
        if self._config.use_4_agent_team:
            print("ToT/4-AGENT TEAM SYSTEM (Thinker → Validators → Executor)")
        else:
            print("ToT/CoT MULTI-AGENT SYSTEM")
        print(f"{'='*70}")
        print(f"Query: {sanitized_query}")

        # Step 1: Entity Resolution FIRST (identify entity types before decomposition)
        effective_query = sanitized_query
        resolved_entity_context = ""  # Context to pass to decomposition AND CoT agents
        if self._config.entity_resolution_enabled and self._entity_resolver:
            print(f"\n[RESOLVE] STEP 1: Resolving entity types...")
            resolution_result = await self._entity_resolver.execute(sanitized_query)
            if resolution_result.has_issues:
                print(f"   Found {len(resolution_result.corrections)} entity name issues:")
                for correction in resolution_result.corrections:
                    print(f"   - '{correction.original_term}' -> '{correction.suggested_name}' ({correction.issue_type})")
                if resolution_result.corrected_query:
                    effective_query = resolution_result.corrected_query
                    print(f"   Corrected query: {effective_query}")
            else:
                print(f"   No entity name issues found ({resolution_result.execution_time_ms}ms)")

            # Build resolved entity context (for BOTH decomposition AND CoT agents)
            if resolution_result.resolved_entities:
                print(f"   Resolved {len(resolution_result.resolved_entities)} entities:")
                context_lines = ["ENTITY CONTEXT (use these hints for correct queries):"]
                for entity in resolution_result.resolved_entities:
                    print(f"   - {entity.name} is a {entity.entity_type}: {entity.query_hint}")
                    context_lines.append(f"- {entity.name} is a {entity.entity_type}. {entity.query_hint}")
                resolved_entity_context = "\n".join(context_lines)

        # Step 2: Decompose query (WITH entity context so sub-queries are correct)
        print(f"\n[DECOMPOSE] STEP 2: Decomposing query...")
        if resolved_entity_context:
            print(f"   Using entity context for decomposition")
        decomposition = self._tot_orchestrator.decompose_query(effective_query, resolved_entity_context)

        # SECURITY: Limit sub-queries to prevent cost explosion attacks
        original_count = len(decomposition.sub_queries)
        if original_count > self._config.max_sub_queries:
            self._logger.warning(
                f"Sub-query limit exceeded: {original_count} > {self._config.max_sub_queries}. "
                "Truncating to prevent resource exhaustion."
            )
            # Keep highest priority sub-queries (sorted by priority)
            # Create new object since QueryDecomposition is frozen (immutable for parallel safety)
            truncated_queries = sorted(
                decomposition.sub_queries, key=lambda sq: sq.priority
            )[:self._config.max_sub_queries]
            decomposition = QueryDecomposition(
                original_query=decomposition.original_query,
                sub_queries=truncated_queries,
                reasoning=decomposition.reasoning
            )
            print(f"   Sub-queries: {len(decomposition.sub_queries)} (truncated from {original_count})")
        else:
            print(f"   Sub-queries: {len(decomposition.sub_queries)}")
        for i, sq in enumerate(decomposition.sub_queries):
            print(f"   {i+1}. [{sq.focus}] {sq.query}")

        # Step 3: Build execution phases based on dependencies
        print(f"\n[PHASES] STEP 3: Building execution phases...")
        phases = self._build_execution_phases(decomposition.sub_queries)
        print(f"   Execution phases: {len(phases)}")
        for phase_idx, phase_queries in enumerate(phases):
            phase_ids = [sq.id for sq in phase_queries]
            print(f"   Phase {phase_idx + 1}: Sub-queries {phase_ids}")

        # Execute phases sequentially, with parallel execution within each phase
        verified_findings: List[Tuple[Finding, VerificationResult]] = []
        phase_context = ""  # Context from previous phases (verified findings)

        for phase_idx, phase_queries in enumerate(phases):
            print(f"\n[PHASE {phase_idx + 1}] Executing {len(phase_queries)} sub-queries...")

            # Dynamic parallel workers: min(configured max, queries in this phase)
            max_workers_for_phase = min(self._config.max_parallel_workers, len(phase_queries))
            worker_semaphore = asyncio.Semaphore(max_workers_for_phase)
            print(f"   Parallel workers for this phase: {max_workers_for_phase}")

            async def execute_and_verify(subquery: SubQuery, agent_idx: int, context: str):
                """Execute a CoT agent and verify its findings in one task."""
                async with worker_semaphore:
                    cot_agent_id = f"CoT-{subquery.id}"
                    client = None
                    try:
                        # Create MCPClient directly in this task
                        mcp_config_dict = self._config.get_mcp_config_dict()
                        server_name = list(mcp_config_dict.get('mcpServers', {}).keys())[0]

                        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                            json.dump(mcp_config_dict, f)
                            temp_config_path = f.name

                        client = MCPClient.from_config_file(temp_config_path)
                        session = await client.create_session(server_name)

                        # Create tool manager with dedicated session
                        tool_manager = ToolManager(
                            session,
                            self._schema_manager,
                            observer=self._cpg_observer,
                            agent_id=cot_agent_id
                        )
                        tool_manager.set_context(sub_query=subquery.query)

                        # Build full context: entity context + phase context
                        full_context = resolved_entity_context
                        if context:
                            full_context = f"{resolved_entity_context}\n\n{context}" if resolved_entity_context else context

                        # Log context being passed
                        self._logger.info(f"{cot_agent_id}: Context passed =\n{full_context if full_context else 'NONE'}")

                        # Execute CoT agent (with higher temperature for exploration)
                        cot_agent = CoTAgent(
                            tool_manager,
                            self._openai,
                            self._cot_llm_config,  # temp=0.3
                            self._config,
                            cot_agent_id
                        )
                        cot_response = await cot_agent.execute(subquery, full_context)

                        # Verify findings with feedback loop (if enabled)
                        verified = []
                        max_correction_retries = 3  # Allow CoT to retry with verifier feedback

                        if self._config.verification_enabled and cot_response.findings:
                            # Create verifier with same session
                            verifier = VerificationAgent(
                                tool_manager, self._openai, self._llm_config, self._config
                            )

                            for finding_idx, finding in enumerate(cot_response.findings):
                                self._logger.info(f"[{cot_agent_id}] Verifying finding {finding_idx + 1}/{len(cot_response.findings)}")
                                self._logger.info(f"  Finding claim: {finding.claim}")
                                self._logger.info(f"  Finding source_query: {finding.source_query}")

                                current_finding = finding
                                correction_context = ""

                                for retry in range(max_correction_retries + 1):
                                    self._logger.info(f"[{cot_agent_id}] Verification attempt {retry + 1}/{max_correction_retries + 1}")

                                    ver_resp = await verifier.execute(current_finding)

                                    self._logger.info(f"[{cot_agent_id}] Verifier returned: status={ver_resp.result.status.value}")
                                    self._logger.info(f"  Correction feedback: {ver_resp.result.correction_feedback}")
                                    self._logger.info(f"  Suggested query: {ver_resp.result.suggested_query}")

                                    # Check if verifier requests correction
                                    if ver_resp.result.status == VerificationStatus.NEEDS_CORRECTION and retry < max_correction_retries:
                                        # Build correction feedback for CoT agent
                                        feedback = ver_resp.result.correction_feedback or "Query logic needs correction"
                                        suggested = ver_resp.result.suggested_query or ""

                                        correction_context = f"""
VERIFIER FEEDBACK (Attempt {retry + 1}):
Issue: {feedback}
{f'Suggested Query: {suggested}' if suggested else ''}

Please retry with the corrected approach."""

                                        self._logger.info(f"[{cot_agent_id}] NEEDS_CORRECTION - Retrying with feedback")
                                        self._logger.info(f"  Full feedback context:\n{correction_context}")

                                        # Re-run CoT agent with correction context
                                        retry_context = f"{full_context}\n\n{correction_context}" if full_context else correction_context
                                        retry_response = await cot_agent.execute(subquery, retry_context)

                                        self._logger.info(f"[{cot_agent_id}] Retry produced {len(retry_response.findings)} findings")

                                        # Use the new finding for next verification
                                        if retry_response.findings:
                                            current_finding = retry_response.findings[0]
                                            self._logger.info(f"  New finding claim: {current_finding.claim}")
                                            self._logger.info(f"  New finding source_query: {current_finding.source_query}")
                                        else:
                                            self._logger.info(f"[{cot_agent_id}] No new findings from retry, keeping current result")
                                            break
                                    else:
                                        # Either verified, not_verified, or max retries reached
                                        if retry >= max_correction_retries:
                                            self._logger.info(f"[{cot_agent_id}] Max retries reached, accepting current result")
                                        else:
                                            self._logger.info(f"[{cot_agent_id}] Verification complete: {ver_resp.result.status.value}")
                                        break

                                verified.append((current_finding, ver_resp.result))
                                self._logger.info(f"[{cot_agent_id}] Final result for finding {finding_idx + 1}: {ver_resp.result.status.value}")
                        else:
                            # Skip verification
                            for finding in cot_response.findings:
                                verified.append((finding, VerificationResult(
                                    claim=finding.claim,
                                    status=VerificationStatus.VERIFIED,
                                    verified_evidence={},
                                    explanation="Verification skipped",
                                    correction_feedback=None,
                                    suggested_query=None
                                )))

                        return {
                            'subquery_id': subquery.id,
                            'findings_count': len(cot_response.findings),
                            'verified_findings': verified,
                            'execution_time_ms': cot_response.execution_time_ms,
                            'errors': cot_response.errors
                        }

                    finally:
                        if client:
                            try:
                                await client.close_all_sessions()
                            except Exception as e:
                                self._logger.debug(f"Session cleanup for {cot_agent_id}: {e}")

            # Execute all queries in this phase in parallel
            # Use 4-agent workflow if feature flag is enabled, otherwise use legacy CoT+Verifier
            if self._config.use_4_agent_team:
                # Use 4-Agent LangGraph Workflow
                print(f"   Using 4-Agent Team workflow")
                tasks = [
                    self._execute_with_4_agent_workflow(sq, phase_context, resolved_entity_context)
                    for sq in phase_queries
                ]
            else:
                # Use legacy CoT + Verifier
                tasks = [
                    execute_and_verify(sq, idx, phase_context)
                    for idx, sq in enumerate(phase_queries)
                ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect results and build context for next phase
            phase_findings: List[Tuple[Finding, VerificationResult]] = []
            for result in results:
                if isinstance(result, Exception):
                    agent_type = "4Agent" if self._config.use_4_agent_team else "CoT"
                    print(f"   {agent_type} Agent ERROR: {result}")
                else:
                    sq_id = result['subquery_id']
                    findings_count = result['findings_count']
                    verified_count = sum(
                        1 for _, v in result['verified_findings']
                        if v.status == VerificationStatus.VERIFIED
                    )
                    if self._config.use_4_agent_team:
                        iterations = result.get('iterations_used', 0)
                        print(f"   4Agent-{sq_id}: {findings_count} findings, {verified_count} verified, {iterations} iterations ({result['execution_time_ms']}ms)")
                    else:
                        print(f"   CoT-{sq_id}: {findings_count} findings, {verified_count} verified ({result['execution_time_ms']}ms)")

                    # Add to overall verified findings
                    verified_findings.extend(result['verified_findings'])
                    # Collect this phase's findings for context extraction
                    phase_findings.extend(result['verified_findings'])

                    # Store execution trace for debugging/analysis (4-agent only)
                    if self._config.use_4_agent_team:
                        self._last_execution_traces.append({
                            'subquery_id': sq_id,
                            'iterations_used': result.get('iterations_used', 0),
                            'findings_count': findings_count,
                            'verified_count': verified_count,
                            'execution_time_ms': result.get('execution_time_ms', 0),
                            'validation_history': result.get('validation_history', []),
                            'executed_queries': result.get('executed_queries', []),
                            'errors': result.get('errors', [])
                        })

            # Build context for next phase using LLM-based extraction
            if phase_findings and phase_idx + 1 < len(phases):
                next_phase_queries = phases[phase_idx + 1]
                print(f"   Extracting relevant context for Phase {phase_idx + 2}...")
                extracted_context = self._extract_relevant_context(phase_findings, next_phase_queries)
                if extracted_context:
                    print(f"   [EXTRACTED CONTEXT]:\n{extracted_context}\n   [END CONTEXT]")
                    new_context = f"VERIFIED CONTEXT FROM PHASE {phase_idx + 1}:\n{extracted_context}"
                    phase_context = f"{phase_context}\n\n{new_context}" if phase_context else new_context

        # Step 4: Build citations from verified findings
        print(f"\n[CITATIONS] STEP 4: Building citations from {len(verified_findings)} findings...")
        citations: List[Citation] = []
        for finding, verification in verified_findings:
            citation = self._build_citation(finding, verification)
            citations.append(citation)

        # Step 5: Synthesize answer
        print(f"\n[SYNTHESIS] STEP 5: Synthesizing final answer...")
        final_answer = self._tot_orchestrator.synthesize_answer(sanitized_query, verified_findings)

        elapsed = time.time() - start_time
        execution_time_ms = int(elapsed * 1000)

        # Build production response
        verified_count = sum(1 for c in citations if c.verification_status == VerificationStatus.VERIFIED)
        unverified_count = len(citations) - verified_count

        production_response = ProductionResponse(
            answer=final_answer.answer,
            confidence=final_answer.confidence,
            citations=citations,
            verified_count=verified_count,
            unverified_count=unverified_count,
            token_usage=self._token_tracker,
            execution_time_ms=execution_time_ms,
            sub_queries_count=len(decomposition.sub_queries),
            llm_calls_count=self._token_tracker.call_count,
            original_query=sanitized_query
        )

        # Print results for CLI usage
        self._print_results(production_response)

        # OBSERVER: Save memory after each run for persistence
        if self._cpg_observer:
            self._cpg_observer.save_memory()
            stats = self._cpg_observer.get_stats()
            self._logger.info(f"CPG Observer: {stats['total_observations']} observations recorded")

        return production_response

    # =========================================================================
    # CPG OBSERVER PUBLIC API
    # =========================================================================

    async def get_observer_report(self, force: bool = False) -> Optional[ObserverReport]:
        """
        Generate and return a CPG improvement report from the observer.

        Args:
            force: If True, generate report even with few observations
        Returns:
            ObserverReport with identified issues and improvement suggestions
        """
        if not self._cpg_observer:
            self._logger.warning("CPG Observer is not enabled")
            return None
        return await self._cpg_observer.analyze_and_report(force=force)

    def get_observer_stats(self) -> Optional[Dict[str, Any]]:
        """Get current observer statistics"""
        if not self._cpg_observer:
            return None
        return self._cpg_observer.get_stats()

    def print_observer_report(self):
        """Print the latest observer report to console"""
        if not self._cpg_observer:
            print("CPG Observer is not enabled")
            return
        self._cpg_observer.print_report()

    async def explore_cpg(self, question: str) -> str:
        """
        Use the observer to explore the CPG and answer a question.

        Args:
            question: Natural language question about the CPG structure
        Returns:
            Answer from the observer's exploration
        """
        if not self._cpg_observer:
            return "CPG Observer is not enabled"
        return await self._cpg_observer.explore_cpg(question)

    @property
    def observer(self) -> Optional[CPGObserverAgent]:
        """Direct access to the CPG Observer Agent (if enabled)"""
        return self._cpg_observer

    @property
    def last_execution_traces(self) -> List[Dict[str, Any]]:
        """
        Get execution traces from the last run.

        Returns list of trace dicts per sub-query, each containing:
        - subquery_id: The sub-query identifier
        - validation_history: List of validation attempts with reasoning
        - executed_queries: List of Cypher queries executed with results
        - iterations_used: Number of thinker iterations
        """
        return self._last_execution_traces

    async def shutdown(self) -> None:
        """
        Gracefully shutdown the multi-agent system and cleanup resources.

        This method should be called when done using the system to prevent
        cancel scope errors from MCP session cleanup during garbage collection.
        Errors during cleanup are suppressed since they're benign - the sessions
        will close anyway when the process ends.
        """
        self._logger.debug("Shutting down Multi-Agent System...")

        # Close per-agent SDK sessions (if fallback was used)
        if self._openai and hasattr(self._openai, 'close_all_agent_sessions'):
            try:
                await self._openai.close_all_agent_sessions()
            except Exception as e:
                self._logger.debug(f"Per-agent session cleanup (suppressed): {e}")

        # Release all sessions from the pool
        if self._session_pool:
            try:
                await self._session_pool.release_all()
            except Exception as e:
                self._logger.debug(f"Session pool cleanup (suppressed): {e}")

        # Close main MCP client session
        # Note: We don't explicitly close because MCP sessions have async context
        # managers that must be exited in the same task they were created in.
        # Just clear references to allow garbage collection.
        self._mcp_session = None
        self._mcp_client = None

        self._initialized = False
        self._logger.debug("Multi-Agent System shutdown complete")

    def _build_citation(self, finding: Finding, verification: VerificationResult) -> Citation:
        """Build a Citation from a Finding and its VerificationResult"""
        # Extract primary entity info if available
        entity_name = None
        entity_type = None
        source_file = None
        source_line = None

        if finding.entities:
            primary_entity = finding.entities[0]
            entity_name = primary_entity.name
            entity_type = primary_entity.entity_type
            source_file = primary_entity.file_path
            # Try to get line number from properties
            if primary_entity.properties:
                source_line = primary_entity.properties.get('lineNumber') or primary_entity.properties.get('line')

        # Build human-readable source location
        source_location = None
        if source_file:
            source_location = source_file
            if source_line:
                source_location = f"{source_file}:{source_line}"

        return Citation(
            claim=finding.claim,
            source_file=source_file,
            source_line=source_line,
            source_location=source_location,
            entity_name=entity_name,
            entity_type=entity_type,
            evidence=finding.evidence,
            verification_status=verification.status,
            verification_explanation=verification.explanation,
            discovery_query=finding.source_query,
            verification_query=verification.verification_query,
            cot_agent_id=finding.cot_agent_id,
            confidence=finding.confidence
        )

    def _print_results(self, response: ProductionResponse) -> None:
        """Print results to console for CLI usage"""
        print(f"\n{'='*70}")
        print(f"FINAL ANSWER ({response.execution_time_ms / 1000:.2f}s)")
        print(f"{'='*70}")
        print(response.answer)

        print(f"\n{'='*70}")
        print("CITATIONS")
        print(f"{'='*70}")
        for i, citation in enumerate(response.citations, 1):
            status_icon = "[OK]" if citation.verification_status == VerificationStatus.VERIFIED else "[X]"
            print(f"\n{i}. {status_icon} {citation.claim}")
            if citation.source_location:
                print(f"   Location: {citation.source_location}")
            if citation.entity_name:
                print(f"   Entity: {citation.entity_name} ({citation.entity_type})")
            if citation.verification_explanation:
                print(f"   Verification: {citation.verification_explanation}")
            if citation.discovery_query:
                print(f"   Discovery Query: {citation.discovery_query}")
            if citation.verification_query:
                print(f"   Verification Query: {citation.verification_query}")

        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"{'='*70}")
        print(f"Time: {response.execution_time_ms / 1000:.2f}s")
        print(f"Sub-queries: {response.sub_queries_count}")
        print(f"Total citations: {len(response.citations)}")
        print(f"Verified: {response.verified_count}/{len(response.citations)}")
        print(f"Confidence: {response.confidence.value}")

        # Token usage transparency
        if response.token_usage:
            print(f"\n{'='*70}")
            print("TOKEN USAGE")
            print(f"{'='*70}")
            print(f"Total tokens: {response.token_usage.total_tokens:,}")
            print(f"  Prompt tokens: {response.token_usage.total_prompt_tokens:,}")
            print(f"  Completion tokens: {response.token_usage.total_completion_tokens:,}")
            print(f"LLM calls: {response.token_usage.call_count}")
            if response.token_usage.by_agent_role:
                print(f"By role:")
                for role, tokens in response.token_usage.by_agent_role.items():
                    print(f"  {role}: {tokens:,} tokens")


__all__ = ['MultiAgentCoT']

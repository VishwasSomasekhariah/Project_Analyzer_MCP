"""
Calls individual agent MCP tools in the order specified by a RoutingPlan.
Mirrors the session/connector setup from properly_fixed_comparative_analysis.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, List

from mcp_use import MCPSession
from mcp_use.connectors.http import HttpConnector

from dataset_pipeline.models import CitationRecord, HopRecord, PlanExecutionTrace, RoutingPlan

logger = logging.getLogger(__name__)


def _make_session(mcp_config_file: str) -> MCPSession:
    with open(mcp_config_file) as f:
        config = json.load(f)
    server = config["mcpServers"]["mcp-analysis-server"]
    connector = HttpConnector(
        base_url=server["url"],
        headers=server.get("headers"),
        auth_token=server.get("auth_token"),
        timeout=10,
        sse_read_timeout=3600,
    )
    return MCPSession(connector)


def _citation_id(agent: str, file_path: str, entity: str) -> str:
    raw = f"{agent}:{file_path}:{entity}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _extract_citations(agent: str, hop_number: int, raw_results: list) -> List[CitationRecord]:
    citations = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata", item)
        file_path = meta.get("file_path", meta.get("path", ""))
        entity = meta.get("name", meta.get("function_name", meta.get("node_id", "")))
        if not file_path and not entity:
            continue
        citations.append(CitationRecord(
            citation_id=_citation_id(agent, file_path, entity),
            agent=agent,
            file_path=file_path,
            entity_name=entity,
            start_line=int(meta.get("start_line", 0)),
            end_line=int(meta.get("end_line", 0)),
            evidence_text=str(item.get("content", item.get("scoring_text", "")))[:300],
            relevance_score=float(meta.get("relevance_score", meta.get("score", 0.0))),
        ))
    return citations


def _parse_tool_result(result: Any) -> dict:
    content = result.content[0] if isinstance(result.content, list) else result.content
    text = content.text if hasattr(content, "text") else str(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"status": "success", "ai_response": text, "raw_results": []}


async def _call_with_retry(mcp_config_file: str, tool: str, params: dict, retries: int = 3) -> Any:
    # Fresh session per attempt — a dropped SSE connection cannot be reused
    delay = 30
    for attempt in range(retries):
        session = None
        try:
            session = _make_session(mcp_config_file)
            await session.initialize()
            return await session.call_tool(tool, params)
        except Exception as e:
            if attempt == retries - 1:
                raise
            logger.warning(f"Tool call {tool} failed (attempt {attempt + 1}): {e} — retrying in {delay}s")
            await asyncio.sleep(delay)
            delay *= 2
        finally:
            if session:
                try:
                    await session.disconnect()
                except Exception:
                    pass


async def _short_call(mcp_config_file: str, tool: str, params: dict, attempts: int = 3) -> Any:
    """One short-lived MCP call with retry on transient connection errors.

    Used for submit_job / check_job_status / cancel_job — each completes in
    milliseconds, so a fresh session per attempt is cheap and robust against a
    dropped connection (and never re-runs the underlying long job).
    """
    delay = 5
    for attempt in range(attempts):
        session = None
        try:
            session = _make_session(mcp_config_file)
            await session.initialize()
            return await session.call_tool(tool, params)
        except Exception as e:
            if attempt == attempts - 1:
                raise
            logger.warning(f"{tool} call failed (attempt {attempt + 1}): {e} — retrying in {delay}s")
            await asyncio.sleep(delay)
            delay *= 2
        finally:
            if session:
                try:
                    await session.disconnect()
                except Exception:
                    pass


async def _call_job(
    mcp_config_file: str,
    tool: str,
    params: dict,
    poll_interval_s: int = 20,
    deadline_s: int = 7200,
) -> dict:
    """Submit `tool` as a background job, then poll until it finishes.

    No SSE connection is held open during the long-running work — each poll is a
    fresh millisecond-long call. Returns the original tool result dict (the same
    shape the synchronous tool would have returned). Raises on failure/timeout so
    the caller's per-hop try/except records the error exactly as before.
    """
    # A per-call idempotency key makes the submit retry-safe: if a submit's
    # response is lost and _short_call retries, the server returns the same job
    # instead of starting a duplicate. A fresh uuid per call means no cross-call
    # result caching.
    idem = uuid.uuid4().hex
    submit = _parse_tool_result(await _short_call(
        mcp_config_file,
        "submit_job",
        {"tool_name": tool, "params": params, "idempotency_key": idem},
    ))
    job_id = submit.get("job_id")
    if not job_id:
        raise RuntimeError(f"submit_job failed for {tool}: {submit.get('error', submit)}")

    deadline = time.time() + deadline_s
    not_found = 0
    while time.time() < deadline:
        await asyncio.sleep(poll_interval_s)
        st = _parse_tool_result(
            await _short_call(mcp_config_file, "check_job_status", {"job_id": job_id})
        )
        status = st.get("status")
        if status == "succeeded":
            return st.get("result") or {}
        if status in ("failed", "cancelled", "lost"):
            raise RuntimeError(f"job {job_id} ({tool}) {status}: {st.get('error')}")
        if status == "not_found":
            not_found += 1
            if not_found >= 3:
                raise RuntimeError(f"job {job_id} ({tool}) not found — server may have lost it")
        else:
            not_found = 0  # queued / running — keep polling

    # Deadline exceeded — best-effort cancel, then fail.
    try:
        await _short_call(mcp_config_file, "cancel_job", {"job_id": job_id})
    except Exception:
        pass
    raise TimeoutError(f"job {job_id} ({tool}) exceeded deadline of {deadline_s}s")


class AgentRunner:
    def __init__(
        self,
        mcp_config_file: str,
        project_path: str,
        project_name: str,
        collection_name: str,
        qdrant_config: str,
        neo4j_config: str,
        mappings_path: str,
        queries_path: str,
        max_results: int = 5,
        use_async_jobs: bool = True,
        poll_interval_s: int = 20,
        job_deadline_s: int = 7200,
    ) -> None:
        self.mcp_config_file = mcp_config_file
        self.project_path = project_path
        self.project_name = project_name
        self.collection_name = collection_name
        self.qdrant_config = qdrant_config
        self.neo4j_config = neo4j_config
        self.mappings_path = mappings_path
        self.queries_path = queries_path
        self.max_results = max_results
        self.use_async_jobs = use_async_jobs
        self.poll_interval_s = poll_interval_s
        self.job_deadline_s = job_deadline_s

    async def execute_plan(
        self,
        plan: RoutingPlan,
        original_query: str,
    ) -> PlanExecutionTrace:
        trace_id = f"{plan.query_id}_plan{plan.plan_index}"
        start = time.time()

        try:
            hops: List[HopRecord] = []
            all_citations: List[CitationRecord] = []

            for step in plan.step_instructions:
                instruction = step.what_to_look_for or original_query
                hop_number = len(hops) + 1
                agent = step.agent

                try:
                    raw = await self._call_agent(agent, instruction)
                    summary = str(raw.get("ai_response", raw.get("response", "")))[:500]
                    raw_results = raw.get("raw_results", [])
                    citations = _extract_citations(agent, hop_number, raw_results)
                    all_citations.extend(citations)
                    hops.append(HopRecord(
                        hop_number=hop_number,
                        agent=agent,
                        instruction=instruction,
                        raw_result_summary=summary,
                        citation_ids=[c.citation_id for c in citations],
                    ))
                except Exception as e:
                    logger.warning(f"Hop {hop_number} ({agent}) failed for {trace_id}: {e}")
                    hops.append(HopRecord(
                        hop_number=hop_number,
                        agent=agent,
                        instruction=instruction,
                        raw_result_summary=f"ERROR: {e}",
                        citation_ids=[],
                    ))

            # Deduplicate citations by citation_id
            seen_ids: set = set()
            unique_citations = []
            for c in all_citations:
                if c.citation_id not in seen_ids:
                    seen_ids.add(c.citation_id)
                    unique_citations.append(c)

            elapsed = int((time.time() - start) * 1000)
            return PlanExecutionTrace(
                trace_id=trace_id,
                query_id=plan.query_id,
                plan_id=plan.plan_id,
                status="success",
                hops=hops,
                citations=unique_citations,
                execution_time_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"Plan execution failed for {trace_id}: {e}")
            return PlanExecutionTrace(
                trace_id=trace_id,
                query_id=plan.query_id,
                plan_id=plan.plan_id,
                status="error",
                execution_time_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    async def _call_agent(self, agent: str, instruction: str) -> dict:
        if agent == "pageindex":
            tool, params = "query_pageindex_only", {
                "query": instruction,
                "project_path": self.project_path,
                "mcts_iterations": 20,
                "config": self.qdrant_config,
                "output_format": "json",
            }
        elif agent == "vector":
            tool, params = "query_vector_only", {
                "query": instruction,
                "collection_name": self.collection_name,
                "max_results": self.max_results,
                "output_format": "json",
                "vector_db": "qdrant",
                "config": self.qdrant_config,
            }
        elif agent == "graph":
            tool, params = "query_cpg_rag", {
                "user_query": instruction,
                "project_name": self.project_name,
                "config_path": self.neo4j_config,
                "project_path": self.project_path,
                "mappings_path": self.mappings_path,
                "queries_path": self.queries_path,
                "max_results": 100,
                "max_agent_iterations": 25,
                "parallel_agents": False,
                "use_4_agent_team": True,
                "four_agent_max_iterations": 3,
            }
        else:
            raise ValueError(f"Unknown agent: {agent}")

        # Async-job path: submit + poll (no long-held SSE connection). Falls back
        # to the legacy single long call when use_async_jobs is disabled.
        if self.use_async_jobs:
            return await _call_job(
                self.mcp_config_file, tool, params,
                poll_interval_s=self.poll_interval_s,
                deadline_s=self.job_deadline_s,
            )
        return _parse_tool_result(await _call_with_retry(self.mcp_config_file, tool, params))

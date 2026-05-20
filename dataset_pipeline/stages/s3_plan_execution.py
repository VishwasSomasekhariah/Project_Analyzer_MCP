"""
Stage 3 — Plan Execution.
Reads routing_plans.jsonl + raw_queries.jsonl, executes each plan via direct
agent tool calls, writes execution_traces.jsonl.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dataset_pipeline.config import PipelineConfig
from dataset_pipeline.execution.agent_runner import AgentRunner
from dataset_pipeline.execution.checkpoint import CheckpointManager
from dataset_pipeline.execution.sufficiency_checker import check_sufficiency
from dataset_pipeline.models import RoutingPlan, StepInstruction
from dataset_pipeline.utils.io import append_jsonl, iter_jsonl, read_jsonl

logger = logging.getLogger(__name__)

_GENPOD = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _GENPOD not in sys.path:
    sys.path.insert(0, _GENPOD)


def _make_llm_service():
    from src.core.resilient_llm_service import ResilientLLMService
    return ResilientLLMService()


class PlanExecutionStage:
    PLANS_FILE = "routing_plans.jsonl"
    QUERIES_FILE = "raw_queries.jsonl"
    OUTPUT_FILE = "execution_traces.jsonl"

    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.plans_path = os.path.join(cfg.data_dir, self.PLANS_FILE)
        self.queries_path = os.path.join(cfg.data_dir, self.QUERIES_FILE)
        self.output_path = os.path.join(cfg.data_dir, self.OUTPUT_FILE)

    async def run(self) -> None:
        plans_raw = read_jsonl(self.plans_path)
        if not plans_raw:
            raise RuntimeError(f"Stage 3: no plans found at {self.plans_path} — run Stage 2 first")

        # Build query text map
        query_map: dict = {}
        for rec in iter_jsonl(self.queries_path):
            query_map[rec["query_id"]] = rec["query"]

        checkpoint = CheckpointManager(self.cfg.checkpoint_dir, name="execution")
        if self.cfg.resume:
            logger.info(f"Stage 3: resuming — {checkpoint.completed_count} traces already done")

        runner = AgentRunner(
            mcp_config_file=self.cfg.mcp_config_file,
            project_path=self.cfg.repo_path,
            project_name=self.cfg.project_name,
            collection_name=self.cfg.collection_name,
            qdrant_config=self.cfg.qdrant_config,
            neo4j_config=self.cfg.neo4j_config,
            mappings_path=self.cfg.mappings_path,
            queries_path=self.cfg.queries_path,
            max_results=self.cfg.max_results,
        )
        llm = _make_llm_service()

        total = 0
        for i, rec in enumerate(plans_raw):
            plan = _dict_to_plan(rec)
            original_query = query_map.get(plan.query_id, "")

            if not original_query:
                logger.warning(f"No query text for {plan.query_id}, skipping")
                continue

            if self.cfg.resume and checkpoint.is_done(plan.plan_id):
                continue

            logger.info(f"Stage 3: executing {plan.plan_id} [{i+1}/{len(plans_raw)}]")

            try:
                trace = await runner.execute_plan(plan, original_query)
                trace = await check_sufficiency(original_query, trace, llm)
                append_jsonl(self.output_path, trace)
                checkpoint.mark_done(plan.plan_id)
                total += 1
            except Exception as e:
                logger.error(f"Execution failed for {plan.plan_id}: {e}")
                checkpoint.mark_failed(plan.plan_id)

            # Brief pause between queries to avoid overloading MCP server
            if (i + 1) % self.cfg.batch_size == 0:
                logger.info(f"Stage 3: batch complete ({i+1} processed), pausing 5s")
                await asyncio.sleep(5)

        logger.info(
            f"Stage 3 complete: {total} new traces written. "
            f"Checkpoint: {checkpoint.completed_count} done, {checkpoint.failed_count} failed"
        )

    def assert_output(self) -> None:
        records = read_jsonl(self.output_path)
        assert records, "Stage 3 produced no output"
        assert len(records) <= len(read_jsonl(self.plans_path)), \
            "More traces than plans — something went wrong"
        logger.info(f"Stage 3 assertions passed: {len(records)} traces")


def _dict_to_plan(rec: dict) -> RoutingPlan:
    steps = []
    for s in rec.get("step_instructions", []):
        if isinstance(s, dict):
            steps.append(StepInstruction(
                agent=s.get("agent", "pageindex"),
                what_to_look_for=s.get("what_to_look_for", ""),
            ))
    return RoutingPlan(
        plan_id=rec["plan_id"],
        query_id=rec["query_id"],
        agent_sequence=rec.get("agent_sequence", []),
        step_instructions=steps,
        llm_reasoning=rec.get("llm_reasoning", ""),
        plan_index=rec.get("plan_index", 0),
    )

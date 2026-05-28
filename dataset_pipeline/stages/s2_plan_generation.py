"""
Stage 2 — Multi-Plan Generation.
Reads raw_queries.jsonl, generates N routing plans per query, writes routing_plans.jsonl.
"""

from __future__ import annotations

import logging
import os
import sys

from dataset_pipeline.config import PipelineConfig
from dataset_pipeline.models import RawQuery, RoutingPlan
from dataset_pipeline.planning.plan_generator import generate_plans_for_query
from dataset_pipeline.utils.io import append_jsonl, iter_jsonl, read_jsonl, write_jsonl

logger = logging.getLogger(__name__)

_GENPOD = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _GENPOD not in sys.path:
    sys.path.insert(0, _GENPOD)


def _make_llm_service():
    from src.core.resilient_llm_service import ResilientLLMService
    return ResilientLLMService()


class PlanGenerationStage:
    INPUT_FILE = "raw_queries.jsonl"
    OUTPUT_FILE = "routing_plans.jsonl"

    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.input_path = os.path.join(cfg.data_dir, self.INPUT_FILE)
        self.output_path = os.path.join(cfg.data_dir, self.OUTPUT_FILE)

    async def run(self) -> None:
        raw_records = read_jsonl(self.input_path)
        if not raw_records:
            raise RuntimeError(f"Stage 2: no input found at {self.input_path} — run Stage 1 first")

        # Resume: find already-planned query_ids
        done_query_ids: set = set()
        if self.cfg.resume and os.path.exists(self.output_path):
            for rec in iter_jsonl(self.output_path):
                done_query_ids.add(rec.get("query_id", ""))
            logger.info(f"Stage 2: resuming — {len(done_query_ids)} queries already planned")

        llm = _make_llm_service()
        total = 0

        for rec in raw_records:
            qid = rec.get("query_id", "")
            if qid in done_query_ids:
                continue

            raw_query = RawQuery(
                query_id=qid,
                query=rec["query"],
                source=rec.get("source", "repo_generated"),
                base_query_id=rec.get("base_query_id"),
                query_type=rec.get("query_type", "factual"),
                difficulty=rec.get("difficulty", "medium"),
                expected_files=rec.get("expected_files", []),
                metadata=rec.get("metadata", {}),
                ambiguity_type=rec.get("ambiguity_type"),
                expected_resolution=rec.get("expected_resolution"),
            )

            plans = await generate_plans_for_query(
                raw_query=raw_query,
                llm_service=llm,
                n_plans=self.cfg.plans_per_query,
            )

            for plan in plans:
                append_jsonl(self.output_path, plan)

            total += len(plans)
            logger.info(f"Stage 2: {qid} → {len(plans)} plans (total: {total})")

        logger.info(f"Stage 2 complete: {total} new plans written to {self.output_path}")

    def assert_output(self) -> None:
        records = read_jsonl(self.output_path)
        assert records, "Stage 2 produced no output"
        for r in records:
            seq = r.get("agent_sequence", [])
            assert seq, f"Empty agent_sequence in plan {r.get('plan_id')}"
            for a in seq:
                assert a in ("pageindex", "vector", "graph"), f"Unknown agent: {a}"
        logger.info(f"Stage 2 assertions passed: {len(records)} plans")

"""
Stage 1 — Query Generation.
Orchestrates three generators and writes raw_queries.jsonl.
"""

from __future__ import annotations

import logging
import os
import sys

from dataset_pipeline.config import PipelineConfig
from dataset_pipeline.generation.ambiguous_query_generator import generate_ambiguous_queries
from dataset_pipeline.generation.ground_truth_variants import generate_gt_variants
from dataset_pipeline.generation.query_templates import generate_template_queries
from dataset_pipeline.models import RawQuery
from dataset_pipeline.utils.io import read_jsonl, write_jsonl

logger = logging.getLogger(__name__)

# Ensure src/ is importable for ResilientLLMService
_GENPOD = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _GENPOD not in sys.path:
    sys.path.insert(0, _GENPOD)


def _make_llm_service():
    from src.core.resilient_llm_service import ResilientLLMService
    return ResilientLLMService()


class QueryGenerationStage:
    OUTPUT_FILE = "raw_queries.jsonl"

    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.output_path = os.path.join(cfg.data_dir, self.OUTPUT_FILE)

    async def run(self) -> list[RawQuery]:
        if os.path.exists(self.output_path):
            existing = read_jsonl(self.output_path)
            if existing:
                logger.info(f"Stage 1: found {len(existing)} existing queries, skipping regeneration")
                return existing

        llm = _make_llm_service()
        all_queries: list[RawQuery] = []

        # Source A: ground truth variants
        logger.info("Stage 1: generating GT variants...")
        gt_queries = await generate_gt_variants(
            gt_path=self.cfg.gt_path,
            llm_service=llm,
            variants_per_query=self.cfg.gt_variants_per_query,
        )
        all_queries.extend(gt_queries)
        logger.info(f"Stage 1: {len(gt_queries)} GT variants generated")

        # Source B: template-based queries from repo
        logger.info("Stage 1: generating template queries...")
        template_queries = generate_template_queries(repo_path=self.cfg.repo_path)
        all_queries.extend(template_queries)
        logger.info(f"Stage 1: {len(template_queries)} template queries generated")

        # Source C: ambiguous queries
        logger.info("Stage 1: generating ambiguous queries...")
        ambiguous_queries = await generate_ambiguous_queries(
            repo_path=self.cfg.repo_path,
            llm_service=llm,
        )
        all_queries.extend(ambiguous_queries)
        logger.info(f"Stage 1: {len(ambiguous_queries)} ambiguous queries generated")

        # Deduplicate by query text
        seen: set = set()
        unique: list[RawQuery] = []
        for q in all_queries:
            key = q.query.strip().lower()
            if key not in seen:
                seen.add(key)
                unique.append(q)

        write_jsonl(self.output_path, unique)
        logger.info(f"Stage 1 complete: {len(unique)} unique queries → {self.output_path}")
        return unique

    def assert_output(self) -> None:
        records = read_jsonl(self.output_path)
        assert records, "Stage 1 produced no output"
        for r in records:
            assert len(r.get("query", "")) > 20, f"Query too short: {r}"
            assert r.get("query_id"), "Missing query_id"
            assert r.get("expected_files") is not None, "Missing expected_files"
        logger.info(f"Stage 1 assertions passed: {len(records)} records")

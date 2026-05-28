"""
Stage 4 — Validation.
Validates execution traces and writes validated_results.jsonl.
Both valid AND invalid traces are kept — both are RL training signal.
"""

from __future__ import annotations

import logging
import os

from dataset_pipeline.config import PipelineConfig
from dataset_pipeline.utils.io import iter_jsonl, read_jsonl, write_jsonl
from dataset_pipeline.validation.validator import validate_trace

logger = logging.getLogger(__name__)


class ValidationStage:
    TRACES_FILE = "execution_traces.jsonl"
    QUERIES_FILE = "raw_queries.jsonl"
    OUTPUT_FILE = "validated_results.jsonl"

    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.traces_path = os.path.join(cfg.data_dir, self.TRACES_FILE)
        self.queries_path = os.path.join(cfg.data_dir, self.QUERIES_FILE)
        self.output_path = os.path.join(cfg.data_dir, self.OUTPUT_FILE)

    async def run(self) -> None:
        traces = read_jsonl(self.traces_path)
        if not traces:
            raise RuntimeError(f"Stage 4: no traces at {self.traces_path} — run Stage 3 first")

        # Build query lookup
        query_map = {rec["query_id"]: rec for rec in iter_jsonl(self.queries_path)}

        results = []
        valid_count = 0
        invalid_count = 0

        for trace in traces:
            qid = trace.get("query_id", "")
            raw_query = query_map.get(qid, {})
            result = validate_trace(
                trace=trace,
                raw_query=raw_query,
                min_citation_coverage=self.cfg.min_citation_coverage,
                min_answer_length=self.cfg.min_answer_length,
            )
            results.append(result)
            if result.is_valid:
                valid_count += 1
            else:
                invalid_count += 1

        write_jsonl(self.output_path, results)
        total = len(results)
        logger.info(
            f"Stage 4 complete: {total} results — "
            f"{valid_count} valid ({100*valid_count/total:.1f}%), "
            f"{invalid_count} invalid → {self.output_path}"
        )

    def assert_output(self) -> None:
        records = read_jsonl(self.output_path)
        traces = read_jsonl(self.traces_path)
        assert len(records) == len(traces), "Validation count != trace count"
        logger.info(f"Stage 4 assertions passed: {len(records)} validated results")

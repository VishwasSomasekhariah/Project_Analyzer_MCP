"""
Stage 6 — Formatting.
Assembles train.jsonl + val.jsonl from original and augmented validated traces.
Writes manifest.json with dataset statistics.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import random
from collections import Counter
from typing import Any, Dict, List, Optional

from dataset_pipeline.config import PipelineConfig
from dataset_pipeline.models import TrainingExample
from dataset_pipeline.utils.io import iter_jsonl, read_jsonl, save_json, write_jsonl

logger = logging.getLogger(__name__)


def _seq_hash(agent_sequence: list) -> str:
    return hashlib.md5("|".join(agent_sequence).encode()).hexdigest()[:8]


def _build_training_example(
    trace: dict,
    validation: dict,
    plan: dict,
    raw_query: dict,
    split: str,
) -> TrainingExample:
    hops_out = []
    for h in trace.get("hops", []):
        hops_out.append({
            "hop_number": h.get("hop_number", 0),
            "agent": h.get("agent", ""),
            "instruction": h.get("instruction", ""),
            "result_summary": h.get("raw_result_summary", "")[:300],
        })

    citations_out = []
    for c in trace.get("citations", [])[:10]:
        citations_out.append({
            "agent": c.get("agent", ""),
            "file_path": c.get("file_path", ""),
            "entity_name": c.get("entity_name", ""),
            "evidence_text": c.get("evidence_text", "")[:200],
        })

    evidence_summary = trace.get("sufficiency_reasoning", "") or " | ".join(
        h.get("raw_result_summary", "")[:100] for h in trace.get("hops", [])
    )

    return TrainingExample(
        id=trace.get("trace_id", ""),
        source=raw_query.get("source", ""),
        query=raw_query.get("query", ""),
        query_type=raw_query.get("query_type", "factual"),
        difficulty=raw_query.get("difficulty", "medium"),
        routing_plan={
            "agent_sequence": plan.get("agent_sequence", []),
            "step_instructions": [
                {"agent": s.get("agent", ""), "what_to_look_for": s.get("what_to_look_for", "")}
                for s in plan.get("step_instructions", [])
            ],
            "llm_reasoning": plan.get("llm_reasoning", ""),
        },
        execution_trace={"hops": hops_out, "citations": citations_out},
        is_successful_plan=validation.get("is_valid", False),
        final_evidence_summary=evidence_summary[:500],
        ambiguity_type=raw_query.get("ambiguity_type"),
        ambiguity_resolution_correct=validation.get("ambiguity_resolution_correct"),
        validation={
            "citation_coverage": validation.get("citation_coverage", 0.0),
            "answer_quality_score": validation.get("answer_quality_score", 0.0),
            "rejection_reasons": validation.get("rejection_reasons", []),
        },
        split=split,
    )


class FormattingStage:
    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.data_dir = cfg.data_dir
        self.output_dir = cfg.output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    async def run(self) -> None:
        # Load all data
        traces = {t["trace_id"]: t for t in iter_jsonl(os.path.join(self.data_dir, "execution_traces.jsonl"))}
        validations = {v["trace_id"]: v for v in iter_jsonl(os.path.join(self.data_dir, "validated_results.jsonl"))}
        plans = {p["plan_id"]: p for p in iter_jsonl(os.path.join(self.data_dir, "routing_plans.jsonl"))}
        raw_queries = {q["query_id"]: q for q in iter_jsonl(os.path.join(self.data_dir, "raw_queries.jsonl"))}

        # Also load augmented if available
        for aug_file, plan_file in [
            ("augmented_traces.jsonl", "augmented_plans.jsonl"),
            ("augmented_validated.jsonl", None),
        ]:
            path = os.path.join(self.data_dir, aug_file)
            if os.path.exists(path):
                if aug_file == "augmented_traces.jsonl":
                    for t in iter_jsonl(path):
                        traces[t["trace_id"]] = t
                elif aug_file == "augmented_validated.jsonl":
                    for v in iter_jsonl(path):
                        validations[v["trace_id"]] = v

        aug_plans_path = os.path.join(self.data_dir, "augmented_plans.jsonl")
        if os.path.exists(aug_plans_path):
            for p in iter_jsonl(aug_plans_path):
                plans[p["plan_id"]] = p

        aug_queries_path = os.path.join(self.data_dir, "augmented_queries.jsonl")
        if os.path.exists(aug_queries_path):
            for q in iter_jsonl(aug_queries_path):
                raw_queries[q["query_id"]] = q

        # Build training examples
        examples: List[TrainingExample] = []
        seen: set = set()

        for trace_id, trace in traces.items():
            validation = validations.get(trace_id)
            if not validation:
                continue
            plan = plans.get(trace.get("plan_id", ""), {})
            raw_query = raw_queries.get(trace.get("query_id", ""), {})
            if not raw_query:
                continue

            # Dedup by (parent_query_id, agent_sequence_hash)
            parent_qid = raw_query.get("base_query_id") or raw_query.get("query_id", "")
            seq_hash = _seq_hash(plan.get("agent_sequence", []))
            dedup_key = f"{parent_qid}:{seq_hash}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            examples.append(_build_training_example(trace, validation, plan, raw_query, "train"))

        if not examples:
            logger.warning("Stage 6: no examples to format")
            return

        # Stratified train/val split
        random.seed(42)
        random.shuffle(examples)
        val_size = max(1, int(len(examples) * self.cfg.val_split))

        # Cap at max_examples
        examples = examples[:self.cfg.max_examples]
        val_examples = examples[:val_size]
        train_examples = examples[val_size:]

        for ex in val_examples:
            ex = dataclasses.replace(ex, split="val")
        for ex in train_examples:
            ex = dataclasses.replace(ex, split="train")

        all_examples = train_examples + val_examples

        train_path = os.path.join(self.output_dir, "train.jsonl")
        val_path = os.path.join(self.output_dir, "val.jsonl")
        write_jsonl(train_path, train_examples)
        write_jsonl(val_path, val_examples)

        # Manifest
        manifest = _compute_manifest(all_examples, len(train_examples), len(val_examples))
        save_json(os.path.join(self.output_dir, "manifest.json"), manifest)

        logger.info(
            f"Stage 6 complete: {len(train_examples)} train + {len(val_examples)} val examples\n"
            f"  → {train_path}\n  → {val_path}"
        )

    def assert_output(self) -> None:
        train = read_jsonl(os.path.join(self.output_dir, "train.jsonl"))
        val = read_jsonl(os.path.join(self.output_dir, "val.jsonl"))
        all_ids = [r.get("id") for r in train + val]
        assert len(all_ids) == len(set(all_ids)), "Duplicate IDs found across splits"
        assert len(train) > 0, "Empty train split"
        logger.info(f"Stage 6 assertions passed: {len(train)} train, {len(val)} val")


def _compute_manifest(examples: list, train_count: int, val_count: int) -> dict:
    total = len(examples)
    successful = sum(1 for e in examples if e.is_successful_plan)
    qt_counter = Counter(e.query_type for e in examples)
    diff_counter = Counter(e.difficulty for e in examples)
    src_counter = Counter(e.source for e in examples)
    agent_counter: Counter = Counter()
    hop_counts = []
    for e in examples:
        for h in e.execution_trace.get("hops", []):
            agent_counter[h.get("agent", "")] += 1
        hop_counts.append(len(e.execution_trace.get("hops", [])))

    return {
        "total_examples": total,
        "train_count": train_count,
        "val_count": val_count,
        "successful_plans": successful,
        "success_rate": round(successful / max(total, 1), 3),
        "query_type_distribution": {k: round(v / max(total, 1), 3) for k, v in qt_counter.items()},
        "difficulty_distribution": {k: round(v / max(total, 1), 3) for k, v in diff_counter.items()},
        "source_distribution": {k: round(v / max(total, 1), 3) for k, v in src_counter.items()},
        "mean_hop_count": round(sum(hop_counts) / max(len(hop_counts), 1), 2),
        "agent_call_counts": dict(agent_counter),
    }

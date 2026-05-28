"""
Stage 5 — Augmentation.
Takes queries where ≥1 plan succeeded, generates paraphrases, writes
them as new RawQuery entries (augmented_queries.jsonl) and then re-runs
Stages 2, 3, 4 on them to produce augmented_traces.jsonl + augmented_validated.jsonl.
"""

from __future__ import annotations

import logging
import os
import sys

from dataset_pipeline.augmentation.paraphraser import paraphrase_query
from dataset_pipeline.config import PipelineConfig
from dataset_pipeline.models import RawQuery
from dataset_pipeline.utils.io import append_jsonl, iter_jsonl, read_jsonl, write_jsonl

logger = logging.getLogger(__name__)

_GENPOD = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _GENPOD not in sys.path:
    sys.path.insert(0, _GENPOD)


def _make_llm_service():
    from src.core.resilient_llm_service import ResilientLLMService
    return ResilientLLMService()


class AugmentationStage:
    VALIDATED_FILE = "validated_results.jsonl"
    QUERIES_FILE = "raw_queries.jsonl"
    OUTPUT_QUERIES = "augmented_queries.jsonl"
    AUG_TRACES = "augmented_traces.jsonl"
    AUG_VALIDATED = "augmented_validated.jsonl"

    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.validated_path = os.path.join(cfg.data_dir, self.VALIDATED_FILE)
        self.queries_path = os.path.join(cfg.data_dir, self.QUERIES_FILE)
        self.aug_queries_path = os.path.join(cfg.data_dir, self.OUTPUT_QUERIES)
        self.aug_traces_path = os.path.join(cfg.data_dir, self.AUG_TRACES)
        self.aug_validated_path = os.path.join(cfg.data_dir, self.AUG_VALIDATED)

    async def run(self) -> None:
        validated = read_jsonl(self.validated_path)
        if not validated:
            raise RuntimeError(f"Stage 5: no validated results at {self.validated_path}")

        # Find query_ids with ≥1 successful plan
        successful_query_ids: set = {
            r.get("query_id") for r in validated if r.get("is_valid", False)
        }
        logger.info(f"Stage 5: {len(successful_query_ids)} queries have ≥1 successful plan")

        # Build query lookup (non-ambiguous only — don't paraphrase ambiguous queries)
        query_map = {
            rec["query_id"]: rec
            for rec in iter_jsonl(self.queries_path)
            if not rec.get("ambiguity_type")
        }

        # Resume: skip already augmented parent query_ids
        done_parents: set = set()
        if self.cfg.resume and os.path.exists(self.aug_queries_path):
            for rec in iter_jsonl(self.aug_queries_path):
                done_parents.add(rec.get("parent_query_id", ""))

        llm = _make_llm_service()
        total_aug = 0

        for qid in successful_query_ids:
            if qid not in query_map or qid in done_parents:
                continue
            original = query_map[qid]["query"]
            paraphrases = await paraphrase_query(
                parent_query_id=qid,
                query=original,
                llm_service=llm,
                n=self.cfg.augment_factor,
                similarity_threshold=self.cfg.similarity_threshold,
            )
            for aug in paraphrases:
                # Construct a full RawQuery from the augmented query
                parent_rec = query_map[qid]
                aug_raw_query = RawQuery(
                    query_id=aug.query_id,
                    query=aug.query,
                    source="augmented",
                    base_query_id=qid,
                    query_type=parent_rec.get("query_type", "factual"),
                    difficulty=parent_rec.get("difficulty", "medium"),
                    expected_files=parent_rec.get("expected_files", []),
                    metadata={"augmentation_type": aug.augmentation_type, "augment_index": aug.augment_index},
                )
                append_jsonl(self.aug_queries_path, aug_raw_query)
                total_aug += 1

            logger.info(f"Stage 5: {qid} → {len(paraphrases)} augmented queries")

        logger.info(f"Stage 5: {total_aug} augmented queries written to {self.aug_queries_path}")

        # Now run stages 2, 3, 4 on augmented queries
        if total_aug > 0 or os.path.exists(self.aug_queries_path):
            await self._run_augmented_pipeline()

    async def _run_augmented_pipeline(self) -> None:
        """Runs plan gen + execution + validation on augmented queries."""
        from dataset_pipeline.config import PipelineConfig
        from dataset_pipeline.stages.s2_plan_generation import PlanGenerationStage
        from dataset_pipeline.stages.s3_plan_execution import PlanExecutionStage
        from dataset_pipeline.stages.s4_validation import ValidationStage

        # Create a sub-config pointing to augmented files
        aug_cfg = PipelineConfig(**{
            **self.cfg.__dict__,
        })
        # Override data paths to use augmented files
        import dataclasses
        aug_cfg = dataclasses.replace(
            self.cfg,
            data_dir=self.cfg.data_dir,  # same dir, different file names handled below
        )

        # Use a mini config that redirects I/O
        aug_plan_stage = _AugPlanStage(self.cfg, self.aug_queries_path)
        await aug_plan_stage.run()

        aug_exec_stage = _AugExecStage(self.cfg, aug_plan_stage.output_path, self.aug_queries_path, self.aug_traces_path)
        await aug_exec_stage.run()

        aug_val_stage = _AugValStage(self.cfg, self.aug_traces_path, self.aug_queries_path, self.aug_validated_path)
        await aug_val_stage.run()


# ---------------------------------------------------------------------------
# Mini stage wrappers that redirect I/O for augmented files
# ---------------------------------------------------------------------------

class _AugPlanStage:
    def __init__(self, cfg: PipelineConfig, queries_path: str) -> None:
        self.cfg = cfg
        self.queries_path = queries_path
        self.output_path = os.path.join(cfg.data_dir, "augmented_plans.jsonl")

    async def run(self) -> None:
        from dataset_pipeline.stages.s2_plan_generation import PlanGenerationStage, _make_llm_service
        from dataset_pipeline.models import RawQuery
        from dataset_pipeline.planning.plan_generator import generate_plans_for_query
        from dataset_pipeline.utils.io import append_jsonl, iter_jsonl, read_jsonl

        from dataset_pipeline.execution.checkpoint import CheckpointManager
        checkpoint = CheckpointManager(self.cfg.checkpoint_dir, name="aug_plans")

        llm = _make_llm_service()
        for rec in read_jsonl(self.queries_path):
            qid = rec.get("query_id", "")
            if self.cfg.resume and checkpoint.is_done(qid):
                continue
            raw_query = RawQuery(
                query_id=qid,
                query=rec["query"],
                source=rec.get("source", "augmented"),
                base_query_id=rec.get("base_query_id"),
                query_type=rec.get("query_type", "factual"),
                difficulty=rec.get("difficulty", "medium"),
                expected_files=rec.get("expected_files", []),
                metadata=rec.get("metadata", {}),
            )
            plans = await generate_plans_for_query(raw_query, llm, self.cfg.plans_per_query)
            for p in plans:
                append_jsonl(self.output_path, p)
            checkpoint.mark_done(qid)


class _AugExecStage:
    def __init__(self, cfg: PipelineConfig, plans_path: str, queries_path: str, output_path: str) -> None:
        self.cfg = cfg
        self.plans_path = plans_path
        self.queries_path = queries_path
        self.output_path = output_path

    async def run(self) -> None:
        import asyncio
        from dataset_pipeline.execution.agent_runner import AgentRunner
        from dataset_pipeline.execution.checkpoint import CheckpointManager
        from dataset_pipeline.execution.sufficiency_checker import check_sufficiency
        from dataset_pipeline.stages.s3_plan_execution import _dict_to_plan, _make_llm_service
        from dataset_pipeline.utils.io import append_jsonl, iter_jsonl, read_jsonl

        query_map = {rec["query_id"]: rec["query"] for rec in iter_jsonl(self.queries_path)}
        plans_raw = read_jsonl(self.plans_path)
        checkpoint = CheckpointManager(self.cfg.checkpoint_dir, name="aug_execution")
        runner = AgentRunner(
            mcp_config_file=self.cfg.mcp_config_file,
            project_path=self.cfg.repo_path,
            project_name=self.cfg.project_name,
            collection_name=self.cfg.collection_name,
            qdrant_config=self.cfg.qdrant_config,
            neo4j_config=self.cfg.neo4j_config,
            mappings_path=self.cfg.mappings_path,
            queries_path=self.cfg.queries_path,
        )
        llm = _make_llm_service()
        for i, rec in enumerate(plans_raw):
            plan = _dict_to_plan(rec)
            if self.cfg.resume and checkpoint.is_done(plan.plan_id):
                continue
            original_query = query_map.get(plan.query_id, "")
            if not original_query:
                continue
            try:
                trace = await runner.execute_plan(plan, original_query)
                trace = await check_sufficiency(original_query, trace, llm)
                append_jsonl(self.output_path, trace)
                checkpoint.mark_done(plan.plan_id)
            except Exception as e:
                logger.error(f"Aug execution failed for {plan.plan_id}: {e}")
                checkpoint.mark_failed(plan.plan_id)
            if (i + 1) % self.cfg.batch_size == 0:
                await asyncio.sleep(5)


class _AugValStage:
    def __init__(self, cfg: PipelineConfig, traces_path: str, queries_path: str, output_path: str) -> None:
        self.cfg = cfg
        self.traces_path = traces_path
        self.queries_path = queries_path
        self.output_path = output_path

    async def run(self) -> None:
        from dataset_pipeline.utils.io import iter_jsonl, read_jsonl, write_jsonl
        from dataset_pipeline.validation.validator import validate_trace

        traces = read_jsonl(self.traces_path)
        query_map = {rec["query_id"]: rec for rec in iter_jsonl(self.queries_path)}
        results = []
        for trace in traces:
            qid = trace.get("query_id", "")
            raw_query = query_map.get(qid, {})
            result = validate_trace(trace, raw_query, self.cfg.min_citation_coverage)
            results.append(result)
        write_jsonl(self.output_path, results)
        valid = sum(1 for r in results if r.is_valid)
        logger.info(f"Aug validation: {valid}/{len(results)} valid")

"""
CLI entry point for the RL training dataset pipeline.

Usage:
  python -m dataset_pipeline --stage all
  python -m dataset_pipeline --stage 1
  python -m dataset_pipeline --stage 3 --resume
  python -m dataset_pipeline --stage 6 --max-examples 2000 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dataset_pipeline.config import PipelineConfig
from dataset_pipeline.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m dataset_pipeline",
        description="RL training dataset pipeline for the hybrid fast RAG orchestrator",
    )

    p.add_argument(
        "--stage",
        choices=["all", "1", "2", "3", "4", "5", "6"],
        default="all",
        help="Which stage(s) to run (default: all)",
    )

    # Stage 1
    p.add_argument("--gt-path", help="Ground truth JSON path")
    p.add_argument("--repo-path", help="Target codebase path")
    p.add_argument("--gt-variants-per-query", type=int, default=7)

    # Stage 2
    p.add_argument("--plans-per-query", type=int, default=3)

    # Stage 3
    p.add_argument("--collection-name", help="Qdrant collection name")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--no-resume", action="store_true", help="Start execution from scratch")
    p.add_argument("--query-timeout", type=int, default=300)
    p.add_argument("--no-async-jobs", action="store_true",
                   help="Use the legacy single long-held MCP call instead of submit/poll jobs")
    p.add_argument("--poll-interval", type=int, default=20,
                   help="Seconds between check_job_status polls (async jobs)")
    p.add_argument("--job-deadline", type=int, default=7200,
                   help="Give up on an async job after this many seconds")
    p.add_argument("--limit", type=int, default=0,
                   help="Stage 3: only execute the first N not-yet-done plans (0 = all)")

    # Stage 4
    p.add_argument("--min-citation-coverage", type=float, default=0.3)
    p.add_argument("--min-answer-length", type=int, default=50)

    # Stage 5
    p.add_argument("--augment-factor", type=int, default=3)

    # Stage 6
    p.add_argument("--val-split", type=float, default=0.1)
    p.add_argument("--max-examples", type=int, default=2500)
    p.add_argument("--output-dir", help="Output directory for train/val JSONL files")

    # General
    p.add_argument("--data-dir", help="Pipeline working directory (checkpoints stored inside data-dir/checkpoints)")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING"], default="INFO")
    p.add_argument("--dry-run", action="store_true", help="Print plan, execute nothing")

    return p


def build_config(args: argparse.Namespace) -> PipelineConfig:
    cfg = PipelineConfig()
    if args.gt_path:
        cfg.gt_path = args.gt_path
    if args.repo_path:
        cfg.repo_path = args.repo_path
    if args.gt_variants_per_query:
        cfg.gt_variants_per_query = args.gt_variants_per_query
    if args.plans_per_query:
        cfg.plans_per_query = args.plans_per_query
    if args.collection_name:
        cfg.collection_name = args.collection_name
    if args.batch_size:
        cfg.batch_size = args.batch_size
    cfg.resume = not args.no_resume
    cfg.query_timeout = args.query_timeout
    cfg.use_async_jobs = not args.no_async_jobs
    cfg.poll_interval_s = args.poll_interval
    cfg.job_deadline_s = args.job_deadline
    cfg.limit = args.limit
    cfg.min_citation_coverage = args.min_citation_coverage
    cfg.min_answer_length = args.min_answer_length
    cfg.augment_factor = args.augment_factor
    cfg.val_split = args.val_split
    cfg.max_examples = args.max_examples
    if args.output_dir:
        cfg.output_dir = args.output_dir
    if args.data_dir:
        cfg.data_dir = args.data_dir
        cfg.checkpoint_dir = str(os.path.join(args.data_dir, "checkpoints"))
    return cfg


async def run_stages(stage: str, cfg: PipelineConfig, dry_run: bool) -> None:
    from dataset_pipeline.stages.s1_query_generation import QueryGenerationStage
    from dataset_pipeline.stages.s2_plan_generation import PlanGenerationStage
    from dataset_pipeline.stages.s3_plan_execution import PlanExecutionStage
    from dataset_pipeline.stages.s4_validation import ValidationStage
    from dataset_pipeline.stages.s5_augmentation import AugmentationStage
    from dataset_pipeline.stages.s6_formatting import FormattingStage

    stages_to_run = (
        ["1", "2", "3", "4", "5", "6"] if stage == "all" else [stage]
    )

    stage_map = {
        "1": QueryGenerationStage,
        "2": PlanGenerationStage,
        "3": PlanExecutionStage,
        "4": ValidationStage,
        "5": AugmentationStage,
        "6": FormattingStage,
    }

    for s in stages_to_run:
        cls = stage_map[s]
        instance = cls(cfg)
        logger.info(f"--- Stage {s}: {cls.__name__} ---")
        if dry_run:
            logger.info(f"[dry-run] would run {cls.__name__}")
            continue
        await instance.run()
        logger.info(f"--- Stage {s} complete ---")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.log_level)

    cfg = build_config(args)
    cfg.ensure_dirs()

    asyncio.run(run_stages(args.stage, cfg, args.dry_run))


if __name__ == "__main__":
    main()

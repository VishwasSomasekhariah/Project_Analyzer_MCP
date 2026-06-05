"""
Pipeline configuration dataclass and default paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from src.core.paths import (
    NEO4J_CONFIG,
    QDRANT_CONFIG,
    FILE_WATCHER_CONFIG,
    GRAPH_INDEXER_MAPPINGS,
    GRAPH_INDEXER_QUERIES,
    GENPOD_DATA,
)

_PIPELINE_DATA = GENPOD_DATA / "dataset_pipeline" / "data"


@dataclass
class PipelineConfig:
    # --- Source paths ---
    gt_path: str = str(Path("/opt/rag-evaluation-framework/data/ground_truth.json"))
    repo_path: str = "/opt/HelloWorldApp"
    project_name: str = "HelloWorldApp"

    # --- MCP / server config ---
    mcp_config_file: str = FILE_WATCHER_CONFIG
    neo4j_config: str = NEO4J_CONFIG
    qdrant_config: str = QDRANT_CONFIG
    collection_name: str = "HelloWorldApp_pageindex_v3"
    mappings_path: str = GRAPH_INDEXER_MAPPINGS
    queries_path: str = GRAPH_INDEXER_QUERIES

    # --- Stage 1 ---
    gt_variants_per_query: int = 7
    ambiguous_queries_count: int = 180

    # --- Stage 2 ---
    plans_per_query: int = 3
    oracle_method: str = "llm"             # "llm" only (no heuristics)

    # --- Stage 3 ---
    max_hops: int = 5
    max_results: int = 5
    batch_size: int = 10
    query_timeout: int = 300               # seconds per MCP call
    resume: bool = True
    # Async job execution: submit a long-running tool, then poll for the result
    # instead of holding one SSE call open for 30-90 min (which proxies drop).
    use_async_jobs: bool = True
    poll_interval_s: int = 20              # seconds between check_job_status polls
    job_deadline_s: int = 7200             # give up on a job after this long (2h)
    limit: int = 0                         # max plans to execute this run (0 = all)

    # --- Stage 4 ---
    min_citation_coverage: float = 0.3
    min_answer_length: int = 50

    # --- Stage 5 ---
    augment_factor: int = 3
    similarity_threshold: float = 0.75

    # --- Stage 6 ---
    val_split: float = 0.1
    max_examples: int = 2500
    output_dir: str = str(GENPOD_DATA / "dataset_pipeline" / "output")

    # --- Working directories ---
    data_dir: str = str(_PIPELINE_DATA)
    checkpoint_dir: str = str(_PIPELINE_DATA / "checkpoints")
    traces_dir: str = str(_PIPELINE_DATA / "traces")

    def ensure_dirs(self) -> None:
        for d in [self.data_dir, self.checkpoint_dir, self.traces_dir, self.output_dir]:
            os.makedirs(d, exist_ok=True)

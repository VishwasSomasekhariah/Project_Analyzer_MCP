"""
Pipeline configuration dataclass and default paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_GENPOD = Path("/opt/genpod")
_DATA = _GENPOD / "dataset_pipeline" / "data"


@dataclass
class PipelineConfig:
    # --- Source paths ---
    gt_path: str = str(Path("/opt/rag-evaluation-framework/data/ground_truth.json"))
    repo_path: str = "/opt/HelloWorldApp"
    project_name: str = "HelloWorldApp"

    # --- MCP / server config ---
    mcp_config_file: str = str(_GENPOD / "file_watcher_mcp_config.json")
    neo4j_config: str = str(_GENPOD / "neo4j_config.json")
    qdrant_config: str = str(_GENPOD / "qdrant_config.json")
    collection_name: str = "HelloWorldApp_pageindex_v3"
    mappings_path: str = str(_GENPOD / "project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml")
    queries_path: str = str(_GENPOD / "project_analyzer_cli/project_analyzer/final_queries")

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

    # --- Stage 4 ---
    min_citation_coverage: float = 0.3
    min_answer_length: int = 50

    # --- Stage 5 ---
    augment_factor: int = 3
    similarity_threshold: float = 0.75

    # --- Stage 6 ---
    val_split: float = 0.1
    max_examples: int = 2500
    output_dir: str = str(_GENPOD / "dataset_pipeline" / "output")

    # --- Working directories ---
    data_dir: str = str(_DATA)
    checkpoint_dir: str = str(_DATA / "checkpoints")
    traces_dir: str = str(_DATA / "traces")

    def ensure_dirs(self) -> None:
        for d in [self.data_dir, self.checkpoint_dir, self.traces_dir, self.output_dir]:
            os.makedirs(d, exist_ok=True)

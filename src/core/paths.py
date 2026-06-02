"""
Centralized path resolution for genpod infrastructure.

All paths are driven by two env vars that install.sh sets in ~/.config/genpod/.env
(or /etc/genpod/.env for root installs):

    GENPOD_HOME   config dir — holds the three MCP JSON configs and .env
                  default: $XDG_CONFIG_HOME/genpod  (~/.config/genpod)

    GENPOD_DATA   data dir — Docker volume mounts, cache, logs, debug dumps
                  default: $XDG_DATA_HOME/genpod  (~/.local/share/genpod)

    GENPOD_LOG_DIR  override log location (optional)

Import pattern (use only what each module needs):

    from src.core.paths import NEO4J_CONFIG, QDRANT_CONFIG, SCHEMA_PATH
"""
from __future__ import annotations

import importlib.resources
import importlib.util
import os
import shutil
from pathlib import Path

# ── Base directories ──────────────────────────────────────────────────────────

def _resolve_home() -> Path:
    if v := os.environ.get("GENPOD_HOME"):
        return Path(v)
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg) / "genpod"

def _resolve_data() -> Path:
    if v := os.environ.get("GENPOD_DATA"):
        return Path(v)
    xdg = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return Path(xdg) / "genpod"

GENPOD_HOME: Path = _resolve_home()
GENPOD_DATA: Path = _resolve_data()

# ── MCP config files (written by install.sh) ─────────────────────────────────

NEO4J_CONFIG        = str(GENPOD_HOME / "neo4j_config.json")
QDRANT_CONFIG       = str(GENPOD_HOME / "qdrant_config.json")
FILE_WATCHER_CONFIG = str(GENPOD_HOME / "file_watcher_mcp_config.json")
# MCP servers the Claude SDK fallback agent is permitted to use.
# Currently restricted to neo4j only; add qdrant_server or others here when
# the fallback should also have vector-search capability.
CLAUDE_SDK_MCP_CONFIG = str(GENPOD_HOME / "claude_sdk_mcp_config.json")

# ── Schema (bundled with this package via src/schemas/) ──────────────────────

def _resolve_schema() -> str:
    try:
        ref = importlib.resources.files("src.schemas").joinpath(
            "project_knowledgebase_graph_schema.yaml"
        )
        return str(ref)
    except (ModuleNotFoundError, TypeError):
        # Running outside the installed package — fall back to repo-relative path
        _repo = Path(__file__).parent.parent.parent
        return str(_repo / "src" / "schemas" / "project_knowledgebase_graph_schema.yaml")

SCHEMA_PATH: str = _resolve_schema()

# ── genpod-graph-indexer package paths ───────────────────────────────────────
# Resolved at runtime via importlib so it works wherever uv installed the tool.

def _resolve_graph_indexer() -> tuple[str, str]:
    for pkg_name in ("genpod_graph_indexer", "project_analyzer"):
        spec = importlib.util.find_spec(pkg_name)
        if spec and spec.origin:
            pkg_root = Path(spec.origin).parent
            return (
                str(pkg_root / "parsing_utils" / "mappings.yaml"),
                str(pkg_root / "final_queries"),
            )
    # Fallback: scan the uv tools dir for the package regardless of Python version
    _tools = Path.home() / ".local" / "share" / "uv" / "tools" / "genpod-graph-indexer"
    for py_dir in sorted((_tools / "lib").iterdir()) if (_tools / "lib").exists() else []:
        for pkg_name in ("genpod_graph_indexer", "project_analyzer"):
            _pkg = py_dir / "site-packages" / pkg_name
            if (_pkg / "parsing_utils" / "mappings.yaml").exists():
                return (
                    str(_pkg / "parsing_utils" / "mappings.yaml"),
                    str(_pkg / "final_queries"),
                )
    raise FileNotFoundError(
        "Cannot locate genpod-graph-indexer package data (mappings.yaml). "
        "Run: uv tool install git+https://github.com/VishwasSomasekhariah/genpod-graph-indexer.git@main"
    )

GRAPH_INDEXER_MAPPINGS: str
GRAPH_INDEXER_QUERIES: str
GRAPH_INDEXER_MAPPINGS, GRAPH_INDEXER_QUERIES = _resolve_graph_indexer()

# ── CLI binary paths (resolved at startup, used directly in subprocess calls) ──
# Using absolute paths avoids PATH manipulation and binary shadowing risks.

def _find_cli(name: str) -> str:
    """Resolve a uv tool binary to its absolute path.

    Searches PATH first (covers terminal launches where ~/.local/bin is set),
    then falls back to the conventional uv tools location. Raises FileNotFoundError
    at server startup if the tool is not installed, failing fast with a clear message.
    """
    path = shutil.which(name)
    if path:
        return path
    fallback = Path.home() / ".local" / "bin" / name
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError(
        f"CLI tool '{name}' not found in PATH or ~/.local/bin. "
        f"Install it with: uv tool install git+https://github.com/VishwasSomasekhariah/{name}.git@main"
    )

GENPOD_SEMANTIC_RAG_BIN:  str = _find_cli("genpod-semantic-rag")
GENPOD_GRAPH_INDEXER_BIN: str = _find_cli("genpod-graph-indexer")

# ── Cache, state, logs, debug ─────────────────────────────────────────────────

APOC_CACHE    = str(GENPOD_HOME / ".cache" / "apoc_procedures.json")
STATE_PKL     = str(GENPOD_DATA / "STATE.pkl")
DEBUG_DUMPS   = str(GENPOD_DATA / "debug_dumps")
LOG_DIR       = str(Path(os.environ.get("GENPOD_LOG_DIR", str(GENPOD_DATA / "logs"))))

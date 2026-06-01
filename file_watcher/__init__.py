"""
File watcher service — monitors a project directory for changes and notifies
project-analyzer-mcp to trigger re-indexing.

Run via the repo-root wrapper:
    ./watch.sh [--project-root /path/to/project] [extra args...]

Or directly as a module:
    python -m file_watcher --config /etc/genpod/file_watcher_mcp_config.json
"""
from file_watcher.service import main

__all__ = ["main"]

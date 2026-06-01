#!/usr/bin/env bash
# watch.sh — start the file watcher service from the repo root.
#
# Automatically sources GENPOD_HOME/.env so you don't need to set environment
# variables manually. All arguments are forwarded to the watcher.
#
# Usage:
#   ./watch.sh --project-root /path/to/project/to/watch
#   ./watch.sh --project-root /path/to/project --debounce-interval 5.0
#   ./watch.sh --project-root /path/to/project --daemon
#
# The watcher calls project-analyzer-mcp (port 9000) via the MCP config at
# GENPOD_HOME/file_watcher_mcp_config.json whenever files change, using Redis
# (localhost:6379) for checksum-based dedup.
#
# Prerequisites: install.sh must have been run first.
set -euo pipefail

# ─── Resolve GENPOD_HOME ─────────────────────────────────────────────────────
if [[ -n "${GENPOD_HOME:-}" ]]; then
    GENPOD_CONFIG="${GENPOD_HOME}"
elif [[ $EUID -eq 0 ]]; then
    GENPOD_CONFIG="/etc/genpod"
else
    GENPOD_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/genpod"
fi

ENV_FILE="${GENPOD_CONFIG}/.env"
MCP_CONFIG="${GENPOD_CONFIG}/file_watcher_mcp_config.json"

# ─── Source .env ─────────────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
else
    echo "⚠  ${ENV_FILE} not found — run install.sh first" >&2
    exit 1
fi

# ─── Verify prerequisites ─────────────────────────────────────────────────────
if [[ ! -f "$MCP_CONFIG" ]]; then
    echo "✗  MCP config not found: ${MCP_CONFIG}" >&2
    echo "   Run install.sh to create it." >&2
    exit 1
fi

if ! (echo > "/dev/tcp/localhost/${REDIS_PORT:-6379}") &>/dev/null 2>&1; then
    echo "✗  Redis is not reachable on localhost:${REDIS_PORT:-6379}" >&2
    echo "   Start it: docker start genpod-redis" >&2
    exit 1
fi

if ! (echo > "/dev/tcp/localhost/9000") &>/dev/null 2>&1; then
    echo "⚠  project-analyzer-mcp is not running on port 9000" >&2
    echo "   Start it: uvicorn src.server:app --host 0.0.0.0 --port 9000" >&2
    echo "   Continuing anyway — the watcher will retry on connection failure." >&2
fi

# ─── Run ─────────────────────────────────────────────────────────────────────
echo "Starting file watcher..."
echo "  MCP config : ${MCP_CONFIG}"
echo "  Redis      : localhost:${REDIS_PORT:-6379}"
echo "  Pass --help for all options."
echo

exec python -m file_watcher \
    --config "${MCP_CONFIG}" \
    --redis-host "${REDIS_HOST:-localhost}" \
    --redis-port "${REDIS_PORT:-6379}" \
    "$@"

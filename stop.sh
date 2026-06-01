#!/usr/bin/env bash
# stop.sh — gracefully shut down all Genpod services.
#
# Order (reverse of start.sh):
#   1. Stop project-analyzer-mcp
#   2. Stop mcp-server-qdrant
#   3. Stop neo4j-mcp-server
#   4. Stop Docker containers (Neo4j, Qdrant, Redis)
#
# Usage:
#   ./stop.sh
set -uo pipefail

# ─── STYLING ─────────────────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
step() { echo -e "\n${BOLD}${CYAN}── $* ──${NC}"; }

# ─── ENVIRONMENT ─────────────────────────────────────────────────────────────
if [[ -n "${GENPOD_HOME:-}" ]]; then
    GENPOD_CONFIG="${GENPOD_HOME}"
elif [[ $EUID -eq 0 ]]; then
    GENPOD_CONFIG="/etc/genpod"
else
    GENPOD_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/genpod"
fi

ENV_FILE="${GENPOD_CONFIG}/.env"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
fi

RUN_DIR="${GENPOD_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/genpod}/run"

# ─── STOP PROCESS ────────────────────────────────────────────────────────────
# Stops a service: tries systemd first, falls back to PID file, then port scan.
stop_service() {
    local svc="$1" display="$2" port="$3" pid_file="${RUN_DIR}/${4:-}"

    if systemctl --user is-active "${svc}" &>/dev/null 2>&1; then
        systemctl --user stop "${svc}"
        log "${display} stopped (systemd)"
        return 0
    fi

    if [[ -f "${pid_file}" ]]; then
        local pid
        pid=$(cat "${pid_file}")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            rm -f "${pid_file}"
            log "${display} stopped (PID ${pid})"
            return 0
        else
            rm -f "${pid_file}"
        fi
    fi

    # Last resort: find by port
    local pid
    pid=$(lsof -ti "tcp:${port}" 2>/dev/null || true)
    if [[ -n "$pid" ]]; then
        kill "$pid"
        log "${display} stopped (found on port ${port})"
    else
        warn "${display} was not running"
    fi
}

# ─── MCP SERVERS ─────────────────────────────────────────────────────────────
step "Stopping MCP servers"

stop_service "project-analyzer-mcp" "project-analyzer-mcp" \
    "${PROJECT_ANALYZER_PORT:-9000}" "project-analyzer-mcp.pid"

stop_service "qdrant-mcp-server" "mcp-server-qdrant" \
    "${QDRANT_MCP_PORT:-8000}" "qdrant-mcp.pid"

stop_service "neo4j-mcp-server" "neo4j-mcp-server" \
    "${NEO4J_MCP_PORT:-8100}" "neo4j-mcp.pid"

# ─── DOCKER CONTAINERS ───────────────────────────────────────────────────────
step "Stopping databases"

stop_container() {
    local name="$1"
    local status
    status=$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || echo "missing")
    case "$status" in
        running)
            docker stop "$name" &>/dev/null
            log "${name} stopped"
            ;;
        missing) warn "${name} container not found" ;;
        *)       warn "${name} was already stopped" ;;
    esac
}

stop_container "genpod-neo4j"
stop_container "genpod-qdrant"
stop_container "genpod-redis"

# ─── DONE ────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}${GREEN}  All services stopped.${NC}"
echo -e "  Start again: ${BOLD}./start.sh${NC}"
echo

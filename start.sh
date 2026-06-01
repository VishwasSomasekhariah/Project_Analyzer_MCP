#!/usr/bin/env bash
# start.sh — bring all Genpod services up and start the MCP server.
#
# Order:
#   1. Load environment from GENPOD_HOME/.env
#   2. Start Docker containers (Neo4j, Qdrant, Redis)
#   3. Wait for databases to be healthy
#   4. Start neo4j-mcp-server and mcp-server-qdrant
#      (via systemd if registered, else background processes)
#   5. Run preflight check to verify everything is healthy
#   6. Start project-analyzer-mcp (foreground if no systemd, else via systemd)
#
# Usage:
#   ./start.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── STYLING ─────────────────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()  { echo -e "${RED}  ✗${NC} $*" >&2; exit 1; }
step() { echo -e "\n${BOLD}${CYAN}── $* ──${NC}"; }

# ─── ENVIRONMENT ─────────────────────────────────────────────────────────────
step "Loading environment"

if [[ -n "${GENPOD_HOME:-}" ]]; then
    GENPOD_CONFIG="${GENPOD_HOME}"
elif [[ $EUID -eq 0 ]]; then
    GENPOD_CONFIG="/etc/genpod"
else
    GENPOD_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/genpod"
fi

ENV_FILE="${GENPOD_CONFIG}/.env"
[[ -f "$ENV_FILE" ]] || err ".env not found at ${ENV_FILE} — run install.sh first"

# shellcheck source=/dev/null
source "$ENV_FILE"
log "Loaded ${ENV_FILE}"

NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
QDRANT_PORT="${QDRANT_PORT:-7000}"
REDIS_PORT="${REDIS_PORT:-6379}"
NEO4J_MCP_PORT="${NEO4J_MCP_PORT:-8100}"
QDRANT_MCP_PORT="${QDRANT_MCP_PORT:-8000}"
PROJECT_ANALYZER_PORT="${PROJECT_ANALYZER_PORT:-9000}"

# Directory for background process PID files (used when systemd is not available)
RUN_DIR="${GENPOD_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/genpod}/run"
mkdir -p "$RUN_DIR"

# ─── DOCKER CONTAINERS ───────────────────────────────────────────────────────
step "Starting databases"

start_container() {
    local name="$1"
    local status
    status=$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null || echo "missing")
    case "$status" in
        running) warn "${name} already running" ;;
        missing) err "${name} container not found — run install.sh first" ;;
        *)
            docker start "$name" &>/dev/null
            log "${name} started"
            ;;
    esac
}

start_container "genpod-neo4j"
start_container "genpod-qdrant"
start_container "genpod-redis"

# ─── WAIT FOR DATABASES ──────────────────────────────────────────────────────
step "Waiting for databases to be ready"

wait_for_http() {
    local name="$1" url="$2" max=40
    echo -n "  ${name}"
    for _ in $(seq 1 $max); do
        if curl -sf --max-time 2 "$url" &>/dev/null; then
            echo; log "${name} is ready"; return 0
        fi
        echo -n "."; sleep 3
    done
    echo
    err "${name} did not respond after $((max * 3))s — check: docker logs ${name}"
}

wait_for_tcp() {
    local name="$1" port="$2" max=20
    echo -n "  ${name}"
    for _ in $(seq 1 $max); do
        if (echo > "/dev/tcp/localhost/${port}") &>/dev/null 2>&1; then
            echo; log "${name} is ready"; return 0
        fi
        echo -n "."; sleep 2
    done
    echo
    err "${name} not ready on port ${port}"
}

wait_for_http "Neo4j"  "http://localhost:${NEO4J_HTTP_PORT}"
wait_for_http "Qdrant" "http://localhost:${QDRANT_PORT}/healthz"
wait_for_tcp  "Redis"  "${REDIS_PORT}"

# ─── MCP SERVERS ─────────────────────────────────────────────────────────────
step "Starting MCP servers"

start_mcp() {
    local svc="$1" display="$2" port="$3" pid_file="$4"
    shift 4
    local cmd=("$@")

    # Already responding — nothing to do
    if (echo > "/dev/tcp/localhost/${port}") &>/dev/null 2>&1; then
        warn "${display} already responding on port ${port}"
        return 0
    fi

    if systemctl --user is-enabled "${svc}" &>/dev/null 2>&1; then
        systemctl --user start "${svc}"
        log "${display} started via systemd"
    else
        "${cmd[@]}" &
        echo $! > "${pid_file}"
        log "${display} started (PID $(cat "${pid_file}"))"
    fi

    echo -n "  Waiting for ${display}"
    for _ in $(seq 1 15); do
        if (echo > "/dev/tcp/localhost/${port}") &>/dev/null 2>&1; then
            echo; log "${display} is responding"; return 0
        fi
        echo -n "."; sleep 2
    done
    echo
    warn "${display} not yet responding on port ${port}"
}

start_mcp \
    "neo4j-mcp-server" "neo4j-mcp-server" "${NEO4J_MCP_PORT}" \
    "${RUN_DIR}/neo4j-mcp.pid" \
    neo4j-mcp-server

start_mcp \
    "qdrant-mcp-server" "mcp-server-qdrant" "${QDRANT_MCP_PORT}" \
    "${RUN_DIR}/qdrant-mcp.pid" \
    mcp-server-qdrant --transport sse

# ─── PREFLIGHT ───────────────────────────────────────────────────────────────
step "Running preflight check"

if ! "${REPO_DIR}/preflight.sh"; then
    err "Preflight failed — fix the issues above before starting the server"
fi

# ─── MAIN SERVER ─────────────────────────────────────────────────────────────
step "Starting project-analyzer-mcp"

if systemctl --user is-enabled "project-analyzer-mcp" &>/dev/null 2>&1; then
    systemctl --user start project-analyzer-mcp
    log "project-analyzer-mcp started via systemd"
    echo
    echo -e "${BOLD}${GREEN}  All services are up.${NC}"
    echo "  Logs:  journalctl -u project-analyzer-mcp -f"
    echo "  Stop:  ./stop.sh"
else
    echo
    echo -e "${BOLD}${GREEN}  All services are up — starting server on port ${PROJECT_ANALYZER_PORT}${NC}"
    echo -e "  Stop everything:  ${BOLD}./stop.sh${NC}  (from another terminal)"
    echo
    # Run in foreground so logs stream to the terminal; Ctrl-C stops the server
    # (stop.sh handles the MCP servers and databases)
    exec project-analyzer-mcp
fi

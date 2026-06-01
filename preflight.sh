#!/usr/bin/env bash
# preflight.sh — verify all infrastructure is in place before starting
#                project-analyzer-mcp.
#
# Checks (in order):
#   1. GENPOD_HOME and GENPOD_DATA resolve correctly
#   2. .env exists and exports required variables
#   3. Required uv tools are installed
#   4. Docker containers (neo4j, qdrant, redis) are running
#   5. Neo4j HTTP responds AND bolt auth succeeds with the password in .env
#   6. Qdrant HTTP responds
#   7. Redis TCP port is open
#   8. neo4j-mcp-server SSE endpoint responds (port 8100)
#   9. mcp-server-qdrant SSE endpoint responds (port 8000)
#  10. All four config files exist in GENPOD_HOME
#  11. Claude auth — either ANTHROPIC_API_KEY is set, or Claude Code CLI is logged in
#
# Exit code 0 = all checks passed, safe to start the server.
# Exit code 1 = one or more checks failed (details printed inline).
#
# Usage:
#   chmod +x preflight.sh
#   source /etc/genpod/.env && ./preflight.sh
set -uo pipefail

# ─── STYLING ─────────────────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0

ok()   { echo -e "  ${GREEN}✓${NC} $*"; ((PASS++)) || true; }
fail() { echo -e "  ${RED}✗${NC} $*"; ((FAIL++)) || true; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
section() { echo -e "\n${BOLD}${CYAN}── $* ──${NC}"; }

# ─── 1. PATHS ────────────────────────────────────────────────────────────────
section "Paths"

if [[ -n "${GENPOD_HOME:-}" ]]; then
    GENPOD_CONFIG="${GENPOD_HOME}"
elif [[ $EUID -eq 0 ]]; then
    GENPOD_CONFIG="/etc/genpod"
else
    GENPOD_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/genpod"
fi

if [[ -n "${GENPOD_DATA:-}" ]]; then
    GENPOD_DATA_DIR="${GENPOD_DATA}"
elif [[ $EUID -eq 0 ]]; then
    GENPOD_DATA_DIR="/var/lib/genpod"
else
    GENPOD_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/genpod"
fi

ok "GENPOD_CONFIG = ${GENPOD_CONFIG}"
ok "GENPOD_DATA   = ${GENPOD_DATA_DIR}"

# ─── 2. ENV FILE ─────────────────────────────────────────────────────────────
section "Environment (.env)"

ENV_FILE="${GENPOD_CONFIG}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    fail ".env not found at ${ENV_FILE}  →  run install.sh first"
else
    ok ".env exists"
    # shellcheck source=/dev/null
    source "$ENV_FILE"

    for var in NEO4J_URI NEO4J_USER NEO4J_PASSWORD \
               QDRANT_URL EMBEDDING_MODEL \
               REDIS_HOST REDIS_PORT; do
        if [[ -n "${!var:-}" ]]; then
            ok "${var} is set"
        else
            fail "${var} is missing or empty in ${ENV_FILE}"
        fi
    done

    if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
        ok "ANTHROPIC_API_KEY is set"
    elif command -v claude &>/dev/null; then
        ok "Claude Code CLI in PATH — session auth will be used"
    elif [[ -n "${CLAUDE_CLI_PATH:-}" && -x "${CLAUDE_CLI_PATH}" ]]; then
        ok "Claude Code CLI found via CLAUDE_CLI_PATH — session auth will be used"
    else
        fail "No Claude auth found — set ANTHROPIC_API_KEY in genpod.conf, install Claude Code CLI, or set CLAUDE_CLI_PATH"
    fi
fi

# ─── 3. UV TOOLS ─────────────────────────────────────────────────────────────
section "uv tools"

if ! command -v uv &>/dev/null; then
    fail "uv not found in PATH — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
else
    for tool in genpod-graph-indexer genpod-semantic-rag neo4j-mcp-server mcp-server-qdrant; do
        if uv tool list 2>/dev/null | grep -q "^${tool} "; then
            version=$(uv tool list 2>/dev/null | awk -v t="$tool" '$1==t {print $2}')
            ok "${tool} ${version}"
        else
            fail "${tool} not installed  →  run install.sh"
        fi
    done
fi

# ─── 4. DOCKER CONTAINERS ────────────────────────────────────────────────────
section "Docker containers"

if ! docker info &>/dev/null; then
    fail "Docker daemon is not running"
else
    for container in genpod-neo4j genpod-qdrant genpod-redis; do
        status=$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || echo "missing")
        if [[ "$status" == "running" ]]; then
            ok "${container} is running"
        elif [[ "$status" == "missing" ]]; then
            fail "${container} container does not exist  →  run install.sh"
        else
            fail "${container} exists but status is '${status}'  →  docker start ${container}"
        fi
    done
fi

# ─── 5. NEO4J DB ─────────────────────────────────────────────────────────────
section "Neo4j database"

NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687

if curl -sf --max-time 5 "http://localhost:${NEO4J_HTTP_PORT}" &>/dev/null; then
    ok "Neo4j HTTP reachable on port ${NEO4J_HTTP_PORT}"

    # Verify bolt auth using Neo4j's HTTP transaction API with the .env credentials
    NEO4J_USER_VAL="${NEO4J_USER:-neo4j}"
    NEO4J_PASS_VAL="${NEO4J_PASSWORD:-}"

    if [[ -z "$NEO4J_PASS_VAL" ]]; then
        fail "NEO4J_PASSWORD is empty — cannot test auth"
    else
        HTTP_CODE=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" \
            -u "${NEO4J_USER_VAL}:${NEO4J_PASS_VAL}" \
            -H "Content-Type: application/json" \
            -d '{"statements":[{"statement":"RETURN 1"}]}' \
            "http://localhost:${NEO4J_HTTP_PORT}/db/neo4j/tx/commit" 2>/dev/null || echo "000")

        case "$HTTP_CODE" in
            200) ok "Neo4j bolt auth succeeded (user: ${NEO4J_USER_VAL})" ;;
            401) fail "Neo4j auth FAILED — password in .env does not match the container
             Fix: docker rm -f genpod-neo4j && delete ${GENPOD_DATA_DIR}/neo4j && re-run install.sh" ;;
            403) fail "Neo4j auth FAILED — user '${NEO4J_USER_VAL}' exists but is denied access" ;;
            000) fail "Neo4j HTTP transaction API did not respond (curl error)" ;;
            *)   fail "Neo4j returned unexpected HTTP ${HTTP_CODE}" ;;
        esac
    fi
else
    fail "Neo4j HTTP not reachable on port ${NEO4J_HTTP_PORT}  →  check: docker logs genpod-neo4j"
fi

# ─── 6. QDRANT DB ────────────────────────────────────────────────────────────
section "Qdrant database"

QDRANT_PORT=7000

if curl -sf --max-time 5 "http://localhost:${QDRANT_PORT}/healthz" &>/dev/null; then
    ok "Qdrant reachable on port ${QDRANT_PORT}"
else
    fail "Qdrant not reachable on port ${QDRANT_PORT}  →  check: docker logs genpod-qdrant"
fi

# ─── 7. REDIS ────────────────────────────────────────────────────────────────
section "Redis"

REDIS_TCP_PORT="${REDIS_PORT:-6379}"

if (echo > "/dev/tcp/localhost/${REDIS_TCP_PORT}") &>/dev/null 2>&1; then
    ok "Redis reachable on port ${REDIS_TCP_PORT}"
else
    fail "Redis not reachable on port ${REDIS_TCP_PORT}  →  check: docker logs genpod-redis"
fi

# ─── 8 & 9. MCP SERVERS ──────────────────────────────────────────────────────
section "MCP servers"

NEO4J_MCP_PORT=8100
QDRANT_MCP_PORT=8000

check_mcp_port() {
    local name="$1"
    local port="$2"
    local start_cmd="$3"
    if (echo > "/dev/tcp/localhost/${port}") &>/dev/null 2>&1; then
        ok "${name} responding on port ${port}"
    else
        fail "${name} not responding on port ${port}
             Start it:  source ${ENV_FILE} && ${start_cmd} &
             Or check:  systemctl status $(echo "$name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
    fi
}

check_mcp_port "neo4j-mcp-server" "${NEO4J_MCP_PORT}" "neo4j-mcp-server"
check_mcp_port "mcp-server-qdrant" "${QDRANT_MCP_PORT}" "mcp-server-qdrant --transport sse"

# ─── 10. CONFIG FILES ────────────────────────────────────────────────────────
section "Config files"

for cfg in neo4j_config.json qdrant_config.json \
           file_watcher_mcp_config.json claude_sdk_mcp_config.json; do
    path="${GENPOD_CONFIG}/${cfg}"
    if [[ -f "$path" ]]; then
        ok "${cfg}"
    else
        fail "${cfg} missing at ${path}  →  run install.sh"
    fi
done

# ─── 11. OMNISHARP (optional) ────────────────────────────────────────────────
section "OmniSharp (C# parsing)"

OMNISHARP_BIN="${OMNISHARP_PATH:-${XDG_DATA_HOME:-$HOME/.local/share}/omnisharp}/OmniSharp"
if [[ -x "$OMNISHARP_BIN" ]]; then
    ok "OmniSharp installed at ${OMNISHARP_BIN}"
else
    warn "OmniSharp not found at ${OMNISHARP_BIN} — C# projects will not be parseable
         Install: run install.sh"
fi

if command -v dotnet &>/dev/null; then
    ok ".NET SDK $(dotnet --version)"
else
    warn ".NET SDK not found — OmniSharp requires it for C# parsing"
fi

# ─── RESULT ──────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}──────────────────────────────────────────────────────────────${NC}"
if [[ $FAIL -eq 0 ]]; then
    echo -e "${BOLD}${GREEN}  All ${PASS} checks passed — safe to start the server${NC}"
    echo
    echo -e "  source ${ENV_FILE}"
    echo -e "  uvicorn src.server:app --host 0.0.0.0 --port 9000"
else
    echo -e "${BOLD}${RED}  ${FAIL} check(s) failed, ${PASS} passed${NC}"
    echo -e "  Fix the issues above then re-run: ./preflight.sh"
fi
echo -e "${BOLD}──────────────────────────────────────────────────────────────${NC}"
echo

exit $FAIL

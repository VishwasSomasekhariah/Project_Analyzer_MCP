#!/usr/bin/env bash
# install.sh — bootstrap all infrastructure needed to run project-analyzer-mcp.
#
# What this script does:
#   1. Installs .NET SDK 9.0 and OmniSharp Roslyn (required for C# parsing)
#   2. Installs four uv tools:
#        genpod-graph-indexer  (from @main)
#        genpod-semantic-rag   (from @main)
#        neo4j-mcp-server      (from @main)
#        mcp-server-qdrant     (==0.8.0, pinned — third-party PyPI)
#   3. Starts Neo4j, Qdrant, and Redis as Docker containers with persistent
#      local volumes under GENPOD_DATA
#   4. Writes four default config files under GENPOD_CONFIG:
#        neo4j_config.json             → neo4j-mcp-server (port 8100)
#        qdrant_config.json            → mcp-server-qdrant (port 8000)
#        file_watcher_mcp_config.json  → this server (port 9000)
#        claude_sdk_mcp_config.json    → Claude SDK fallback (neo4j only for now;
#                                        add qdrant here to expand its tool access)
#   5. Writes GENPOD_CONFIG/.env with all required service environment variables
#   6. (Optional, requires root) Installs systemd services for neo4j-mcp-server
#      and mcp-server-qdrant so they survive reboots
#
# Paths follow XDG base directory conventions — no hardcoded /opt/genpod:
#   Root install:  GENPOD_CONFIG=/etc/genpod        GENPOD_DATA=/var/lib/genpod
#   User install:  GENPOD_CONFIG=~/.config/genpod   GENPOD_DATA=~/.local/share/genpod
#   Override:      export GENPOD_HOME=...  GENPOD_DATA=...  before running
#
# Idempotent: already-running containers and installed tools are detected and skipped.
#
# Usage:
#   cp genpod.conf.example genpod.conf   # first time only
#   # edit genpod.conf — set ANTHROPIC_API_KEY, NEO4J_PASSWORD, etc.
#   chmod +x install.sh
#   ./install.sh
#
# File watcher (optional, user-triggered):
#   Redis is required for checksum dedup. Start the watcher with:
#     ./watch.sh --project-root /path/to/project/to/watch
#
# Prerequisites: docker (running daemon), uv, curl, wget, unzip, openssl
set -euo pipefail

# ─── STYLING ─────────────────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()  { echo -e "${RED}  ✗${NC} $*" >&2; }
step() { echo -e "\n${BOLD}${CYAN}── $* ──${NC}"; }

# ─── VERSIONS ────────────────────────────────────────────────────────────────
QDRANT_MCP_VERSION="0.8.0"
DOTNET_SDK_VERSION="8.0"
OMNISHARP_INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/omnisharp"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── GENPOD.CONF ─────────────────────────────────────────────────────────────
# Read user configuration from genpod.conf in the repo root.
# If it doesn't exist, print a clear message and exit — no silent fallbacks
# for secrets.
CONF_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/genpod.conf"

if [[ ! -f "$CONF_FILE" ]]; then
    echo
    echo -e "${RED}  ✗  genpod.conf not found.${NC}"
    echo
    echo "  Create it from the example and fill in your values:"
    echo "    cp genpod.conf.example genpod.conf"
    echo "    \$EDITOR genpod.conf"
    echo
    echo "  Then re-run: ./install.sh"
    echo
    exit 1
fi

# shellcheck source=/dev/null
source "$CONF_FILE"
log "Loaded configuration from genpod.conf"

# ─── PATHS (XDG-aware, overridable via genpod.conf) ──────────────────────────
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

ENV_FILE="${GENPOD_CONFIG}/.env"

# ─── PORTS (defaults overridable via genpod.conf) ────────────────────────────
NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
NEO4J_BOLT_PORT="${NEO4J_BOLT_PORT:-7687}"
QDRANT_PORT="${QDRANT_PORT:-7000}"
REDIS_PORT="${REDIS_PORT:-6379}"
NEO4J_MCP_PORT="${NEO4J_MCP_PORT:-8100}"
QDRANT_MCP_PORT="${QDRANT_MCP_PORT:-8000}"
PROJECT_ANALYZER_PORT="${PROJECT_ANALYZER_PORT:-9000}"

# Other overridable settings
NEO4J_USER="${NEO4J_USER:-neo4j}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-BAAI/bge-large-en-v1.5}"

# ─── CONTAINER NAMES ─────────────────────────────────────────────────────────
NEO4J_CONTAINER="genpod-neo4j"
QDRANT_CONTAINER="genpod-qdrant"
REDIS_CONTAINER="genpod-redis"

NEO4J_IMAGE="neo4j:5"
QDRANT_IMAGE="qdrant/qdrant"
REDIS_IMAGE="redis:7-alpine"

# ─── PREREQS ─────────────────────────────────────────────────────────────────
step "Checking prerequisites"

for cmd in docker uv curl wget openssl; do
    if ! command -v "$cmd" &>/dev/null; then
        err "Required tool '${cmd}' is not installed."
        [[ "$cmd" == "uv" ]] && echo "        Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    log "$cmd"
done

# unzip is needed for OmniSharp — install automatically if missing
if ! command -v unzip &>/dev/null; then
    echo "  Installing unzip..."
    sudo apt-get install -y unzip
    log "unzip"
else
    log "unzip"
fi

if ! docker info &>/dev/null; then
    err "Docker daemon is not running. Start Docker and re-run."
    exit 1
fi
log "Docker daemon is running"

# ─── DIRECTORIES ─────────────────────────────────────────────────────────────
step "Creating directory structure"

mkdir -p \
    "${GENPOD_CONFIG}" \
    "${GENPOD_DATA_DIR}/neo4j" \
    "${GENPOD_DATA_DIR}/qdrant" \
    "${GENPOD_DATA_DIR}/redis" \
    "${OMNISHARP_INSTALL_DIR}"

log "GENPOD_CONFIG = ${GENPOD_CONFIG}"
log "GENPOD_DATA   = ${GENPOD_DATA_DIR}"
log "${OMNISHARP_INSTALL_DIR}/"

# ─── .NET SDK ────────────────────────────────────────────────────────────────
step ".NET SDK ${DOTNET_SDK_VERSION} (required for C# parsing)"

if command -v dotnet &>/dev/null; then
    DOTNET_MAJOR=$(dotnet --version 2>/dev/null | cut -d'.' -f1)
    DOTNET_MAJOR="${DOTNET_MAJOR//[^0-9]/}"   # strip any non-numeric chars
    DOTNET_MAJOR="${DOTNET_MAJOR:-0}"
else
    DOTNET_MAJOR=0
fi
if [[ "${DOTNET_MAJOR}" -ge 8 ]]; then
    warn ".NET SDK $(dotnet --version 2>/dev/null) already installed — skipping"
else
    if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        source /etc/os-release
        DISTRO_ID="${ID:-unknown}"
        DISTRO_VERSION="${VERSION_ID:-}"
    fi

    case "${DISTRO_ID:-}" in
        ubuntu|debian)
            echo "  Installing .NET SDK ${DOTNET_SDK_VERSION} via Microsoft package feed..."
            wget -q "https://packages.microsoft.com/config/${DISTRO_ID}/${DISTRO_VERSION}/packages-microsoft-prod.deb" \
                -O /tmp/packages-microsoft-prod.deb
            sudo dpkg -i /tmp/packages-microsoft-prod.deb
            sudo apt-get update -qq
            sudo apt-get install -y "dotnet-sdk-${DOTNET_SDK_VERSION}" \
                libc6 libgcc-s1 libgssapi-krb5-2 libicu-dev libssl3 libstdc++6 zlib1g
            rm /tmp/packages-microsoft-prod.deb
            log ".NET SDK ${DOTNET_SDK_VERSION}"
            ;;
        *)
            warn "Unsupported distro '${DISTRO_ID:-}' — install .NET SDK ${DOTNET_SDK_VERSION} manually"
            warn "https://learn.microsoft.com/dotnet/core/install/linux"
            ;;
    esac
fi

# ─── OMNISHARP ROSLYN ────────────────────────────────────────────────────────
step "OmniSharp Roslyn (C# language server for genpod-graph-indexer)"

if [[ -x "${OMNISHARP_INSTALL_DIR}/OmniSharp" ]]; then
    warn "OmniSharp already installed at ${OMNISHARP_INSTALL_DIR}/OmniSharp — skipping"
else
    echo "  Downloading OmniSharp Roslyn (linux-x64, net6.0)..."
    OMNISHARP_ZIP="/tmp/omnisharp-linux-x64-net6.0.zip"
    wget -q --show-progress \
        "https://github.com/OmniSharp/omnisharp-roslyn/releases/latest/download/omnisharp-linux-x64-net6.0.zip" \
        -O "${OMNISHARP_ZIP}"
    unzip -q -o "${OMNISHARP_ZIP}" -d "${OMNISHARP_INSTALL_DIR}"
    chmod +x "${OMNISHARP_INSTALL_DIR}/OmniSharp"
    rm "${OMNISHARP_ZIP}"
    log "OmniSharp installed at ${OMNISHARP_INSTALL_DIR}/OmniSharp"
fi

# ─── CREDENTIALS & ENV FILE ──────────────────────────────────────────────────
step "Credentials and environment"

if [[ -f "$ENV_FILE" ]]; then
    warn "Found existing ${ENV_FILE} — loading it. Delete it to reconfigure."
    # shellcheck source=/dev/null
    source "$ENV_FILE"
else
    # Resolve secrets — genpod.conf takes priority, prompt only for blanks.

    # Neo4j password
    if [[ -z "${NEO4J_PASSWORD:-}" ]]; then
        echo -n "  Neo4j password (leave blank to auto-generate): "
        read -rs NEO4J_PASSWORD; echo
    else
        log "Neo4j password loaded from genpod.conf"
    fi
    if [[ -z "${NEO4J_PASSWORD:-}" ]]; then
        NEO4J_PASSWORD=$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 24)
        warn "Generated Neo4j password — saved to ${ENV_FILE}"
    fi

    # ANTHROPIC_API_KEY
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        echo -n "  ANTHROPIC_API_KEY: "
        read -rs ANTHROPIC_API_KEY; echo
    else
        log "ANTHROPIC_API_KEY loaded from genpod.conf"
    fi

    # OPENAI_API_KEY (optional)
    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
        echo -n "  OPENAI_API_KEY (optional): "
        read -rs OPENAI_API_KEY; echo
    else
        log "OPENAI_API_KEY loaded from genpod.conf"
    fi

    cat > "${ENV_FILE}" <<ENVEOF
# Genpod service environment — generated by install.sh from genpod.conf.
# Source this before starting any MCP server, or add to your shell profile:
#   source ${ENV_FILE}
#
# GENPOD_HOME and GENPOD_DATA are read by src/core/paths.py so the app
# finds all config files and data directories without hardcoded paths.
GENPOD_HOME=${GENPOD_CONFIG}
GENPOD_DATA=${GENPOD_DATA_DIR}

# ── Neo4j DB connection (read by neo4j-mcp-server) ───────────────────────────
NEO4J_URI=bolt://localhost:${NEO4J_BOLT_PORT}
NEO4J_USER=${NEO4J_USER}
NEO4J_PASSWORD=${NEO4J_PASSWORD}

# ── Qdrant MCP server (mcp-server-qdrant) ────────────────────────────────────
QDRANT_URL=http://localhost:${QDRANT_PORT}
EMBEDDING_MODEL=${EMBEDDING_MODEL}
QDRANT_ALLOW_ARBITRARY_FILTER=True

# ── Redis (used by file_watcher.py for checksum dedup) ───────────────────────
REDIS_HOST=localhost
REDIS_PORT=${REDIS_PORT}

# ── LLM API keys ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
OPENAI_API_KEY=${OPENAI_API_KEY:-}

# ── OmniSharp (C# language server) ───────────────────────────────────────────
OMNISHARP_PATH=${OMNISHARP_INSTALL_DIR}
PATH=\${OMNISHARP_PATH}:\$PATH
ENVEOF
    chmod 600 "${ENV_FILE}"
    log "Written ${ENV_FILE} (mode 600)"
fi

# ─── UV TOOLS ────────────────────────────────────────────────────────────────
step "Installing uv tools"

install_git_tool() {
    local name="$1"
    local url="$2"
    if uv tool list 2>/dev/null | grep -q "^${name} "; then
        warn "${name} already installed — run 'uv tool upgrade ${name}' to pull latest main"
    else
        echo "  Installing ${name} from ${url}@main..."
        uv tool install "git+${url}@main"
        log "${name}"
    fi
}

install_git_tool "genpod-graph-indexer" \
    "https://github.com/VishwasSomasekhariah/genpod-graph-indexer.git"

install_git_tool "genpod-semantic-rag" \
    "https://github.com/VishwasSomasekhariah/genpod-semantic-rag.git"

install_git_tool "neo4j-mcp-server" \
    "https://github.com/VishwasSomasekhariah/neo4j-mcp.git"

# Third-party — pin to tested version
if uv tool list 2>/dev/null | grep -q "^mcp-server-qdrant v${QDRANT_MCP_VERSION}"; then
    warn "mcp-server-qdrant v${QDRANT_MCP_VERSION} already installed — skipping"
else
    echo "  Installing mcp-server-qdrant==${QDRANT_MCP_VERSION}..."
    uv tool install "mcp-server-qdrant==${QDRANT_MCP_VERSION}"
    log "mcp-server-qdrant v${QDRANT_MCP_VERSION}"
fi

# Install this server itself as a uv tool from the local repo
echo "  Installing project-analyzer-mcp from local repo..."
uv tool install --force "${REPO_DIR}"
log "project-analyzer-mcp"

NEO4J_MCP_BIN=$(which neo4j-mcp-server)
QDRANT_MCP_BIN=$(which mcp-server-qdrant)
PROJECT_ANALYZER_BIN=$(which project-analyzer-mcp)

# ─── DOCKER: NEO4J ───────────────────────────────────────────────────────────
step "Neo4j database (Docker — ${NEO4J_IMAGE})"

if docker ps -a --format '{{.Names}}' | grep -q "^${NEO4J_CONTAINER}$"; then
    if docker ps --format '{{.Names}}' | grep -q "^${NEO4J_CONTAINER}$"; then
        warn "Container '${NEO4J_CONTAINER}' already running — skipping"
    else
        warn "Container '${NEO4J_CONTAINER}' exists but stopped — starting it"
        docker start "${NEO4J_CONTAINER}"
    fi
else
    echo "  Creating Neo4j container (APOC enabled, data at ${GENPOD_DATA_DIR}/neo4j)..."
    docker run -d \
        --name "${NEO4J_CONTAINER}" \
        --restart unless-stopped \
        -p "127.0.0.1:${NEO4J_HTTP_PORT}:7474" \
        -p "127.0.0.1:${NEO4J_BOLT_PORT}:7687" \
        -v "${GENPOD_DATA_DIR}/neo4j:/data" \
        -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
        -e NEO4J_PLUGINS='["apoc"]' \
        -e NEO4J_dbms_security_procedures_unrestricted="apoc.*" \
        -e NEO4J_dbms_security_procedures_allowlist="apoc.*" \
        -e NEO4J_apoc_export_file_enabled="true" \
        -e NEO4J_apoc_import_file_enabled="true" \
        "${NEO4J_IMAGE}"
    log "Neo4j container created"
fi

# ─── DOCKER: QDRANT ──────────────────────────────────────────────────────────
step "Qdrant database (Docker — ${QDRANT_IMAGE})"

if docker ps -a --format '{{.Names}}' | grep -q "^${QDRANT_CONTAINER}$"; then
    if docker ps --format '{{.Names}}' | grep -q "^${QDRANT_CONTAINER}$"; then
        warn "Container '${QDRANT_CONTAINER}' already running — skipping"
    else
        warn "Container '${QDRANT_CONTAINER}' exists but stopped — starting it"
        docker start "${QDRANT_CONTAINER}"
    fi
else
    echo "  Creating Qdrant container (data at ${GENPOD_DATA_DIR}/qdrant)..."
    docker run -d \
        --name "${QDRANT_CONTAINER}" \
        --restart unless-stopped \
        -p "127.0.0.1:${QDRANT_PORT}:6333" \
        -v "${GENPOD_DATA_DIR}/qdrant:/qdrant/storage:z" \
        "${QDRANT_IMAGE}"
    log "Qdrant container created"
fi

# ─── DOCKER: REDIS ───────────────────────────────────────────────────────────
step "Redis (Docker — ${REDIS_IMAGE})"
# Redis is used by file_watcher.py to store per-file checksums for dedup.
# Data is persisted with appendonly AOF so checksums survive container restarts.

if docker ps -a --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER}$"; then
    if docker ps --format '{{.Names}}' | grep -q "^${REDIS_CONTAINER}$"; then
        warn "Container '${REDIS_CONTAINER}' already running — skipping"
    else
        warn "Container '${REDIS_CONTAINER}' exists but stopped — starting it"
        docker start "${REDIS_CONTAINER}"
    fi
else
    echo "  Creating Redis container (AOF persistence at ${GENPOD_DATA_DIR}/redis)..."
    docker run -d \
        --name "${REDIS_CONTAINER}" \
        --restart unless-stopped \
        -p "127.0.0.1:${REDIS_PORT}:6379" \
        -v "${GENPOD_DATA_DIR}/redis:/data" \
        "${REDIS_IMAGE}" \
        redis-server --appendonly yes --appendfsync everysec
    log "Redis container created"
fi

# ─── WAIT FOR DATABASES ──────────────────────────────────────────────────────
step "Waiting for databases to be ready"

wait_for_http() {
    local name="$1"
    local url="$2"
    local max=40
    echo -n "  ${name}"
    for _ in $(seq 1 $max); do
        if curl -sf --max-time 2 "${url}" &>/dev/null; then
            echo
            log "${name} is ready"
            return 0
        fi
        echo -n "."
        sleep 3
    done
    echo
    err "${name} did not respond after $((max * 3))s — check: docker logs ${name}"
    exit 1
}

wait_for_tcp() {
    local name="$1"
    local port="$2"
    local max=20
    echo -n "  ${name}"
    for _ in $(seq 1 $max); do
        if (echo > "/dev/tcp/localhost/${port}") &>/dev/null 2>&1; then
            echo
            log "${name} is ready"
            return 0
        fi
        echo -n "."
        sleep 2
    done
    echo
    err "${name} (port ${port}) not ready after $((max * 2))s"
    exit 1
}

wait_for_http "${NEO4J_CONTAINER}" "http://localhost:${NEO4J_HTTP_PORT}"
wait_for_http "${QDRANT_CONTAINER}" "http://localhost:${QDRANT_PORT}/healthz"
wait_for_tcp  "${REDIS_CONTAINER}"  "${REDIS_PORT}"

# ─── CONFIG FILES ────────────────────────────────────────────────────────────
step "Writing default config files to ${GENPOD_CONFIG}/"

cat > "${GENPOD_CONFIG}/neo4j_config.json" <<CFGEOF
{
    "mcpServers": {
        "neo4j_memory": {
            "type": "http",
            "url": "http://localhost:${NEO4J_MCP_PORT}/sse"
        }
    }
}
CFGEOF
log "neo4j_config.json  (→ neo4j-mcp-server on localhost:${NEO4J_MCP_PORT})"

cat > "${GENPOD_CONFIG}/qdrant_config.json" <<CFGEOF
{
    "mcpServers": {
        "qdrant_server": {
            "type": "http",
            "url": "http://localhost:${QDRANT_MCP_PORT}/sse"
        }
    }
}
CFGEOF
log "qdrant_config.json  (→ mcp-server-qdrant on localhost:${QDRANT_MCP_PORT})"

cat > "${GENPOD_CONFIG}/file_watcher_mcp_config.json" <<CFGEOF
{
    "mcpServers": {
        "mcp-analysis-server": {
            "type": "http",
            "url": "http://localhost:${PROJECT_ANALYZER_PORT}/sse"
        }
    }
}
CFGEOF
log "file_watcher_mcp_config.json  (→ project-analyzer-mcp on localhost:${PROJECT_ANALYZER_PORT})"

# Claude SDK fallback MCP config — controls which MCP servers the Claude SDK
# fallback agent is permitted to use. Currently neo4j only. Add qdrant_server
# here (same format) when the fallback agent should also have vector-search access.
cat > "${GENPOD_CONFIG}/claude_sdk_mcp_config.json" <<CFGEOF
{
    "_comment": "MCP servers available to the Claude SDK fallback agent. Currently restricted to neo4j for CPG-only queries. Add qdrant_server here to expand its tool access to vector search.",
    "mcpServers": {
        "neo4j_memory": {
            "type": "http",
            "url": "http://localhost:${NEO4J_MCP_PORT}/sse"
        }
    }
}
CFGEOF
log "claude_sdk_mcp_config.json  (Claude SDK fallback — neo4j only, expand as needed)"

# ─── SYSTEMD SERVICES ────────────────────────────────────────────────────────
# Register services so they survive reboots. start.sh brings them up.
step "Registering systemd services"

if ! command -v systemctl &>/dev/null; then
    warn "systemd not available — services will be started as background processes by start.sh"
else
    # User-level systemd services — no root needed.
    # Lives in ~/.config/systemd/user/, managed with `systemctl --user`.
    SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
    mkdir -p "${SYSTEMD_USER_DIR}"

    cat > "${SYSTEMD_USER_DIR}/neo4j-mcp-server.service" <<SVCEOF
[Unit]
Description=Neo4j MCP Server (Genpod)
After=network.target

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
ExecStart=${NEO4J_MCP_BIN}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF
    log "neo4j-mcp-server.service registered"

    cat > "${SYSTEMD_USER_DIR}/qdrant-mcp-server.service" <<SVCEOF
[Unit]
Description=Qdrant MCP Server (Genpod)
After=network.target

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
ExecStart=${QDRANT_MCP_BIN} --transport sse
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF
    log "qdrant-mcp-server.service registered"

    cat > "${SYSTEMD_USER_DIR}/project-analyzer-mcp.service" <<SVCEOF
[Unit]
Description=Project Analyzer MCP Server (Genpod)
After=network.target neo4j-mcp-server.service qdrant-mcp-server.service
Wants=neo4j-mcp-server.service qdrant-mcp-server.service

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
ExecStart=${PROJECT_ANALYZER_BIN}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF
    log "project-analyzer-mcp.service registered"

    systemctl --user daemon-reload
    systemctl --user enable neo4j-mcp-server.service qdrant-mcp-server.service project-analyzer-mcp.service
    log "All three services enabled (will auto-start on login)"
    log "Run ./start.sh to bring everything up now"
fi

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}${GREEN}┌──────────────────────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}${GREEN}│        Genpod infrastructure is ready                        │${NC}"
echo -e "${BOLD}${GREEN}└──────────────────────────────────────────────────────────────┘${NC}"
echo
echo -e "${BOLD}Install paths:${NC}"
echo "  Config  ${GENPOD_CONFIG}/"
echo "  Data    ${GENPOD_DATA_DIR}/"
echo
echo -e "${BOLD}Databases (Docker, restart=unless-stopped):${NC}"
echo "  Neo4j   http://localhost:${NEO4J_HTTP_PORT}   bolt://localhost:${NEO4J_BOLT_PORT}"
echo "  Qdrant  http://localhost:${QDRANT_PORT}"
echo "  Redis   localhost:${REDIS_PORT}"
echo
echo -e "${BOLD}CLI tools (uv):${NC}"
uv tool list 2>/dev/null \
    | grep -E "^(genpod-graph-indexer|genpod-semantic-rag|neo4j-mcp-server|mcp-server-qdrant|project-analyzer-mcp) " \
    | while read -r line; do echo "  ${line}"; done
echo
echo -e "${BOLD}Config files written:${NC}"
echo "  neo4j_config.json            → localhost:${NEO4J_MCP_PORT}"
echo "  qdrant_config.json           → localhost:${QDRANT_MCP_PORT}"
echo "  file_watcher_mcp_config.json → localhost:${PROJECT_ANALYZER_PORT}"
echo "  claude_sdk_mcp_config.json   → neo4j only (expand to add more MCP servers)"
echo
echo -e "${BOLD}Next steps:${NC}"
echo "  ./start.sh                                    # bring everything up"
echo "  ./stop.sh                                     # shut everything down"
echo "  ./watch.sh --project-root /path/to/project   # optional file watcher"
echo
echo -e "${BOLD}Credentials:${NC}  cat ${ENV_FILE}"
echo

# Project Analyzer MCP

An MCP server for intelligent code analysis using Code Property Graphs (CPG) and vector RAG. It indexes a codebase into Neo4j (graph) and Qdrant (vectors), then answers questions about it using LangGraph-powered retrieval workflows.

## Architecture

```
project-analyzer-mcp  (port 9000)
         │
         ├── genpod-graph-indexer  →  neo4j-mcp-server (port 8100)  →  Neo4j DB (port 7687)
         └── genpod-semantic-rag   →  mcp-server-qdrant (port 8000)  →  Qdrant DB (port 7000)

file_watcher (optional)  →  Redis (port 6379) for checksum dedup
                          →  project-analyzer-mcp to trigger re-indexing
```

## Quickstart

### 1. Clone

```bash
git clone https://github.com/VishwasSomasekhariah/Project_Analyzer_MCP.git
cd Project_Analyzer_MCP
```

### 2. Configure

```bash
cp genpod.conf.example genpod.conf
$EDITOR genpod.conf
```

At minimum set these two values:

```bash
ANTHROPIC_API_KEY=sk-ant-...
NEO4J_PASSWORD=your-secure-password   # min 8 chars
```

Everything else has sensible defaults. See `genpod.conf.example` for all options with full documentation.

> `genpod.conf` is gitignored — your secrets are never committed.

### 3. Install

```bash
chmod +x install.sh preflight.sh watch.sh start.sh stop.sh
./install.sh
```

What `install.sh` does:
- Reads your settings from `genpod.conf`
- Installs .NET SDK 9.0 and OmniSharp Roslyn (required for C# parsing)
- Installs four CLI tools via `uv`: `genpod-graph-indexer`, `genpod-semantic-rag`, `neo4j-mcp-server`, `mcp-server-qdrant`
- Starts Neo4j, Qdrant, and Redis as Docker containers with persistent local volumes
- Writes config files and `.env` to `~/.config/genpod/` (or `/etc/genpod/` for root installs)
- Installs and starts systemd services for `neo4j-mcp-server` and `mcp-server-qdrant` (root only)

### 4. Pre-flight check

```bash
source ~/.config/genpod/.env
./preflight.sh
```

Verifies every layer — env vars, Docker containers, Neo4j auth, MCP server ports, config files — before you start the server. Exits 0 if everything is ready.

### 5. Start MCP servers (if not using systemd)

```bash
source ~/.config/genpod/.env
neo4j-mcp-server &
mcp-server-qdrant --transport sse &
```

### 6. Start this server

```bash
source ~/.config/genpod/.env
uvicorn src.server:app --host 0.0.0.0 --port 9000
```

---

## File Watcher (optional)

Monitors a project directory for file changes and triggers re-indexing automatically. Uses Redis for checksum-based dedup so unchanged files are skipped.

```bash
./watch.sh --project-root /path/to/project
```

`watch.sh` sources `~/.config/genpod/.env` automatically, checks Redis and the MCP server are up, then starts the watcher. All arguments are forwarded to the service.

```bash
./watch.sh --help   # see all options
```

---

## Configuration reference

All settings live in `genpod.conf` (copy from `genpod.conf.example`). Only the two required fields need to be set — everything else defaults to the values below.

| Setting | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | optional | API key for Claude — not needed if logged into Claude Code CLI |
| `NEO4J_PASSWORD` | auto-generated | Neo4j database password (min 8 chars) |
| `NEO4J_USER` | `neo4j` | Neo4j database username |
| `NEO4J_HTTP_PORT` | `7474` | Neo4j browser / HTTP port |
| `NEO4J_BOLT_PORT` | `7687` | Neo4j Bolt protocol port |
| `QDRANT_PORT` | `7000` | Qdrant REST API port |
| `REDIS_PORT` | `6379` | Redis port (used by file watcher) |
| `NEO4J_MCP_PORT` | `8100` | neo4j-mcp-server SSE port |
| `QDRANT_MCP_PORT` | `8000` | mcp-server-qdrant SSE port (fixed by the tool) |
| `PROJECT_ANALYZER_PORT` | `9000` | This server's port |
| `EMBEDDING_MODEL` | `BAAI/bge-large-en-v1.5` | Embedding model for vector search |
| `GENPOD_HOME` | `~/.config/genpod` | Where config files live |
| `GENPOD_DATA` | `~/.local/share/genpod` | Where database volumes and logs live |
| `OPENAI_API_KEY` | optional | For qdrant MCP built-in AI response features |
| `CLAUDE_CLI_PATH` | optional | Path to a `claude` wrapper script used by `claude-agent-sdk` fallback in sub-tools. Set when the default bundled CLI is not authenticated (e.g. shared/service accounts). |

---

## Dependencies

### CLI tools (uv)

| Tool | Source | Purpose |
|---|---|---|
| `genpod-graph-indexer` | [GitHub @main](https://github.com/VishwasSomasekhariah/genpod-graph-indexer) | CPG indexing into Neo4j |
| `genpod-semantic-rag` | [GitHub @main](https://github.com/VishwasSomasekhariah/genpod-semantic-rag) | Vector indexing and RAG via Qdrant — installed with `[fallback]` extra for AI summaries |
| `neo4j-mcp-server` | [GitHub @main](https://github.com/VishwasSomasekhariah/neo4j-mcp) | MCP server exposing Neo4j CPG tools |
| `mcp-server-qdrant` | [PyPI v0.8.0](https://pypi.org/project/mcp-server-qdrant/) | MCP server for Qdrant vector search |

> **Note:** `genpod-semantic-rag` always builds the PageIndex alongside vector embeddings (`enable_pageindex` is permanently on). As a result the two preprocessing tools (`genpod-graph-indexer` for CPG/Neo4j, `genpod-semantic-rag` for vectors+pageindex) may be consolidated into a single tool in a future version once the separation is no longer needed.

### Databases (Docker)

| Container | Image | Ports | Persistent data |
|---|---|---|---|
| `genpod-neo4j` | `neo4j:5` | 7474, 7687 | `GENPOD_DATA/neo4j/` |
| `genpod-qdrant` | `qdrant/qdrant` | 7000 | `GENPOD_DATA/qdrant/` |
| `genpod-redis` | `redis:7-alpine` | 6379 | `GENPOD_DATA/redis/` |

All containers run with `--restart unless-stopped` and survive reboots.

---

## Troubleshooting

**Server fails to start with "CLI tool not found":**
The server resolves `genpod-semantic-rag` and `genpod-graph-indexer` at startup and exits immediately if either is missing from `PATH` or `~/.local/bin`.

```bash
# Re-run install to reinstall missing tools:
./install.sh
# Or install manually:
uv tool install "git+https://github.com/VishwasSomasekhariah/genpod-graph-indexer.git@main"
uv tool install "git+https://github.com/VishwasSomasekhariah/genpod-semantic-rag.git@main[fallback]"
```

---

**Neo4j auth fails (`401`) in preflight:**
The password in `.env` doesn't match the one Neo4j was initialized with. Neo4j locks in the password on first boot from the data volume.

```bash
docker rm -f genpod-neo4j
rm -rf ~/.local/share/genpod/neo4j
# Set the correct NEO4J_PASSWORD in genpod.conf, delete ~/.config/genpod/.env, then:
./install.sh
```

**MCP server not responding:**
```bash
source ~/.config/genpod/.env
systemctl status neo4j-mcp-server     # if using systemd
journalctl -u neo4j-mcp-server -f
# or start manually:
neo4j-mcp-server &
mcp-server-qdrant --transport sse &
```

**Check container logs:**
```bash
docker logs genpod-neo4j
docker logs genpod-qdrant
docker logs genpod-redis
```

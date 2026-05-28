# Claude Code Integration for GenPod RAG Workflow

## Overview

This integration allows users with Claude Code setup to run the entire GenPod RAG workflow using Claude models **without paying for OpenAI or Anthropic API access**.

The adapter creates an OpenAI-compatible HTTP server that internally uses Claude Agent SDK, making it a drop-in replacement for your existing LLM configuration.

## How It Works

```
Your RAG Workflow (unchanged)
       ↓
OpenAI Client with custom base_url
       ↓
Claude Code OpenAI Adapter (localhost:8888)
       ↓
Claude Agent SDK
       ↓
Claude Code CLI (local)
```

## Setup

### 1. Install Claude Agent SDK (if not already done)

```bash
cd /opt/genpod/fallback_agent
uv add claude-agent-sdk
```

### 2. Start the Adapter Server

```bash
# Default port: 8889
python3 claude_code_openai_adapter.py

# Or specify custom port to avoid conflicts:
CLAUDE_ADAPTER_PORT=9000 python3 claude_code_openai_adapter.py
```

**Port Configuration:**
- Default: `8889` (configurable via `CLAUDE_ADAPTER_PORT` env var)
- Avoid: `8100` (Neo4j MCP), `8001` (main server), `8888` (common conflicts)

The server exposes OpenAI-compatible endpoints.

### 3. Configure Your RAG Workflow

**Option A: Using SystemConfig (for graph_rag workflows)**

```python
from src.core.graph_rag.core.config import SystemConfig

config = SystemConfig(
    mcp_config_path="neo4j_config.json",
    yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
    llm_config={
        "model": "claude-sonnet-4.5",  # or "claude-haiku-4.5"
        "base_url": "http://localhost:8889/v1",
        "api_key": "not-needed",  # Claude Code uses CLI auth
        "temperature": 0.0
    }
)
```

**Option B: Direct LLMConfig usage**

```python
from src.core.graph_rag.core.config import LLMConfig

llm_config = LLMConfig(
    model="claude-sonnet-4.5",
    base_url="http://localhost:8889/v1",
    api_key="not-needed",
    temperature=0.0
)

# Create OpenAI client (it actually connects to Claude!)
openai_client = llm_config.create_client()
```

**Option C: For legacy LLMService**

```python
from src.core.llm_service import LLMService

# The LLMService doesn't directly support base_url, but you can
# modify the agents initialization to use SystemConfig approach above
```

## Model Mapping

The adapter automatically maps model names to correct Claude Agent SDK format:

| Request Model | Claude Agent SDK Model | Notes |
|---------------|------------------------|-------|
| `claude-sonnet-4.5` | `claude-sonnet-4-5` | **Recommended for complex tasks** |
| `claude-haiku-4.5` | `claude-haiku-4-5` | **Recommended for fast inference** |
| `claude-3-5-sonnet-20241022` | `claude-sonnet-4-5` | Legacy name mapping |
| `claude-3-haiku-20240307` | `claude-haiku-4-5` | Legacy name mapping |
| `gpt-4o` | `claude-sonnet-4-5` | OpenAI fallback |
| `gpt-4o-mini` | `claude-haiku-4-5` | OpenAI fallback |

**Note:** Claude Agent SDK uses hyphens in model names (`claude-sonnet-4-5`), not dots.

## Complete Example

```python
#!/usr/bin/env python3
"""
Example: Run 4-Agent RAG workflow with Claude Code
"""

import asyncio
from src.core.graph_rag.core.config import SystemConfig
from src.core.graph_rag.workflows.four_agent_workflow import FourAgentWorkflow

async def main():
    # Configure to use Claude Code via adapter
    config = SystemConfig(
        mcp_config_path="neo4j_config.json",
        yaml_schema_path="/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        llm_config={
            "model": "claude-sonnet-4.5",
            "base_url": "http://localhost:8889/v1",
            "api_key": "not-needed"
        },
        use_4_agent_team=True
    )

    # Run workflow (uses Claude Code seamlessly!)
    workflow = FourAgentWorkflow(config)
    result = await workflow.run("What does CreateWorkers return?")

    print(result)

if __name__ == "__main__":
    asyncio.run(main())
```

## Cost Comparison

For ~306k tokens/scenario (from benchmark_v28):

| Provider | Cost/Scenario | Setup |
|----------|---------------|-------|
| GPT-4o (OpenAI) | $1.22 | API key + pay per use |
| Claude Sonnet 4.5 (Anthropic API) | $1.65 | API key + pay per use |
| **Claude Sonnet 4.5 (Claude Code)** | **$0.00** | One-time CLI setup |
| **Claude Haiku 4.5 (Claude Code)** | **$0.00** | One-time CLI setup |

## Features

✅ **Zero API costs** for users with Claude Code
✅ **Drop-in replacement** - no code changes needed
✅ **OpenAI-compatible API** - works with existing OpenAI clients
✅ **Both streaming and non-streaming** supported
✅ **Model flexibility** - choose Sonnet or Haiku
✅ **Token usage tracking** - estimates token counts

## Limitations

⚠️ **Single-turn only** - Each API call is a fresh session (no conversation context between calls)
⚠️ **Local only** - Server must run on same machine as Claude Code CLI
⚠️ **Token estimates** - Uses character-based estimation, not exact counts
⚠️ **No function calling** - Tools/function calling not supported (inference only)

## Troubleshooting

### Error: "Claude Agent SDK not available"
```bash
cd /opt/genpod/fallback_agent
uv add claude-agent-sdk
```

### Error: "Connection refused"
Make sure the adapter server is running:
```bash
python3 claude_code_openai_adapter.py
```

### Error: "CLIConnectionError"
Ensure Claude Code CLI is authenticated:
```bash
claude --version
```

### Slow responses?
- Use `claude-haiku-4.5` for faster inference
- Reduce `max_tokens` in config
- Check Claude Code CLI performance

## Architecture

```python
# Your code calls:
response = openai_client.chat.completions.create(
    model="claude-sonnet-4.5",
    messages=[{"role": "user", "content": "Hello"}]
)

# Adapter translates to:
async with ClaudeSDKClient(options=...) as client:
    await client.query("User: Hello")
    # Returns response in OpenAI format
```

## Next Steps

1. **Start the adapter**: `python3 claude_code_openai_adapter.py`
2. **Update your config** to point to `http://localhost:8888/v1`
3. **Run your workflow** - it now uses Claude Code!

No other changes needed. Your entire RAG system seamlessly uses Claude.

# Claude SDK Integration for Graph RAG

This document describes how Claude Agent SDK is integrated into the Graph RAG system as a fallback when the primary LLM provider (OpenAI) is unavailable.

## Overview

The integration provides:
- **Seamless fallback** from OpenAI to Claude SDK
- **Per-agent tool restrictions** - each agent only sees its allowed tools
- **Security guardrails** - Cypher validation, prompt injection detection, built-in tool blocking
- **Session management** - preserves multi-turn context across queries
- **Parallel execution safety** - concurrent agents with isolated sessions

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User Code / Agents                        │
│  (ThinkerAgent, ExecutorAgent, EntityResolutionAgent, etc.) │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   ResilientLLMClient                         │
│            (OpenAI-compatible facade with fallback)          │
└────────────────────────────┬────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                              ▼
          PRIMARY                     FALLBACK (Claude SDK)
         (OpenAI)                            │
              │                   ┌──────────┴──────────┐
              │                   ▼                      ▼
              │            Per-Agent Mode          Direct Mode
              │          (PerAgentSDKClient)   (ClaudeSDKFallback)
              │                   │                      │
              │                   └──────────┬───────────┘
              │                              ▼
              │                      ClaudeSDKClient
              │                       (async query)
              │                              │
              │                   ┌──────────┴──────────┐
              │                   ▼                      ▼
              │            In-Process Tools       External MCP
              │            (Schema Tools)        (Neo4j Server)
              │
              └──────────────────────────────────────────────┘
                                     │
                                     ▼
                            Response (OpenAI-compatible)
```

## Key Components

### 1. ResilientLLMClient (`llm_client.py`)

The main entry point providing an OpenAI-compatible interface with automatic fallback.

```python
from src.core.graph_rag.core.llm_client import ResilientLLMClient

# Initialize with fallback enabled
client = ResilientLLMClient(
    api_key="...",  # Optional - if missing, uses fallback only
    fallback_enabled=True,
    fallback_mode="direct",  # "direct" (Claude SDK) or "adapter" (legacy)
    mcp_config_path="/path/to/mcp_config.json"
)

# Use like OpenAI client - falls back automatically
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "..."}],
    tools=[...],
    agent_context={  # For per-agent tool restrictions
        "agent_id": "ThinkerAgent",
        "allowed_tools": ["mcp__neo4j_memory__neo4j_execute_query", ...]
    }
)
```

**Features:**
- Automatic fallback on connection errors, timeouts, rate limits, 5xx errors
- Circuit breaker pattern to skip primary when known to be down
- Per-agent mode for tool restrictions
- Schema context injection for in-process tools

### 2. PerAgentSDKClient (`per_agent_sdk_client.py`)

Manages separate SDK sessions for each agent, enabling per-agent tool restrictions.

```python
# Created internally by ResilientLLMClient when per-agent mode is enabled
session_manager = AgentSessionManager()
per_agent_client = PerAgentSDKClient(
    mcp_config_path="/path/to/mcp_config.json",
    session_manager=session_manager
)

# Each agent gets its own session with its own tools
response = await per_agent_client.query(
    agent_id="ThinkerAgent",
    allowed_tools=["mcp__schema_tools__get_node_labels", ...],
    prompt="Analyze this query...",
    system_prompt="You are a code analysis agent..."
)
```

**Key Design:**
- **One session per agent** - preserves multi-turn context
- **Per-agent locks** - serializes concurrent calls to same agent
- **Tool enforcement via hooks** - blocks disallowed tools at execution time

### 3. ClaudeSDKFallback (`claude_sdk_fallback.py`)

Direct integration with Claude Agent SDK for single-session fallback queries.

```python
from src.core.graph_rag.core.claude_sdk_fallback import ClaudeSDKFallback

fallback = ClaudeSDKFallback(
    mcp_config_path="/path/to/mcp_config.json",
    system_prompt="You are a code analysis assistant...",
    strict_security=True,
    validate_cypher=True,
    block_builtin_tools=True
)

response = await fallback.query(
    prompt="What classes implement IService?",
    response_format={"type": "json_object"}
)
```

**Features:**
- Security validators (Cypher, prompt injection)
- Built-in tool blocking (Bash, Read, Write, etc.)
- In-process schema tools support
- JSON output extraction

### 4. SDK Tools Server (`sdk_tools.py`)

Creates in-process MCP-compatible tools that work in the Claude SDK subprocess context.

```python
from src.core.graph_rag.core.sdk_tools import create_sdk_tools_server

# Create in-process tools server with schema manager
tools_server = create_sdk_tools_server(
    schema_manager=schema_manager,
    name="schema_tools",
    version="1.0.0"
)

# Tools available:
# - mcp__schema_tools__get_node_labels
# - mcp__schema_tools__get_valid_pairs
# - mcp__schema_tools__validate_relationship_triplet
# - mcp__schema_tools__get_node_properties
# - mcp__schema_tools__get_outgoing_relationships
# - mcp__schema_tools__get_incoming_relationships
# - mcp__schema_tools__get_schema_overview
```

**Design Decision:** Schema tools are in-process (use schema_manager directly) while Neo4j query tools go through external MCP servers. This avoids async issues in the subprocess context.

## Agent Tool Definitions

Each agent defines two tool lists:

```python
class ThinkerAgent(BaseAgent):
    # Short names for OpenAI API / ToolManager
    ALLOWED_TOOLS = [
        "neo4j_execute_query",
        "get_node_labels",
        "validate_relationship_triplet",
    ]

    # Fully qualified names for Claude SDK fallback
    SDK_ALLOWED_TOOLS = [
        "mcp__neo4j_memory__neo4j_execute_query",
        "mcp__schema_tools__get_node_labels",
        "mcp__schema_tools__validate_relationship_triplet",
    ]
```

| Agent | Purpose | Key Tools |
|-------|---------|-----------|
| **ThinkerAgent** | Analyze queries, generate Cypher | Schema tools, neo4j_execute_query |
| **EntityResolutionAgent** | Resolve entity names | neo4j_fuzzy_search, neo4j_execute_query |
| **ExecutorVerifierAgent** | Execute queries, build findings | neo4j_execute_query, neo4j_execute_batch_cypher |
| **CypherValidatorAgent** | Validate Cypher syntax | neo4j_execute_query (for testing) |

## Security Features

### Multi-Layer Security

```
Layer 1: Prompt Validation
    └─ InputPromptValidator blocks injection attempts

Layer 2: Tool Blocking
    ├─ Built-in tools blocked (Bash, Read, Write, Glob, etc.)
    └─ Per-agent tool whitelist enforcement

Layer 3: Pre-Tool Hooks
    ├─ Inspect tool before execution
    └─ Validate Cypher queries for write operations

Layer 4: Read-Only Enforcement
    ├─ CypherQueryValidator blocks CREATE, MERGE, DELETE, SET, REMOVE
    └─ System prompt emphasizes READ-ONLY mode

Layer 5: Observer Integration
    └─ CPGObserverAgent tracks all query execution for audit
```

### Blocked Built-in Tools

The following Claude built-in tools are blocked by default:
- `Bash`, `Read`, `Write`, `Edit`
- `Glob`, `Grep`, `LS`
- `MultiEdit`, `NotebookEdit`, `NotebookRead`
- `WebFetch`, `WebSearch`
- `Task`, `TodoRead`, `TodoWrite`

### Always-Allowed SDK Internal Tools

These tools are always allowed (used by SDK itself):
- `StructuredOutput` - for JSON responses
- `ListMcpResourcesTool` - for MCP discovery
- `ListMcpToolsTool` - for tool discovery

## Session Management

### Three-Level Strategy

```
Level 1: SDK Session (ClaudeSDKClient)
    └─ Session ID assigned by Claude SDK, preserves multi-turn context

Level 2: Agent Session (AgentSessionManager)
    └─ One session per agent, tracks session_id from Level 1

Level 3: Per-Agent Locks (asyncio.Lock)
    └─ Serializes concurrent calls to same agent
```

### Session Lifecycle

```
First Query to Agent:
    session_id = None  →  New session
           ↓
    SDK assigns session_id
           ↓
    Store in AgentSessionManager
           ↓
    session_id = "s_xxxx"

Subsequent Queries:
    session_id = "s_xxxx"  →  Resume session
           ↓
    Context preserved across queries
```

### Parallel Execution

```python
# Parallel subqueries calling different agents - runs concurrently
async with asyncio.TaskGroup() as tg:
    tg.create_task(query_thinker_agent(sq1))    # No wait
    tg.create_task(query_executor_agent(sq2))   # No wait (different agent)
    tg.create_task(query_thinker_agent(sq3))    # Waits for sq1 (same agent)
```

## Fallback Decision Tree

```
client.chat.completions.create()
    │
    ▼
Is primary disabled?
    ├─ YES → Skip to fallback
    └─ NO → Try primary (OpenAI)
              │
              ├─ Success → Return response
              ├─ Connection/Timeout/Rate limit → Fallback
              ├─ 5xx error → Fallback
              └─ 4xx error → Raise (don't retry)

Is fallback enabled?
    ├─ NO → Raise original error
    └─ YES ↓

Is per-agent mode enabled + agent_context provided?
    ├─ YES → PerAgentSDKClient (per-agent tool restrictions)
    └─ NO → ClaudeSDKFallback (shared tools)
```

## Configuration

### MCP Config File Format

```json
{
  "mcpServers": {
    "neo4j_memory": {
      "transport": "sse",
      "url": "http://localhost:8100/sse"
    }
  }
}
```

### SystemConfig Options

```python
from src.core.graph_rag.core.config import SystemConfig

config = SystemConfig(
    # Fallback settings
    fallback_enabled=True,
    fallback_mode="direct",  # "direct" or "adapter"
    fallback_model="claude-sonnet-4-20250514",
    fallback_max_turns=10,
    fallback_strict_security=True,
    fallback_validate_cypher=True,
    fallback_block_builtin_tools=True,

    # MCP config path
    mcp_config_path="/path/to/mcp_config.json"
)
```

## Usage in Graph RAG Orchestrator

```python
# In MultiAgentCoTOrchestrator.initialize()

# 1. Create resilient client with fallback
self._openai = self._config.get_llm_client(use_fallback=True)

# 2. Load schema and set tool context for in-process tools
schema_manager = DynamicSchemaManager(...)
await schema_manager.initialize(mcp_session)
self._openai.set_tool_context(schema_manager, mcp_session)

# 3. Enable per-agent mode for parallel execution
self._openai.enable_per_agent_mode(session_manager)

# 4. Agents use client normally - fallback is transparent
response = self._create_chat_completion(
    messages=messages,
    tools=tools,
    response_format={"type": "json_object"}
)

# 5. Clean up at end
await self._openai.close_all_agent_sessions()
```

## Frozen Models and Immutability

Pydantic models like `QueryDecomposition` use `frozen=True` for parallel safety:

```python
class QueryDecomposition(BaseModel):
    model_config = ConfigDict(frozen=True)  # Immutable

    original_query: str
    sub_queries: List[SubQuery]
    reasoning: str
```

**Why frozen?** During parallel execution, multiple agents may reference the same decomposition. Immutability prevents accidental modifications that could cause race conditions.

**Working with frozen models:**
```python
# WRONG - will raise "Instance is frozen" error
decomposition.sub_queries = truncated_list

# CORRECT - create new object
decomposition = QueryDecomposition(
    original_query=decomposition.original_query,
    sub_queries=truncated_list,
    reasoning=decomposition.reasoning
)
```

## Troubleshooting

### Common Issues

1. **"Instance is frozen" error**
   - Cause: Trying to modify a frozen Pydantic model
   - Fix: Create a new instance instead of modifying

2. **Built-in tools being blocked repeatedly**
   - Expected behavior: Claude tries built-in tools first, they get blocked, then it uses MCP tools
   - The system prompt guides Claude to use MCP tools

3. **"name 'X' is not defined" after editing**
   - Cause: Missing import after adding new class usage
   - Fix: Add the import statement

4. **Session context not preserved**
   - Cause: Using `session_id` parameter instead of `resume` in ClaudeAgentOptions
   - Fix: Use `resume=session_id` for session continuation

### Debug Logging

Enable detailed logging:
```python
import logging
logging.getLogger("src.core.graph_rag.core.claude_sdk_fallback").setLevel(logging.DEBUG)
logging.getLogger("src.core.graph_rag.core.per_agent_sdk_client").setLevel(logging.DEBUG)
```

## Summary

The Claude SDK integration provides a robust fallback mechanism that:

1. **Transparently handles** OpenAI unavailability
2. **Preserves per-agent tool restrictions** via session management
3. **Enforces security** through multiple validation layers
4. **Supports parallel execution** with per-agent locks
5. **Maintains conversation context** across multi-turn queries

The key architectural decisions:
- **Dual tool lists** (ALLOWED_TOOLS + SDK_ALLOWED_TOOLS) for compatibility
- **In-process schema tools** vs external MCP tools for reliability
- **Frozen models** for parallel safety
- **Hook-based security** for runtime enforcement

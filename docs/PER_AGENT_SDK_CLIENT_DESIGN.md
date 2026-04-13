# Per-Agent Claude SDK Client Design

## Implementation Status

**Status: IMPLEMENTED** (2026-01-14)

The Session-Based Per-Agent Clients (Approach 4) has been implemented in the following files:
- `src/core/graph_rag/core/per_agent_sdk_client.py` - AgentSessionManager and PerAgentSDKClient
- `src/core/graph_rag/core/llm_client.py` - Integration with ResilientLLMClient
- `src/core/graph_rag/agents/base_agent.py` - Agent context passing

See [Usage](#usage-example) section below for how to enable per-agent mode.

---

## Problem Statement

Currently, all agents share ONE `ResilientLLMClient` instance. When Claude SDK fallback is triggered, all agents get access to the same tools, losing per-agent restrictions.

## Current Architecture

```
                    ┌─────────────────────────────┐
                    │      Orchestrator           │
                    │  self._openai = create()    │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │   ResilientLLMClient        │
                    │   (ONE shared instance)     │
                    │   _allowed_tools = [...]    │  ← Single tool config
                    │   _sdk_fallback = SDK()     │  ← Single SDK client
                    └─────────────┬───────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│ ThinkerAgent  │       │ValidatorAgent │       │ExecutorAgent  │
│ ALLOWED_TOOLS │       │ ALLOWED_TOOLS │       │ ALLOWED_TOOLS │
│ (IGNORED!)    │       │ (IGNORED!)    │       │ (IGNORED!)    │
└───────────────┘       └───────────────┘       └───────────────┘
```

## Proposed Solutions

### Approach 1: Per-Agent SDK Client Factory

Create separate `ClaudeSDKFallback` instances for each agent, each configured with agent-specific tools.

```
                    ┌─────────────────────────────┐
                    │      Orchestrator           │
                    │  client_factory = Factory() │
                    └─────────────┬───────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ ThinkerAgent      │   │ ValidatorAgent    │   │ ExecutorAgent     │
│                   │   │                   │   │                   │
│ _sdk_client =     │   │ _sdk_client =     │   │ _sdk_client =     │
│   factory.get(    │   │   factory.get(    │   │   factory.get(    │
│     ALLOWED_TOOLS │   │     ALLOWED_TOOLS │   │     ALLOWED_TOOLS │
│   )               │   │   )               │   │   )               │
└───────────────────┘   └───────────────────┘   └───────────────────┘
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ SDKClient #1      │   │ SDKClient #2      │   │ SDKClient #3      │
│ tools: schema     │   │ tools: schema     │   │ tools: execute    │
│ hook: block others│   │ hook: block others│   │ hook: block others│
└───────────────────┘   └───────────────────┘   └───────────────────┘
```

**Pros:**
- Clean separation - each agent has its own SDK instance
- Tool restrictions enforced per-agent
- Hook blocking is specific to each agent's forbidden tools

**Cons:**
- Multiple Claude Code CLI subprocesses (resource intensive)
- Each subprocess needs initialization time
- More memory usage
- Potential concurrency issues

**Implementation:**

```python
class ClaudeSDKClientFactory:
    """Factory to create per-agent Claude SDK clients."""

    def __init__(self, base_config: Dict[str, Any], schema_manager, mcp_session):
        self._base_config = base_config
        self._schema_manager = schema_manager
        self._mcp_session = mcp_session
        self._clients: Dict[str, ClaudeSDKFallback] = {}

    def get_client(self, agent_id: str, allowed_tools: List[str]) -> ClaudeSDKFallback:
        """Get or create an SDK client for a specific agent."""
        cache_key = f"{agent_id}:{','.join(sorted(allowed_tools))}"

        if cache_key not in self._clients:
            self._clients[cache_key] = ClaudeSDKFallback(
                **self._base_config,
                allowed_tools=allowed_tools,
                agent_id=agent_id,
                # Hook configured to ONLY allow these tools
                pre_tool_hook=self._create_tool_filter(allowed_tools)
            )

        return self._clients[cache_key]

    def _create_tool_filter(self, allowed_tools: List[str]):
        """Create a hook that blocks tools not in allowed list."""
        def filter_hook(tool_name, tool_input):
            if tool_name not in allowed_tools:
                return False  # Block
            return True  # Allow
        return filter_hook
```

---

### Approach 2: Agent-Aware Hook (Single Client)

Keep single SDK client but pass agent's allowed tools per-call, using hook to enforce restrictions.

```
                    ┌─────────────────────────────┐
                    │      Orchestrator           │
                    │  self._openai = create()    │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │   ResilientLLMClient        │
                    │   (ONE shared instance)     │
                    │   _sdk_fallback = SDK()     │
                    └─────────────┬───────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ ThinkerAgent      │   │ ValidatorAgent    │   │ ExecutorAgent     │
│ ALLOWED_TOOLS     │   │ ALLOWED_TOOLS     │   │ ALLOWED_TOOLS     │
│       │           │   │       │           │   │       │           │
│       ▼           │   │       ▼           │   │       ▼           │
│ create(...,       │   │ create(...,       │   │ create(...,       │
│   agent_tools=    │   │   agent_tools=    │   │   agent_tools=    │
│   ALLOWED_TOOLS)  │   │   ALLOWED_TOOLS)  │   │   ALLOWED_TOOLS)  │
└───────────────────┘   └───────────────────┘   └───────────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │   SDK Pre-Tool Hook         │
                    │   if tool not in            │
                    │     current_agent_tools:    │
                    │       BLOCK                 │
                    └─────────────────────────────┘
```

**Pros:**
- Single SDK client (less resource usage)
- No subprocess overhead per agent
- Dynamic tool filtering per call

**Cons:**
- Need to pass tool context through call chain
- More complex state management
- Hook needs to track "current agent" context
- Potential race conditions with concurrent calls

**Implementation:**

```python
# In ResilientLLMClient
class Completions:
    def create(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,  # OpenAI tools
        agent_allowed_tools: Optional[List[str]] = None,  # NEW: For SDK fallback
        **kwargs
    ):
        # ... existing code ...

        # On fallback, pass agent's allowed tools
        if agent_allowed_tools:
            self._parent.set_current_agent_tools(agent_allowed_tools)

        # ... fallback code ...

# In ClaudeSDKFallback
def set_current_agent_tools(self, tools: List[str]):
    """Set the allowed tools for the current call."""
    self._current_agent_tools = tools

# In pre-tool hook
def pre_tool_hook(tool_name, tool_input):
    if self._current_agent_tools:
        if tool_name not in self._current_agent_tools:
            return BLOCK
    return ALLOW
```

---

### Approach 3: Hybrid - Lazy Per-Agent Clients

Create SDK clients lazily when fallback is needed, reuse across calls for same agent.

```python
class AgentAwareResilientClient:
    """Client that creates per-agent SDK fallbacks lazily."""

    def __init__(self, base_config: Dict):
        self._base_config = base_config
        self._agent_fallbacks: Dict[str, ClaudeSDKFallback] = {}

    def create_for_agent(self, agent_id: str, allowed_tools: List[str]):
        """Get completion creator configured for a specific agent."""
        if agent_id not in self._agent_fallbacks:
            # Create SDK client lazily on first fallback
            self._agent_fallbacks[agent_id] = ClaudeSDKFallback(
                **self._base_config,
                allowed_tools=allowed_tools,
                agent_id=agent_id
            )
        return AgentCompletions(self, agent_id, allowed_tools)
```

---

## Recommendation

**For immediate implementation**: Approach 2 (Agent-Aware Hook)
- Lower resource usage
- Simpler to implement
- Can be done incrementally

**For production quality**: Approach 1 or 3 (Per-Agent Clients)
- Cleaner architecture
- Better isolation
- More robust tool enforcement

---

## Implementation Steps (Approach 2)

1. **Modify BaseAgent** to pass its `ALLOWED_TOOLS` when making LLM calls
2. **Modify ResilientLLMClient.Completions.create()** to accept `agent_allowed_tools` parameter
3. **Modify ClaudeSDKFallback** to track current agent's allowed tools
4. **Update pre-tool hook** to check against current agent's tools (not global list)
5. **Clear context after call** to prevent leakage between agents

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Concurrent agent calls may conflict | Use thread-local storage for current agent context |
| Hook may block legitimate tools | Extensive logging of block decisions |
| Performance impact of multiple SDK clients | Use client pooling/caching |
| Subprocess resource exhaustion | Limit max concurrent SDK clients |

---

## Approach 4: Session-Based Per-Agent Clients (RECOMMENDED)

The Claude SDK supports **session persistence and resumption**:

```python
# StreamEvent contains session_id
StreamEvent: {
    'uuid': str,
    'session_id': str,      # ← Can be stored and reused!
    'event': dict,
    'parent_tool_use_id': str | None
}

# ClaudeAgentOptions supports resuming
ClaudeAgentOptions(
    resume="session_abc123",     # Resume previous session
    continue_conversation=True,   # Or continue last conversation
    fork_session=False            # Or fork from existing
)
```

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     AgentSessionManager                              │
│                                                                      │
│  _sessions: Dict[str, AgentSession] = {                             │
│    "ThinkerAgent": AgentSession(                                    │
│        session_id="sess_abc123",                                    │
│        allowed_tools=["get_node_labels", "get_valid_pairs", ...],   │
│        last_used=datetime.now(),                                    │
│        context_preserved=True                                       │
│    ),                                                                │
│    "ExecutorAgent": AgentSession(                                   │
│        session_id="sess_def456",                                    │
│        allowed_tools=["neo4j_execute_query", ...],                  │
│        last_used=datetime.now(),                                    │
│        context_preserved=True                                       │
│    )                                                                 │
│  }                                                                   │
│                                                                      │
│  + get_or_create_session(agent_id, allowed_tools) -> session_id     │
│  + close_session(agent_id)                                          │
│  + cleanup_stale_sessions(max_age)                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Flow

```
ThinkerAgent needs to make a call
         │
         ▼
┌─────────────────────────────┐
│ SessionManager.get_session( │
│   agent_id="ThinkerAgent",  │
│   allowed_tools=[...]       │
│ )                           │
└─────────────┬───────────────┘
              │
              ▼
     ┌────────────────┐
     │ Session exists?│
     └───────┬────────┘
             │
      ┌──────┴──────┐
      │             │
      ▼             ▼
    [NO]          [YES]
      │             │
      ▼             ▼
┌───────────┐  ┌───────────────┐
│ Create    │  │ Return        │
│ new query │  │ resume=       │
│ resume=   │  │ session_id    │
│ None      │  │               │
└─────┬─────┘  └───────┬───────┘
      │                │
      └───────┬────────┘
              │
              ▼
┌─────────────────────────────┐
│ ClaudeAgentOptions(         │
│   resume=session_id,        │  ← Context preserved!
│   allowed_tools=[...],      │  ← Per-agent tools!
│   hooks=[tool_filter_hook]  │  ← Enforce restrictions!
│ )                           │
└─────────────────────────────┘
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **Context Preservation** | Session retains conversation history, tool results, reasoning |
| **Resource Efficient** | No need to keep subprocesses running; resume on demand |
| **Per-Agent Isolation** | Each agent has its own session with own tool config |
| **Clean State Management** | Sessions can be closed, forked, or cleaned up |
| **Resumable** | If a query is interrupted, can resume from where it left off |
| **Parallel Safe** | Per-agent locks serialize SDK calls for concurrent subqueries |

### Parallel Safety (Added)

When multiple subqueries run in parallel and invoke the same agent (e.g., SQ1.ThinkerAgent and SQ2.ThinkerAgent), the `PerAgentSDKClient` acquires a per-agent lock to serialize SDK calls:

```
SQ1 and SQ2 run in parallel, both need ThinkerAgent:

SQ1.ThinkerAgent ──┐
                   │ acquire_lock("ThinkerAgent")
SQ2.ThinkerAgent ──┤
                   │
                   ▼
           ┌──────────────────┐
           │  Per-Agent Lock  │
           │  (ThinkerAgent)  │
           └────────┬─────────┘
                    │
        ┌───────────┴───────────┐
        │ SQ1 gets lock first   │
        │                       │
        ▼                       │
   SDK Call for SQ1             │ SQ2 waits
        │                       │
        ▼                       │
   Response + Context           │
        │                       │
   Release lock ────────────────┤
                                │
                                ▼
                          SQ2 gets lock
                                │
                                ▼
                          SDK Call for SQ2
                          (has context from SQ1!)
                                │
                                ▼
                          Response
```

**Key points:**
- Subqueries still run in parallel for OpenAI calls (primary path)
- Only SDK fallback calls are serialized per-agent
- Context from earlier subquery benefits later ones
- Lock is automatically released even on errors (async with)

### Implementation

```python
from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime
import asyncio

@dataclass
class AgentSession:
    """Represents a Claude SDK session for an agent."""
    agent_id: str
    session_id: Optional[str]  # None until first query
    allowed_tools: List[str]
    created_at: datetime
    last_used: datetime
    query_count: int = 0


class AgentSessionManager:
    """Manages Claude SDK sessions per agent."""

    def __init__(self, base_config: Dict):
        self._base_config = base_config
        self._sessions: Dict[str, AgentSession] = {}
        self._lock = asyncio.Lock()

    async def get_session(
        self,
        agent_id: str,
        allowed_tools: List[str]
    ) -> Optional[str]:
        """
        Get session_id for an agent. Returns None for new sessions.

        Args:
            agent_id: Unique agent identifier
            allowed_tools: Tools this agent is allowed to use

        Returns:
            session_id to resume, or None for new session
        """
        async with self._lock:
            if agent_id not in self._sessions:
                # Create new session record (no session_id yet)
                self._sessions[agent_id] = AgentSession(
                    agent_id=agent_id,
                    session_id=None,
                    allowed_tools=allowed_tools,
                    created_at=datetime.now(),
                    last_used=datetime.now()
                )
                return None  # New session

            session = self._sessions[agent_id]
            session.last_used = datetime.now()
            session.query_count += 1
            return session.session_id  # Resume existing

    async def update_session_id(self, agent_id: str, session_id: str):
        """Update session_id after first query completes."""
        async with self._lock:
            if agent_id in self._sessions:
                self._sessions[agent_id].session_id = session_id

    async def close_session(self, agent_id: str):
        """Close and remove a session."""
        async with self._lock:
            if agent_id in self._sessions:
                del self._sessions[agent_id]

    async def cleanup_stale_sessions(self, max_age_seconds: int = 3600):
        """Remove sessions not used within max_age."""
        async with self._lock:
            now = datetime.now()
            stale = [
                agent_id for agent_id, session in self._sessions.items()
                if (now - session.last_used).seconds > max_age_seconds
            ]
            for agent_id in stale:
                del self._sessions[agent_id]


class PerAgentSDKClient:
    """Claude SDK client with per-agent session management."""

    def __init__(
        self,
        mcp_config_path: str,
        schema_manager,
        session_manager: AgentSessionManager
    ):
        self._mcp_config_path = mcp_config_path
        self._schema_manager = schema_manager
        self._session_manager = session_manager

    async def query(
        self,
        agent_id: str,
        allowed_tools: List[str],
        prompt: str,
        system_prompt: Optional[str] = None
    ):
        """
        Execute a query for a specific agent with tool restrictions.

        Args:
            agent_id: Which agent is making the query
            allowed_tools: Tools this agent can use
            prompt: The query prompt
            system_prompt: Optional system prompt
        """
        from claude_agent_sdk import query, ClaudeAgentOptions
        from claude_agent_sdk.types import HookMatcher, SyncHookJSONOutput

        # Get session_id for this agent (None if new)
        session_id = await self._session_manager.get_session(
            agent_id, allowed_tools
        )

        # Create tool filter hook for this agent's allowed tools
        def create_tool_filter_hook(allowed: List[str]):
            async def hook(hook_input, tool_use_id, context):
                tool_name = hook_input.get("tool_name", "")

                # Check against agent's allowed tools
                if tool_name not in allowed:
                    return SyncHookJSONOutput(
                        continue_=True,
                        hookSpecificOutput={
                            'hookEventName': 'PreToolUse',
                            'permissionDecision': 'deny',
                            'permissionDecisionReason': f"Tool '{tool_name}' not allowed for {agent_id}"
                        }
                    )
                return SyncHookJSONOutput(continue_=True)
            return hook

        # Build options with session resumption
        options = ClaudeAgentOptions(
            resume=session_id,  # Resume if exists, None for new
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,  # Hint (may be ignored by SDK)
            mcp_servers=self._load_mcp_config(),
            hooks={
                "PreToolUse": [
                    HookMatcher(
                        matcher=".*",
                        hooks=[create_tool_filter_hook(allowed_tools)]
                    )
                ]
            }
        )

        # Execute query
        response_text = ""
        new_session_id = None

        async for event in query(prompt=prompt, options=options):
            if hasattr(event, 'session_id'):
                new_session_id = event.session_id
            if hasattr(event, 'result'):
                response_text = event.result

        # Update session_id if this was first query
        if new_session_id and session_id is None:
            await self._session_manager.update_session_id(
                agent_id, new_session_id
            )

        return response_text
```

### Usage in Agents

```python
class ThinkerAgent(BaseAgent):
    ALLOWED_TOOLS = [
        "get_node_labels",
        "get_node_properties",
        "get_valid_pairs",
        # ...
    ]

    async def execute(self, sub_query, context):
        # When SDK fallback is needed
        response = await self._sdk_client.query(
            agent_id=self._agent_id,        # "ThinkerAgent"
            allowed_tools=self.ALLOWED_TOOLS,  # Per-agent!
            prompt=self._build_prompt(sub_query, context),
            system_prompt=THINKER_SYSTEM_PROMPT
        )
        return self._parse_response(response)
```

### Session Lifecycle

```
Workflow Start
     │
     ▼
┌────────────────────────────┐
│ Create SessionManager      │
│ (empty sessions dict)      │
└─────────────┬──────────────┘
              │
     ┌────────┴────────┐
     │                 │
     ▼                 ▼
[ThinkerAgent]    [ExecutorAgent]
     │                 │
     ▼                 ▼
1st query:         1st query:
session_id=None    session_id=None
     │                 │
     ▼                 ▼
SDK creates        SDK creates
new session        new session
     │                 │
     ▼                 ▼
Returns            Returns
sess_abc123        sess_def456
     │                 │
     ▼                 ▼
Store in           Store in
SessionManager     SessionManager
     │                 │
     ▼                 ▼
2nd query:         2nd query:
resume=            resume=
sess_abc123        sess_def456
     │                 │
     ▼                 ▼
Context            Context
preserved!         preserved!
     │                 │
     └────────┬────────┘
              │
              ▼
     Workflow Complete
              │
              ▼
┌────────────────────────────┐
│ SessionManager.cleanup()   │
│ Close all sessions         │
└────────────────────────────┘
```

### Comparison with Other Approaches

| Feature | Approach 1 (Per-Client) | Approach 2 (Hook) | Approach 4 (Sessions) |
|---------|------------------------|-------------------|----------------------|
| Per-agent tool restrictions | ✅ | ⚠️ Complex | ✅ |
| Resource efficiency | ❌ Multiple processes | ✅ Single | ✅ On-demand |
| Context preservation | ❌ Lost between calls | ❌ Lost | ✅ Preserved |
| Implementation complexity | Medium | Medium | Medium |
| Session management | None | None | ✅ Built-in |
| Resumable queries | ❌ | ❌ | ✅ |
| Parallel subquery safe | ⚠️ Race conditions | ❌ | ✅ Per-agent locks |

**Recommendation: Approach 4 (Session-Based) is the best solution** because it provides per-agent tool restrictions while preserving context and being resource efficient.

---

## Usage Example

### Enabling Per-Agent Mode

```python
from src.core.graph_rag.core.llm_client import ResilientLLMClient

# Create the client
client = ResilientLLMClient(
    primary_config={"api_key": "sk-..."},
    fallback_mode="direct",
    mcp_config_path="/path/to/mcp_config.json",
    block_builtin_tools=True  # Block Bash, Read, Write, etc.
)

# Enable per-agent mode (creates AgentSessionManager automatically)
client.enable_per_agent_mode()

# Now SDK fallback will use per-agent sessions with tool restrictions
```

### Agents Automatically Pass Context

When `BaseAgent._create_chat_completion()` is called, agent context is automatically
passed if the agent has `ALLOWED_TOOLS` defined:

```python
class ThinkerAgent(BaseAgent):
    ALLOWED_TOOLS = [
        "mcp__cpg_tools__get_node_labels",
        "mcp__cpg_tools__get_node_properties",
        "mcp__cpg_tools__get_valid_pairs",
        # ...
    ]

    async def execute(self, sub_query, context):
        # When SDK fallback is triggered, ThinkerAgent's ALLOWED_TOOLS
        # will be enforced - only schema discovery tools are allowed
        response = self._create_chat_completion(messages=[...])
        return response
```

### Closing Sessions at Workflow End

```python
# At the end of workflow
await client.close_all_agent_sessions()

# Or get session stats
stats = await client.get_agent_session_stats()
print(stats)
# Output:
# {
#     "total_sessions": 4,
#     "agents": {
#         "ThinkerAgent": {"query_count": 5, "blocked_tool_attempts": 12, ...},
#         "ExecutorAgent": {"query_count": 3, "blocked_tool_attempts": 0, ...}
#     }
# }
```

### Direct Use of PerAgentSDKClient

For advanced use cases, you can use `PerAgentSDKClient` directly:

```python
from src.core.graph_rag.core.per_agent_sdk_client import (
    PerAgentSDKClient,
    AgentSessionManager
)

session_manager = AgentSessionManager()
sdk_client = PerAgentSDKClient(
    mcp_config_path="/path/to/config.json",
    schema_manager=schema_manager,
    session_manager=session_manager,
    block_builtin_tools=True
)

# Each agent gets its own session with its own tool restrictions
response = await sdk_client.query(
    agent_id="ThinkerAgent",
    allowed_tools=["mcp__cpg_tools__get_node_labels", ...],
    prompt="Find all Function nodes in the codebase"
)

# Different agent, different session, different tools
response = await sdk_client.query(
    agent_id="ExecutorAgent",
    allowed_tools=["mcp__neo4j_memory__neo4j_execute_query"],
    prompt="Execute: MATCH (n:Function) RETURN n.name LIMIT 10"
)

# Close all sessions when done
await sdk_client.close_all_sessions()
```

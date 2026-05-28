# Claude SDK Integration Challenges

## Executive Summary

This document outlines the technical challenges encountered when integrating the Claude Agent SDK as a fallback for our Graph RAG workflow system. The Claude Agent SDK (which wraps Claude Code CLI) presents significant architectural differences compared to direct API access (Anthropic API or OpenAI API), making it unsuitable as a drop-in replacement for our use case.

## Background

Our system uses a 4-Agent Team architecture (Thinker → ThinkingValidator → CypherValidator → Executor) that requires:
- Precise control over which tools each agent can use
- Integration with external MCP servers (Neo4j)
- Structured JSON output from LLM responses
- Read-only query execution with security validation

## Critical Issues Identified

### 1. Built-in Tools Cannot Be Disabled

**Issue**: The Claude Agent SDK (Claude Code) comes with 15+ built-in tools that cannot be removed:
- Bash, Read, Write, Edit, Glob, Grep, LS, MultiEdit
- NotebookEdit, NotebookRead, Task, TodoRead, TodoWrite
- WebFetch, WebSearch

**Impact**: Our agents require restricted tool access (e.g., only schema discovery tools), but Claude Code always has access to file system and shell operations, creating security concerns and workflow interference.

**Evidence**: Even when we block these tools via hooks, Claude continues attempting to use them as fallbacks.

---

### 2. `allowed_tools` Parameter is Ignored (Known Bug)

**Issue**: The `allowed_tools` parameter in `ClaudeAgentOptions` is documented but **does not work**. This is a confirmed bug (GitHub Issue #361).

**Expected Behavior**:
```python
options = ClaudeAgentOptions(
    allowed_tools=["mcp__neo4j__execute_query"]  # Only allow this tool
)
```

**Actual Behavior**: All tools remain available regardless of this setting.

**Workaround Attempted**: Using `PreToolUse` hooks to block tools - partially effective but Claude still attempts blocked tools repeatedly.

---

### 3. `disallowed_tools` Parameter Doesn't Block Built-in Tools

**Issue**: The `disallowed_tools` parameter only affects MCP tools, not Claude Code's built-in tools.

**Impact**: Cannot prevent Claude from using Bash, Read, Write, etc. even when explicitly listed in `disallowed_tools`.

---

### 4. Hook-Based Tool Blocking Has Limitations

**Issue**: The only reliable way to block tools is via `PreToolUse` hooks with `permissionDecision: 'deny'`. However:

1. **Return format is fragile**: Returning `None` causes `'NoneType' object has no attribute 'items'` errors
2. **Claude doesn't learn**: After a tool is blocked, Claude tries other built-in tools as alternatives
3. **Repeated attempts**: Claude may attempt the same blocked tool multiple times per query
4. **No feedback loop**: The denial reason doesn't effectively guide Claude to use allowed tools

**Example from logs**:
```
🚫 BLOCKED: Built-in tool 'Bash' is not permitted.
🚫 BLOCKED: Built-in tool 'Glob' is not permitted.
🚫 BLOCKED: Built-in tool 'Read' is not permitted.
🚫 BLOCKED: Built-in tool 'Bash' is not permitted.  # Same tool, tried again
🚫 BLOCKED: Built-in tool 'Bash' is not permitted.  # And again
```

---

### 5. In-Process MCP Tools Don't Work with External Sessions ✅ SOLVED

**Issue**: The SDK's `create_sdk_mcp_server()` allows creating in-process tools, but these tools cannot reliably call external MCP servers.

**Technical Details**:
- MCP session is created in the main application's async event loop
- SDK executes tools in a different async context (subprocess communication)
- `await mcp_session.call_tool()` hangs indefinitely due to event loop mismatch

**Evidence from logs**:
```
SDK neo4j_fuzzy_search called: search_term=WorkerZ, limit=10
MCP session type: <class 'mcp_use.session.MCPSession'>
Calling mcp_session.call_tool...
# No response - hangs here, then Claude tries other tools
```

**Solution Implemented**: Separate schema tools from MCP tools:
- **Schema tools** (get_node_labels, etc.) use `schema_manager` directly (synchronous Python) - work in-process ✅
- **MCP tools** (neo4j_execute_query, fuzzy_search) go through external MCP servers via HTTP/SSE ✅

**Files Updated**:
- `src/core/graph_rag/core/sdk_tools.py` - Removed MCP-dependent tools from in-process server
- `src/core/graph_rag/core/per_agent_sdk_client.py` - Creates in-process schema tools separately

---

### 6. Subprocess Architecture Creates Integration Barriers

**Issue**: Claude Code runs as a subprocess, not as an in-process library call.

**Implications**:
- Cannot share Python objects (like MCP sessions) between main process and Claude Code
- Tool execution happens in isolated subprocess context
- State management is complex
- Debugging is difficult (errors appear as minified JS stack traces)

**Workaround**: Use two types of tools:
- **In-process tools**: For schema discovery (uses Python objects directly)
- **External MCP servers**: For Neo4j queries (uses HTTP/SSE, works across process boundary)

**Example Error**:
```
Error in hook callback hook_0: 4951 | `),enablePromptCaching:!0,signal:new AbortController()...
error: 'NoneType' object has no attribute 'items'
    at processLine (/$bunfs/root/claude:4956:837)
```

---

### 7. System Prompt Guidance is Not Respected

**Issue**: Even explicit instructions in the system prompt to avoid certain tools are ignored.

**Example System Prompt**:
```
**FORBIDDEN - WILL BE BLOCKED:**
- Bash, Read, Write, Glob, Grep, Edit, LS, Task, TodoWrite, TodoRead
- ANY file system operations

**DO NOT ATTEMPT TO USE FORBIDDEN TOOLS.** They WILL fail.
```

**Actual Behavior**: Claude still attempts Bash, Glob, Read, etc.

---

### 8. No "Bare Agent" Configuration

**Issue**: There is no way to instantiate Claude Code without its built-in tools. The SDK is designed as a general-purpose coding assistant, not a restricted agent.

**Comparison**:
| Feature | OpenAI API | Anthropic API | Claude SDK |
|---------|------------|---------------|------------|
| Custom tools only | ✅ | ✅ | ❌ |
| No built-in tools | ✅ | ✅ | ❌ |
| Tool whitelist works | ✅ | ✅ | ❌ (bug) |
| Predictable tool usage | ✅ | ✅ | ❌ |

---

### 9. Structured Output Handling Differs

**Issue**: The SDK's response format differs from standard API responses, requiring additional parsing logic.

- OpenAI/Anthropic: Direct JSON in `response.choices[0].message.content`
- Claude SDK: Wrapped in `ClaudeSDKResponse` with different structure, tool calls tracked separately

---

### 10. Cost and Performance Overhead

**Issue**: The subprocess architecture adds latency and makes cost tracking difficult.

- Each query spawns a subprocess
- Tool calls go through IPC
- Token usage tracking is indirect
- No direct control over API parameters like temperature per-call

---

### 11. Per-Agent Tool Restrictions Are Lost

**Issue**: Our multi-agent architecture requires different tools for different agents. With OpenAI/Anthropic APIs, each agent passes its own `ALLOWED_TOOLS` list. With Claude SDK fallback, all agents share ONE client instance, losing per-agent restrictions.

**Architecture**:
```
OpenAI API (Working):
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  ThinkerAgent   │     │ ValidatorAgent  │     │ ExecutorAgent   │
│  ALLOWED_TOOLS: │     │  ALLOWED_TOOLS: │     │  ALLOWED_TOOLS: │
│  - get_node_*   │     │  - get_node_*   │     │  - neo4j_execute│
│  - get_valid_*  │     │  - validate_*   │     │  - fuzzy_search │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┴───────────────────────┘
                                 │
                    Each call specifies its own tools
                                 ↓
                         ┌──────────────┐
                         │  OpenAI API  │
                         └──────────────┘

Claude SDK Fallback (Broken):
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  ThinkerAgent   │     │ ValidatorAgent  │     │ ExecutorAgent   │
│  (tools ignored)│     │  (tools ignored)│     │  (tools ignored)│
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┴───────────────────────┘
                                 │
                    All share ONE client instance
                                 ↓
                    ┌────────────────────────┐
                    │  Shared SDK Client     │
                    │  (single tool config)  │
                    │  + 15 built-in tools   │
                    └────────────────────────┘
```

**Per-Agent Tool Configuration (What We Need)**:

| Agent | Required Tools | Forbidden Tools |
|-------|---------------|-----------------|
| ThinkerAgent | get_node_labels, get_node_properties, get_valid_pairs, validate_relationship_triplet, get_outgoing_relationships | neo4j_execute_query (except exploration) |
| ThinkingValidator | get_schema_overview | All execution tools |
| CypherValidator | get_node_labels, get_node_properties, get_valid_pairs, validate_relationship_triplet | neo4j_execute_query |
| ExecutorAgent | neo4j_execute_query, neo4j_batch_execute | Schema discovery tools |
| EntityResolver | neo4j_fuzzy_search, neo4j_execute_query, get_node_properties | Other tools |

**Impact**: When Claude SDK fallback triggers, ALL agents get access to ALL tools (plus built-ins), breaking our security model and causing agents to use inappropriate tools for their role.

**Solution Implemented**: Session-Based Per-Agent Clients (see `PER_AGENT_SDK_CLIENT_DESIGN.md`):
- `AgentSessionManager` tracks sessions per agent with tool restrictions
- `PerAgentSDKClient` enforces per-agent tool whitelist via hooks
- Each agent gets its own session for context preservation
- Built-in tools are blocked per-agent (not globally)

**Files**:
- `src/core/graph_rag/core/per_agent_sdk_client.py`
- `src/core/graph_rag/core/llm_client.py` (enable_per_agent_mode)
- `src/core/graph_rag/agents/base_agent.py` (agent_context passing)

---

## Comparison: Claude SDK vs Direct API

| Capability | OpenAI API | Anthropic API | Claude SDK | Claude SDK + Per-Agent Solution |
|------------|------------|---------------|------------|-------------------------------|
| Tool restriction | Full control | Full control | Not working | ✅ Via hooks |
| Custom tools only | Yes | Yes | No (built-ins always present) | ⚠️ Built-ins blocked via hooks |
| Per-agent tool config | Yes | Yes | No (shared client) | ✅ Via session manager |
| MCP integration | Via wrapper | Via wrapper | Native but limited | ✅ Works |
| Structured output | Native | Native | Requires wrapper | ✅ Wrapper included |
| Security control | Full | Full | Limited | ✅ Improved with hooks |
| Subprocess overhead | None | None | Significant | Still significant |
| Error messages | Clear | Clear | Minified JS traces | Still limited |
| Event loop compatibility | N/A | N/A | Problematic | ✅ In-process + external tools |

---

## Recommendations

### Current State (After Per-Agent Solution)

With the `PerAgentSDKClient` implementation, Claude SDK fallback is now usable:

1. **Enable per-agent mode** in the orchestrator:
   ```python
   client.enable_per_agent_mode()
   ```
2. **Agents automatically pass context** via `ALLOWED_TOOLS` class attribute
3. **Tool restrictions are enforced** via hooks (since `allowed_tools` param is bugged)
4. **Sessions are managed per-agent** for context preservation

### Remaining Limitations

1. **Subprocess overhead** - Each query spawns a subprocess (can't fix without SDK changes)
2. **Built-in tools still exist** - We block them via hooks, but Claude still tries them sometimes
3. **Error messages** - Still minified JS traces (SDK issue)

### Recent Fixes (2026-01-14)

1. ✅ **Event loop compatibility** - Separated in-process schema tools from MCP-dependent tools:
   - Schema tools (get_node_labels, etc.) use `schema_manager` directly - work in-process
   - MCP tools (neo4j_execute_query, fuzzy_search) go through external MCP servers via HTTP/SSE

### Short Term
1. ✅ ~~Do not use Claude SDK as primary fallback~~ → Now usable with per-agent mode
2. Continue using OpenAI API as primary
3. Use Claude SDK with per-agent mode as fallback

### Medium Term
1. Monitor GitHub Issue #361 for `allowed_tools` fix (would simplify our hook-based solution)
2. Track SDK improvements for better subprocess handling

### Long Term
1. Contribute feedback to Claude SDK team about our use case
2. Evaluate when SDK adds "restricted mode" or bare agent configuration

---

## References

- GitHub Issue #361: `allowed_tools` parameter ignored
- Claude Agent SDK Documentation: https://docs.anthropic.com/claude-agent-sdk
- MCP Protocol Specification: https://modelcontextprotocol.io

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-01-14 | Engineering Team | Initial document based on integration attempts |

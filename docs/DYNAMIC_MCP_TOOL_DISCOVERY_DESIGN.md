# Dynamic MCP Tool Discovery Design

## Problem Statement

Currently, MCP tools are **hard-coded** in multiple places:
- `ToolManager._build_tools()` - lines 1149-1184
- `EntityResolutionAgent._build_tools()` - lines 1716-1763

This creates:
1. **Maintenance burden** - Update code when MCP server adds/changes tools
2. **Duplication** - Tool definitions exist in MCP server AND our code
3. **Sync issues** - Easy to get out of sync with actual MCP capabilities

## Proposed Solution

Use MCP's built-in `tools/list` (via `session.discover_tools()`) to dynamically discover tools at runtime.

## Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Current (Hard-coded)                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ToolManager                    EntityResolutionAgent           │
│  ┌─────────────────┐            ┌─────────────────┐             │
│  │ _build_tools()  │            │ _build_tools()  │             │
│  │                 │            │                 │             │
│  │ HARD-CODED:     │            │ HARD-CODED:     │             │
│  │ - neo4j_query   │            │ - fuzzy_search  │             │
│  │                 │            │ - neo4j_query   │             │
│  └────────┬────────┘            └────────┬────────┘             │
│           │                              │                       │
│           ▼                              ▼                       │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                     MCP Server                               ││
│  │  (Has its own tool definitions - SOURCE OF TRUTH)            ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Proposed (Dynamic Discovery)                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ToolManager                    EntityResolutionAgent           │
│  ┌─────────────────┐            ┌─────────────────┐             │
│  │ discover_mcp_   │            │ discover_mcp_   │             │
│  │ tools()         │            │ tools()         │             │
│  │                 │            │                 │             │
│  │ DYNAMIC:        │            │ DYNAMIC:        │             │
│  │ session.        │            │ session.        │             │
│  │ discover_tools()│            │ discover_tools()│             │
│  └────────┬────────┘            └────────┬────────┘             │
│           │                              │                       │
│           │    ┌──────────────────┐      │                       │
│           └───►│ MCP Protocol     │◄─────┘                       │
│                │ tools/list       │                              │
│                └────────┬─────────┘                              │
│                         │                                        │
│                         ▼                                        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                     MCP Server                               ││
│  │  (SINGLE SOURCE OF TRUTH for tool definitions)               ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Steps

### Step 1: Add Conversion Utility

```python
@staticmethod
def convert_mcp_tool_to_openai(mcp_tool: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert MCP tool definition to OpenAI function calling format.

    MCP format:
    {
        "name": "tool_name",
        "description": "...",
        "inputSchema": { JSON Schema }
    }

    OpenAI format:
    {
        "type": "function",
        "function": {
            "name": "tool_name",
            "description": "...",
            "parameters": { JSON Schema }
        }
    }
    """
    return {
        "type": "function",
        "function": {
            "name": mcp_tool.get("name", "unknown"),
            "description": mcp_tool.get("description", ""),
            "parameters": mcp_tool.get("inputSchema", {"type": "object", "properties": {}})
        }
    }
```

### Step 2: Add Dynamic Discovery Method to ToolManager

```python
async def discover_mcp_tools(self, tool_filter: Optional[List[str]] = None) -> int:
    """
    Dynamically discover tools from MCP server and register them.

    Args:
        tool_filter: Optional list of tool names to include. If None, includes all.

    Returns:
        Number of MCP tools registered
    """
    try:
        # Use mcp_use's discover_tools()
        mcp_tools = await self._session.discover_tools()

        for mcp_tool in mcp_tools:
            tool_name = mcp_tool.get("name", "")

            # Apply filter if specified
            if tool_filter and tool_name not in tool_filter:
                continue

            # Convert and register
            openai_tool = self.convert_mcp_tool_to_openai(mcp_tool)
            self._tools.append(openai_tool)
            self._tool_map[tool_name] = ('mcp', tool_name)

        return len(mcp_tools)

    except Exception as e:
        self._logger.warning(f"MCP discovery failed, using fallback: {e}")
        self._add_fallback_mcp_tools()
        return 0
```

### Step 3: Update Initialization Flow

```python
# In ToolManager.__init__:
def __init__(self, ...):
    # ... existing setup ...
    self._build_schema_tools()  # Local schema tools (sync)
    # MCP tools discovered later via async call

# Separate sync and async initialization:
def _build_schema_tools(self):
    """Build local LangChain schema tools (sync)"""
    lc_tools = create_schema_tools(self._schema_manager)
    for tool in lc_tools:
        # ... register schema tools ...
```

### Step 4: Update Callers to Use Async Discovery

```python
# In MultiAgentCoT._initialize():
async def _initialize(self):
    # ... existing setup ...

    # Initialize tool manager
    self._tool_manager = ToolManager(
        self._mcp_session,
        self._schema_manager,
        observer=self._cpg_observer
    )

    # Discover MCP tools dynamically
    await self._tool_manager.discover_mcp_tools()
```

### Step 5: Update EntityResolutionAgent Similarly

```python
class EntityResolutionAgent:
    async def _discover_tools(self):
        """Discover tools from MCP server"""
        mcp_tools = await self._session.discover_tools()

        # Filter to only the tools we need
        needed_tools = ['neo4j_fuzzy_search', 'neo4j_execute_query']

        for mcp_tool in mcp_tools:
            if mcp_tool['name'] in needed_tools:
                self._tools.append(
                    ToolManager.convert_mcp_tool_to_openai(mcp_tool)
                )
```

## Files to Modify

| File | Changes |
|------|---------|
| `test_multi_agent_cot.py` | ToolManager, EntityResolutionAgent, MultiAgentCoT |

## Specific Line Ranges

1. **ToolManager** (lines 1118-1185)
   - Add `convert_mcp_tool_to_openai()` static method
   - Add `async discover_mcp_tools()` method
   - Rename `_build_tools()` to `_build_schema_tools()`
   - Remove hard-coded MCP tool definition
   - Keep fallback for error cases

2. **EntityResolutionAgent** (lines 1648-1763)
   - Add `async _discover_tools()` method
   - Remove hard-coded `_build_tools()` method
   - Update `__init__` to call discovery

3. **MultiAgentCoT** (lines 2696-3080)
   - Update `_initialize()` to call tool discovery after creating managers
   - Update CoT agent creation to discover tools

## Backward Compatibility

- Keep fallback hard-coded tools if discovery fails
- Log warning when using fallback
- No breaking changes to external API

## Benefits

1. **Single source of truth** - MCP server defines tools once
2. **Auto-sync** - New tools automatically available
3. **Less maintenance** - No code changes when tools change
4. **Consistency** - All agents see same tool definitions

## Testing Plan

1. Unit test `convert_mcp_tool_to_openai()` with various inputs
2. Integration test `discover_mcp_tools()` against running MCP server
3. Test fallback behavior when MCP server unavailable
4. End-to-end test with full RAG workflow

## Rollout Strategy

1. Implement with feature flag: `use_dynamic_tool_discovery=True`
2. Run parallel tests comparing hard-coded vs dynamic
3. Verify tool schemas match
4. Remove feature flag and hard-coded definitions

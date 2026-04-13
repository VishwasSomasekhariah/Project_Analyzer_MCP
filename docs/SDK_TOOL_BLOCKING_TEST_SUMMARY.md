# Claude Agent SDK Tool Blocking Test Results

**SDK Version:** 0.1.25 (latest as of 2026-01-29)
**Issue:** Testing if built-in tools can be blocked via SDK parameters instead of pre-tool hooks

## Executive Summary

❌ **The `disallowed_tools` parameter exists but does NOT work for blocking built-in tools**

✅ **Pre-tool hook remains the ONLY reliable method to block built-in tools**

## Test Results

### 1. Parameter Availability Check

| Parameter | Exists? | Works? |
|-----------|---------|--------|
| `disallowed_tools` | ✅ Yes | ❌ No |
| `allowed_tools` | ✅ Yes | ❌ No |
| `blocked_tools` | ❌ No | N/A |
| `denied_tools` | ❌ No | N/A |
| `can_use_tool` | ✅ Yes | ❌ No |
| `tools` | ✅ Yes | ⚠️ Partial |

### 2. Detailed Test Results

#### Test: `disallowed_tools = ["Read"]`
```python
options = ClaudeAgentOptions(
    disallowed_tools=["Read"]
)
```
**Result:** ❌ FAIL - Read tool was still called

#### Test: `allowed_tools = []` (empty list)
```python
options = ClaudeAgentOptions(
    allowed_tools=[]
)
```
**Result:** ❌ FAIL - Read tool was still called

#### Test: `allowed_tools = [mcp_tools_only]`
```python
options = ClaudeAgentOptions(
    allowed_tools=["mcp__neo4j_memory__neo4j_execute_query"],
    mcp_servers=mcp_servers
)
```
**Result:** ❌ FAIL - Read tool was still called despite not being in allowed list

#### Test: `tools = []` (empty list)
```python
options = ClaudeAgentOptions(
    tools=[]
)
```
**Result:** ✅ PASS - No tools called (but blocks ALL tools including MCP)

#### Test: `can_use_tool` callback
```python
def cannot_use_read(tool_name: str) -> bool:
    return tool_name != "Read"

options = ClaudeAgentOptions(
    can_use_tool=cannot_use_read
)
```
**Result:** ❌ FAIL - Read tool was still called

#### Test: Pre-tool hook (current workaround)
```python
async def pre_tool_hook(hook_input, tool_use_id, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name in CLAUDE_BUILTIN_TOOLS:
        return SyncHookJSONOutput(
            continue_=True,
            hookSpecificOutput={
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny',
                'permissionDecisionReason': f"Tool '{tool_name}' is blocked"
            }
        )
    return SyncHookJSONOutput(continue_=True)

options = ClaudeAgentOptions(
    hooks={"PreToolUse": [HookMatcher(matcher=".*", hooks=[pre_tool_hook])]}
)
```
**Result:** ✅ PASS - Successfully blocked Read tool

## Conclusions

### What Works
1. **Pre-tool hook** - The ONLY reliable method to block built-in tools selectively
   - ✅ Can block specific tools (Bash, Read, Write, etc.)
   - ✅ Can allow MCP tools while blocking built-ins
   - ✅ Fully tested and working in production

2. **`tools = []`** - Blocks ALL tools (too restrictive for most use cases)
   - ✅ Blocks built-in tools
   - ❌ Also blocks MCP tools (not useful for agent workflows)

### What Doesn't Work
1. **`disallowed_tools` parameter** - Exists but doesn't block built-in tools
2. **`allowed_tools` parameter** - Doesn't prevent built-in tools from being called
3. **`can_use_tool` callback** - Doesn't prevent built-in tools from being called

## Recommendations

### Current Best Practice (Keep Using)
**Continue using the pre-tool hook approach** as implemented in `per_agent_sdk_client.py`:

```python
def _create_tool_filter_hook(self, agent_id: str, allowed_tools: List[str]):
    async def pre_tool_hook(hook_input, tool_use_id, context):
        tool_name = hook_input.get("tool_name", "")

        # Block Claude's built-in tools
        if self._block_builtin_tools and tool_name in CLAUDE_BUILTIN_TOOLS:
            return SyncHookJSONOutput(
                continue_=True,
                hookSpecificOutput={
                    'hookEventName': 'PreToolUse',
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': (
                        f"Built-in tool '{tool_name}' is not allowed for {agent_id}. "
                        "Use MCP tools to query the code property graph."
                    )
                }
            )

        # Check against agent's allowed tools
        if allowed_tools and tool_name not in allowed_tools:
            return SyncHookJSONOutput(
                continue_=True,
                hookSpecificOutput={
                    'hookEventName': 'PreToolUse',
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': (
                        f"Tool '{tool_name}' is not allowed for {agent_id}."
                    )
                }
            )

        return SyncHookJSONOutput(continue_=True)

    return pre_tool_hook
```

### Monitor for Future SDK Updates
The `disallowed_tools` parameter exists but doesn't work yet. This suggests:
- Feature may be in development
- May work in future SDK versions
- Worth re-testing after SDK updates

### Testing After Future SDK Updates
When a new SDK version is released, re-run these tests:
```bash
# Update SDK
pip install --upgrade claude-agent-sdk

# Run comprehensive tests
python test_sdk_tool_blocking.py
python test_sdk_disallowed_tools_variations.py
```

## Technical Details

### Built-in Tools List
These tools are available in Claude Code CLI but should be blocked in agent workflows:
- Bash
- Read, Write, Edit
- Glob, Grep, LS
- MultiEdit
- NotebookRead, NotebookEdit
- WebFetch, WebSearch
- TodoRead, TodoWrite
- Task

### SDK-Internal Tools (Should NOT be blocked)
- StructuredOutput - Used by SDK for structured output responses
- ListMcpResourcesTool - Used by SDK for MCP discovery
- ListMcpToolsTool - Used by SDK for MCP tool discovery

## Files Generated by Tests
- `test_sdk_tool_blocking.py` - Main test suite
- `test_sdk_disallowed_tools_variations.py` - Variations test
- `test_sdk_tools_parameter_selective.py` - MCP tools test
- `sdk_tool_blocking_test_results.json` - First test results
- `sdk_disallowed_tools_variations_results.json` - Variations results
- `sdk_tools_parameter_test_results.json` - MCP tools results

## Conclusion

**KEEP YOUR CURRENT IMPLEMENTATION** - The pre-tool hook is the only working solution in SDK 0.1.25.

The `disallowed_tools` parameter exists in the SDK API but is not functional for blocking built-in tools yet. Re-test this after future SDK updates to see if it becomes functional.

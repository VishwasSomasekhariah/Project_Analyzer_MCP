# Claude Agent SDK Complete Guide

> Documentation based on hands-on testing with `claude_agent_sdk` package.
> Tested: January 2026

## Table of Contents

1. [Overview](#overview)
2. [Core Components](#core-components)
3. [ClaudeSDKClient](#claudesdkclient)
4. [ClaudeAgentOptions](#claudeagentoptions)
5. [Custom Tools with @tool Decorator](#custom-tools-with-tool-decorator)
6. [In-Process MCP Servers](#in-process-mcp-servers)
7. [Hooks System](#hooks-system)
8. [can_use_tool Callback](#can_use_tool-callback)
9. [Structured Output](#structured-output)
10. [Message Types](#message-types)
11. [Best Practices](#best-practices)
12. [Examples](#examples)
13. [Message Roles (Claude API vs SDK)](#message-roles-claude-api-vs-sdk)

---

## Overview

### Claude Agent SDK vs Claude API

**Important distinction**: The Claude Agent SDK (`claude_agent_sdk`) is **not** the same as the raw Claude API (`anthropic` package).

| Feature | Claude API (`anthropic`) | Claude Agent SDK (`claude_agent_sdk`) |
|---------|--------------------------|---------------------------------------|
| Package | `pip install anthropic` | `pip install claude-agent-sdk` |
| Level | Low-level API | High-level agentic wrapper |
| Message control | Full (all 4 roles) | Managed (no prefill) |
| Tool execution | Manual | Automatic with MCP |
| Multi-turn | Manual message list | Automatic session context |
| Use case | Direct API calls | Agentic workflows |

```python
# Raw Claude API - full message control
from anthropic import Anthropic
client = Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    messages=[
        {"role": "user", "content": "Count to 5"},
        {"role": "assistant", "content": "1, 2, "}  # Prefill supported!
    ]
)

# Claude Agent SDK - managed agentic flow
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
async with ClaudeSDKClient(options=ClaudeAgentOptions(...)) as client:
    await client.query("Count to 5")  # String only, no prefill
```

**This guide covers the Claude Agent SDK**, which wraps the Claude Code CLI for agentic workflows.

---

The Claude Agent SDK provides a Python interface to run Claude Code agents programmatically. It supports:

- **Inference-only mode**: Simple question/answer without tools
- **Tool execution**: Custom tools via in-process MCP servers
- **External MCP servers**: Connect to http/sse/stdio MCP servers
- **Hooks**: Intercept and control tool execution
- **Multi-turn conversations**: Context retention across queries
- **Structured output**: JSON schema-constrained responses

### Installation

```bash
pip install claude-agent-sdk
# or with uv
uv add claude-agent-sdk
```

---

## Core Components

```python
from claude_agent_sdk import (
    # Client
    ClaudeSDKClient,
    ClaudeAgentOptions,

    # Tool creation
    tool,
    create_sdk_mcp_server,

    # Messages
    AssistantMessage,
    ResultMessage,
    UserMessage,
    SystemMessage,

    # Content blocks
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,

    # Permissions
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,

    # Hooks
    HookMatcher,
    PreToolUseHookInput,
    PostToolUseHookInput,
    HookContext,
)
from claude_agent_sdk.types import SyncHookJSONOutput
```

---

## ClaudeSDKClient

The main client for interacting with Claude.

### Basic Usage

```python
async with ClaudeSDKClient(options=ClaudeAgentOptions(...)) as client:
    await client.query("Your prompt here")

    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
        elif isinstance(message, ResultMessage):
            print(f"Done! Cost: ${message.total_cost_usd}")
```

### Methods

| Method | Description |
|--------|-------------|
| `connect(prompt)` | Connect with initial prompt |
| `query(prompt, session_id)` | Send a new query |
| `receive_response()` | Async iterator for messages until ResultMessage |
| `receive_messages()` | Async iterator for all messages (streaming) |
| `interrupt()` | Send interrupt signal |
| `set_model(model)` | Change model mid-conversation |
| `set_permission_mode(mode)` | Change permission mode |
| `rewind_files(message_id)` | Rewind file state to specific point |
| `disconnect()` | Close connection |
| `get_server_info()` | Get server initialization info |

### Multi-turn Conversations

Context is retained within a `ClaudeSDKClient` session:

```python
async with ClaudeSDKClient(options=options) as client:
    # First query
    await client.query("Remember the number 42.")
    async for msg in client.receive_response():
        pass

    # Second query - Claude remembers!
    await client.query("What number did I mention?")
    async for msg in client.receive_response():
        # Claude will respond with "42"
```

---

## ClaudeAgentOptions

All configuration options for the Claude agent.

```python
ClaudeAgentOptions(
    # =========== TOOLS & MCP ===========
    mcp_servers: dict,              # MCP server configurations
    allowed_tools: list[str],       # Whitelist of allowed tools
    disallowed_tools: list[str],    # Blacklist of tools
    tools: list[str] | ToolsPreset, # Tool presets

    # =========== MODEL ===========
    model: str,                     # e.g., "claude-sonnet-4-5-20250514"
    fallback_model: str,            # Fallback if primary fails

    # =========== LIMITS ===========
    max_turns: int,                 # Max agentic turns (default: unlimited)
    max_budget_usd: float,          # Cost limit
    max_thinking_tokens: int,       # Thinking token limit

    # =========== PERMISSIONS ===========
    permission_mode: str,           # "default", "acceptEdits", "plan", "bypassPermissions"
    can_use_tool: Callable,         # Permission callback (external MCP only!)

    # =========== HOOKS ===========
    hooks: dict,                    # Event hooks (see Hooks section)

    # =========== CONVERSATION ===========
    system_prompt: str,             # Custom system prompt
    continue_conversation: bool,    # Continue previous session
    resume: str,                    # Resume specific session ID
    fork_session: bool,             # Fork current session

    # =========== OUTPUT ===========
    output_format: dict,            # Structured output schema
    include_partial_messages: bool, # Include partial streaming messages

    # =========== SUB-AGENTS ===========
    agents: dict[str, AgentDefinition],  # Define sub-agents

    # =========== ENVIRONMENT ===========
    cwd: str | Path,                # Working directory
    env: dict[str, str],            # Environment variables
    add_dirs: list[Path],           # Additional directories
    sandbox: SandboxSettings,       # Sandbox configuration

    # =========== ADVANCED ===========
    betas: list[str],               # Beta features
    plugins: list[SdkPluginConfig], # SDK plugins
    cli_path: str,                  # Custom CLI path
    settings: str,                  # Settings file path
)
```

### Permission Modes

| Mode | Description |
|------|-------------|
| `"default"` | Ask for permission on sensitive operations |
| `"acceptEdits"` | Auto-accept file edits |
| `"plan"` | Planning mode |
| `"bypassPermissions"` | Skip all permission checks (NOT allowed as root!) |

---

## Custom Tools with @tool Decorator

Create custom tools that execute **in your Python process**:

```python
from claude_agent_sdk import tool

@tool(
    name="get_weather",
    description="Get weather for a city",
    input_schema={"city": str, "units": str}
)
async def get_weather(args: dict) -> dict:
    """
    This function runs IN YOUR PROCESS when Claude calls the tool.
    """
    city = args.get("city", "Unknown")
    units = args.get("units", "celsius")

    # Your implementation here
    weather_data = await fetch_weather_api(city, units)

    # Return format required by SDK
    return {
        "content": [
            {"type": "text", "text": f"Weather in {city}: {weather_data}"}
        ]
    }
```

### Input Schema

The `input_schema` can be:
- A type: `str`, `int`, `bool`, `dict`
- A dict describing parameters: `{"param_name": type, ...}`

### Return Format

Tools must return a dict with `content` key:

```python
return {
    "content": [
        {"type": "text", "text": "Result text here"}
    ],
    "isError": False  # Optional, set True for errors
}
```

---

## In-Process MCP Servers

Create an MCP server from your tools that runs in your application:

```python
from claude_agent_sdk import create_sdk_mcp_server, tool

@tool(name="tool1", description="...", input_schema={...})
async def tool1(args): ...

@tool(name="tool2", description="...", input_schema={...})
async def tool2(args): ...

# Create in-process MCP server
tools_server = create_sdk_mcp_server(
    name="my_tools",
    version="1.0.0",
    tools=[tool1, tool2]
)

# Use in options
options = ClaudeAgentOptions(
    mcp_servers={"my_tools": tools_server},
    allowed_tools=[
        "mcp__my_tools__tool1",
        "mcp__my_tools__tool2"
    ]
)
```

### Tool Naming Convention

Tools are accessed as: `mcp__<server_name>__<tool_name>`

---

## Hooks System

Hooks let you intercept Claude's behavior at key points.

### Available Hooks

| Hook | When Called | Use Case |
|------|-------------|----------|
| `PreToolUse` | Before tool execution | Validate, block, log |
| `PostToolUse` | After tool execution | Log results, audit |
| `UserPromptSubmit` | Before processing user input | Input validation |
| `Stop` | When agent stops | Cleanup |
| `SubagentStop` | When sub-agent stops | Sub-agent coordination |
| `PreCompact` | Before context compaction | Save important context |

### Hook Implementation

```python
from claude_agent_sdk import HookMatcher, PreToolUseHookInput, HookContext
from claude_agent_sdk.types import SyncHookJSONOutput

async def my_pre_tool_hook(
    hook_input: PreToolUseHookInput,
    tool_use_id: str | None,
    context: HookContext
) -> SyncHookJSONOutput:
    """
    Called BEFORE each tool execution.

    hook_input contains:
    - session_id: str
    - tool_name: str (e.g., "mcp__my_tools__get_weather")
    - tool_input: dict (the arguments)
    - tool_use_id: str
    - cwd: str
    - permission_mode: str
    """
    tool_name = hook_input.get("tool_name")
    tool_input = hook_input.get("tool_input")

    print(f"Tool called: {tool_name} with {tool_input}")

    # Allow execution
    return SyncHookJSONOutput(continue_=True)

    # OR block execution
    return SyncHookJSONOutput(
        continue_=True,
        decision="block",
        reason="Blocked for security",
        systemMessage="This tool is not allowed."
    )
```

### Registering Hooks

```python
options = ClaudeAgentOptions(
    hooks={
        "PreToolUse": [
            HookMatcher(
                matcher=".*",  # Regex to match tool names
                hooks=[my_pre_tool_hook],
                timeout=30  # seconds
            )
        ],
        "PostToolUse": [
            HookMatcher(matcher=".*neo4j.*", hooks=[log_neo4j_queries])
        ]
    }
)
```

### PostToolUse Hook

```python
async def my_post_tool_hook(hook_input, tool_use_id, context):
    """
    Called AFTER tool execution.

    hook_input contains:
    - tool_name: str
    - tool_input: dict
    - tool_response: list  # The result from the tool!
    - tool_use_id: str
    """
    response = hook_input.get("tool_response")
    print(f"Tool returned: {response}")
    return SyncHookJSONOutput(continue_=True)
```

### SyncHookJSONOutput Fields

| Field | Type | Description |
|-------|------|-------------|
| `continue_` | bool | Must be True |
| `decision` | str | `"block"` to block execution |
| `reason` | str | Reason for blocking |
| `systemMessage` | str | Message shown to Claude |

**Important**: Hooks can only **allow** or **block** tool execution. They **cannot modify** the tool input.

---

## can_use_tool Callback

**IMPORTANT FINDING**: `can_use_tool` is **NOT called for in-process SDK MCP servers**.

It only applies to:
- External MCP servers (http, sse, stdio)
- Built-in Claude tools

```python
async def my_permission_callback(
    tool_name: str,
    tool_input: dict,
    context: ToolPermissionContext
) -> PermissionResultAllow | PermissionResultDeny:
    """
    Called for EXTERNAL MCP tools only.
    """
    # Allow with optional input modification
    return PermissionResultAllow(
        updated_input={"modified": "input"},  # Can modify!
        updated_permissions=None
    )

    # Or deny
    return PermissionResultDeny(
        message="Not allowed",
        interrupt=False  # True to stop entire session
    )

options = ClaudeAgentOptions(
    can_use_tool=my_permission_callback,  # Only for external MCP!
    ...
)
```

### When to Use What

| Scenario | Use |
|----------|-----|
| In-process SDK tools | `PreToolUse` hook to block, `@tool` function for logic |
| External MCP tools | `can_use_tool` callback |
| Modify input | `can_use_tool` (external only) or implement in `@tool` function |

---

## Structured Output

Request JSON output matching a schema:

```python
options = ClaudeAgentOptions(
    output_format={
        "type": "json_schema",
        "json_schema": {
            "name": "response_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "confidence": {"type": "number"}
                },
                "required": ["answer"]
            }
        }
    }
)
```

**Note**: In testing, `ResultMessage.structured_output` was `None`. The structured output appears in the `TextBlock` content. Parse it yourself if needed.

---

## Message Types

### AssistantMessage

```python
AssistantMessage:
    content: list[TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock]
    model: str
    parent_tool_use_id: str | None
    error: str | None  # "authentication_failed", "rate_limit", etc.
```

### ResultMessage

```python
ResultMessage:
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    total_cost_usd: float | None
    usage: dict | None
    result: str | None
    structured_output: Any  # Often None, check TextBlock instead
```

### Content Blocks

```python
TextBlock:
    text: str

ToolUseBlock:
    id: str
    name: str
    input: dict

ToolResultBlock:
    tool_use_id: str
    content: str | list[dict] | None
    is_error: bool | None

ThinkingBlock:
    thinking: str
    signature: str
```

---

## Best Practices

### 1. Use In-Process MCP for Custom Tools

```python
# Good - tools run in your process
@tool(name="my_tool", ...)
async def my_tool(args):
    result = await my_app.do_something(args)
    return {"content": [{"type": "text", "text": result}]}

server = create_sdk_mcp_server(name="app", tools=[my_tool])
```

### 2. Use Hooks for Validation/Logging

```python
# Block dangerous operations
async def security_hook(hook_input, tool_use_id, context):
    if "DROP" in str(hook_input.get("tool_input", {})):
        return SyncHookJSONOutput(
            continue_=True,
            decision="block",
            reason="Dangerous operation blocked"
        )
    return SyncHookJSONOutput(continue_=True)
```

### 3. Handle Errors in Tools

```python
@tool(name="risky_op", ...)
async def risky_op(args):
    try:
        result = await do_risky_thing(args)
        return {"content": [{"type": "text", "text": result}]}
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error: {e}"}],
            "isError": True
        }
```

### 4. Set Reasonable Limits

```python
options = ClaudeAgentOptions(
    max_turns=10,           # Prevent infinite loops
    max_budget_usd=1.0,     # Cost control
)
```

---

## Examples

### Example 1: Simple Inference

```python
async def ask_claude(question: str) -> str:
    options = ClaudeAgentOptions(allowed_tools=[], max_turns=1)

    async with ClaudeSDKClient(options=options) as client:
        await client.query(question)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        return block.text
    return ""
```

### Example 2: Tool-Using Agent

```python
@tool(name="search_db", description="Search the database",
      input_schema={"query": str})
async def search_db(args):
    results = await database.search(args["query"])
    return {"content": [{"type": "text", "text": str(results)}]}

async def agent_with_tools(question: str):
    server = create_sdk_mcp_server(name="db", tools=[search_db])

    options = ClaudeAgentOptions(
        mcp_servers={"db": server},
        allowed_tools=["mcp__db__search_db"],
        max_turns=5
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(question)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")
                    elif isinstance(block, ToolUseBlock):
                        print(f"Using tool: {block.name}")
```

### Example 3: With Security Hook

```python
async def validate_queries(hook_input, tool_use_id, context):
    tool_input = hook_input.get("tool_input", {})
    query = tool_input.get("query", "")

    # Block write operations
    if any(kw in query.upper() for kw in ["DELETE", "DROP", "UPDATE"]):
        return SyncHookJSONOutput(
            continue_=True,
            decision="block",
            reason="Write operations not allowed"
        )
    return SyncHookJSONOutput(continue_=True)

options = ClaudeAgentOptions(
    hooks={
        "PreToolUse": [HookMatcher(matcher=".*db.*", hooks=[validate_queries])]
    },
    ...
)
```

---

## Message Roles (Claude API vs SDK)

The raw Claude API (`anthropic` package) supports 4 message roles. The Claude Agent SDK only exposes 3 of them:

### The 4 Roles

| Role | Description | SDK Support |
|------|-------------|-------------|
| **System** | Instructions that guide Claude's behavior | ✅ Yes |
| **User** | Human messages/prompts | ✅ Yes |
| **Assistant (prefill)** | Partial assistant response Claude completes | ❌ No |
| **Assistant** | Claude's responses | ✅ Yes (automatic) |

### 1. System Prompt ✅

Set via `ClaudeAgentOptions.system_prompt`:

```python
options = ClaudeAgentOptions(
    system_prompt="You are a pirate. Always respond like a pirate.",
    allowed_tools=[],
    max_turns=1
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Hello!")
    # Response: "Ahoy there, matey! 🏴‍☠️ ..."
```

### SystemPromptPreset

Instead of a string, you can use a preset with optional append:

```python
from claude_agent_sdk.types import SystemPromptPreset

# Structure of SystemPromptPreset (TypedDict):
# - type: Literal["preset"] (required)
# - preset: Literal["claude_code"] (required) - only preset available
# - append: str (optional) - custom text appended to preset

options = ClaudeAgentOptions(
    system_prompt={"type": "preset", "preset": "claude_code", "append": "Focus on Python."}
)
```

### 2. User Message ✅

Send via `client.query()`:

```python
await client.query("What is 2 + 2?")
```

Only string queries are supported. Message streams with role dictionaries fail:

```python
# ❌ This does NOT work:
async def message_stream():
    yield {"role": "user", "content": "Hello"}

await client.query(message_stream())  # Error!
```

### 3. Assistant Prefill ❌

The SDK does **not** support assistant prefill (partial assistant responses for Claude to continue).

In the raw Claude API (`anthropic` package), you can do:
```python
# Raw Anthropic API - prefill IS supported:
from anthropic import Anthropic
client = Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    messages=[
        {"role": "user", "content": "Count to 5"},
        {"role": "assistant", "content": "1, 2, "}  # Claude continues: "3, 4, 5"
    ]
)
```

**Why not supported in SDK?** The Claude Agent SDK wraps the Claude Code CLI, which manages conversation flow internally for agentic use cases. The SDK prioritizes tool execution, multi-turn sessions, and MCP integration over low-level message control.

**If you need prefill**: Use the raw `anthropic` package instead of `claude_agent_sdk`.

### 4. Assistant Response ✅

Claude's responses come as `AssistantMessage` objects:

```python
async for message in client.receive_response():
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(block.text)  # Claude's response
```

---

## Summary Table

| Feature | How to Use |
|---------|------------|
| Custom tool logic | `@tool` decorated async function |
| In-process execution | `create_sdk_mcp_server()` |
| Block tool calls | `PreToolUse` hook with `decision="block"` |
| Log tool results | `PostToolUse` hook |
| Modify input (external MCP) | `can_use_tool` callback |
| Structured output | `output_format` in options |
| Multi-turn context | Same `ClaudeSDKClient` session |
| Cost control | `max_budget_usd` in options |
| System prompt | `system_prompt` string or preset |
| User messages | `client.query("...")` |
| Assistant prefill | ❌ Not supported |

---

## Tested Behavior Summary

Based on actual testing:

1. **`@tool` functions execute in your process** - This is where your code runs
2. **`PreToolUse` hooks CAN block execution** - Claude acknowledges and adapts
3. **`PostToolUse` hooks receive tool results** - Good for logging/audit
4. **`can_use_tool` NOT called for SDK MCP servers** - Only external MCP
5. **Hooks cannot modify input** - Only allow/block
6. **Multi-turn context works** - Claude remembers within session
7. **Structured output in TextBlock** - Not always in `structured_output` field

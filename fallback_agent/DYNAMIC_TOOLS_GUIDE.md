# Dynamic Tool Loading - Claude Code Adapter

## Overview

The enhanced adapter (`claude_code_openai_adapter_with_tools.py`) supports **dynamically loading custom tools at runtime** without server restarts.

This enables:
- ✅ Register tools via HTTP API
- ✅ Use tools in chat completions
- ✅ Add/remove tools on-the-fly
- ✅ No code deployment needed
- ✅ Still maintains OpenAI compatibility

## Architecture

```
Your Code
    ↓
POST /v1/tools (register tool code)
    ↓
Tool Registry (stores tools)
    ↓
POST /v1/chat/completions (with tools parameter)
    ↓
ClaudeSDKClient (uses registered tools)
    ↓
Claude Code CLI
```

## Quick Start

### 1. Start Enhanced Adapter

```bash
cd /opt/genpod/fallback_agent
python3 claude_code_openai_adapter_with_tools.py
```

Server starts on `http://localhost:8889` (default)

### 2. Register a Tool

```bash
curl -X POST http://localhost:8889/v1/tools \
  -H "Content-Type: application/json" \
  -d '{
    "name": "get_weather",
    "description": "Get weather information for a city",
    "input_schema": {"city": "str"},
    "code": "async def get_weather(args):\n    city = args.get(\"city\", \"Unknown\")\n    return {\"content\": [{\"type\": \"text\", \"text\": f\"Weather in {city}: Sunny\"}]}"
  }'
```

### 3. Use Tool in Chat Completion

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8889/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="claude-sonnet-4.5",
    messages=[
        {"role": "user", "content": "What's the weather in San Francisco?"}
    ],
    tools=["get_weather"]  # Specify which tools to use
)

print(response.choices[0].message.content)
```

## API Reference

### Tool Management Endpoints

#### 1. Register Tool

**POST /v1/tools**

Request body:
```json
{
  "name": "tool_name",
  "description": "What the tool does",
  "input_schema": {"param1": "str", "param2": "int"},
  "code": "async def tool_name(args): ..."
}
```

Response:
```json
{
  "status": "success",
  "message": "Tool 'tool_name' registered successfully",
  "tool": {
    "name": "tool_name",
    "description": "...",
    "input_schema": {...},
    "registered_at": 1234567890.0
  }
}
```

#### 2. List Tools

**GET /v1/tools**

Response:
```json
{
  "object": "list",
  "data": [
    {
      "name": "tool_name",
      "description": "...",
      "input_schema": {...},
      "registered_at": 1234567890.0
    }
  ]
}
```

#### 3. Delete Tool

**DELETE /v1/tools/{tool_name}**

Response:
```json
{
  "status": "success",
  "message": "Tool 'tool_name' removed"
}
```

### Chat Completions with Tools

**POST /v1/chat/completions**

Extended request format:
```json
{
  "model": "claude-sonnet-4.5",
  "messages": [...],
  "tools": ["tool1", "tool2"],  // NEW: Specify which tools to use
  "temperature": 0.0,
  "stream": false
}
```

- If `tools` is omitted or empty: **Inference-only mode** (no tools)
- If `tools` is provided: Claude can use specified tools

## Tool Code Requirements

Tool functions must:

1. **Be async functions**:
   ```python
   async def my_tool(args):
       ...
   ```

2. **Accept `args` dict**:
   ```python
   async def my_tool(args):
       param1 = args.get('param1')
       param2 = args.get('param2', 'default')
   ```

3. **Return properly formatted dict**:
   ```python
   return {
       'content': [{
           'type': 'text',
           'text': 'Result text here'
       }]
   }
   ```

4. **Handle errors gracefully**:
   ```python
   try:
       # tool logic
       return {'content': [{'type': 'text', 'text': result}]}
   except Exception as e:
       return {
           'content': [{'type': 'text', 'text': f'Error: {e}'}],
           'isError': True
       }
   ```

## Examples

### Example 1: Weather Tool

```python
import requests

tool_def = {
    "name": "get_weather",
    "description": "Get current weather for a city",
    "input_schema": {"city": "str"},
    "code": """async def get_weather(args):
    city = args.get('city', 'Unknown')

    # Simulate API call
    weather_db = {
        'San Francisco': 'Sunny, 72°F',
        'New York': 'Cloudy, 65°F',
        'London': 'Rainy, 58°F'
    }

    weather = weather_db.get(city, 'Weather data not available')

    return {
        'content': [{
            'type': 'text',
            'text': f'Weather in {city}: {weather}'
        }]
    }
"""
}

# Register
response = requests.post(
    "http://localhost:8889/v1/tools",
    json=tool_def
)
print(response.json())
```

### Example 2: Calculator Tool

```python
calculator_def = {
    "name": "calculate",
    "description": "Evaluate mathematical expressions",
    "input_schema": {"expression": "str"},
    "code": """async def calculate(args):
    try:
        expr = args.get('expression', '0')
        # Safe eval
        result = eval(expr, {"__builtins__": {}}, {})
        return {
            'content': [{
                'type': 'text',
                'text': f'Result: {result}'
            }]
        }
    except Exception as e:
        return {
            'content': [{
                'type': 'text',
                'text': f'Calculation error: {str(e)}'
            }],
            'isError': True
        }
"""
}

requests.post("http://localhost:8889/v1/tools", json=calculator_def)
```

### Example 3: Database Query Tool

```python
db_tool = {
    "name": "query_database",
    "description": "Execute Cypher query on Neo4j",
    "input_schema": {"query": "str"},
    "code": """async def query_database(args):
    # NOTE: You'd need to import neo4j driver in the code
    query = args.get('query', '')

    # Example - in real use, connect to actual DB
    result = f"Executed query: {query}"

    return {
        'content': [{
            'type': 'text',
            'text': result
        }]
    }
"""
}

requests.post("http://localhost:8889/v1/tools", json=db_tool)
```

### Example 4: Using Multiple Tools

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8889/v1",
    api_key="not-needed"
)

# Use multiple tools in one request
response = client.chat.completions.create(
    model="claude-sonnet-4.5",
    messages=[
        {
            "role": "user",
            "content": "What's the weather in London? Also calculate 100 * 50."
        }
    ],
    tools=["get_weather", "calculate"]  # Both tools available
)

print(response.choices[0].message.content)
```

## Python Client Helper

For easier tool management:

```python
class ToolManager:
    """Helper for managing dynamic tools."""

    def __init__(self, base_url="http://localhost:8889"):
        self.base_url = base_url

    def register(self, name: str, description: str, input_schema: dict, code: str):
        """Register a new tool."""
        response = requests.post(
            f"{self.base_url}/v1/tools",
            json={
                "name": name,
                "description": description,
                "input_schema": input_schema,
                "code": code
            }
        )
        return response.json()

    def list(self):
        """List all registered tools."""
        response = requests.get(f"{self.base_url}/v1/tools")
        return response.json()['data']

    def delete(self, name: str):
        """Delete a tool."""
        response = requests.delete(f"{self.base_url}/v1/tools/{name}")
        return response.json()

# Usage
tm = ToolManager()
tm.register(
    name="greet",
    description="Greet someone",
    input_schema={"name": "str"},
    code='async def greet(args): return {"content": [{"type": "text", "text": f"Hello {args[\'name\']}!"}]}'
)

print(tm.list())
tm.delete("greet")
```

## Use Cases

### 1. RAG Workflow with Custom Retrieval

```python
# Register custom retrieval tool
retrieval_tool = {
    "name": "search_codebase",
    "description": "Search code using CPG",
    "input_schema": {"query": "str"},
    "code": """async def search_codebase(args):
    # Your custom CPG search logic
    query = args.get('query')
    # ... search implementation ...
    return {'content': [{'type': 'text', 'text': results}]}
"""
}

tm.register(**retrieval_tool)

# Use in workflow
response = client.chat.completions.create(
    model="claude-sonnet-4.5",
    messages=[{"role": "user", "content": "Find all classes implementing IWorker"}],
    tools=["search_codebase"]
)
```

### 2. Dynamic Neo4j Integration

```python
# Register Neo4j query tool at runtime
neo4j_tool = {
    "name": "neo4j_query",
    "description": "Query the code property graph",
    "input_schema": {"cypher": "str"},
    "code": """async def neo4j_query(args):
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver("bolt://localhost:7687")
    cypher = args.get('cypher')

    with driver.session() as session:
        result = session.run(cypher)
        records = [dict(r) for r in result]

    return {'content': [{'type': 'text', 'text': str(records)}]}
"""
}

tm.register(**neo4j_tool)
```

### 3. Testing Different Tool Implementations

```python
# Version 1
tm.register(
    name="analyzer",
    description="Analyze code",
    input_schema={"code": "str"},
    code="async def analyzer(args): return {'content': [{'type': 'text', 'text': 'V1 analysis'}]}"
)

# Test version 1
test_response = client.chat.completions.create(...)

# Update to version 2
tm.delete("analyzer")
tm.register(
    name="analyzer",
    description="Analyze code",
    input_schema={"code": "str"},
    code="async def analyzer(args): return {'content': [{'type': 'text', 'text': 'V2 improved analysis'}]}"
)

# Test version 2
test_response = client.chat.completions.create(...)
```

## Limitations & Considerations

### Security

⚠️ **Important:** Tool code is executed with `exec()`. In production:

1. **Validate tool code** before registration
2. **Restrict access** to tool registration endpoint
3. **Sandbox execution** if accepting user-provided tools
4. **Use authentication** for /v1/tools endpoints

### Performance

- Tools are stored in-memory (lost on restart)
- MCP server is rebuilt on each tool registration
- For production, consider persistent storage

### Compatibility

- ✅ Works with OpenAI client library
- ✅ Compatible with existing LLMConfig
- ✅ Can mix with inference-only requests
- ⚠️ Tools require async functions
- ⚠️ Tool state is server-local (not distributed)

## Running the Test

```bash
cd /opt/genpod/fallback_agent

# Terminal 1: Start enhanced adapter
python3 claude_code_openai_adapter_with_tools.py

# Terminal 2: Run test
uv run python test_dynamic_tools.py
```

Expected output:
```
1. Checking server status... ✅
2. Registering 'get_weather' tool... ✅
3. Registering 'calculate' tool... ✅
4. Listing all registered tools... ✅ Found 2 tools
5. Testing chat completion WITH tools...
   💬 Weather in San Francisco: Sunny, 72°F
   💬 Result: 0.736758
6. Testing chat completion WITHOUT tools... ✅
7. Testing tool deletion... ✅
```

## Comparison: Standard vs Enhanced Adapter

| Feature | Standard Adapter | Enhanced Adapter |
|---------|------------------|------------------|
| Chat completions | ✅ | ✅ |
| Streaming | ✅ | ✅ |
| OpenAI compatible | ✅ | ✅ |
| **Tool support** | ❌ | ✅ |
| **Dynamic tool loading** | ❌ | ✅ |
| **Runtime tool registration** | ❌ | ✅ |
| Zero-cost inference | ✅ | ✅ |
| Production ready | ✅ | ⚠️ (needs auth) |

## Next Steps

1. **Try the test**: Run `test_dynamic_tools.py`
2. **Register your tools**: Create tools for your RAG workflow
3. **Add authentication**: Protect `/v1/tools` endpoints
4. **Persist tools**: Add database storage for tools
5. **Monitor usage**: Add logging/metrics for tool calls

This feature enables **zero-cost agentic workflows** with custom tools using Claude Code!

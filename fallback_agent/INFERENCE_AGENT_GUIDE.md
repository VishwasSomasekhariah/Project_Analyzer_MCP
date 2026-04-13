# Building Inference-Only Claude Agents with ClaudeSDKClient

## Quick Start

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock

async def simple_inference(prompt: str) -> str:
    options = ClaudeAgentOptions(allowed_tools=[])  # Inference only

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        response = ""
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text

        return response
```

## Key Patterns

### 1. Single-Turn Query (One-Off Inference)
**Use for:** Classification, summarization, code generation

```python
options = ClaudeAgentOptions(
    allowed_tools=[],
    max_turns=1  # Limit to single response
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("What is 25 * 47?")
    # Process response...
```

### 2. Multi-Turn Conversation (Context Retention)
**Use for:** Iterative refinement, follow-up questions, RAG workflows

```python
options = ClaudeAgentOptions(allowed_tools=[])

async with ClaudeSDKClient(options=options) as client:
    # Query 1
    await client.query("I'm analyzing a C# codebase.")
    # Process response...

    # Query 2 - remembers Query 1!
    await client.query("What should I look for?")
    # Process response...
```

### 3. RAG Workflow Integration
**Use for:** Context-based reasoning

```python
# Your retrieval step gets context from CPG/Vector DB
context = get_context_from_cpg(user_question)

# Claude performs reasoning
prompt = f"""
Based on this context, answer the question:

Context:
{context}

Question: {user_question}
"""

response = await agent.query(prompt)
```

### 4. Cypher Query Generation
**Use for:** Converting English to Cypher

```python
prompt = f"""
Generate a Cypher query for this question.

Schema:
{your_schema}

Question: {user_query}

Return ONLY the Cypher query.
"""

cypher = await agent.query(prompt)
```

## Configuration Options

```python
ClaudeAgentOptions(
    allowed_tools=[],              # Empty = inference only
    max_turns=1,                   # Limit responses (default: unlimited)
    model="claude-sonnet-4.5",     # Or "claude-haiku-4.5"
    temperature=0.7,               # 0-1, lower = more deterministic
    max_tokens=4096                # Response length limit
)
```

## Message Types

### 1. AssistantMessage
Claude's response with text content.

```python
if isinstance(message, AssistantMessage):
    for block in message.content:
        if isinstance(block, TextBlock):
            print(block.text)  # This is Claude's response
```

### 2. ResultMessage
Metadata about the conversation.

```python
if isinstance(message, ResultMessage):
    print(f"Duration: {message.duration_ms}ms")
    print(f"Turns: {message.num_turns}")
    print(f"Cost: ${message.total_cost_usd}")
    print(f"Session ID: {message.session_id}")
```

### 3. SystemMessage
Lifecycle events (session started/ended).

```python
if isinstance(message, SystemMessage):
    print(f"Event: {message.subtype}")
```

## query() vs ClaudeSDKClient

| Feature | `query()` | `ClaudeSDKClient` |
|---------|-----------|-------------------|
| Session lifetime | Single query | Reusable across calls |
| Context retention | ❌ None | ✅ Full conversation |
| Custom tools | ⚠️ Limited | ✅ Full support |
| Interrupts | ❌ No | ✅ Yes |
| Use case | Quick one-offs | Multi-turn workflows |

**For RAG workflows:** Use `ClaudeSDKClient` to maintain context across reasoning steps.

## Cost Comparison (per 1M tokens)

| Model | Input | Output | Use Case |
|-------|-------|--------|----------|
| GPT-4o | $2.50 | $10.00 | Current system |
| Claude Sonnet 4.5 | $3.00 | $15.00 | High quality (35% more expensive) |
| Claude Haiku 4.5 | $1.00 | $5.00 | Fast inference (55% cheaper) |

## Production Template

See `minimal_inference_agent.py` for a ready-to-use class:

```python
from minimal_inference_agent import ClaudeInferenceAgent

# Create agent
agent = ClaudeInferenceAgent(
    model="claude-sonnet-4.5",
    max_turns=1
)

# Single query
response = await agent.query("Your prompt here")

# Multi-turn conversation
responses = await agent.conversation([
    "Query 1",
    "Query 2",
    "Query 3"
])
```

## Files in This Directory

1. **inference_agent_guide.py** - Comprehensive guide with 6 patterns
2. **minimal_inference_agent.py** - Production-ready template class
3. **test_cypher_generation.py** - Example: Cypher generation
4. **test_query_vs_client.py** - Comparison of query() vs ClaudeSDKClient
5. **test_query_with_tools.py** - Why custom tools need ClaudeSDKClient

## Authentication

Claude Agent SDK uses Claude Code CLI authentication:
- **No API key needed** in code
- Uses your existing Claude Code CLI session
- Runs locally through Claude Code CLI

## Common Patterns for Your RAG System

### Pattern A: Single-Step Reasoning
```python
# Retrieve context from CPG
context = cpg_retrieval(question)

# Claude reasons over context
agent = ClaudeInferenceAgent(max_turns=1)
answer = await agent.query(f"Context: {context}\nQuestion: {question}")
```

### Pattern B: Multi-Agent Chain
```python
agent = ClaudeInferenceAgent()  # Maintains context

async with ClaudeSDKClient(options=agent.options) as client:
    # Agent 1: Query decomposition
    await client.query(f"Decompose this: {question}")
    decomposition = await get_response(client)

    # Agent 2: Entity extraction (remembers decomposition)
    await client.query("Extract entities from the subqueries")
    entities = await get_response(client)

    # Agent 3: Path discovery (remembers everything)
    await client.query("Find paths connecting these entities")
    paths = await get_response(client)
```

### Pattern C: Iterative Refinement
```python
agent = ClaudeInferenceAgent()

async with ClaudeSDKClient(options=agent.options) as client:
    # Initial query
    await client.query(f"Generate Cypher for: {question}")
    cypher = await get_response(client)

    # If query fails, refine (Claude remembers previous attempt)
    if not validate_cypher(cypher):
        await client.query(f"Fix this error: {error_msg}")
        fixed_cypher = await get_response(client)
```

## Next Steps

1. **Try the examples:**
   ```bash
   cd /opt/genpod/fallback_agent
   python3 minimal_inference_agent.py
   python3 inference_agent_guide.py
   ```

2. **Test with your RAG workflow:**
   - Replace one agent in your 4-agent system with Claude
   - Compare quality vs GPT-4o
   - Track cost differences

3. **Choose model based on task:**
   - **Sonnet 4.5**: Complex reasoning (Thinker, CypherValidator)
   - **Haiku 4.5**: Simple tasks (Entity extraction, formatting)

4. **Monitor costs:**
   ```python
   async for message in client.receive_response():
       if isinstance(message, ResultMessage):
           print(f"Cost: ${message.total_cost_usd}")
   ```

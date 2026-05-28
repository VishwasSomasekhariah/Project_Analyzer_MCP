#!/usr/bin/env python3
"""
Guide: Building Inference-Only Claude Agent with ClaudeSDKClient

This demonstrates three patterns for inference-only agents:
1. Single-turn query (one-off inference)
2. Multi-turn conversation (context retention)
3. Batch processing (multiple independent queries)
"""

import asyncio
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    SystemMessage,
    ResultMessage,
    TextBlock
)


# ============================================================================
# Pattern 1: Single-Turn Query (Simple Inference)
# ============================================================================
async def single_turn_inference(user_query: str) -> str:
    """
    Simplest pattern - ask one question, get one answer.
    Good for: Classification, summarization, code generation, etc.
    """
    options = ClaudeAgentOptions(
        allowed_tools=[],  # No tools = inference only
        max_turns=1        # Limit to single response
    )

    result_text = ""

    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_query)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_text += block.text

    return result_text


# ============================================================================
# Pattern 2: Multi-Turn Conversation (Context Retention)
# ============================================================================
async def conversational_inference():
    """
    Maintain context across multiple queries in same session.
    Good for: Iterative refinement, follow-up questions, RAG workflows.
    """
    options = ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=10  # Allow multiple back-and-forth turns
    )

    async with ClaudeSDKClient(options=options) as client:
        # Query 1: Set context
        print("Query 1: Setting context...")
        await client.query("I'm analyzing a C# codebase with Worker classes. Remember this.")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Response: {block.text}\n")

        # Query 2: Follow-up (remembers previous context)
        print("Query 2: Follow-up question...")
        await client.query("What should I look for in the Worker classes?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Response: {block.text}\n")

        # Query 3: Another follow-up
        print("Query 3: Another follow-up...")
        await client.query("Can you list 3 specific things to check?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Response: {block.text}\n")


# ============================================================================
# Pattern 3: Batch Processing (Multiple Independent Queries)
# ============================================================================
async def batch_inference(queries: list[str]) -> list[str]:
    """
    Process multiple independent queries.
    Each query uses a fresh session (no context sharing).
    Good for: Parallel processing, independent classifications.
    """
    results = []

    for query in queries:
        result = await single_turn_inference(query)
        results.append(result)

    return results


# ============================================================================
# Pattern 4: Structured Output Extraction
# ============================================================================
async def extract_structured_data(raw_text: str, schema: str) -> str:
    """
    Use Claude to extract structured data from unstructured text.
    Good for: JSON extraction, entity recognition, data parsing.
    """
    prompt = f"""
Extract structured data from the following text according to this schema:

Schema:
{schema}

Text:
{raw_text}

Return ONLY valid JSON matching the schema. No explanation.
"""

    options = ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=1,
        # Optionally specify model
        # model="claude-sonnet-4.5" or "claude-haiku-4.5"
    )

    json_result = ""

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        json_result += block.text

    return json_result


# ============================================================================
# Pattern 5: Collecting Metadata (Tokens, Cost, Timing)
# ============================================================================
async def inference_with_metadata(user_query: str) -> dict:
    """
    Capture response text along with usage metadata.
    Good for: Cost tracking, performance monitoring.
    """
    options = ClaudeAgentOptions(allowed_tools=[])

    metadata = {
        "response": "",
        "duration_ms": 0,
        "num_turns": 0,
        "session_id": "",
        "cost_usd": 0.0
    }

    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_query)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        metadata["response"] += block.text

            elif isinstance(message, ResultMessage):
                metadata["duration_ms"] = message.duration_ms
                metadata["num_turns"] = message.num_turns
                metadata["session_id"] = message.session_id
                if message.total_cost_usd:
                    metadata["cost_usd"] = message.total_cost_usd

    return metadata


# ============================================================================
# Pattern 6: RAG Workflow Integration
# ============================================================================
async def rag_inference_step(context: str, question: str) -> str:
    """
    Claude as reasoning step in RAG pipeline.
    Context comes from retrieval, Claude does reasoning.
    """
    prompt = f"""
You are helping analyze a codebase. Use the provided context to answer the question.

Context from Code Property Graph:
{context}

Question: {question}

Provide a concise, accurate answer based ONLY on the context provided.
"""

    options = ClaudeAgentOptions(
        allowed_tools=[],
        max_turns=1
    )

    answer = ""

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        answer += block.text

    return answer


# ============================================================================
# Usage Examples
# ============================================================================
async def main():
    print("=" * 70)
    print("CLAUDE AGENT SDK - INFERENCE-ONLY PATTERNS")
    print("=" * 70)

    # Example 1: Simple inference
    print("\n[1] Single-turn inference:")
    print("-" * 70)
    result = await single_turn_inference("What is 25 * 47?")
    print(f"Result: {result}\n")

    # Example 2: Conversational
    print("\n[2] Multi-turn conversation:")
    print("-" * 70)
    await conversational_inference()

    # Example 3: Batch processing
    print("\n[3] Batch processing:")
    print("-" * 70)
    queries = [
        "What is the capital of France?",
        "What is 10 + 15?",
        "What color is the sky?"
    ]
    batch_results = await batch_inference(queries)
    for q, r in zip(queries, batch_results):
        print(f"Q: {q}")
        print(f"A: {r}\n")

    # Example 4: Structured extraction
    print("\n[4] Structured data extraction:")
    print("-" * 70)
    raw_text = """
    John Smith works as a Software Engineer at TechCorp.
    He has 5 years of experience and specializes in Python.
    """
    schema = """
    {
        "name": string,
        "role": string,
        "company": string,
        "years_experience": number,
        "specialty": string
    }
    """
    json_result = await extract_structured_data(raw_text, schema)
    print(f"Extracted JSON:\n{json_result}\n")

    # Example 5: With metadata
    print("\n[5] Inference with metadata tracking:")
    print("-" * 70)
    metadata = await inference_with_metadata("Explain async/await in Python in one sentence.")
    print(f"Response: {metadata['response']}")
    print(f"Duration: {metadata['duration_ms']}ms")
    print(f"Turns: {metadata['num_turns']}")
    print(f"Session ID: {metadata['session_id']}")
    print(f"Cost: ${metadata['cost_usd']:.4f}\n")

    # Example 6: RAG workflow step
    print("\n[6] RAG workflow inference:")
    print("-" * 70)
    cpg_context = """
    Function: CreateWorkers
    Return Type: List<Worker>
    Calls: WorkerA.Process(), WorkerB.Process(), WorkerC.Process()
    """
    question = "What does CreateWorkers return?"
    rag_answer = await rag_inference_step(cpg_context, question)
    print(f"Question: {question}")
    print(f"Answer: {rag_answer}\n")


# ============================================================================
# Key Configuration Options
# ============================================================================
def show_configuration_options():
    """
    ClaudeAgentOptions for inference-only agents.
    """
    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║  ClaudeAgentOptions for Inference-Only Agents                    ║
    ╠══════════════════════════════════════════════════════════════════╣
    ║  allowed_tools: []        # Empty = inference only, no tool use  ║
    ║  max_turns: 1             # Single response (default: unlimited) ║
    ║  model: "claude-sonnet-4.5"  # Or "claude-haiku-4.5"             ║
    ║  temperature: 0.7         # Lower = more deterministic           ║
    ║  max_tokens: 4096         # Response length limit                ║
    ╚══════════════════════════════════════════════════════════════════╝

    Message Types You'll Receive:

    1. SystemMessage
       - subtype: "session_started", "session_ended"
       - Use for: Lifecycle tracking

    2. AssistantMessage
       - content: List[TextBlock, ToolUseBlock, etc.]
       - Use for: Extracting Claude's text response

    3. ResultMessage
       - duration_ms: int
       - num_turns: int
       - total_cost_usd: float
       - session_id: str
       - Use for: Metadata tracking

    Key Differences from query():

    ┌──────────────────────────────────────────────────────────────────┐
    │ Feature              │ query()         │ ClaudeSDKClient        │
    ├──────────────────────────────────────────────────────────────────┤
    │ Session lifetime     │ Single query    │ Reusable across calls  │
    │ Context retention    │ ❌ None         │ ✅ Full conversation   │
    │ Custom tools support │ ⚠️  Limited     │ ✅ Full support        │
    │ Interrupts           │ ❌              │ ✅ Yes                 │
    │ Use case             │ Quick one-offs  │ Multi-turn workflows   │
    └──────────────────────────────────────────────────────────────────┘

    For RAG workflows with multiple reasoning steps:
    → Use ClaudeSDKClient for context retention across steps
    """)


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("CONFIGURATION REFERENCE")
    print("=" * 70)
    show_configuration_options()

    print("\n" + "=" * 70)
    print("RUNNING EXAMPLES")
    print("=" * 70)
    asyncio.run(main())

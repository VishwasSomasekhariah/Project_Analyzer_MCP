#!/usr/bin/env python3
"""
Minimal Inference-Only Claude Agent Template

Use this as a starting point for building your inference agent.
"""

import asyncio
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock
)


class ClaudeInferenceAgent:
    """
    Simple wrapper for Claude inference-only operations.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4.5",
        max_turns: int | None = None,
        temperature: float = 0.7
    ):
        self.options = ClaudeAgentOptions(
            allowed_tools=[],  # Inference only
            model=model,
            max_turns=max_turns,
            temperature=temperature
        )

    async def query(self, prompt: str) -> str:
        """
        Send a single query and return the response text.

        Args:
            prompt: The user query/prompt

        Returns:
            Claude's response as a string
        """
        response_text = ""

        async with ClaudeSDKClient(options=self.options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_text += block.text

        return response_text

    async def conversation(self, queries: list[str]) -> list[str]:
        """
        Multi-turn conversation with context retention.

        Args:
            queries: List of prompts to send in sequence

        Returns:
            List of responses (one per query)
        """
        responses = []

        async with ClaudeSDKClient(options=self.options) as client:
            for query_text in queries:
                await client.query(query_text)

                response_text = ""
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                response_text += block.text

                responses.append(response_text)

        return responses


# ============================================================================
# Usage Examples
# ============================================================================

async def example_single_query():
    """Simple one-off query."""
    agent = ClaudeInferenceAgent(max_turns=1)

    response = await agent.query("What is 15 * 23?")
    print(f"Response: {response}")


async def example_conversation():
    """Multi-turn conversation with context."""
    agent = ClaudeInferenceAgent()

    queries = [
        "I'm analyzing a C# project with Worker classes.",
        "What should I look for in these Worker classes?",
        "Give me 3 specific things to check."
    ]

    responses = await agent.conversation(queries)

    for i, (q, r) in enumerate(zip(queries, responses), 1):
        print(f"\nTurn {i}:")
        print(f"  User: {q}")
        print(f"  Claude: {r}")


async def example_rag_workflow():
    """
    Integration with RAG workflow.
    Claude receives context from retrieval and performs reasoning.
    """
    agent = ClaudeInferenceAgent(max_turns=1)

    # Context retrieved from your CPG/Vector database
    retrieved_context = """
    Function: CreateWorkers
    Return Type: List<Worker>
    Location: WorkerFactory.cs:45
    Calls: WorkerA.Process(), WorkerB.Process(), WorkerC.Process()
    """

    # User's question
    user_question = "What does CreateWorkers return and what does it call?"

    # Construct prompt with context
    prompt = f"""
Based on this code analysis context, answer the question:

Context:
{retrieved_context}

Question: {user_question}

Provide a concise, accurate answer.
"""

    response = await agent.query(prompt)
    print(f"Question: {user_question}")
    print(f"Answer: {response}")


async def example_cypher_generation():
    """
    Use Claude to generate Cypher queries.
    (Similar to your test_cypher_generation.py)
    """
    agent = ClaudeInferenceAgent(max_turns=1)

    schema = """
    Node Types:
    - Method {name, return_type}
    - Class {name}

    Relationship Types:
    - (Method)-[:CALLS]->(Method)
    - (Method)-[:BELONGS_TO]->(Class)
    """

    user_query = "Find all methods that call CreateWorkers"

    prompt = f"""
Generate a Cypher query for this question.

Schema:
{schema}

Question: {user_query}

Return ONLY the Cypher query, no explanation.
"""

    cypher_query = await agent.query(prompt)
    print(f"Generated Cypher:\n{cypher_query}")


# ============================================================================
# Main
# ============================================================================

async def main():
    print("=" * 70)
    print("MINIMAL CLAUDE INFERENCE AGENT - EXAMPLES")
    print("=" * 70)

    print("\n[1] Single Query:")
    print("-" * 70)
    await example_single_query()

    print("\n\n[2] Multi-Turn Conversation:")
    print("-" * 70)
    await example_conversation()

    print("\n\n[3] RAG Workflow Integration:")
    print("-" * 70)
    await example_rag_workflow()

    print("\n\n[4] Cypher Query Generation:")
    print("-" * 70)
    await example_cypher_generation()


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Claude Code OpenAI-Compatible Adapter Server

This server exposes Claude Agent SDK as an OpenAI-compatible API,
allowing seamless integration into RAG workflows that use OpenAI clients.

Usage in your RAG workflow:
    llm_config = {
        "model": "claude-sonnet-4.5",
        "base_url": "http://localhost:8888/v1",
        "api_key": "not-needed"  # Claude Code uses CLI auth
    }

Start server:
    python3 claude_code_openai_adapter.py

Then your entire RAG workflow uses Claude Code instead of OpenAI!
"""

import asyncio
import time
import uuid
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn
import json

try:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
        TextBlock
    )
    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False


# ============================================================================
# OpenAI API Request/Response Models
# ============================================================================

class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False
    # Ignore other OpenAI params


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage


class StreamChoice(BaseModel):
    index: int
    delta: Dict[str, Any]
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[StreamChoice]


# ============================================================================
# Claude Agent SDK Wrapper
# ============================================================================

class ClaudeCodeAdapter:
    """Adapter that translates OpenAI API calls to Claude Agent SDK calls."""

    # Model mapping - Use correct Claude Agent SDK model names (hyphens not dots)
    # From docs: https://platform.claude.com/docs/en/agent-sdk/migration-guide
    MODEL_MAP = {
        # Correct format uses hyphens: claude-sonnet-4-5 not claude-sonnet-4.5
        "claude-sonnet-4.5": "claude-sonnet-4-5",
        "claude-haiku-4.5": "claude-haiku-4-5",
        "claude-3-5-sonnet-20241022": "claude-sonnet-4-5",
        "claude-3-haiku-20240307": "claude-haiku-4-5",
        # Fallback for generic names
        "gpt-4o": "claude-sonnet-4-5",
        "gpt-4": "claude-sonnet-4-5",
        "gpt-4o-mini": "claude-haiku-4-5",
    }

    def __init__(self):
        if not CLAUDE_SDK_AVAILABLE:
            raise RuntimeError(
                "Claude Agent SDK not installed. "
                "Install with: uv add claude-agent-sdk"
            )

    def _map_model(self, model: str) -> str:
        """Map OpenAI model name to Claude model."""
        return self.MODEL_MAP.get(model, "claude-haiku-4.5")

    def _format_messages(self, messages: List[Message]) -> str:
        """Convert OpenAI messages to Claude prompt."""
        prompt_parts = []

        for msg in messages:
            if msg.role == "system":
                prompt_parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")

        return "\n\n".join(prompt_parts)

    async def create_completion(
        self,
        request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """
        Create a chat completion (non-streaming).

        Translates OpenAI API request to Claude Agent SDK call.
        """
        claude_model = self._map_model(request.model)
        prompt = self._format_messages(request.messages)

        # ClaudeAgentOptions supports model and max_turns
        # But NOT temperature/max_tokens (handled by Claude internally)
        options = ClaudeAgentOptions(
            allowed_tools=[],
            model=claude_model,
            max_turns=1
        )

        # Call Claude
        response_text = ""
        prompt_tokens = 0
        completion_tokens = 0

        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_text += block.text

                elif isinstance(message, ResultMessage):
                    # Claude SDK doesn't provide token counts directly
                    # Estimate based on character count
                    prompt_tokens = len(prompt) // 4
                    completion_tokens = len(response_text) // 4

        # Build OpenAI-compatible response
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            created=int(time.time()),
            model=claude_model,
            choices=[
                Choice(
                    index=0,
                    message=Message(role="assistant", content=response_text),
                    finish_reason="stop"
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            )
        )

    async def create_completion_stream(
        self,
        request: ChatCompletionRequest
    ):
        """
        Create a streaming chat completion.

        Yields Server-Sent Events compatible with OpenAI streaming format.
        """
        claude_model = self._map_model(request.model)
        prompt = self._format_messages(request.messages)

        # ClaudeAgentOptions supports model and max_turns
        # But NOT temperature/max_tokens (handled by Claude internally)
        options = ClaudeAgentOptions(
            allowed_tools=[],
            model=claude_model,
            max_turns=1
        )

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created = int(time.time())

        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            # Stream as chunks
                            chunk = ChatCompletionChunk(
                                id=completion_id,
                                created=created,
                                model=claude_model,
                                choices=[
                                    StreamChoice(
                                        index=0,
                                        delta={"content": block.text}
                                    )
                                ]
                            )
                            yield f"data: {chunk.model_dump_json()}\n\n"

        # Send final chunk
        final_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=claude_model,
            choices=[
                StreamChoice(
                    index=0,
                    delta={},
                    finish_reason="stop"
                )
            ]
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"


# ============================================================================
# FastAPI Server
# ============================================================================

app = FastAPI(
    title="Claude Code OpenAI Adapter",
    description="OpenAI-compatible API for Claude Agent SDK",
    version="1.0.0"
)

adapter = None


@app.on_event("startup")
async def startup():
    global adapter
    if not CLAUDE_SDK_AVAILABLE:
        print("❌ Claude Agent SDK not available!")
        print("   Install with: uv add claude-agent-sdk")
        raise RuntimeError("Claude Agent SDK required")

    adapter = ClaudeCodeAdapter()
    print("✅ Claude Code OpenAI Adapter ready")


@app.get("/")
async def root():
    return {
        "message": "Claude Code OpenAI-Compatible Adapter",
        "endpoints": {
            "chat_completions": "/v1/chat/completions",
            "models": "/v1/models"
        }
    }


@app.get("/v1/models")
async def list_models():
    """List available models (OpenAI-compatible endpoint)."""
    return {
        "object": "list",
        "data": [
            {
                "id": "claude-sonnet-4.5",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "claude-code"
            },
            {
                "id": "claude-haiku-4.5",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "claude-code"
            }
        ]
    }


@app.post("/v1/chat/completions")
async def create_chat_completion(request: ChatCompletionRequest):
    """
    OpenAI-compatible chat completions endpoint.

    This is the endpoint your RAG workflow will call!
    """
    if not adapter:
        raise HTTPException(status_code=500, detail="Adapter not initialized")

    try:
        if request.stream:
            # Streaming response
            return StreamingResponse(
                adapter.create_completion_stream(request),
                media_type="text/event-stream"
            )
        else:
            # Non-streaming response
            response = await adapter.create_completion(request)
            return response.model_dump()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import os

    # Make port configurable via environment variable
    # Default: 8889 (avoid common ports like 8888, 8080, 8100, etc.)
    port = int(os.getenv("CLAUDE_ADAPTER_PORT", "8889"))

    print("=" * 70)
    print("CLAUDE CODE OPENAI-COMPATIBLE ADAPTER")
    print("=" * 70)
    print(f"\n🚀 Starting server on http://localhost:{port}")
    print("\n📝 Configure your RAG workflow with:")
    print(f"""
    llm_config = {{
        "model": "claude-sonnet-4.5",
        "base_url": "http://localhost:{port}/v1",
        "api_key": "not-needed"
    }}
    """)
    print("\n💡 Tip: Change port with CLAUDE_ADAPTER_PORT env var")
    print("   Example: CLAUDE_ADAPTER_PORT=9000 python3 claude_code_openai_adapter.py")
    print("=" * 70)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )

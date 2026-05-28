"""
Schema Tool Calling Helper

Handles LLM tool calling for schema discovery with automatic tool execution loop.
Wraps the existing LLMService to add tool calling capabilities.
"""

import json
import logging
from typing import Dict, List, Any, Optional
from langchain_core.utils.function_calling import convert_to_openai_tool

logger = logging.getLogger(__name__)


class SchemaToolCaller:
    """
    Helper class for LLM tool calling with schema discovery tools.

    Handles:
    - Converting LangChain tools to OpenAI format
    - Making tool-enabled LLM calls
    - Executing tools and collecting results
    - Multi-turn tool calling loops
    """

    def __init__(self, llm_service, schema_tools_list):
        """
        Initialize tool caller.

        Args:
            llm_service: LLMService instance
            schema_tools_list: List of LangChain tools (from create_schema_tools)
        """
        self.llm_service = llm_service
        self.schema_tools = {tool.name: tool for tool in schema_tools_list}

        # Convert to OpenAI tool format
        self.openai_tools = [convert_to_openai_tool(tool) for tool in schema_tools_list]

        logger.info(f"🛠️ SchemaToolCaller initialized with {len(self.schema_tools)} tools")

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str = "gpt-4o",
        max_iterations: int = 10,
        max_tokens: int = 4000,
        temperature: float = 0.1,
        tool_filter: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generate response with tool calling support.

        Automatically handles multi-turn tool calling:
        1. LLM generates response (may include tool calls)
        2. Execute any tool calls
        3. Feed tool results back to LLM
        4. Repeat until LLM generates final answer (no more tool calls)

        Args:
            system_prompt: System prompt for LLM
            user_prompt: User prompt for LLM
            model_name: Model to use (default: gpt-4o)
            max_iterations: Maximum tool calling rounds (default: 10)
            max_tokens: Max tokens per request
            temperature: Temperature for generation
            tool_filter: Optional list of tool names to allow (None = all tools)

        Returns:
            {
                "content": "Final LLM response",
                "tool_calls_made": 5,
                "tool_call_history": [
                    {
                        "tool": "get_node_labels",
                        "args": {},
                        "result": {...}
                    },
                    ...
                ],
                "total_tokens": 12000,
                "iterations": 3
            }
        """
        # Filter tools if specified
        if tool_filter:
            filtered_openai_tools = [
                t for t in self.openai_tools
                if t.get('function', {}).get('name') in tool_filter
            ]
            logger.info(f"  🔧 Filtered to {len(filtered_openai_tools)} tools: {tool_filter}")
        else:
            filtered_openai_tools = self.openai_tools
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        tool_call_history = []
        total_tokens = 0
        iteration = 0

        for iteration in range(1, max_iterations + 1):
            logger.info(f"  🔄 Tool calling iteration {iteration}/{max_iterations}")

            # Make LLM call with tools
            response = await self._call_llm_with_tools(
                messages=messages,
                model_name=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=filtered_openai_tools
            )

            total_tokens += response.get("tokens_used", 0)

            # Check if LLM made tool calls
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                # No more tool calls - we have final answer
                logger.info(f"  ✅ Final answer generated after {iteration} iterations, {len(tool_call_history)} tool calls")
                return {
                    "content": response["content"],
                    "tool_calls_made": len(tool_call_history),
                    "tool_call_history": tool_call_history,
                    "total_tokens": total_tokens,
                    "iterations": iteration
                }

            # Execute tool calls
            logger.info(f"  🛠️ Executing {len(tool_calls)} tool call(s)")

            # Add assistant message with tool calls to history
            messages.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": tool_calls
            })

            # Execute each tool and add results
            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args = json.loads(tool_call["function"]["arguments"])
                tool_id = tool_call["id"]

                logger.info(f"     • {tool_name}({tool_args})")

                # Execute tool
                try:
                    tool = self.schema_tools[tool_name]
                    result = tool.invoke(tool_args)

                    tool_call_history.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": result,
                        "iteration": iteration
                    })

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "content": json.dumps(result),
                        "tool_call_id": tool_id
                    })

                except Exception as e:
                    logger.error(f"     ❌ Tool execution failed: {e}")
                    # Add error as tool result
                    messages.append({
                        "role": "tool",
                        "content": json.dumps({"error": str(e)}),
                        "tool_call_id": tool_id
                    })

        # Max iterations reached
        logger.warning(f"  ⚠️ Max iterations ({max_iterations}) reached, returning partial result")
        return {
            "content": "Max tool calling iterations reached. Please simplify your query.",
            "tool_calls_made": len(tool_call_history),
            "tool_call_history": tool_call_history,
            "total_tokens": total_tokens,
            "iterations": max_iterations,
            "truncated": True
        }

    async def _call_llm_with_tools(
        self,
        messages: List[Dict[str, Any]],
        model_name: str,
        max_tokens: int,
        temperature: float,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Make a single LLM call with tools enabled.

        Args:
            messages: Conversation history
            model_name: Model to use
            max_tokens: Max tokens
            temperature: Temperature
            tools: Optional filtered tools list (defaults to all tools)

        Returns:
            {
                "content": "Response text",
                "tool_calls": [...] or [],
                "tokens_used": 1234
            }
        """
        try:
            import openai

            # Create OpenAI client (using same pattern as llm_service.py)
            client = openai.AsyncOpenAI(
                api_key=self.llm_service.providers[self.llm_service.fallback_chain[0]].api_key,
                timeout=60.0
            )

            # Use provided tools or default to all
            active_tools = tools if tools is not None else self.openai_tools

            kwargs = {
                "model": model_name,
                "messages": messages,
                "tools": active_tools,
                "tool_choice": "auto"
            }

            # O4/O3 models use max_completion_tokens
            if model_name.startswith(("o3", "o4")):
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens
                kwargs["temperature"] = temperature

            response = await client.chat.completions.create(**kwargs)

            message = response.choices[0].message

            # Extract tool calls if present
            tool_calls = []
            if message.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]

            return {
                "content": message.content or "",
                "tool_calls": tool_calls,
                "tokens_used": response.usage.total_tokens if response.usage else 0
            }

        except Exception as e:
            logger.error(f"  ❌ LLM call with tools failed: {e}")
            raise

    def get_tools_documentation(self, tool_filter: Optional[List[str]] = None) -> str:
        """
        Get human-readable documentation of available tools.

        Args:
            tool_filter: Optional list of tool names to include (None = all tools)

        Returns:
            Markdown documentation string
        """
        if tool_filter:
            # Generate docs dynamically from filtered tools
            docs = ["## Available Tools\n"]
            for tool_name in tool_filter:
                if tool_name in self.schema_tools:
                    tool = self.schema_tools[tool_name]
                    docs.append(f"### {tool.name}")
                    docs.append(f"{tool.description}\n")
                    # Get input schema if available
                    if hasattr(tool, 'args_schema') and tool.args_schema:
                        schema = tool.args_schema.schema()
                        props = schema.get('properties', {})
                        if props:
                            docs.append("**Parameters:**")
                            for prop_name, prop_info in props.items():
                                desc = prop_info.get('description', '')
                                docs.append(f"- `{prop_name}`: {desc}")
                            docs.append("")
            return "\n".join(docs)
        else:
            # Return full documentation
            from src.core.workflow.schema_tools_langchain import get_schema_tools_instructions
            return get_schema_tools_instructions()

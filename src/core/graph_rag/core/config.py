"""
Configuration classes for the Graph RAG Multi-Agent system.
"""

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from openai import OpenAI

from .exceptions import ConfigurationError


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server connection"""
    model_config = ConfigDict(frozen=False, extra='allow')

    type: str = Field(default="http", description="Transport type: http, stdio")
    url: Optional[str] = Field(None, description="URL for HTTP/SSE transport")
    command: Optional[str] = Field(None, description="Command for stdio transport")
    args: List[str] = Field(default_factory=list, description="Arguments for stdio command")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")


class MCPConfig(BaseModel):
    """
    MCP configuration - can be passed directly as dict or loaded from file.

    Example direct usage:
        config = SystemConfig(
            mcp_config={
                "mcpServers": {
                    "neo4j_memory": {"type": "http", "url": "http://localhost:8100/sse"}
                }
            }
        )

    Example file usage:
        config = SystemConfig(mcp_config_path="neo4j_config.json")
    """
    model_config = ConfigDict(frozen=False, populate_by_name=True)

    servers: Dict[str, MCPServerConfig] = Field(
        default_factory=dict,
        alias="mcpServers",
        description="Map of server name to server config"
    )

    @classmethod
    def from_file(cls, path: str) -> "MCPConfig":
        """Load MCP config from a JSON file"""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPConfig":
        """Create MCP config from a dictionary"""
        return cls(**data)


class LLMConfig(BaseModel):
    """
    Configuration for LLM model and parameters.

    Supports OpenAI and OpenAI-compatible APIs (Azure, Groq, Together AI, local LLMs).

    Examples:
        # OpenAI (default)
        llm_config = {"model": "gpt-4o", "temperature": 0.0}

        # Azure OpenAI
        llm_config = {
            "model": "gpt-4o",
            "base_url": "https://your-resource.openai.azure.com",
            "api_key": "your-azure-key"
        }

        # Groq
        llm_config = {
            "model": "llama-3.1-70b-versatile",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key": "your-groq-key"
        }

        # Local Ollama (with OpenAI adapter)
        llm_config = {
            "model": "llama3",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama"  # Ollama doesn't need real key
        }

        # Google Gemini (OpenAI-compatible API)
        llm_config = {
            "model": "gemini-1.5-pro",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "api_key": "your-google-api-key"
        }
    """
    model_config = ConfigDict(frozen=False)

    model: str = Field(default="gpt-4o", description="Model name")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, description="Max tokens in response")
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Top-p sampling")
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0, description="Frequency penalty")
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0, description="Presence penalty")
    seed: Optional[int] = Field(default=None, description="Random seed for reproducibility")

    # Provider configuration for non-OpenAI providers
    base_url: Optional[str] = Field(default=None, description="Custom API base URL for OpenAI-compatible providers")
    api_key: Optional[str] = Field(default=None, description="API key (defaults to OPENAI_API_KEY env var)")

    # Fallback configuration
    fallback_enabled: bool = Field(default=True, description="Enable fallback to Claude SDK")
    fallback_mode: str = Field(default="direct", description="Fallback mode: 'direct' (Claude SDK) or 'adapter' (legacy server)")
    fallback_url: str = Field(default="http://localhost:8889/v1", description="Claude Code adapter URL (only for adapter mode)")
    fallback_model: str = Field(default="claude-sonnet-4-6", description="Model to use for fallback")
    fallback_mcp_config_path: Optional[str] = Field(default=None, description="MCP config path for fallback")
    fallback_system_prompt: Optional[str] = Field(default=None, description="System prompt for Claude SDK fallback")
    fallback_max_turns: int = Field(default=10, description="Max agentic turns for Claude SDK fallback")

    # Security options (direct mode fallback)
    fallback_strict_security: bool = Field(default=True, description="Block dangerous operations in fallback")
    fallback_validate_prompts: bool = Field(default=True, description="Validate prompts for injection attacks")
    fallback_validate_cypher: bool = Field(default=True, description="Validate Cypher queries for write operations")
    fallback_max_buffer_size: int = Field(default=10 * 1024 * 1024, description="Max JSON buffer size (default 10MB)")
    fallback_block_builtin_tools: bool = Field(default=True, description="Block Claude's built-in tools (Bash, Read, Write, etc.)")

    def to_openai_kwargs(self) -> Dict[str, Any]:
        """Convert to OpenAI API kwargs, excluding None values"""
        kwargs = {"model": self.model, "temperature": self.temperature}
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            kwargs["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            kwargs["presence_penalty"] = self.presence_penalty
        if self.seed is not None:
            kwargs["seed"] = self.seed
        return kwargs

    def create_client(self, use_fallback: bool = True) -> OpenAI:
        """
        Create an LLM client configured for this provider.

        Args:
            use_fallback: If True, returns ResilientLLMClient with Claude SDK fallback.
                         If False, returns plain OpenAI client.

        Returns:
            OpenAI-compatible client (ResilientLLMClient or OpenAI)
        """
        import os
        from pathlib import Path

        client_kwargs = {}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        if self.api_key:
            client_kwargs["api_key"] = self.api_key

        if use_fallback and self.fallback_enabled:
            from .llm_client import ResilientLLMClient

            # Auto-detect Claude MCP config if not explicitly provided
            mcp_config_path = self.fallback_mcp_config_path

            if not mcp_config_path:
                # Check environment variable first
                mcp_config_path = os.environ.get("CLAUDE_MCP_CONFIG")

                # Then check common locations
                if not mcp_config_path:
                    common_paths = [
                        Path("fallback_agent/claude_code_mcp_config.json"),
                        Path("/opt/genpod/fallback_agent/claude_code_mcp_config.json"),
                        Path.home() / ".claude" / "mcp_config.json",
                    ]
                    for path in common_paths:
                        if path.exists():
                            mcp_config_path = str(path)
                            break

            return ResilientLLMClient(
                primary_config=client_kwargs,
                fallback_mode=self.fallback_mode,  # "direct" (Claude SDK) or "adapter"
                fallback_url=self.fallback_url,
                fallback_model=self.fallback_model,
                fallback_enabled=True,
                mcp_config_path=mcp_config_path,
                allowed_mcp_servers=["neo4j_memory"],  # Graph RAG only needs Neo4j
                system_prompt=self.fallback_system_prompt,
                max_turns=self.fallback_max_turns,
                # Security options (direct mode)
                strict_security=self.fallback_strict_security,
                validate_prompts=self.fallback_validate_prompts,
                validate_cypher=self.fallback_validate_cypher,
                max_buffer_size=self.fallback_max_buffer_size,
                block_builtin_tools=self.fallback_block_builtin_tools,
            )
        else:
            return OpenAI(**client_kwargs)


class SystemConfig(BaseModel):
    """
    Configuration for the multi-agent system.

    MCP and Schema can be configured via:
    - Direct dict (mcp_config, yaml_schema)
    - File paths (mcp_config_path, yaml_schema_path)

    LLM can be configured via:
    - Direct dict/object (llm_config) with model, temperature, etc.
    - Simple model name (llm_model) for backwards compatibility

    Examples:
        # Using file paths (backwards compatible)
        config = SystemConfig(
            mcp_config_path="neo4j_config.json",
            yaml_schema_path="/path/to/schema.yaml",
            llm_model="gpt-4o"
        )

        # Using direct config dicts
        config = SystemConfig(
            mcp_config={
                "mcpServers": {
                    "neo4j_memory": {"type": "http", "url": "http://localhost:8100/sse"}
                }
            },
            yaml_schema={"nodes": {...}, "relationships": {...}},
            llm_config={"model": "gpt-4o", "temperature": 0.0}
        )
    """
    model_config = ConfigDict(frozen=False)

    # MCP Configuration - either pass config dict directly or provide path
    mcp_config: Optional[Dict[str, Any]] = Field(default=None, description="MCP config dict (takes precedence)")
    mcp_config_path: Optional[str] = Field(default=None, description="Path to MCP config JSON file")

    # Schema Configuration - either pass dict directly or provide path
    yaml_schema: Optional[Dict[str, Any]] = Field(default=None, description="YAML schema as dict (takes precedence)")
    yaml_schema_path: Optional[str] = Field(default=None, description="Path to YAML schema file")

    # LLM Configuration - either pass config dict or use simple model name
    llm_config: Optional[Dict[str, Any]] = Field(default=None, description="LLM config dict {model, temperature, ...}")
    llm_model: str = Field(default="gpt-4o", description="Simple model name (used if llm_config not provided)")

    # Fallback configuration for Claude Code adapter
    # NOTE: This MCP config should use Claude-compatible format (type: "sse" for SSE endpoints)
    # Unlike the standard mcp_config which uses type: "http" for MCPClient
    fallback_mcp_config_path: Optional[str] = Field(
        default=None,
        description="Path to Claude-compatible MCP config for fallback adapter (uses 'sse' transport type)"
    )

    # Agent behavior settings
    max_cot_iterations: int = Field(default=10, ge=1, le=25, description="Max iterations per CoT agent")
    max_verifier_iterations: int = Field(default=10, ge=1, le=15, description="Max iterations for verifier (needs more than CoT for schema exploration + query + analysis)")
    max_retries: int = Field(default=3, ge=1, le=5, description="Max retries on API errors")
    retry_delay_base: float = Field(default=1.0, ge=0.1, le=10.0, description="Base delay for exponential backoff")
    parallel_cot_agents: bool = Field(default=True, description="Run CoT agents in parallel")
    max_parallel_workers: int = Field(default=5, ge=1, le=10, description="Max concurrent CoT agents (prevents resource exhaustion)")
    max_sub_queries: int = Field(default=8, ge=1, le=15, description="Max sub-queries ToT can generate (prevents cost explosion)")
    verification_enabled: bool = Field(default=True, description="Enable verification step")
    entity_resolution_enabled: bool = Field(default=True, description="Enable entity resolution for case sensitivity and typos")

    # IR Pipeline Feature Flag
    use_ir_pipeline: bool = Field(
        default=True,
        description="Use IR-based pipeline (IRPlannerAgent + IRValidator + CypherCompiler) instead of CoT+Verifier loop"
    )

    # 4-Agent Team Feature Flag
    use_4_agent_team: bool = Field(
        default=False,
        description="Use 4-agent team (Thinker + ThinkingValidator + CypherValidator + ExecutorVerifier) instead of CoT+Verifier"
    )
    four_agent_max_iterations: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Max iterations for 4-agent workflow (thinker retries on validation failure)"
    )
    four_agent_max_queries_per_subquery: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Max Cypher queries the Thinker can propose per sub-query"
    )

    def get_llm_config(self) -> LLMConfig:
        """Get effective LLM config (explicit config dict or from simple model name)"""
        if self.llm_config:
            llm_config = LLMConfig(**self.llm_config)
        else:
            llm_config = LLMConfig(model=self.llm_model)

        # Set fallback MCP config path if provided at system level
        # This allows the ResilientLLMClient to load Claude-compatible MCP config
        if self.fallback_mcp_config_path and not llm_config.fallback_mcp_config_path:
            llm_config.fallback_mcp_config_path = self.fallback_mcp_config_path

        return llm_config

    def get_mcp_config_dict(self) -> Dict[str, Any]:
        """Get effective MCP config as dict (explicit dict or from file path)"""
        if self.mcp_config:
            return self.mcp_config
        if self.mcp_config_path:
            with open(self.mcp_config_path, 'r') as f:
                return json.load(f)
        raise ConfigurationError("Either mcp_config or mcp_config_path must be provided")

    def get_yaml_schema(self) -> Dict[str, Any]:
        """Get effective YAML schema (explicit dict or from file path)"""
        if self.yaml_schema:
            return self.yaml_schema
        if self.yaml_schema_path:
            import yaml
            with open(self.yaml_schema_path, 'r') as f:
                return yaml.safe_load(f)
        raise ConfigurationError("Either yaml_schema or yaml_schema_path must be provided")


__all__ = [
    'MCPServerConfig',
    'MCPConfig',
    'LLMConfig',
    'SystemConfig',
]

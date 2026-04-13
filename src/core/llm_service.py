"""
Production-ready LLM service for MCP server integration.

This module provides a robust, configurable LLM service that supports:
- Multiple providers (OpenAI, Anthropic, Azure OpenAI)
- Fallback chains and error handling
- Cost optimization and token management
- Async operations with proper resource management
- Security and input validation
- Comprehensive logging and monitoring
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Union, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"


class LLMModel(Enum):
    """Supported LLM models with cost tiers."""
    # Cheap models for filtering/summarization
    GPT4O_MINI = "gpt-4o-mini"
    GPT35_TURBO = "gpt-3.5-turbo"
    CLAUDE_HAIKU = "claude-3-haiku-20240307"
    
    # Powerful models for complex analysis
    GPT4O = "gpt-4o"
    GPT4_TURBO = "gpt-4-turbo"
    # CLAUDE_SONNET = "claude-3-5-sonnet-20241022"
    CLAUDE_SONNET = "claude-sonnet-4-6"
    # CLAUDE_OPUS = "claude-3-opus-20240229"
    CLAUDE_OPUS = "claude-opus-4-6"
    
    # O4 models for advanced reasoning (no temperature control)
    O4_MINI = "o4-mini"
    O3_MINI = "o3-mini"


@dataclass
class LLMRequest:
    """Structured LLM request with validation."""
    prompt: str
    model: LLMModel
    max_tokens: int = 1000
    temperature: float = 0.1
    system_prompt: Optional[str] = None
    json_mode: bool = False
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Validate request parameters."""
        if not self.prompt.strip():
            raise ValueError("Prompt cannot be empty")
        if not 0 <= self.temperature <= 2:
            raise ValueError("Temperature must be between 0 and 2")
        if not 1 <= self.max_tokens <= 16000:
            raise ValueError("Max tokens must be between 1 and 16000")


@dataclass
class LLMResponse:
    """Structured LLM response with metadata."""
    content: str
    model: str
    usage: Dict[str, int]
    cost_estimate: float
    latency_ms: int
    provider: str
    cached: bool = False
    error: Optional[str] = None


class LLMProviderBase(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response from LLM."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is properly configured."""
        pass


class OpenAIProvider(LLMProviderBase):
    """OpenAI provider implementation."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = None
        
    def is_available(self) -> bool:
        """Check if OpenAI is configured."""
        try:
            import openai
            return bool(self.api_key)
        except ImportError:
            return False
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response using OpenAI."""
        if not self.is_available():
            raise RuntimeError("OpenAI provider not available")
        
        try:
            import openai
            if not self._client:
                self._client = openai.AsyncOpenAI(
                    api_key=self.api_key,
                    timeout=60.0  # Increase timeout from default ~30s to 60s
                )
            
            start_time = time.time()
            
            messages = []
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.prompt})
            
            kwargs = {
                "model": request.model.value,
                "messages": messages,
            }
            
            # O4 and O3 models use max_completion_tokens instead of max_tokens
            if request.model.value.startswith(("o3", "o4")):
                kwargs["max_completion_tokens"] = request.max_tokens
            else:
                kwargs["max_tokens"] = request.max_tokens
            
            # O3 and O4 models don't support temperature parameter
            if not request.model.value.startswith(("o3", "o4")):
                kwargs["temperature"] = request.temperature
            
            # Add JSON mode if requested
            if request.json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            
            response = await self._client.chat.completions.create(**kwargs)
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Simple cost estimation (approximate)
            cost_per_1k_tokens = {
                "gpt-4o-mini": 0.00015,
                "gpt-3.5-turbo": 0.0015,
                "gpt-4o": 0.03,
                "gpt-4-turbo": 0.01,
                "o3-mini": 0.002,  # Placeholder cost for O3 mini
                "o4-mini": 0.003   # Placeholder cost for O4 mini
            }
            
            usage = response.usage.model_dump() if response.usage else {}
            total_tokens = usage.get("total_tokens", 0)
            cost_estimate = (total_tokens / 1000) * cost_per_1k_tokens.get(request.model.value, 0.01)
            
            return LLMResponse(
                content=response.choices[0].message.content or "",
                model=response.model,
                usage=usage,
                cost_estimate=cost_estimate,
                latency_ms=latency_ms,
                provider="openai"
            )
            
        except Exception as e:
            logger.error(f"OpenAI generation failed: {e}")
            return LLMResponse(
                content="",
                model=request.model.value,
                usage={},
                cost_estimate=0.0,
                latency_ms=0,
                provider="openai",
                error=str(e)
            )


class AnthropicProvider(LLMProviderBase):
    """Anthropic provider implementation."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None
        
    def is_available(self) -> bool:
        """Check if Anthropic is configured."""
        try:
            import anthropic
            return bool(self.api_key)
        except ImportError:
            return False
    
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate response using Anthropic."""
        if not self.is_available():
            raise RuntimeError("Anthropic provider not available")
        
        try:
            import anthropic
            if not self._client:
                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            
            start_time = time.time()
            
            message = await self._client.messages.create(
                model=request.model.value,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=request.system_prompt or "",
                messages=[{"role": "user", "content": request.prompt}]
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Simple cost estimation for Claude models
            cost_per_1k_tokens = {
                "claude-3-haiku-20240307": 0.00025,
                # "claude-3-5-sonnet-20241022": 0.003,
                "claude-sonnet-4-6": 0.003,
                # "claude-3-opus-20240229": 0.015
                "claude-opus-4-6": 0.015
            }
            
            usage = {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
                "total_tokens": message.usage.input_tokens + message.usage.output_tokens
            }
            
            total_tokens = usage["total_tokens"]
            cost_estimate = (total_tokens / 1000) * cost_per_1k_tokens.get(request.model.value, 0.003)
            
            return LLMResponse(
                content=message.content[0].text if message.content else "",
                model=message.model,
                usage=usage,
                cost_estimate=cost_estimate,
                latency_ms=latency_ms,
                provider="anthropic"
            )
            
        except Exception as e:
            logger.error(f"Anthropic generation failed: {e}")
            return LLMResponse(
                content="",
                model=request.model.value,
                usage={},
                cost_estimate=0.0,
                latency_ms=0,
                provider="anthropic",
                error=str(e)
            )


class LLMService:
    """
    Production-ready LLM service with multiple providers, caching, and fallbacks.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize LLM service with configuration.
        
        Args:
            config: Configuration dictionary with provider settings
        """
        self.config = config or self._load_default_config()
        self.providers: Dict[LLMProvider, LLMProviderBase] = {}
        self.cache: Dict[str, LLMResponse] = {}
        self.cache_ttl = self.config.get("cache_ttl", 3600)  # 1 hour default
        self.fallback_chain = self.config.get("fallback_chain", [
            LLMProvider.OPENAI,
            LLMProvider.ANTHROPIC
        ])
        
        # Initialize providers
        self._initialize_providers()
        
    def _load_default_config(self) -> Dict[str, Any]:
        """Load default configuration."""
        return {
            "cache_ttl": 3600,
            "fallback_chain": [LLMProvider.OPENAI, LLMProvider.ANTHROPIC],
            "max_retries": 3,
            "timeout": 30,
            "cost_tracking": True
        }
    
    def _initialize_providers(self):
        """Initialize available providers."""
        # OpenAI
        openai_provider = OpenAIProvider()
        if openai_provider.is_available():
            self.providers[LLMProvider.OPENAI] = openai_provider
            logger.info("OpenAI provider initialized")
        
        # Anthropic
        anthropic_provider = AnthropicProvider()
        if anthropic_provider.is_available():
            self.providers[LLMProvider.ANTHROPIC] = anthropic_provider
            logger.info("Anthropic provider initialized")
        
        if not self.providers:
            logger.warning("No LLM providers available")
    
    def _get_cache_key(self, request: LLMRequest) -> str:
        """Generate cache key for request."""
        key_data = {
            "prompt": request.prompt,
            "model": request.model.value,
            "system_prompt": request.system_prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature
        }
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _is_cache_valid(self, cached_response: LLMResponse, cache_time: float) -> bool:
        """Check if cached response is still valid."""
        return (time.time() - cache_time) < self.cache_ttl
    
    async def generate_response(self, prompt: str, system_prompt: Optional[str] = None, model: LLMModel = LLMModel.GPT4O, max_tokens: int = 4096, temperature: float = 0.1, json_mode: bool = False, use_cache: bool = True) -> LLMResponse:
        """
        Simple wrapper for generate() method that accepts string prompts.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            model: LLM model to use
            max_tokens: Maximum tokens to generate (default: 4096)
            temperature: Temperature for randomness
            json_mode: Force JSON response format (default: False)
            use_cache: Whether to use caching (default: True)

        Returns:
            LLM response
        """
        request = LLMRequest(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=system_prompt,
            json_mode=json_mode
        )
        return await self.generate(request, use_cache=use_cache)

    async def generate_with_pydantic(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Any,
        model_name: str = "gpt-4o-mini",
        call_type: Optional[str] = None,
        approach_index: Optional[int] = None,
        call_purpose: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.1,
        use_cache: bool = True
    ) -> Any:
        """
        Generate response and validate with Pydantic model.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            response_model: Pydantic model class for validation
            model_name: Model name string (converted to LLMModel enum)
            call_type: Type of call for logging (optional)
            approach_index: Approach index for logging (optional)
            call_purpose: Purpose of call for logging (optional)
            max_tokens: Maximum tokens to generate
            temperature: Temperature for randomness
            use_cache: Whether to use caching

        Returns:
            Validated Pydantic model instance with _tokens_used and _metadata attributes
        """
        # Convert model_name string to LLMModel enum
        model_map = {
            "gpt-4o-mini": LLMModel.GPT4O_MINI,
            "gpt-4o": LLMModel.GPT4O,
            "gpt-3.5-turbo": LLMModel.GPT35_TURBO,
            "gpt-4-turbo": LLMModel.GPT4_TURBO,
            # "claude-3-5-sonnet-20241022": LLMModel.CLAUDE_SONNET,
            "claude-sonnet-4-6": LLMModel.CLAUDE_SONNET,
            "claude-3-haiku-20240307": LLMModel.CLAUDE_HAIKU,
            # "claude-3-opus-20240229": LLMModel.CLAUDE_OPUS,
            "claude-opus-4-6": LLMModel.CLAUDE_OPUS,
            "o3-mini": LLMModel.O3_MINI,
            "o4-mini": LLMModel.O4_MINI
        }
        model = model_map.get(model_name, LLMModel.GPT4O_MINI)

        # Generate response with JSON mode enabled
        response = await self.generate_response(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
            use_cache=use_cache
        )

        if response.error:
            raise RuntimeError(f"LLM generation failed: {response.error}")

        # Parse and validate with Pydantic
        try:
            # Extract JSON from markdown code blocks if present
            content = response.content.strip()
            if content.startswith("```json"):
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                if json_end != -1:
                    content = content[json_start:json_end].strip()
                else:
                    content = content[json_start:].strip()
            elif content.startswith("```"):
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                if json_end != -1:
                    content = content[json_start:json_end].strip()
                else:
                    content = content[json_start:].strip()

            # Parse JSON
            data = json.loads(content)

            # Validate with Pydantic model
            validated_model = response_model(**data)

            # Attach metadata to the model instance as private attributes
            # This allows the caller to access token info without breaking the Pydantic model
            validated_model._tokens_used = response.usage.get('total_tokens', 0)
            validated_model._metadata = {
                'model': response.model,
                'cost': response.cost_estimate,
                'latency_ms': response.latency_ms,
                'usage': response.usage
            }

            return validated_model

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}\nContent: {response.content[:500]}")
            raise ValueError(f"Invalid JSON in LLM response: {e}")
        except Exception as e:
            logger.error(f"Failed to validate with Pydantic model {response_model.__name__}: {e}")
            raise ValueError(f"Pydantic validation failed: {e}")
    
    async def generate(self, request: LLMRequest, use_cache: bool = True) -> LLMResponse:
        """
        Generate response with fallback and caching.
        
        Args:
            request: LLM request
            use_cache: Whether to use caching
            
        Returns:
            LLM response
        """
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(request)
            if cache_key in self.cache:
                cached_response = self.cache[cache_key]
                cached_response.cached = True
                logger.debug(f"Cache hit for request: {cache_key[:8]}...")
                return cached_response
        
        # Try providers in fallback order
        last_error = None
        for provider_type in self.fallback_chain:
            if provider_type not in self.providers:
                continue
                
            try:
                provider = self.providers[provider_type]
                response = await provider.generate(request)
                
                if not response.error:
                    # Cache successful response
                    if use_cache:
                        self.cache[cache_key] = response
                    
                    logger.info(f"Successfully generated response using {provider_type.value}")
                    return response
                else:
                    last_error = response.error
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Provider {provider_type.value} failed: {e}")
                continue
        
        # All providers failed
        logger.error(f"All LLM providers failed. Last error: {last_error}")
        return LLMResponse(
            content="",
            model="unknown",
            usage={},
            cost_estimate=0.0,
            latency_ms=0,
            provider="none",
            error=f"All providers failed: {last_error}"
        )
    
    async def filter_code_results(self, vector_results: str, query: str) -> Dict[str, Any]:
        """
        Filter and prioritize vector search results using LLM.
        
        Args:
            vector_results: Raw results from codebase-vector-rag
            query: Original user query
            
        Returns:
            Filtered and prioritized results
        """
        system_prompt = """You are a code analysis expert. Your task is to analyze vector search results from a codebase and filter/prioritize them based on relevance to the user's query.

Return a JSON response with:
1. "relevant_chunks": List of most relevant code chunks (max 5)
2. "key_concepts": Extracted key concepts from the query
3. "suggested_cypher_targets": Neo4j node types/relationships to target
4. "analysis_focus": What aspects to focus on in further analysis

Be concise and focus on actionable insights."""
        
        prompt = f"""
User Query: {query}

Vector Search Results:
{vector_results}

Please analyze these results and provide a filtered, prioritized response focusing on the most relevant code chunks for the user's query.
"""
        
        request = LLMRequest(
            prompt=prompt,
            model=LLMModel.GPT4O_MINI,  # Use cheap model for filtering
            system_prompt=system_prompt,
            max_tokens=800,
            temperature=0.1
        )
        
        response = await self.generate(request)
        
        if response.error:
            return {
                "error": f"LLM filtering failed: {response.error}",
                "raw_results": vector_results
            }
        
        try:
            # Extract JSON from markdown code blocks if present
            content = response.content.strip()
            if content.startswith("```json"):
                # Extract JSON from markdown code block
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                if json_end != -1:
                    content = content[json_start:json_end].strip()
                else:
                    # If no closing ```, take everything after ```json
                    content = content[json_start:].strip()
            elif content.startswith("```"):
                # Handle generic code block
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                if json_end != -1:
                    content = content[json_start:json_end].strip()
                else:
                    content = content[json_start:].strip()
            
            # Try to parse JSON response
            filtered_data = json.loads(content)
            filtered_data["llm_metadata"] = {
                "model": response.model,
                "cost": response.cost_estimate,
                "latency_ms": response.latency_ms
            }
            return filtered_data
        except json.JSONDecodeError as e:
            # Fallback if JSON parsing fails
            return {
                "filtered_analysis": response.content,
                "raw_results": vector_results,
                "llm_metadata": {
                    "model": response.model,
                    "cost": response.cost_estimate,
                    "latency_ms": response.latency_ms
                }
            }
    
    async def generate_cypher_query(self, filtered_results: Dict[str, Any], user_query: str, error_feedback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate Cypher queries based on filtered vector results with optional error feedback for retries.
        
        Args:
            filtered_results: Filtered results from vector analysis
            user_query: Original user query
            error_feedback: Optional feedback from previous failed attempts containing
                          previous_queries, previous_errors, retry_attempt, and instructions
            
        Returns:
            Generated Cypher queries and execution plan
        """
        # Load the graph schema for more accurate query generation
        schema_content = self._load_graph_schema()
        
        system_prompt = f"""CRITICAL: UNIVERSAL LANGUAGE-AGNOSTIC CPG DISCLAIMER
=====================================================
This is a UNIVERSAL, LANGUAGE-AGNOSTIC Code Property Graph that represents codebases 
written in ANY programming language (C, C++, C#, Java, JavaScript, Python, COBOL, etc.).

DO NOT make language-specific assumptions about node types:
- "Function" node ≠ standalone function (could be method, procedure, subroutine)
- "Type" node ≠ just classes (could be struct, interface, enum, typedef)
- "Variable" node ≠ just variables (could be field, parameter, constant)

RELY ONLY ON THE SCHEMA RELATIONSHIPS PROVIDED BELOW.
The schema defines the ONLY valid connections between nodes.

You are a Neo4j Cypher expert specializing in code property graphs (CPG). 

You have access to a detailed graph schema that defines the exact node types, attributes, and relationships available in the database.

GRAPH SCHEMA:
{schema_content}

ENHANCED SEMANTIC ANALYSIS GUIDELINES:
Generate Cypher queries that capture rich semantic information from the graph by:

1. **Leveraging Rich Node Attributes**: Beyond basic name/file_path, use semantic attributes like:
   - Function: `body`, `return_type`, `parameters`, `modifier`, `documentation`, `constraints`
   - Type: `fields`, `base_list`, `is_abstract`, `access_modifier`, `documentation`, `type_parameters`
   - Variable: `initial_value`, `access_modifier`, `type_kind`, `explicit_interface`, `accessors`
   - Position data: `start_point`, `end_point`, `start_byte`, `end_byte` for location context

2. **Complex Relationship Patterns**: Create queries that traverse multiple relationships to reveal:
   - Call chains: Function -> CALLS -> Function patterns
   - Inheritance hierarchies: Type -> INHERITS_FROM -> Type chains
   - Composition patterns: Type -> CONTAINS -> Variable/Function relationships
   - Cross-file dependencies: File -> CONTAINS -> Type -> CALLS -> Function patterns

3. **Semantic Context Queries**: Include queries that provide contextual understanding:
   - Functions with their parameters and return types
   - Classes with their inheritance relationships and member details
   - Variable usage patterns and their scope contexts
   - Interface implementations and contract fulfillments

4. **Multi-hop Analysis**: Generate queries that span multiple nodes to reveal deeper insights:
   - Who calls what and with what parameters
   - Implementation patterns across inheritance hierarchies
   - Data flow through variable assignments and function parameters
   - Architectural patterns through namespace and file organization

IMPORTANT TECHNICAL GUIDELINES:
- Use only node types from the schema: File, Function, Type, Variable, Namespace, Macro, Block, Literal
- Use only relationships from the schema: CALLS, DEFINED_IN, HAS_TYPE, INCLUDED_IN, HAS_PARAMETER, CONTAINS, INHERITS_FROM, IMPLEMENTS, DECLARED_IN
- Reference only attributes that exist for each node type as defined in the schema
- Use OPTIONAL MATCH when relationships might not exist
- Include WHERE clauses to filter by meaningful attributes (not just name matching)
- Use appropriate LIMIT clauses but prioritize semantic richness over arbitrary limits


Return JSON with:
1. "primary_query": Main Cypher query that captures the most semantic information relevant to the user query
2. "supporting_queries": Additional queries that provide complementary semantic context (max 2)
3. "query_explanation": Detailed explanation of what semantic insights each query provides
4. "expected_results": Specific description of the Neo4j data structures that will be returned, including exact node properties and relationship details (e.g., "List of Type nodes with properties: {{name, type_kind, access_modifier, fields, base_list, file_path}} and connected Function nodes with properties: {{name, parameters, return_type, body, modifier}}")

Focus on generating queries that reveal deep semantic understanding of the codebase structure, relationships, and patterns, ensuring the raw graph data contains rich semantic information."""
        
        # Build the main prompt
        prompt_parts = [
            f"User Query: {user_query}",
            "",
            "Filtered Analysis Results:",
            json.dumps(filtered_results, indent=2)
        ]
        
        # Add error feedback if provided (for retry attempts)
        if error_feedback:
            prompt_parts.extend([
                "",
                "=== ERROR FEEDBACK FROM PREVIOUS ATTEMPTS ===",
                f"Retry Attempt: {error_feedback.get('retry_attempt', 'Unknown')}",
                f"Instructions: {error_feedback.get('instructions', '')}",
                ""
            ])
            
            if error_feedback.get('previous_queries'):
                prompt_parts.append("Previous Failed Queries:")
                for i, query in enumerate(error_feedback['previous_queries']):
                    prompt_parts.append(f"{i+1}. {query}")
                prompt_parts.append("")
            
            if error_feedback.get('previous_errors'):
                prompt_parts.append("Previous Errors:")
                for i, error in enumerate(error_feedback['previous_errors']):
                    prompt_parts.append(f"{i+1}. {error}")
                prompt_parts.append("")
            
            prompt_parts.append("Please analyze these errors and generate corrected Cypher queries that avoid these issues.")
        else:
            prompt_parts.append("\nGenerate appropriate Cypher queries to analyze the code property graph based on these filtered results.")
        
        prompt = "\n".join(prompt_parts)
        
        request = LLMRequest(
            prompt=prompt,
            model=LLMModel.GPT4O,  # Use gpt-4o for query generation
            system_prompt=system_prompt,
            max_tokens=1200,
            temperature=0.1
        )
        
        response = await self.generate(request)
        
        if response.error:
            return {
                "error": f"Cypher generation failed: {response.error}",
                "fallback_query": "MATCH (n) RETURN count(n) as total_nodes LIMIT 10"
            }
        
        try:
            # Extract JSON from markdown code blocks if present
            content = response.content.strip()
            
            # First, try to find JSON code blocks
            import re
            json_block_pattern = r'```json\s*(.*?)\s*```'
            json_blocks = re.findall(json_block_pattern, content, re.DOTALL)
            
            if json_blocks:
                # Use the first JSON block found
                content = json_blocks[0].strip()
            else:
                # Fallback: look for any JSON-like structure
                json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                matches = re.findall(json_pattern, content, re.DOTALL)
                if matches:
                    # Try to parse each match until we find a valid one
                    for match in matches:
                        try:
                            test_parse = json.loads(match)
                            if "primary_query" in test_parse or "supporting_queries" in test_parse:
                                content = match
                                break
                        except json.JSONDecodeError:
                            continue
                else:
                    # If no JSON found, try the original parsing logic
                    if content.startswith("```json"):
                        # Extract JSON from markdown code block
                        json_start = content.find("```json") + 7
                        json_end = content.find("```", json_start)
                        if json_end != -1:
                            content = content[json_start:json_end].strip()
                        else:
                            # If no closing ```, take everything after ```json
                            content = content[json_start:].strip()
                    elif content.startswith("```"):
                        # Handle generic code block
                        json_start = content.find("```") + 3
                        json_end = content.find("```", json_start)
                        if json_end != -1:
                            content = content[json_start:json_end].strip()
                        else:
                            content = content[json_start:].strip()
            
            cypher_data = json.loads(content)
            cypher_data["llm_metadata"] = {
                "model": response.model,
                "cost": response.cost_estimate,
                "latency_ms": response.latency_ms
            }
            return cypher_data
        except json.JSONDecodeError:
            return {
                "generated_analysis": response.content,
                "fallback_query": "MATCH (n) RETURN count(n) as total_nodes LIMIT 10",
                "llm_metadata": {
                    "model": response.model,
                    "cost": response.cost_estimate,
                    "latency_ms": response.latency_ms
                }
            }
    
    async def synthesize_comprehensive_response(
        self,
        user_query: str,
        vector_results: Union[str, List, Dict],
        cpg_results: List[Dict],
        max_tokens: int = 2000
    ) -> Dict[str, Any]:
        """
        Synthesize a comprehensive response combining vector and CPG results.
        
        Args:
            user_query: Original user query
            vector_results: Results from vector search (semantic similarity)
            cpg_results: Results from CPG queries (structural analysis)
            max_tokens: Maximum tokens for synthesis response
            
        Returns:
            Dictionary with synthesis response and metadata
        """
        try:
            # Prepare vector results summary
            if isinstance(vector_results, str):
                vector_summary = vector_results[:2000]  # Truncate for context
            elif isinstance(vector_results, list):
                vector_summary = f"Found {len(vector_results)} relevant code segments:\n"
                for i, result in enumerate(vector_results[:3]):  # Take first 3
                    if isinstance(result, dict):
                        content = result.get('content', result.get('text', str(result)))
                        vector_summary += f"- {content[:300]}...\n"
                    else:
                        vector_summary += f"- {str(result)[:300]}...\n"
            elif isinstance(vector_results, dict):
                vector_summary = f"Vector analysis: {str(vector_results)[:2000]}"
            else:
                vector_summary = str(vector_results)[:2000]
            
            # Prepare CPG results summary
            cpg_summary = f"Executed {len(cpg_results)} graph queries:\n"
            successful_queries = 0
            
            for i, cpg_result in enumerate(cpg_results[:3]):  # Take first 3
                if cpg_result.get('status') == 'success':
                    successful_queries += 1
                    query_result = cpg_result.get('result', '')
                    cypher_query = cpg_result.get('cypher_query', '')
                    purpose = cpg_result.get('purpose', 'Graph analysis')
                    
                    cpg_summary += f"\nQuery {i+1} ({purpose}):\n"
                    cpg_summary += f"Cypher: {cypher_query[:100]}...\n"
                    cpg_summary += f"Results: {str(query_result)[:400]}...\n"
                elif cpg_result.get('error'):
                    cpg_summary += f"\nQuery {i+1}: Failed - {cpg_result.get('error', 'Unknown error')[:100]}\n"
            
            cpg_summary += f"\nSummary: {successful_queries}/{len(cpg_results)} queries successful"
            
            # Determine what analysis sources are available
            has_vector_results = (
                isinstance(vector_results, (list, dict)) and vector_results and 
                not (isinstance(vector_results, str) and "No vector search performed" in vector_results)
            ) or (isinstance(vector_results, str) and vector_results.strip() and "No vector search performed" not in vector_results)
            
            has_cpg_results = (
                isinstance(cpg_results, list) and cpg_results and 
                any(r.get('status') == 'success' for r in cpg_results)
            )
            
            # Create adaptive synthesis prompt based on available data
            if has_vector_results and has_cpg_results:
                analysis_context = "both vector search and code property graph analysis"
                instructions = """INSTRUCTIONS:
1. Provide a direct, comprehensive answer to the user's question
2. Combine insights from both vector search (semantic content) and graph analysis (structural relationships)
3. Include specific code examples, file references, and concrete findings when available
4. Highlight key discoveries from both analysis approaches
5. Structure the response clearly with sections if appropriate
6. Avoid repeating the same information from both sources
7. Focus on actionable insights and practical implications

Synthesize these results into a cohesive analysis that leverages the strengths of both approaches."""
            elif has_vector_results:
                analysis_context = "vector search analysis (semantic similarity matching)"
                instructions = """INSTRUCTIONS:
1. Provide a direct, comprehensive answer to the user's question using the vector search results
2. Focus on semantic content analysis and code similarity matching
3. Include specific code examples, file references, and concrete findings when available
4. Structure the response clearly with sections if appropriate
5. Focus on actionable insights from the semantic analysis
6. Note that this analysis is based on content similarity matching

Analyze and synthesize the vector search results to provide comprehensive insights."""
            elif has_cpg_results:
                analysis_context = "code property graph analysis (structural/relationship analysis)"
                instructions = """INSTRUCTIONS:
1. Provide a direct, comprehensive answer to the user's question using the graph analysis results
2. Focus on structural relationships, dependencies, and architectural patterns
3. Include specific code examples, file references, and concrete findings when available
4. Structure the response clearly with sections if appropriate
5. Focus on actionable insights from the structural analysis
6. Note that this analysis is based on code structure and relationships

Analyze and synthesize the graph query results to provide comprehensive insights."""
            else:
                analysis_context = "available analysis data"
                instructions = """INSTRUCTIONS:
1. Provide the best possible answer to the user's question using any available information
2. Be honest about limitations in the available data
3. Focus on any concrete findings that are available
4. Structure the response clearly
5. Suggest alternative approaches if the current analysis is insufficient

Work with the available data to provide the most helpful response possible."""
            
            synthesis_prompt = f"""You are an expert code analyst. Synthesize a comprehensive response using {analysis_context}:

USER QUERY: {user_query}

VECTOR SEARCH RESULTS (semantic similarity matching):
{vector_summary}

CODE PROPERTY GRAPH RESULTS (structural/relationship analysis):
{cpg_summary}

{instructions}"""

            # Generate synthesis using LLM
            request = LLMRequest(
                prompt=synthesis_prompt,
                model=LLMModel.GPT4O,  # Use powerful model for synthesis
                max_tokens=max_tokens,
                temperature=0.1,
                system_prompt="You are an expert code analyst providing comprehensive technical analysis by synthesizing multiple data sources."
            )
            
            response = await self.generate(request, use_cache=True)
            
            if response.error:
                logger.error(f"LLM synthesis failed: {response.error}")
                # Return fallback response with raw data
                return {
                    "status": "fallback",
                    "synthesis": f"""# Analysis Results

## User Query
{user_query}

## Vector Search Results
{vector_summary}

## Code Property Graph Analysis  
{cpg_summary}

*Note: LLM synthesis failed ({response.error}), showing raw analysis results.*""",
                    "error": response.error,
                    "metadata": {
                        "vector_sources": len(vector_results) if isinstance(vector_results, list) else 1,
                        "cpg_queries": len(cpg_results),
                        "successful_cpg_queries": successful_queries,
                        "synthesis_method": "fallback"
                    }
                }
            
            return {
                "status": "success",
                "synthesis": response.content,
                "metadata": {
                    "vector_sources": len(vector_results) if isinstance(vector_results, list) else 1,
                    "cpg_queries": len(cpg_results),
                    "successful_cpg_queries": successful_queries,
                    "synthesis_method": "llm_generated",
                    "llm_model": response.model,
                    "cost_estimate": response.cost_estimate,
                    "latency_ms": response.latency_ms,
                    "tokens_used": response.usage
                }
            }
            
        except Exception as e:
            logger.error(f"Synthesis processing failed: {e}")
            return {
                "status": "error",
                "synthesis": f"""# Analysis Error

**Query:** {user_query}

**Error:** Failed to synthesize results - {str(e)}

**Available Data:**
- Vector Results: {len(vector_results) if isinstance(vector_results, list) else 'Available'}
- CPG Queries: {len(cpg_results)} total

Please review the detailed analysis results for raw data.""",
                "error": str(e),
                "metadata": {
                    "vector_sources": len(vector_results) if isinstance(vector_results, list) else 0,
                    "cpg_queries": len(cpg_results),
                    "successful_cpg_queries": len([r for r in cpg_results if r.get('status') == 'success']),
                    "synthesis_method": "error_fallback"
                }
            }

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get LLM usage statistics."""
        total_requests = len(self.cache)
        available_providers = [p.value for p in self.providers.keys()]
        
        return {
            "total_cached_requests": total_requests,
            "available_providers": available_providers,
            "cache_hit_ratio": "Unknown",  # Would need request tracking
            "total_estimated_cost": 0.0  # Would need cost tracking
        }
    
    def clear_cache(self):
        """Clear the response cache."""
        self.cache.clear()
        logger.info("LLM cache cleared")
    
    def _load_graph_schema(self) -> str:
        """Load the graph schema from the schemas directory."""
        try:
            import os
            import yaml
            
            # Get the path to the schema file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            schema_path = os.path.join(current_dir, "..", "schemas", "project_knowledgebase_graph_schema.yaml")
            
            if os.path.exists(schema_path):
                with open(schema_path, 'r', encoding='utf-8') as f:
                    schema_data = yaml.safe_load(f)
                
                # Format the schema for the LLM prompt
                schema_text = "=== NODE TYPES ===\n"
                for node_type, details in schema_data.get('nodes', {}).items():
                    schema_text += f"\n{node_type}:\n"
                    schema_text += f"  - Attributes: {', '.join(details.get('attributes', []))}\n"
                    schema_text += f"  - Relationships: {', '.join(details.get('relationships', []))}\n"
                
                schema_text += "\n=== RELATIONSHIPS ===\n"
                for rel_type, details in schema_data.get('relationships', {}).items():
                    schema_text += f"\n{rel_type}:\n"
                    from_types = details.get('from', [])
                    to_types = details.get('to', [])
                    if isinstance(from_types, str):
                        from_types = [from_types]
                    if isinstance(to_types, str):
                        to_types = [to_types]
                    schema_text += f"  - From: {', '.join(from_types)}\n"
                    schema_text += f"  - To: {', '.join(to_types)}\n"
                
                return schema_text
            else:
                logger.warning(f"Graph schema file not found at {schema_path}")
                return "Schema not available - using basic CPG knowledge"
                
        except Exception as e:
            logger.error(f"Failed to load graph schema: {e}")
            return "Schema loading failed - using basic CPG knowledge"
    
    async def synthesize_by_intent(self, user_query: str, context: dict, entities: dict) -> dict:
        """
        Generalized synthesis based on detected intent patterns
        """
        try:
            # Import intent classifier
            from core.intent_classifier import IntentClassifier
            
            # Classify intent
            intent_classifier = IntentClassifier(self)
            intent = await intent_classifier.classify_intent(user_query)
            
            # Enhance intent with entity context
            enhanced_intent = intent_classifier.enhance_intent_with_context(intent, entities)
            
            # Dynamic prompt construction
            base_prompt = f"""QUERY ANALYSIS:
- Intent Type: {enhanced_intent['type']}
- Analysis Required: {enhanced_intent['analysis_type']}
- Expected Format: {enhanced_intent['response_format']}
- Confidence: {enhanced_intent['confidence']:.2f}

USER QUESTION: {user_query}

RETRIEVED CONTEXT: {self._format_context_for_intent(context, enhanced_intent)}

EXTRACTED ENTITIES: {entities}

INSTRUCTIONS: {enhanced_intent['instructions']}

RESPONSE GUIDELINES:
1. Be direct and precise - avoid generic architectural discussions
2. Use the specific format indicated: {enhanced_intent['response_format']}
3. Include file:line references when available
4. Focus on answering the exact question asked

Answer:"""
            
            response = await self.generate_response(base_prompt)
            
            return {
                "answer": response.content,
                "intent_detected": enhanced_intent,
                "context_used": context,
                "metadata": {
                    "analysis_type": enhanced_intent['analysis_type'],
                    "response_format": enhanced_intent['response_format'],
                    "confidence": enhanced_intent['confidence'],
                    "model": response.model,
                    "cost": response.cost_estimate,
                    "latency_ms": response.latency_ms
                }
            }
            
        except Exception as e:
            logger.error(f"Intent-based synthesis failed: {e}")
            # Fallback to basic synthesis
            return await self._fallback_template_synthesis(context, user_query, entities)
    
    def _format_context_for_intent(self, context: dict, intent: dict) -> str:
        """Format retrieved context based on intent type"""
        analysis_type = intent.get('analysis_type', '')
        
        if analysis_type == 'parse_and_count':
            # Prioritize code bodies for counting
            return self._extract_code_bodies(context)
        elif analysis_type == 'extract_elements':
            # Prioritize symbols_location data
            return self._extract_structural_data(context)
        elif analysis_type == 'traverse_relationships':
            # Prioritize relationship data
            return self._extract_relationship_data(context)
        elif analysis_type == 'entity_location':
            # Prioritize location information
            return self._extract_location_data(context)
        else:
            # General context formatting
            return self._format_general_context(context)
    
    def _extract_code_bodies(self, context: dict) -> str:
        """Extract code bodies for content analysis"""
        code_bodies = []
        
        # Handle different context structures
        if isinstance(context, dict):
            if "ranked_nodes" in context:
                nodes = context["ranked_nodes"]
            elif "results" in context:
                nodes = context["results"]
            else:
                nodes = [context]
        elif isinstance(context, list):
            nodes = context
        else:
            return str(context)
        
        for node in nodes:
            if isinstance(node, dict):
                # Handle template-based query field patterns
                body = (node.get("body") or 
                       node.get("t.body") or 
                       node.get("contained.body") or  # From expansion queries
                       node.get("func.body") or       # From function queries  
                       node.get("f.body"))            # From file queries
                if body and isinstance(body, str) and len(body) > 10:
                    # Extract file path using template patterns
                    file_path = (node.get("file_path") or 
                               node.get("t.file_path") or
                               node.get("contained.file_path") or
                               node.get("func.file_path") or
                               node.get("f.file_path") or "unknown")
                    
                    # Extract name using template patterns  
                    name = (node.get("name") or 
                           node.get("t.name") or
                           node.get("contained.name") or
                           node.get("func.name") or
                           node.get("f.name") or "unnamed")
                    
                    code_bodies.append(f"=== {name} in {file_path} ===\n{body}\n")
        
        return "\n".join(code_bodies) if code_bodies else "No code bodies available"
    
    def _extract_structural_data(self, context: dict) -> str:
        """Extract structural data for element analysis"""
        structural_info = []
        
        # Handle different context structures
        if isinstance(context, dict):
            if "ranked_nodes" in context:
                nodes = context["ranked_nodes"]
            elif "results" in context:
                nodes = context["results"]
            else:
                nodes = [context]
        elif isinstance(context, list):
            nodes = context
        else:
            return str(context)
        
        for node in nodes:
            if isinstance(node, dict):
                # Handle template-based query field patterns for names and paths
                name = (node.get("name") or 
                       node.get("t.name") or
                       node.get("contained.name") or
                       node.get("func.name") or
                       node.get("f.name") or "unnamed")
                
                file_path = (node.get("file_path") or 
                           node.get("t.file_path") or
                           node.get("contained.file_path") or
                           node.get("func.file_path") or
                           node.get("f.file_path") or "unknown")
                
                # Extract structural properties with template patterns
                symbols_location = (node.get("symbols_location") or 
                                  node.get("t.symbols_location") or
                                  node.get("contained.symbols_location") or
                                  node.get("func.symbols_location"))
                
                fields = (node.get("fields") or 
                         node.get("t.fields") or
                         node.get("contained.fields"))
                         
                parameters = (node.get("parameters") or 
                            node.get("t.parameters") or
                            node.get("contained.parameters") or
                            node.get("func.parameters"))
                            
                return_type = (node.get("return_type") or 
                             node.get("t.return_type") or
                             node.get("contained.return_type") or
                             node.get("func.return_type"))
                             
                base_list = (node.get("base_list") or 
                           node.get("t.base_list") or
                           node.get("contained.base_list"))
                
                info = f"=== {name} in {file_path} ===\n"
                if symbols_location:
                    info += f"Symbols: {symbols_location}\n"
                if fields:
                    info += f"Fields: {fields}\n"
                if parameters:
                    info += f"Parameters: {parameters}\n"
                if return_type:
                    info += f"Return Type: {return_type}\n"
                if base_list:
                    info += f"Base Types: {base_list}\n"
                
                structural_info.append(info)
        
        return "\n".join(structural_info) if structural_info else "No structural data available"
    
    def _extract_relationship_data(self, context: dict) -> str:
        """Extract relationship data for traversal analysis"""
        relationship_info = []
        
        # Handle different context structures
        if isinstance(context, dict):
            if "ranked_nodes" in context:
                nodes = context["ranked_nodes"]
            elif "results" in context:
                nodes = context["results"]
            else:
                nodes = [context]
        elif isinstance(context, list):
            nodes = context
        else:
            return str(context)
        
        for node in nodes:
            if isinstance(node, dict):
                name = node.get("name") or node.get("t.name", "unnamed")
                file_path = node.get("file_path") or node.get("t.file_path", "unknown")
                type_kind = node.get("type_kind") or node.get("t.type_kind", "unknown")
                
                # Extract relationship properties
                base_list = node.get("base_list") or node.get("t.base_list")
                
                info = f"=== {name} ({type_kind}) in {file_path} ===\n"
                if base_list:
                    info += f"Inherits/Implements: {base_list}\n"
                
                # Add query source information if available
                source = node.get("_source")
                if source:
                    info += f"Source: {source}\n"
                
                relationship_info.append(info)
        
        return "\n".join(relationship_info) if relationship_info else "No relationship data available"
    
    def _extract_location_data(self, context: dict) -> str:
        """Extract location data for entity location queries"""
        location_info = []
        
        # Handle different context structures
        if isinstance(context, dict):
            if "ranked_nodes" in context:
                nodes = context["ranked_nodes"]
            elif "results" in context:
                nodes = context["results"]
            else:
                nodes = [context]
        elif isinstance(context, list):
            nodes = context
        else:
            return str(context)
        
        for node in nodes:
            if isinstance(node, dict):
                name = node.get("name") or node.get("t.name", "unnamed")
                file_path = node.get("file_path") or node.get("t.file_path", "unknown")
                start_point = node.get("start_point") or node.get("t.start_point")
                end_point = node.get("end_point") or node.get("t.end_point")
                
                info = f"=== {name} ===\n"
                info += f"File: {file_path}\n"
                if start_point:
                    info += f"Start: {start_point}\n"
                if end_point:
                    info += f"End: {end_point}\n"
                
                location_info.append(info)
        
        return "\n".join(location_info) if location_info else "No location data available"
    
    def _format_general_context(self, context: dict) -> str:
        """General context formatting"""
        if isinstance(context, dict):
            return str(context)[:2000]  # Truncate for manageable size
        elif isinstance(context, list):
            return f"Found {len(context)} items: " + str(context)[:1500]
        else:
            return str(context)[:2000]
    
    async def _fallback_template_synthesis(self, context: dict, user_query: str, entities: dict) -> dict:
        """Fallback synthesis method when intent-based synthesis fails"""
        try:
            # Simple template-based synthesis
            prompt = f"""Answer this code analysis question directly and concisely.

Question: {user_query}
Context: {str(context)[:1500]}
Entities: {entities}

Provide a direct answer focused on the specific question asked."""
            
            response = await self.generate_response(prompt)
            
            return {
                "answer": response.content,
                "intent_detected": {"type": "fallback", "confidence": 0.3},
                "context_used": context,
                "metadata": {
                    "analysis_type": "fallback_synthesis",
                    "response_format": "general",
                    "confidence": 0.3,
                    "model": response.model,
                    "cost": response.cost_estimate,
                    "latency_ms": response.latency_ms
                }
            }
            
        except Exception as e:
            logger.error(f"Fallback synthesis failed: {e}")
            return {
                "answer": "Error: Unable to synthesize response",
                "intent_detected": {"type": "error", "confidence": 0.0},
                "context_used": context,
                "metadata": {
                    "analysis_type": "error",
                    "response_format": "error",
                    "confidence": 0.0,
                    "error": str(e)
                }
            }
    
    async def synthesize_targeted_response(self, context: dict, user_query: str, entities: dict) -> dict:
        """
        Main synthesis method with evolution path
        """
        try:
            # Try generalized intent-based approach first
            return await self.synthesize_by_intent(user_query, context, entities)
        except Exception as e:
            logger.warning(f"Intent-based synthesis failed, using fallback: {e}")
            # Fallback to template synthesis for reliability
            return await self._fallback_template_synthesis(context, user_query, entities)
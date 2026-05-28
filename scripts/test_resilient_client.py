#!/usr/bin/env python3
"""Test script for ResilientLLMClient fallback mechanism."""

import json
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

from src.core.graph_rag.core.llm_client import ResilientLLMClient
from src.core.graph_rag.core.config import LLMConfig

# Import 4-agent RAG workflow Pydantic models for structured output tests
from src.core.graph_rag.core.models import (
    ProposedQuery,
    ThinkerOutput,
    CodeEntity,
    Finding,
    CypherValidationResult,
)
from src.core.graph_rag.core.enums import ConfidenceLevel

def test_resilient_client_direct():
    """Test ResilientLLMClient directly."""
    print("\n" + "="*60)
    print("Test 1: Direct ResilientLLMClient usage")
    print("="*60)

    # Create client with invalid primary (to trigger fallback)
    client = ResilientLLMClient(
        primary_config={
            "base_url": "http://localhost:9999/v1",  # Invalid URL to force fallback
            "api_key": "invalid-key"
        },
        fallback_url="http://localhost:8889/v1",
        fallback_model="claude-sonnet-4-5-20250514",
        fallback_enabled=True,
    )

    print(f"Fallback available: {client._fallback_available}")

    # Test chat completion (should fall back to Claude adapter)
    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Primary model
            messages=[{"role": "user", "content": "Say 'Hello from fallback!' in exactly 5 words."}],
            max_tokens=50,
            temperature=0.0
        )
        print(f"✅ Response: {response.choices[0].message.content}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_resilient_client_via_config():
    """Test ResilientLLMClient via LLMConfig."""
    print("\n" + "="*60)
    print("Test 2: ResilientLLMClient via LLMConfig.create_client()")
    print("="*60)

    # Create LLMConfig with fallback enabled
    config = LLMConfig(
        model="gpt-4o",
        temperature=0.0,
        base_url="http://localhost:9999/v1",  # Invalid to force fallback
        api_key="invalid-key",
        fallback_enabled=True,
        fallback_url="http://localhost:8889/v1",
        fallback_model="claude-sonnet-4-5-20250514",
    )

    # Create client (should return ResilientLLMClient)
    client = config.create_client(use_fallback=True)
    print(f"Client type: {type(client).__name__}")

    try:
        response = client.chat.completions.create(
            model=config.model,
            messages=[{"role": "user", "content": "What is 2+2? Answer with just the number."}],
            max_tokens=10,
            temperature=0.0
        )
        print(f"✅ Response: {response.choices[0].message.content}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_mcp_management():
    """Test MCP server management on ResilientLLMClient."""
    print("\n" + "="*60)
    print("Test 3: MCP Server Management")
    print("="*60)

    client = ResilientLLMClient(
        fallback_url="http://localhost:8889/v1",
        fallback_enabled=True,
    )

    print(f"Fallback available: {client._fallback_available}")

    if client._fallback_available:
        # Test loading MCP config
        mcp_config_path = "/opt/genpod/fallback_agent/claude_code_mcp_config.json"
        result = client.load_mcp_config(mcp_config_path)
        print(f"Load MCP config result: {result}")

        # Test listing servers
        servers = client.list_mcp_servers()
        print(f"MCP servers: {servers}")

        # Test setting allowed tools
        client.set_allowed_tools([
            "mcp__neo4j_memory__neo4j_execute_query",
            "mcp__qdrant_server__qdrant-find"
        ])
        print(f"Allowed tools: {client.get_allowed_tools()}")
    else:
        print("⚠️  Fallback adapter not running - MCP management tests skipped")


def test_query_validation_blocking():
    """Test that write queries are blocked by CypherQueryValidator."""
    print("\n" + "="*60)
    print("Test 4: Query Validation - CREATE should be BLOCKED")
    print("="*60)

    client = ResilientLLMClient(
        primary_config={
            "base_url": "http://localhost:9999/v1",  # Invalid to force fallback
            "api_key": "invalid-key"
        },
        fallback_url="http://localhost:8889/v1",
        fallback_enabled=True,
        mcp_config_path="/opt/genpod/fallback_agent/claude_code_mcp_config.json",
        allowed_tools=[
            "mcp__neo4j_memory__neo4j_execute_query",
        ]
    )

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping test")
        return

    try:
        # Attempt to CREATE a node - this should be BLOCKED by CypherQueryValidator
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": """Execute this Cypher query using the neo4j_execute_query tool:

CREATE (n:TestNode {name: "test_node", created_by: "resilient_client_test"}) RETURN n

Run the query and tell me what happened."""
            }],
            max_tokens=1000,
            temperature=0.0
        )
        print(f"Response:\n{response.choices[0].message.content}")

        # Check if the response indicates blocking
        content = response.choices[0].message.content.lower()
        if "block" in content or "denied" in content or "not allowed" in content or "rejected" in content:
            print("\n✅ CREATE query was properly BLOCKED!")
        else:
            print("\n⚠️  Response received - check if CREATE was blocked")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_with_mcp_tools():
    """Test using MCP tools through fallback with a READ query."""
    print("\n" + "="*60)
    print("Test 5: Using MCP Tools via Fallback (READ query)")
    print("="*60)

    client = ResilientLLMClient(
        primary_config={
            "base_url": "http://localhost:9999/v1",  # Invalid to force fallback
            "api_key": "invalid-key"
        },
        fallback_url="http://localhost:8889/v1",
        fallback_enabled=True,
        mcp_config_path="/opt/genpod/fallback_agent/claude_code_mcp_config.json",
        allowed_tools=[
            "mcp__neo4j_memory__neo4j_execute_query",
        ]
    )

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping MCP tools test")
        return

    try:
        # Use a specific Cypher query that will actually be executed
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": """Execute this Cypher query using the neo4j_execute_query tool and tell me what node labels exist in the database:

MATCH (n) RETURN DISTINCT labels(n) as labels LIMIT 10

Just run the query and show me the results."""
            }],
            max_tokens=1000,
            temperature=0.0
        )
        print(f"✅ Response:\n{response.choices[0].message.content}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_structured_output_json_object():
    """Test structured output with json_object format."""
    print("\n" + "="*60)
    print("Test 6: Structured Output - JSON Object")
    print("="*60)

    client = ResilientLLMClient(
        primary_config={
            "base_url": "http://localhost:9999/v1",
            "api_key": "invalid-key"
        },
        fallback_url="http://localhost:8889/v1",
        fallback_enabled=True,
    )

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping test")
        return

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": "List 3 programming languages with their year of creation. Return as JSON."
            }],
            max_tokens=500,
            temperature=0.0,
            extra_body={
                "response_format": {"type": "json_object"}
            }
        )
        content = response.choices[0].message.content
        print(f"Response:\n{content}")

        # Try to parse as JSON
        import json
        try:
            parsed = json.loads(content)
            print("\n✅ Valid JSON returned!")
            print(f"Parsed: {json.dumps(parsed, indent=2)}")
        except json.JSONDecodeError as e:
            print(f"\n⚠️  Response is not valid JSON: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_structured_output_json_schema():
    """Test structured output with json_schema format."""
    print("\n" + "="*60)
    print("Test 7: Structured Output - JSON Schema")
    print("="*60)

    client = ResilientLLMClient(
        primary_config={
            "base_url": "http://localhost:9999/v1",
            "api_key": "invalid-key"
        },
        fallback_url="http://localhost:8889/v1",
        fallback_enabled=True,
    )

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping test")
        return

    try:
        # Define a schema for the expected response
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": "Analyze the sentiment of: 'I love this product, it works great!'"
            }],
            max_tokens=500,
            temperature=0.0,
            extra_body={
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "sentiment_analysis",
                        "description": "Sentiment analysis result",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "sentiment": {
                                    "type": "string",
                                    "enum": ["positive", "negative", "neutral"]
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1
                                },
                                "reasoning": {
                                    "type": "string"
                                }
                            },
                            "required": ["sentiment", "confidence", "reasoning"]
                        },
                        "strict": True
                    }
                }
            }
        )
        content = response.choices[0].message.content
        print(f"Response:\n{content}")

        # Try to parse as JSON
        import json
        try:
            parsed = json.loads(content)
            print("\n✅ Valid JSON returned!")
            print(f"Sentiment: {parsed.get('sentiment')}")
            print(f"Confidence: {parsed.get('confidence')}")
            print(f"Reasoning: {parsed.get('reasoning')}")
        except json.JSONDecodeError as e:
            print(f"\n⚠️  Response is not valid JSON: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


# =============================================================================
# Tests using actual 4-Agent RAG Workflow Pydantic Models
# =============================================================================

def _create_fallback_client():
    """Helper to create a ResilientLLMClient with fallback enabled."""
    return ResilientLLMClient(
        primary_config={
            "base_url": "http://localhost:9999/v1",  # Invalid URL to force fallback
            "api_key": "invalid-key"
        },
        fallback_url="http://localhost:8889/v1",
        fallback_model="claude-sonnet-4-5-20250514",
        fallback_enabled=True,
    )


def test_structured_output_proposed_query():
    """Test structured output with ProposedQuery Pydantic model from RAG workflow."""
    print("\n" + "="*60)
    print("Test 8: Structured Output - ProposedQuery Model")
    print("="*60)

    client = _create_fallback_client()

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping test")
        return

    # Get the JSON schema from the Pydantic model
    schema = ProposedQuery.model_json_schema()
    print(f"ProposedQuery schema: {json.dumps(schema, indent=2)[:500]}...")

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": """Generate a proposed Cypher query to find all classes that implement an interface named 'IUserService'.

Include:
- query_id: a unique integer
- purpose: what this query retrieves
- reasoning: why this query helps
- cypher_query: the actual Cypher query
- target_entities: list of entity names being queried
- expected_result_type: what type of results (list, count, etc.)
- depends_on: list of query IDs this depends on (empty if none)"""
            }],
            max_tokens=1000,
            temperature=0.0,
            extra_body={
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "proposed_query",
                        "description": "A proposed Cypher query for code analysis",
                        "schema": schema,
                        "strict": True
                    }
                }
            }
        )
        content = response.choices[0].message.content
        print(f"Response:\n{content}")

        # Validate against Pydantic model
        try:
            parsed = json.loads(content)
            query = ProposedQuery(**parsed)
            print("\n✅ Valid ProposedQuery returned!")
            print(f"Query ID: {query.query_id}")
            print(f"Purpose: {query.purpose}")
            print(f"Cypher: {query.cypher_query}")
            print(f"Target Entities: {query.target_entities}")
        except Exception as e:
            print(f"\n⚠️  Validation failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_structured_output_code_entity():
    """Test structured output with CodeEntity Pydantic model from RAG workflow."""
    print("\n" + "="*60)
    print("Test 9: Structured Output - CodeEntity Model")
    print("="*60)

    client = _create_fallback_client()

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping test")
        return

    # Get the JSON schema from the Pydantic model
    schema = CodeEntity.model_json_schema()
    print(f"CodeEntity schema: {json.dumps(schema, indent=2)}")

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": """Describe a code entity for a Python class named 'UserRepository' in a file 'src/repositories/user.py'.

The entity should have:
- name: the entity name
- entity_type: what type (class, function, interface, etc.)
- file_path: where it's defined
- node_id: a Neo4j node ID (use 12345 as an example)
- properties: additional properties like methods, base_classes, etc."""
            }],
            max_tokens=500,
            temperature=0.0,
            extra_body={
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "code_entity",
                        "description": "A code entity from the codebase",
                        "schema": schema,
                        "strict": True
                    }
                }
            }
        )
        content = response.choices[0].message.content
        print(f"Response:\n{content}")

        # Validate against Pydantic model
        try:
            parsed = json.loads(content)
            entity = CodeEntity(**parsed)
            print("\n✅ Valid CodeEntity returned!")
            print(f"Name: {entity.name}")
            print(f"Type: {entity.entity_type}")
            print(f"File: {entity.file_path}")
            print(f"Node ID: {entity.node_id}")
            print(f"Properties: {entity.properties}")
        except Exception as e:
            print(f"\n⚠️  Validation failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_structured_output_finding():
    """Test structured output with Finding Pydantic model from RAG workflow."""
    print("\n" + "="*60)
    print("Test 10: Structured Output - Finding Model")
    print("="*60)

    client = _create_fallback_client()

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping test")
        return

    # Get the JSON schema from the Pydantic model
    schema = Finding.model_json_schema()
    print(f"Finding schema keys: {list(schema.get('properties', {}).keys())}")

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": """Generate a finding from analyzing a codebase. The finding should be about:
"The UserService class depends on 3 external services: EmailService, CacheService, and LoggingService"

Include:
- claim: the natural language claim about the codebase
- entities: list of code entities involved (each with name, entity_type, optional file_path, node_id, properties)
- evidence: supporting data as a dictionary
- confidence: one of "high", "medium", or "low"
- source_query: the Cypher query that produced this (use a MATCH query)
- cot_agent_id: an agent ID (use "agent_001")"""
            }],
            max_tokens=1500,
            temperature=0.0,
            extra_body={
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "finding",
                        "description": "A structured finding from code analysis",
                        "schema": schema,
                        "strict": True
                    }
                }
            }
        )
        content = response.choices[0].message.content
        print(f"Response:\n{content}")

        # Validate against Pydantic model
        try:
            parsed = json.loads(content)
            finding = Finding(**parsed)
            print("\n✅ Valid Finding returned!")
            print(f"Claim: {finding.claim}")
            print(f"Confidence: {finding.confidence}")
            print(f"Entities count: {len(finding.entities)}")
            for entity in finding.entities:
                print(f"  - {entity.name} ({entity.entity_type})")
            print(f"Source Query: {finding.source_query[:50] if finding.source_query else 'None'}...")
        except Exception as e:
            print(f"\n⚠️  Validation failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_structured_output_thinker_output():
    """Test structured output with ThinkerOutput Pydantic model (complex nested model)."""
    print("\n" + "="*60)
    print("Test 11: Structured Output - ThinkerOutput Model (Nested)")
    print("="*60)

    client = _create_fallback_client()

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping test")
        return

    # Get the JSON schema from the Pydantic model
    schema = ThinkerOutput.model_json_schema()
    print(f"ThinkerOutput schema has {len(schema.get('properties', {}))} top-level properties")
    print(f"Schema size: {len(json.dumps(schema))} characters")

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": """You are a code analysis thinker agent. Generate a reasoning plan to answer the question:
"What are all the dependencies of the UserController class?"

Provide:
1. overall_reasoning: Step-by-step reasoning as a list of strings
2. approach_summary: Brief summary of the approach
3. proposed_queries: List of 2 Cypher queries to execute (each with query_id, purpose, reasoning, cypher_query, target_entities, expected_result_type, depends_on)
4. total_queries: Number of queries"""
            }],
            max_tokens=2000,
            temperature=0.0,
            extra_body={
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "thinker_output",
                        "description": "Output from the Thinker Agent with reasoning and proposed queries",
                        "schema": schema,
                        "strict": True
                    }
                }
            }
        )
        content = response.choices[0].message.content
        print(f"Response (first 500 chars):\n{content[:500]}...")

        # Validate against Pydantic model
        try:
            parsed = json.loads(content)
            output = ThinkerOutput(**parsed)
            print("\n✅ Valid ThinkerOutput returned!")
            print(f"Approach Summary: {output.approach_summary}")
            print(f"Reasoning Steps: {len(output.overall_reasoning)}")
            print(f"Total Queries: {output.total_queries}")
            for query in output.proposed_queries:
                print(f"  Query {query.query_id}: {query.purpose}")
                print(f"    Cypher: {query.cypher_query[:80]}...")
        except Exception as e:
            print(f"\n⚠️  Validation failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


def test_structured_output_cypher_validation_result():
    """Test structured output with CypherValidationResult Pydantic model."""
    print("\n" + "="*60)
    print("Test 12: Structured Output - CypherValidationResult Model")
    print("="*60)

    client = _create_fallback_client()

    if not client._fallback_available:
        print("⚠️  Fallback adapter not running - skipping test")
        return

    # Get the JSON schema from the Pydantic model
    schema = CypherValidationResult.model_json_schema()
    print(f"CypherValidationResult schema properties: {list(schema.get('properties', {}).keys())}")

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": """Generate a Cypher validation result for a query that has some issues.

The validation should show:
- approved: false (the query has issues)
- feedback: explanation of the problems
- specific_issues: list of 2 specific issues found
- suggested_corrections: how to fix the issues
- query_results: empty list (not validating individual queries here)
- invalid_nodes: list with "InvalidNode" as an example
- invalid_properties: list with "unknownProp" as an example
- invalid_relationships: empty list
- path_issues: list with one path issue about unreachable nodes
- observed_categorical_values: dict with example values like {"Statement.statement_type": ["expression", "declaration"]}"""
            }],
            max_tokens=1500,
            temperature=0.0,
            extra_body={
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "cypher_validation_result",
                        "description": "Validation result for Cypher queries",
                        "schema": schema,
                        "strict": True
                    }
                }
            }
        )
        content = response.choices[0].message.content
        print(f"Response:\n{content}")

        # Validate against Pydantic model
        try:
            parsed = json.loads(content)
            result = CypherValidationResult(**parsed)
            print("\n✅ Valid CypherValidationResult returned!")
            print(f"Approved: {result.approved}")
            print(f"Feedback: {result.feedback}")
            print(f"Specific Issues: {result.specific_issues}")
            print(f"Invalid Nodes: {result.invalid_nodes}")
            print(f"Invalid Properties: {result.invalid_properties}")
            print(f"Path Issues: {result.path_issues}")
            print(f"Observed Values: {result.observed_categorical_values}")
        except Exception as e:
            print(f"\n⚠️  Validation failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    print("Testing ResilientLLMClient Fallback Mechanism")
    print("="*60)
    print("Make sure the Claude Code adapter is running at http://localhost:8889")
    print("="*60)

    # Basic tests
    test_resilient_client_direct()
    test_resilient_client_via_config()
    test_mcp_management()
    test_query_validation_blocking()
    test_with_mcp_tools()

    # Basic structured output tests
    test_structured_output_json_object()
    test_structured_output_json_schema()

    # 4-Agent RAG Workflow Pydantic model tests
    test_structured_output_proposed_query()
    test_structured_output_code_entity()
    test_structured_output_finding()
    test_structured_output_thinker_output()
    test_structured_output_cypher_validation_result()

    print("\n" + "="*60)
    print("Tests completed!")
    print("="*60)

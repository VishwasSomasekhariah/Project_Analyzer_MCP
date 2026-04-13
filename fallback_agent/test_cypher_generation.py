#!/usr/bin/env python3
"""
Simple test: Can Claude generate Cypher queries from English + schema?
NO execution, NO tools - just query generation via OpenAI adapter.
"""

import yaml
from pathlib import Path
from openai import OpenAI


def load_schema() -> str:
    """Load schema YAML and format for Claude."""
    schema_path = Path("/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml")
    with open(schema_path) as f:
        schema_data = yaml.safe_load(f)

    # Simple formatting
    formatted = "# Neo4j CPG Schema\n\n## Nodes:\n"
    for node, details in schema_data.get('nodes', {}).items():
        formatted += f"- {node}: {details.get('attributes', [])}\n"

    formatted += "\n## Relationships:\n"
    for rel, details in schema_data.get('relationships', {}).items():
        formatted += f"- {rel}: {details.get('from')} → {details.get('to')}\n"

    return formatted


def test():
    """Test Cypher generation via adapter."""
    print("Testing Cypher Generation via Adapter\n" + "=" * 70)

    # Create OpenAI client pointing to adapter
    client = OpenAI(
        base_url="http://localhost:8889/v1",
        api_key="not-needed"
    )

    schema = load_schema()
    user_query = "What does the CreateWorkers method return?"

    prompt = f"""Generate a Cypher query for this question.

Schema:
{schema}

Question: {user_query}

Return only the Cypher query."""

    # Call through adapter
    response = client.chat.completions.create(
        model="claude-sonnet-4.5",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.0
    )

    print("Generated Cypher:")
    print(response.choices[0].message.content)
    print("\n" + "=" * 70)
    print(f"✅ Test completed (model: {response.model})")


if __name__ == "__main__":
    test()

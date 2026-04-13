"""
Test DynamicSchemaManager with REAL apoc.meta.schema() data from Neo4j
Using direct subprocess call for simplicity
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


# Simple subprocess-based cypher server for testing
class SubprocessCypherServer:
    """Simple cypher server using subprocess calls"""

    def __init__(self, neo4j_config):
        self.neo4j_config = neo4j_config

    async def execute(self, query):
        """Execute query via subprocess"""
        try:
            cmd = [
                "project-analyzer",
                "--config-file", self.neo4j_config,
                "query",
                "--cypher", query,
                "--limit", "1000",  # Higher limit for schema
                "--output-format", "json"
            ]

            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                response = json.loads(result.stdout)
                if response.get("success"):
                    # Convert to expected format
                    return {
                        'status': 'success',
                        'data': response.get('results', [])
                    }
                else:
                    return {
                        'status': 'error',
                        'error': response.get('error', 'Query failed')
                    }
            else:
                return {
                    'status': 'error',
                    'error': result.stderr or 'Subprocess execution failed'
                }

        except subprocess.TimeoutExpired:
            return {
                'status': 'error',
                'error': 'Query timeout'
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }


async def test_schema_manager():
    """Test the DynamicSchemaManager with REAL Neo4j data"""

    print("=" * 80)
    print("🧪 Testing DynamicSchemaManager with REAL Neo4j CPG")
    print("=" * 80)
    print()

    # 1. Create subprocess-based server
    print("🔄 Setting up connection to Neo4j...")
    neo4j_config = "/opt/genpod/neo4j_config.json"
    cypher_server = SubprocessCypherServer(neo4j_config)
    print("✅ Ready to fetch schema")
    print()

    # 2. Fetch raw apoc.meta.schema()
    print("📊 Fetching apoc.meta.schema() from Neo4j...")
    raw_result = await cypher_server.execute(
        "CALL apoc.meta.schema() YIELD value RETURN value"
    )

    if raw_result.get('status') != 'success' or not raw_result.get('data'):
        print(f"❌ Failed to fetch schema: {raw_result.get('error')}")
        return

    raw_apoc_schema = raw_result['data'][0]['value']

    # Show original APOC schema size
    original_json = json.dumps(raw_apoc_schema, indent=2)
    original_size = len(original_json)
    print(f"   Size: {original_size:,} bytes ({original_size / 1024:.1f} KB)")
    print(f"   Lines: {len(original_json.split(chr(10)))}")
    print(f"   Node types: {sum(1 for v in raw_apoc_schema.values() if v.get('type') == 'node')}")
    print(f"   Relationship types: {sum(1 for v in raw_apoc_schema.values() if v.get('type') == 'relationship')}")
    print()

    # Save original for comparison
    with open('/opt/genpod/schema_original_apoc_REAL.json', 'w') as f:
        f.write(original_json)
    print("💾 Saved original to: schema_original_apoc_REAL.json")
    print()

    # 3. Create schema manager and load
    schema_manager = DynamicSchemaManager(cypher_server)

    print("⏳ Loading and parsing schema...")
    await schema_manager.initialize_background()
    print()

    # 4. Show parsed schema
    full_schema = schema_manager.get_full_schema()
    parsed_json = json.dumps(full_schema, indent=2, default=str)
    parsed_size = len(parsed_json)

    print(f"✅ Parsed schema:")
    print(f"   Size: {parsed_size:,} bytes ({parsed_size / 1024:.1f} KB)")
    print(f"   Lines: {len(parsed_json.split(chr(10)))}")
    print(f"   Reduction: {((original_size - parsed_size) / original_size * 100):.1f}%")
    print()

    # Save parsed schema
    await schema_manager.save_to_file('/opt/genpod/schema_parsed_REAL.json')
    print()

    # 5. Show schema summary
    print("📋 Schema Summary:")
    summary = await schema_manager.get_context_relevant_schema(format='text')
    print(summary)
    print()

    # 6. Test context-relevant slicing
    print("=" * 80)
    print("🎯 Context-Relevant Schema Slicing")
    print("=" * 80)
    print()

    # Scenario 1: Query about function calls
    print("Scenario 1: 'Find all functions that CreateWorkers calls'")
    print("   Context needed: Function, CALLS")
    print()

    slice1 = await schema_manager.get_context_relevant_schema(
        node_types=['Function'],
        relationship_types=['CALLS'],
        format='text'
    )
    slice1_size = len(slice1)
    print(slice1)
    print(f"   Size: {slice1_size} bytes (was {original_size} bytes)")
    print(f"   Reduction: {((original_size - slice1_size) / original_size * 100):.1f}%")
    print()

    # Scenario 2: Query about class hierarchy
    print("-" * 80)
    print("Scenario 2: 'Find all types that implement IWorker'")
    print("   Context needed: Type, IMPLEMENTS")
    print()

    slice2 = await schema_manager.get_context_relevant_schema(
        node_types=['Type'],
        relationship_types=['IMPLEMENTS', 'CONTAINS'],
        format='text'
    )
    slice2_size = len(slice2)
    print(slice2)
    print(f"   Size: {slice2_size} bytes (was {original_size} bytes)")
    print(f"   Reduction: {((original_size - slice2_size) / original_size * 100):.1f}%")
    print()

    # Scenario 3: Query about return statements
    print("-" * 80)
    print("Scenario 3: 'Find what CreateWorkers returns'")
    print("   Context needed: Function, Statement, Block, CONTAINS, REFERENCES")
    print()

    slice3 = await schema_manager.get_context_relevant_schema(
        node_types=['Function', 'Statement', 'Block'],
        relationship_types=['CONTAINS', 'REFERENCES'],
        format='text'
    )
    slice3_size = len(slice3)
    print(slice3)
    print(f"   Size: {slice3_size} bytes (was {original_size} bytes)")
    print(f"   Reduction: {((original_size - slice3_size) / original_size * 100):.1f}%")
    print()

    # 7. Show JSON format for one slice
    print("=" * 80)
    print("📦 Example: Structured Format (for programmatic use)")
    print("=" * 80)
    print()

    slice_dict = await schema_manager.get_context_relevant_schema(
        node_types=['Function'],
        relationship_types=['CALLS'],
        format='dict'
    )
    # Print first 50 lines only (full version is in schema_parsed_REAL.json)
    slice_json = json.dumps(slice_dict, indent=2, default=str)
    slice_lines = slice_json.split('\n')
    print('\n'.join(slice_lines[:50]))
    if len(slice_lines) > 50:
        print(f"... ({len(slice_lines) - 50} more lines, see schema_parsed_REAL.json)")
    print()

    # 8. Performance summary
    print("=" * 80)
    print("⚡ Performance Summary")
    print("=" * 80)
    print()
    print(f"Original Schema Size:     {original_size:,} bytes ({original_size / 1024:.1f} KB)")
    print(f"Parsed Schema Size:       {parsed_size:,} bytes ({parsed_size / 1024:.1f} KB)")
    print(f"Scenario 1 Slice:         {slice1_size:,} bytes  ({((original_size - slice1_size) / original_size * 100):.1f}% reduction)")
    print(f"Scenario 2 Slice:         {slice2_size:,} bytes  ({((original_size - slice2_size) / original_size * 100):.1f}% reduction)")
    print(f"Scenario 3 Slice:         {slice3_size:,} bytes  ({((original_size - slice3_size) / original_size * 100):.1f}% reduction)")
    print()
    print("💡 Expected LLM Impact:")
    print(f"  • Context size: {((original_size - slice1_size) / original_size * 100):.0f}% smaller on average")
    print(f"  • Response time: 2-3x faster (less context to process)")
    print(f"  • Hallucination: Lower (focused on relevant schema only)")
    print(f"  • Token cost: {((original_size - slice1_size) / original_size * 100):.0f}% reduction")
    print()
    print("✅ Test complete!")


if __name__ == "__main__":
    asyncio.run(test_schema_manager())

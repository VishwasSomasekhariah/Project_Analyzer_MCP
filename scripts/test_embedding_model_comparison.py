#!/usr/bin/env python3
"""
Compare embedding models for CPG type extraction.

Tests:
- all-MiniLM-L6-v2 (baseline, lightweight)
- microsoft/codebert-base (code-specific)

Metrics:
- Extraction time
- Types extracted
- Similarity scores
- Ranking quality
"""
import asyncio
import yaml
import sys
import time
import json
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def test_model(model_name: str, subquery: str, yaml_schema: dict, server):
    """Test a single model and return results."""
    print(f"\n{'='*80}")
    print(f"Testing: {model_name}")
    print(f"{'='*80}")

    # Create schema manager with this model
    start_init = time.time()
    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file=f"/tmp/test_{model_name.replace('/', '_')}_cache.json",
        yaml_schema=yaml_schema,
        embedding_model=model_name
    )

    await schema_manager.initialize_background()
    init_time = time.time() - start_init

    print(f"✅ Initialization: {init_time:.2f}s")

    # Extract types
    start_extract = time.time()
    result = schema_manager.extract_types_from_query(subquery)
    extract_time = time.time() - start_extract

    print(f"✅ Extraction: {extract_time*1000:.2f}ms")
    print(f"\nExtracted node types ({len(result['node_types'])}):")
    for i, nt in enumerate(result['node_types'], 1):
        print(f"  {i}. {nt}")

    print(f"\nExtracted relationship types ({len(result['relationship_types'])}):")
    for i, rt in enumerate(result['relationship_types'], 1):
        print(f"  {i}. {rt}")

    return {
        'model': model_name,
        'init_time': init_time,
        'extract_time_ms': extract_time * 1000,
        'node_types': result['node_types'],
        'relationship_types': result['relationship_types'],
        'total_types': len(result['node_types']) + len(result['relationship_types'])
    }


async def main():
    print("=" * 80)
    print("EMBEDDING MODEL COMPARISON FOR CPG TYPE EXTRACTION")
    print("=" * 80)

    # Test subquery
    subquery = "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'"

    print(f"\nTest Subquery:")
    print(f"  {subquery}")
    print()

    # Initialize server once
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    # Models to test
    models = [
        'all-MiniLM-L6-v2',           # Baseline: lightweight, general-purpose
        'microsoft/codebert-base',     # Code-specific
    ]

    results = []

    for model_name in models:
        try:
            result = await test_model(model_name, subquery, yaml_schema, server)
            results.append(result)
        except Exception as e:
            print(f"❌ Failed to test {model_name}: {e}")
            import traceback
            traceback.print_exc()

    # Summary comparison
    print("\n" + "=" * 80)
    print("COMPARISON SUMMARY")
    print("=" * 80)
    print()

    print(f"{'Model':<40} {'Init (s)':>12} {'Extract (ms)':>15} {'Types':>8}")
    print("-" * 80)

    for r in results:
        model_short = r['model'].split('/')[-1]
        print(f"{model_short:<40} {r['init_time']:>12.2f} {r['extract_time_ms']:>15.2f} {r['total_types']:>8}")

    print()

    # Type extraction comparison
    print("=" * 80)
    print("EXTRACTED NODE TYPES (Ordered)")
    print("=" * 80)

    max_len = max(len(r['node_types']) for r in results)

    # Print header
    header_parts = []
    for r in results:
        model_short = r['model'].split('/')[-1][:30]
        header_parts.append(f"{model_short:<32}")
    print("Rank  " + "  ".join(header_parts))
    print("-" * 80)

    # Print ranked types
    for i in range(max_len):
        rank = f"#{i+1:2d}"
        parts = [rank + "  "]
        for r in results:
            if i < len(r['node_types']):
                node = r['node_types'][i]
                parts.append(f"{node:<32}")
            else:
                parts.append(" " * 32)
        print("  ".join(parts))

    print()

    # Accuracy analysis
    print("=" * 80)
    print("ACCURACY ANALYSIS")
    print("=" * 80)
    print()
    print("Expected (VALIDATED ground truth for SQ1):")
    print("  • Type (required by: Type -[CONTAINS]-> Function)")
    print("  • Function (required by: locating F where F.name='CreateWorkers')")
    print("  • Relationship: CONTAINS")
    print("  (Validated via actual Cypher query execution)")
    print()

    for r in results:
        model_short = r['model'].split('/')[-1]
        node_types = r['node_types']

        type_rank = node_types.index('Type') + 1 if 'Type' in node_types else None
        function_rank = node_types.index('Function') + 1 if 'Function' in node_types else None

        print(f"{model_short}:")
        print(f"  Type: Rank #{type_rank}" if type_rank else f"  Type: ❌ NOT EXTRACTED")
        print(f"  Function: Rank #{function_rank}" if function_rank else f"  Function: ❌ NOT EXTRACTED")

        if type_rank and function_rank:
            if type_rank <= 2 and function_rank <= 2:
                print(f"  ✅ Both ranked in top 2 (EXCELLENT)")
            elif type_rank <= 5 and function_rank <= 5:
                print(f"  ⚠️  Both ranked in top 5 (GOOD)")
            else:
                print(f"  ❌ Poor ranking")
        print()

    # Save results
    output_file = "/tmp/embedding_model_comparison.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"📄 Full results saved to: {output_file}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

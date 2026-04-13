#!/usr/bin/env python3
"""
Debug fusion logic directly by calling hybrid service
"""

import asyncio
import logging
import sys
from src.core.hybrid_retrieval_service import HybridRetrievalService

# Set up logging to see debug output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

async def debug_fusion():
    """Debug fusion directly"""
    print("🔍 Direct Fusion Debugging")
    print("=" * 50)
    
    # Initialize hybrid service
    hybrid_service = HybridRetrievalService({
        "vector_weight": 0.4,
        "graph_weight": 0.6,
        "fusion_threshold": 0.3
    })
    
    try:
        # Execute hybrid retrieval with debug logging
        result = await hybrid_service.comprehensive_retrieve(
            user_query="Analyze the structure of WorkerA.cs",
            vector_params={
                "collection_name": "helloworldapp-benchmarking",
                "max_results": 10,
                "config": None
            },
            graph_params={
                "config_path": "/opt/genpod/neo4j_config.json",
                "max_results": 50
            },
            max_results=60
        )
        
        print(f"\n✅ Result Status: {result.get('status')}")
        print(f"📊 Final Counts:")
        print(f"  Vector raw results: {len(result.get('vector_raw_results', []))}")
        print(f"  CPG raw results: {len(result.get('cpg_raw_results', []))}")
        print(f"  Hybrid results: {len(result.get('hybrid_results', []))}")
        
        # Check retrieval results metadata
        if 'retrieval_results' in result:
            ret_results = result['retrieval_results']
            print(f"  Metadata counts:")
            print(f"    Vector count: {ret_results.get('vector', {}).get('count', 0)}")
            print(f"    Graph count: {ret_results.get('graph', {}).get('count', 0)}")
            print(f"    Fused count: {ret_results.get('fused_count', 0)}")
            print(f"    Final count: {ret_results.get('final_count', 0)}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_fusion())
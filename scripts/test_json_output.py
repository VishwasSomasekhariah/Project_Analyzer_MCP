#!/usr/bin/env python3
"""
Test script to show exactly what JSON would be generated with the fixed parsing logic
"""
import asyncio
import json
import sys
import os
sys.path.insert(0, '/opt/genpod')

from properly_fixed_comparative_analysis import ProperlyFixedComparativeAnalyzer

async def test_json_output():
    """Test what JSON would actually be generated"""
    print("🧪 TESTING FIXED JSON OUTPUT")
    print("=" * 60)
    
    analyzer = ProperlyFixedComparativeAnalyzer(test_scenario_filter=1)  # Just first scenario
    scenario = analyzer.filtered_scenarios[0]
    
    print(f"Testing scenario: {scenario['id']} - {scenario['query'][:100]}...")
    print()
    
    # Test each retriever
    print("1️⃣ TESTING VECTOR RETRIEVER:")
    vector_result = await analyzer.run_vector_only_query(scenario['query'])
    print(f"   Status: {vector_result.get('status')}")
    print(f"   AI Response: {vector_result.get('ai_response', '')[:100]}...")
    print(f"   Raw Results Count: {len(vector_result.get('raw_results', []))}")
    print()
    
    print("2️⃣ TESTING CPG RETRIEVER:")
    cpg_result = await analyzer.run_cpg_only_query(scenario['query'], scenario['category'])
    print(f"   Status: {cpg_result.get('status')}")
    print(f"   AI Response: {cpg_result.get('ai_response', '')[:100]}...")
    print(f"   Raw Results Count: {len(cpg_result.get('raw_results', []))}")
    print()
    
    print("3️⃣ TESTING HYBRID RETRIEVER:")
    hybrid_result = await analyzer.run_hybrid_query(scenario['query'], scenario['category'])
    print(f"   Status: {hybrid_result.get('status')}")
    print(f"   AI Response: {hybrid_result.get('ai_response', '')[:100]}...")
    print(f"   Raw Results Count: {len(hybrid_result.get('raw_results', []))}")
    print()
    
    # Now show what would go into the final JSON
    print("📄 FINAL JSON STRUCTURE THAT WOULD BE ADDED:")
    print("=" * 60)
    
    # Simulate the exact logic from the main script
    vector_metadata = vector_result.get('metadata', {})
    hybrid_metadata = hybrid_result.get('metadata', {})
    
    # Extract hybrid workflow components - same logic as in main script
    intent_analysis = hybrid_result.get('intent_analysis', {})
    synthesis_raw = hybrid_result.get('synthesis', {})
    synthesis_result = synthesis_raw if isinstance(synthesis_raw, dict) else {"answer": synthesis_raw}
    critic_result = hybrid_result.get('critic_validation', {})
    cross_validation = hybrid_result.get('cross_validation', {})
    
    # Parse CPG response
    cpg_ai_response = cpg_result.get('response', '')
    cpg_raw_results = cpg_result.get('raw_results', [])
    cpg_synthesis_status = "success" if cpg_result.get('status') == 'success' else "unknown"
    
    final_json_entry = {
        # Key fields that matter for benchmarking
        "query_id": scenario['id'],
        "user_query": scenario['query'],
        
        # VECTOR
        "vector_status": vector_result['status'],
        "vector_ai_response": vector_result.get('ai_response', ''),
        "vector_raw_results_count": len(vector_result.get('raw_results', [])),
        
        # CPG  
        "cpg_status": cpg_result['status'],
        "cpg_ai_response": cpg_ai_response,
        "cpg_raw_results_count": len(cpg_raw_results),
        
        # HYBRID
        "hybrid_status": hybrid_result['status'],
        "hybrid_ai_response": hybrid_result.get('response', synthesis_result.get('answer', '')),
        "hybrid_raw_results_count": len(hybrid_result.get('raw_results', [])),
        
        # Show the actual raw results JSON structure (first few items)
        "vector_raw_results_sample": vector_result.get('raw_results', [])[:2],  # First 2 items
        "cpg_raw_results_sample": cpg_raw_results[:2],  # First 2 items
        "hybrid_raw_results_sample": hybrid_result.get('raw_results', [])[:2],  # First 2 items
    }
    
    print(json.dumps(final_json_entry, indent=2)[:2000] + "...\n")
    
    # Show raw results counts specifically
    print("🔢 RAW RESULTS COUNTS:")
    print(f"   Vector: {len(vector_result.get('raw_results', []))} items")
    print(f"   CPG: {len(cpg_raw_results)} items")
    print(f"   Hybrid: {len(hybrid_result.get('raw_results', []))} items")
    print()
    
    # Show synthesis information
    print("🧠 SYNTHESIS/RESPONSE INFO:")
    print(f"   Vector AI Response: {len(vector_result.get('ai_response', ''))} chars")
    print(f"   CPG AI Response: {len(cpg_ai_response)} chars")
    print(f"   Hybrid AI Response: {len(hybrid_result.get('response', ''))} chars")
    print(f"   Hybrid Synthesis Type: {type(synthesis_raw)} = {str(synthesis_raw)[:100] if synthesis_raw else 'Empty'}...")

if __name__ == "__main__":
    asyncio.run(test_json_output())
#!/usr/bin/env python3
"""
Analyze the fusion logic using actual test data
"""

import json
from typing import Dict, List, Any

def analyze_fusion_logic():
    """Analyze how the current fusion logic works on real data"""
    
    # Load the test results
    with open('/opt/genpod/retrieval_tools_test_results_20250805_200726.json', 'r') as f:
        data = json.load(f)
    
    # Extract comprehensive analysis data
    comp_analysis = data['individual_tests']['comprehensive_analysis']['tool_response']
    
    # Get vector and CPG results
    vector_results = comp_analysis['vector_raw_results']
    cpg_results = comp_analysis['cpg_raw_results'] 
    
    print("=" * 60)
    print("FUSION LOGIC ANALYSIS")
    print("=" * 60)
    
    print(f"\n📊 INPUT DATA:")
    print(f"Vector results: {len(vector_results)}")
    print(f"CPG results: {len(cpg_results)}")
    
    # Analyze vector results
    print(f"\n🔍 VECTOR RESULTS ANALYSIS:")
    for i, result in enumerate(vector_results[:3]):  # Show first 3
        content = result.get('content', '')
        metadata = result.get('metadata', {})
        file_path = metadata.get('file_path', 'unknown')
        
        print(f"  Vector {i+1}:")
        print(f"    File: {file_path}")
        print(f"    Content length: {len(content)} chars")
        print(f"    Content preview: {content[:100]}...")
        print(f"    Current signature: vector::{hash(content[:200])}")
        print()
    
    # Analyze CPG results  
    print(f"\n🔍 CPG RESULTS ANALYSIS:")
    for i, result in enumerate(cpg_results):
        print(f"  CPG {i+1}:")
        file_path = result.get('f.file_path', result.get('file_path', 'unknown'))
        name = result.get('f.name', result.get('name', 'unknown'))
        node_type = 'file' if 'f.name' in result else 'class'
        
        print(f"    File: {file_path}")
        print(f"    Name: {name}")
        print(f"    Type: {node_type}")
        body = result.get('body', result.get('f.body', ''))
        print(f"    Current signature: {file_path}::{name}::{hash(str(body)[:100])}")
        print(f"    Improved signature: cpg::{file_path}::{node_type}::{name}")
        print()
    
    # Simulate current fusion logic
    print(f"\n⚠️  CURRENT FUSION SIMULATION:")
    current_signatures = set()
    current_surviving = []
    
    # Process all results with current logic
    all_results = []
    
    # Add vector results
    for result in vector_results:
        content = result.get('content', '')
        sig = hash(content[:200])  # Current logic
        all_results.append({
            'source': 'vector',
            'signature': sig,
            'content_preview': content[:50],
            'data': result
        })
    
    # Add CPG results  
    for result in cpg_results:
        file_path = result.get('f.file_path', result.get('file_path', ''))
        name = result.get('f.name', result.get('name', ''))
        body = str(result.get('body', ''))
        sig = f"{file_path}::{name}::{hash(body[:100])}"  # Current logic
        all_results.append({
            'source': 'cpg',
            'signature': sig,
            'content_preview': f"{file_path}::{name}",
            'data': result
        })
    
    # Apply current deduplication
    for result in all_results:
        if result['signature'] not in current_signatures:
            current_signatures.add(result['signature'])
            current_surviving.append(result)
        else:
            print(f"    ❌ DUPLICATE: {result['source']} - {result['content_preview']}")
    
    print(f"    Surviving results: {len(current_surviving)}")
    for result in current_surviving:
        print(f"      ✅ {result['source']}: {result['content_preview']}")
    
    # Simulate improved fusion logic
    print(f"\n✅ IMPROVED FUSION SIMULATION:")
    improved_signatures = set()
    improved_surviving = []
    
    # Process with improved logic
    for result in all_results:
        if result['source'] == 'vector':
            # Better vector signature
            content = result['data'].get('content', '')
            file_path = result['data'].get('metadata', {}).get('file_path', 'unknown')
            improved_sig = f"vector::{file_path}::{hash(content[:500])}"
        else:
            # Better CPG signature
            data = result['data']
            file_path = data.get('f.file_path', data.get('file_path', ''))
            name = data.get('f.name', data.get('name', ''))
            node_type = 'file' if 'f.name' in data else 'class'
            improved_sig = f"cpg::{file_path}::{node_type}::{name}"
        
        if improved_sig not in improved_signatures:
            improved_signatures.add(improved_sig)
            improved_surviving.append(result)
        else:
            print(f"    ❌ DUPLICATE: {result['source']} - {result['content_preview']}")
    
    print(f"    Surviving results: {len(improved_surviving)}")
    for result in improved_surviving:
        print(f"      ✅ {result['source']}: {result['content_preview']}")
    
    # Show what raw results should actually be
    print(f"\n📋 RAW RESULTS RECOMMENDATIONS:")
    print(f"Current 'raw results':")
    print(f"  vector_raw_results: {len(vector_results)} (original vector results)")
    print(f"  cpg_raw_results: {len(cpg_results)} (original CPG results)")
    print(f"")
    print(f"Should be (post-fusion):")
    vector_surviving = [r for r in improved_surviving if r['source'] == 'vector']
    cpg_surviving = [r for r in improved_surviving if r['source'] == 'cpg']
    print(f"  vector_raw_results: {len(vector_surviving)} (vector results used for synthesis)")
    print(f"  cpg_raw_results: {len(cpg_surviving)} (CPG results used for synthesis)")
    print(f"  hybrid_raw_results: {len(improved_surviving)} (all results used for synthesis)")

if __name__ == "__main__":
    analyze_fusion_logic()
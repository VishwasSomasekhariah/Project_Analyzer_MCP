#!/usr/bin/env python3
"""
Examine pickle files to understand MCP response structure
"""
import pickle
import json
from pathlib import Path

def examine_pickle_file(pkl_file):
    print(f"\n{'='*60}")
    print(f"EXAMINING: {pkl_file.name}")
    print(f"{'='*60}")
    
    with open(pkl_file, 'rb') as f:
        data = pickle.load(f)
    
    print(f"TYPE: {type(data)}")
    print(f"ATTRIBUTES: {dir(data)}")
    
    if hasattr(data, 'content'):
        print(f"\nCONTENT TYPE: {type(data.content)}")
        if isinstance(data.content, list):
            print(f"CONTENT LENGTH: {len(data.content)}")
            if len(data.content) > 0:
                print(f"FIRST CONTENT ITEM TYPE: {type(data.content[0])}")
                print(f"FIRST CONTENT ITEM ATTRIBUTES: {dir(data.content[0])}")
                
                if hasattr(data.content[0], 'text'):
                    content_text = data.content[0].text
                    print(f"CONTENT TEXT LENGTH: {len(content_text)}")
                    print(f"CONTENT TEXT SAMPLE (first 500 chars):")
                    print(content_text[:500])
                    
                    # Try to parse as JSON
                    try:
                        json_data = json.loads(content_text)
                        print(f"\nJSON PARSING: SUCCESS")
                        print(f"JSON KEYS: {list(json_data.keys())}")
                        
                        # Show structure for key fields
                        for key in ['status', 'raw_results', 'synthesis', 'response', 'analysis_type']:
                            if key in json_data:
                                value = json_data[key]
                                if isinstance(value, list):
                                    print(f"{key}: LIST with {len(value)} items")
                                    if len(value) > 0:
                                        print(f"  First item type: {type(value[0])}")
                                        if isinstance(value[0], dict):
                                            print(f"  First item keys: {list(value[0].keys())}")
                                elif isinstance(value, dict):
                                    print(f"{key}: DICT with keys: {list(value.keys())}")
                                else:
                                    print(f"{key}: {type(value)} = {str(value)[:100]}...")
                        
                    except json.JSONDecodeError as e:
                        print(f"\nJSON PARSING: FAILED - {e}")
        else:
            print(f"CONTENT: {data.content}")

if __name__ == "__main__":
    pkl_dir = Path("/opt/genpod/mcp_debug_dumps")
    
    # Examine the latest files
    vector_files = list(pkl_dir.glob("vector_raw_response_*.pkl"))
    cpg_files = list(pkl_dir.glob("cpg_raw_response_*.pkl")) 
    hybrid_files = list(pkl_dir.glob("hybrid_raw_response_*.pkl"))
    
    # Get the most recent of each type
    if vector_files:
        latest_vector = max(vector_files, key=lambda f: f.stat().st_mtime)
        examine_pickle_file(latest_vector)
        
    if cpg_files:
        latest_cpg = max(cpg_files, key=lambda f: f.stat().st_mtime)
        examine_pickle_file(latest_cpg)
        
    if hybrid_files:
        latest_hybrid = max(hybrid_files, key=lambda f: f.stat().st_mtime)
        examine_pickle_file(latest_hybrid)
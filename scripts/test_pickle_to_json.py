#!/usr/bin/env python3
"""
Test script using saved pickle files to show exact JSON output
"""
import pickle
import json
from pathlib import Path
from datetime import datetime

def load_pickle_and_show_json():
    """Load pickle files and show what JSON would be generated"""
    print("🧪 TESTING JSON OUTPUT FROM PICKLE FILES")
    print("=" * 60)
    
    pkl_dir = Path("/opt/genpod/mcp_debug_dumps")
    
    # Load the most recent files
    vector_files = list(pkl_dir.glob("vector_raw_response_*.pkl"))
    cpg_files = list(pkl_dir.glob("cpg_raw_response_*.pkl")) 
    hybrid_files = list(pkl_dir.glob("hybrid_raw_response_*.pkl"))
    
    latest_vector = max(vector_files, key=lambda f: f.stat().st_mtime) if vector_files else None
    latest_cpg = max(cpg_files, key=lambda f: f.stat().st_mtime) if cpg_files else None
    latest_hybrid = max(hybrid_files, key=lambda f: f.stat().st_mtime) if hybrid_files else None
    
    print(f"📁 Using files:")
    print(f"   Vector: {latest_vector.name if latest_vector else 'None'}")
    print(f"   CPG: {latest_cpg.name if latest_cpg else 'None'}")
    print(f"   Hybrid: {latest_hybrid.name if latest_hybrid else 'None'}")
    print()
    
    # Parse each response using the SAME logic as in the main script
    def parse_vector_response(pkl_file):
        """Parse vector response exactly like the main script"""
        with open(pkl_file, 'rb') as f:
            result = pickle.load(f)
        
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        
        try:
            parsed_result = json.loads(content_text)
            
            if isinstance(parsed_result, dict) and parsed_result.get("status") == "success":
                return {
                    "status": "success",
                    "ai_response": parsed_result.get("ai_response", ""),
                    "raw_results": parsed_result.get("raw_results", []),
                    "response": parsed_result.get("ai_response", ""),
                    "metadata": parsed_result.get("metadata", {})
                }
        except json.JSONDecodeError:
            pass
        
        return {"status": "error", "ai_response": "", "raw_results": [], "response": ""}
    
    def parse_cpg_response(pkl_file):
        """Parse CPG response exactly like the main script"""
        with open(pkl_file, 'rb') as f:
            result = pickle.load(f)
        
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        
        try:
            result_data = json.loads(content_text)
            
            # Based on pickle analysis: CPG has response as a DICT
            response_data = result_data.get("response", {})
            raw_results = result_data.get("raw_results", [])
            
            return {
                "status": result_data.get("status", "success"),
                "ai_response": response_data.get("answer", "") if isinstance(response_data, dict) else str(response_data),
                "raw_results": raw_results,
                "response": response_data.get("answer", "") if isinstance(response_data, dict) else str(response_data),
                "synthesis": response_data if isinstance(response_data, dict) else {"answer": str(response_data)},
            }
        except json.JSONDecodeError:
            pass
        
        return {"status": "error", "ai_response": "", "raw_results": [], "response": ""}
    
    def parse_hybrid_response(pkl_file):
        """Parse hybrid response exactly like the main script"""
        with open(pkl_file, 'rb') as f:
            result = pickle.load(f)
        
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        
        try:
            result_data = json.loads(content_text)
            
            # Based on pickle analysis: hybrid has synthesis as STRING
            synthesis = result_data.get("synthesis", "")
            synthesis_dict = synthesis if isinstance(synthesis, dict) else {"answer": synthesis}
            intent_analysis = result_data.get("intent_analysis", {})
            critic_validation = result_data.get("critic_validation", {})
            raw_results = result_data.get("raw_results", [])
            
            return {
                "status": result_data.get("status", "success"),
                "ai_response": result_data.get("response", synthesis if isinstance(synthesis, str) else synthesis_dict.get("answer", "")),
                "raw_results": raw_results,
                "response": result_data.get("response", synthesis if isinstance(synthesis, str) else synthesis_dict.get("answer", "")),
                "synthesis": synthesis_dict,
                "intent_analysis": intent_analysis,
                "critic_validation": critic_validation,
                "cross_validation": synthesis_dict.get("cross_validation", {}),
            }
        except json.JSONDecodeError:
            pass
        
        return {"status": "error", "ai_response": "", "raw_results": [], "response": ""}
    
    # Parse all responses
    vector_result = parse_vector_response(latest_vector) if latest_vector else {}
    cpg_result = parse_cpg_response(latest_cpg) if latest_cpg else {}
    hybrid_result = parse_hybrid_response(latest_hybrid) if latest_hybrid else {}
    
    # Show what each parser extracted
    print("1️⃣ VECTOR PARSED RESULT:")
    print(f"   Status: {vector_result.get('status')}")
    print(f"   AI Response: {vector_result.get('ai_response', '')[:100]}...")
    print(f"   Raw Results Count: {len(vector_result.get('raw_results', []))}")
    print()
    
    print("2️⃣ CPG PARSED RESULT:")
    print(f"   Status: {cpg_result.get('status')}")
    print(f"   AI Response: {cpg_result.get('ai_response', '')[:100]}...")
    print(f"   Raw Results Count: {len(cpg_result.get('raw_results', []))}")
    print()
    
    print("3️⃣ HYBRID PARSED RESULT:")
    print(f"   Status: {hybrid_result.get('status')}")
    print(f"   AI Response: {hybrid_result.get('ai_response', '')[:100]}...")
    print(f"   Raw Results Count: {len(hybrid_result.get('raw_results', []))}")
    print()
    
    # Now show EXACTLY what would go into the final JSON using the main script logic
    print("📄 FINAL JSON ENTRY (like properly_fixed_comparative_analysis.py):")
    print("=" * 80)
    
    # Extract hybrid workflow components - EXACT same logic as main script
    intent_analysis = hybrid_result.get('intent_analysis', {})
    synthesis_raw = hybrid_result.get('synthesis', {})  # Can be string or dict
    synthesis_result = synthesis_raw if isinstance(synthesis_raw, dict) else {"answer": synthesis_raw}
    critic_result = hybrid_result.get('critic_validation', {})
    cross_validation = hybrid_result.get('cross_validation', {})
    
    # Parse CPG response - EXACT same logic as main script
    cpg_ai_response = cpg_result.get('response', '')
    cpg_raw_results = cpg_result.get('raw_results', [])
    cpg_synthesis_status = "success" if cpg_result.get('status') == 'success' else "unknown"
    
    # Compile results EXACTLY like the main script
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scenario = {"id": "T001", "query": "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?", "category": "Technical", "subcategory": "Architecture", "scenario_type": "analysis"}
    
    vector_metadata = vector_result.get('metadata', {})
    hybrid_metadata = hybrid_result.get('metadata', {})
    
    final_json_result = {
        # Query Information
        "query_id": scenario['id'],
        "user_query": scenario['query'],
        "query_category": scenario['category'],
        "timestamp": timestamp,
        
        # VECTOR RETRIEVER
        "vector_status": vector_result['status'],
        "vector_ai_response": vector_result.get('ai_response', ''),
        "vector_raw_results_json": json.dumps(vector_result.get('raw_results', [])),
        "vector_response_time_ms": 0,  # Not available from pickle
        "vector_error": "",
        
        # CPG RETRIEVER  
        "cpg_status": cpg_result['status'],
        "cpg_ai_response": cpg_ai_response,
        "cpg_raw_results_json": json.dumps(cpg_raw_results),
        "cpg_synthesis_status": cpg_synthesis_status,
        "cpg_response_time_ms": 0,  # Not available from pickle
        "cpg_error": "",
        
        # HYBRID RETRIEVER
        "hybrid_status": hybrid_result['status'],
        "hybrid_ai_response": hybrid_result.get('response', synthesis_result.get('answer', '')),
        "hybrid_raw_results_json": json.dumps(hybrid_result.get('raw_results', [])),
        "hybrid_response_time_ms": 0,  # Not available from pickle
        "hybrid_error": "",
        
        # SYNTHESIS QUALITY METRICS
        "synthesis_status": hybrid_result.get('synthesis_status', 'success' if synthesis_result.get('answer') else 'unknown'),
        "synthesis_confidence": synthesis_result.get('confidence_score', synthesis_result.get('confidence', 0.0)),
    }
    
    # Show key fields
    print(f"✅ VECTOR: {final_json_result['vector_status']} - {len(json.loads(final_json_result['vector_raw_results_json']))} raw results")
    print(f"✅ CPG: {final_json_result['cpg_status']} - {len(json.loads(final_json_result['cpg_raw_results_json']))} raw results")
    print(f"✅ HYBRID: {final_json_result['hybrid_status']} - {len(json.loads(final_json_result['hybrid_raw_results_json']))} raw results")
    print()
    print(f"🔍 CPG AI Response: {final_json_result['cpg_ai_response'][:200]}...")
    print(f"🔍 Hybrid AI Response: {final_json_result['hybrid_ai_response'][:200]}...")
    print()
    print(f"📊 Raw Results Sample Lengths:")
    print(f"   vector_raw_results_json: {len(final_json_result['vector_raw_results_json'])} chars")
    print(f"   cpg_raw_results_json: {len(final_json_result['cpg_raw_results_json'])} chars") 
    print(f"   hybrid_raw_results_json: {len(final_json_result['hybrid_raw_results_json'])} chars")

if __name__ == "__main__":
    load_pickle_and_show_json()
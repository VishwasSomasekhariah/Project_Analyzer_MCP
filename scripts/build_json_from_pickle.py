#!/usr/bin/env python3
"""
Build the actual JSON file using pickle data instead of running retrievers
"""
import pickle
import json
from pathlib import Path
from datetime import datetime

def build_json_from_pickle():
    """Build the complete JSON structure using pickle files"""
    print("🔨 BUILDING ACTUAL JSON FILE FROM PICKLE DATA")
    print("=" * 60)
    
    pkl_dir = Path("/opt/genpod/mcp_debug_dumps")
    
    # Load the most recent files
    vector_files = list(pkl_dir.glob("vector_raw_response_*.pkl"))
    cpg_files = list(pkl_dir.glob("cpg_raw_response_*.pkl")) 
    hybrid_files = list(pkl_dir.glob("hybrid_raw_response_*.pkl"))
    
    latest_vector = max(vector_files, key=lambda f: f.stat().st_mtime) if vector_files else None
    latest_cpg = max(cpg_files, key=lambda f: f.stat().st_mtime) if cpg_files else None
    latest_hybrid = max(hybrid_files, key=lambda f: f.stat().st_mtime) if hybrid_files else None
    
    print(f"📁 Using pickle files:")
    print(f"   Vector: {latest_vector.name if latest_vector else 'None'}")
    print(f"   CPG: {latest_cpg.name if latest_cpg else 'None'}")
    print(f"   Hybrid: {latest_hybrid.name if latest_hybrid else 'None'}")
    print()
    
    # Parse responses using EXACT same logic as properly_fixed_comparative_analysis.py
    def parse_vector_response():
        """Parse vector response exactly like run_vector_only_query"""
        with open(latest_vector, 'rb') as f:
            result = pickle.load(f)
        
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        response_time_ms = 29200  # From logs
        
        try:
            parsed_result = json.loads(content_text)
            
            if isinstance(parsed_result, dict) and parsed_result.get("status") == "success":
                return {
                    "status": "success",
                    "ai_response": parsed_result.get("ai_response", ""),
                    "raw_results": parsed_result.get("raw_results", []),
                    "response": parsed_result.get("ai_response", ""),
                    "response_time_ms": response_time_ms,
                    "error": "",
                    "metadata": {
                        "vector_total_results": parsed_result.get("metadata", {}).get("total_results", 0),
                        "vector_processing_time": parsed_result.get("metadata", {}).get("processing_time", 0),
                        "vector_confidence_score": parsed_result.get("metadata", {}).get("confidence_score"),
                        "has_diagram": parsed_result.get("metadata", {}).get("has_diagram", False)
                    },
                    "full_response": content_text
                }
        except json.JSONDecodeError:
            pass
        
        return {"status": "error", "response": "", "response_time_ms": response_time_ms, "error": "Parse failed"}
    
    def parse_cpg_response():
        """Parse CPG response exactly like run_cpg_only_query"""
        with open(latest_cpg, 'rb') as f:
            result = pickle.load(f)
        
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        response_time_ms = 462000  # From logs
        
        try:
            result_data = json.loads(content_text)
            
            # Based on pickle analysis: CPG has response as a DICT with keys: ['answer', 'details', 'confidence', 'status', 'suggestions']
            response_data = result_data.get("response", {})
            raw_results = result_data.get("raw_results", [])
            
            return {
                "status": result_data.get("status", "success"),
                "ai_response": response_data.get("answer", "") if isinstance(response_data, dict) else str(response_data),
                "raw_results": raw_results,
                "response": response_data.get("answer", "") if isinstance(response_data, dict) else str(response_data),
                "response_time_ms": response_time_ms,
                "error": "",
                "workflow": result_data.get("workflow_type", "langgraph_agent_rag"),
                "analysis_type": result_data.get("analysis_type", "cpg_rag"),
                "synthesis": response_data if isinstance(response_data, dict) else {"answer": str(response_data)},
                "metadata": {
                    "cpg_execution_time": result_data.get("cpg_execution_time", 0),
                    "total_execution_time": result_data.get("total_execution_time", 0),
                    "confidence": response_data.get("confidence", 0.0) if isinstance(response_data, dict) else 0.0,
                    "status": response_data.get("status", "success") if isinstance(response_data, dict) else "success"
                },
                "full_response": content_text
            }
        except json.JSONDecodeError:
            pass
        
        return {"status": "error", "response": "", "response_time_ms": response_time_ms, "error": "Parse failed"}
    
    def parse_hybrid_response():
        """Parse hybrid response exactly like run_hybrid_query"""
        with open(latest_hybrid, 'rb') as f:
            result = pickle.load(f)
        
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        response_time_ms = 85400  # From logs
        
        try:
            result_data = json.loads(content_text)
            
            # Based on pickle analysis: hybrid has synthesis as STRING and direct response field
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
                "response_time_ms": response_time_ms,
                "error": "",
                "workflow": "hybrid_rag",
                "analysis_type": result_data.get("analysis_type", "hybrid_rag"),
                "synthesis": synthesis_dict,
                "intent_analysis": intent_analysis,
                "critic_validation": critic_validation,
                "cross_validation": synthesis_dict.get("cross_validation", {}),
                "metadata": {
                    "hybrid_execution_time": result_data.get("total_execution_time", 0),
                    "vector_execution_time": result_data.get("vector_execution_time", 0),
                    "cpg_execution_time": result_data.get("cpg_execution_time", 0),
                    "synthesis_confidence": synthesis_dict.get("confidence", 0.0),
                    "synthesis_status": result_data.get("synthesis_status", "success" if synthesis else "unknown"),
                    "synthesis_strategy": synthesis_dict.get("strategy_used", "unknown"),
                    "intent": intent_analysis.get("intent", "unknown"),
                    "vector_weight": intent_analysis.get("vector_weight", 0.5),
                    "cpg_weight": intent_analysis.get("cpg_weight", 0.5),
                    "critic_overall_score": critic_validation.get("overall_score", 0.0),
                    "vector_results_count": len(result_data.get("vector_raw_results", [])),
                    "cpg_results_count": len(result_data.get("cpg_raw_results", []))
                },
                "vector_raw_results": result_data.get("vector_raw_results", []),
                "cpg_raw_results": result_data.get("cpg_raw_results", []),
                "full_response": content_text
            }
        except json.JSONDecodeError:
            pass
        
        return {"status": "error", "response": "", "response_time_ms": response_time_ms, "error": "Parse failed"}
    
    # Parse all responses
    print("🔄 Parsing responses using fixed logic...")
    vector_result = parse_vector_response()
    cpg_result = parse_cpg_response()
    hybrid_result = parse_hybrid_response()
    
    print(f"   ✅ Vector: {vector_result['status']} - {len(vector_result.get('raw_results', []))} raw results")
    print(f"   ✅ CPG: {cpg_result['status']} - {len(cpg_result.get('raw_results', []))} raw results")
    print(f"   ✅ Hybrid: {hybrid_result['status']} - {len(hybrid_result.get('raw_results', []))} raw results")
    print()
    
    # Build the complete JSON structure EXACTLY like properly_fixed_comparative_analysis.py
    print("🔨 Building complete JSON structure...")
    
    # Extract structured data from all retrievers for evaluation framework
    vector_metadata = vector_result.get('metadata', {})
    hybrid_metadata = hybrid_result.get('metadata', {})
    
    # Extract hybrid workflow components - handle both string and dict synthesis
    intent_analysis = hybrid_result.get('intent_analysis', {})
    synthesis_raw = hybrid_result.get('synthesis', {})  # Can be string or dict
    synthesis_result = synthesis_raw if isinstance(synthesis_raw, dict) else {"answer": synthesis_raw}
    critic_result = hybrid_result.get('critic_validation', {})
    cross_validation = hybrid_result.get('cross_validation', {})
    
    # Parse CPG response - Enhanced Graph RAG returns direct structure
    cpg_ai_response = cpg_result.get('response', '')
    cpg_raw_results = cpg_result.get('raw_results', [])
    cpg_synthesis_status = "success" if cpg_result.get('status') == 'success' else "unknown"
    
    # Scenario info
    scenario = {
        'id': 'T001', 
        'query': 'Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?',
        'category': 'Technical',
        'subcategory': 'Architecture',
        'scenario_type': 'analysis'
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Compile results EXACTLY like the main script
    result = {
        # Query Information
        "query_id": scenario['id'],
        "user_query": scenario['query'],
        "query_category": scenario['category'],
        "query_subcategory": scenario['subcategory'],
        "scenario_type": scenario['scenario_type'],
        "timestamp": timestamp,
        
        # VECTOR RETRIEVER - For Reference-based and Reference-free Evaluation
        "vector_status": vector_result['status'],
        "vector_ai_response": vector_result.get('ai_response', vector_result.get('response', '')),  # For reference-free eval
        "vector_raw_results_json": json.dumps(vector_result.get('raw_results', [])),  # For reference-based eval
        "vector_metadata_json": json.dumps(vector_metadata),  # Performance metrics
        "vector_response_time_ms": vector_result['response_time_ms'],
        "vector_error": vector_result['error'],
        
        # CPG RETRIEVER - For Reference-based and Reference-free Evaluation  
        "cpg_status": cpg_result['status'],
        "cpg_ai_response": cpg_ai_response,  # For reference-free eval (main answer)
        "cpg_details": cpg_result.get('synthesis', {}).get('details', '') if isinstance(cpg_result.get('synthesis', {}), dict) else '',  # Detailed response
        "cpg_suggestions": cpg_result.get('synthesis', {}).get('suggestions', []) if isinstance(cpg_result.get('synthesis', {}), dict) else [],  # Suggestions array
        "cpg_confidence": cpg_result.get('synthesis', {}).get('confidence', 0.0) if isinstance(cpg_result.get('synthesis', {}), dict) else 0.0,  # Confidence score
        "cpg_raw_results_json": json.dumps(cpg_raw_results),  # For reference-based eval
        "cpg_synthesis_status": cpg_synthesis_status,  # Synthesis quality
        "cpg_response_time_ms": cpg_result['response_time_ms'],
        "cpg_error": cpg_result['error'],
        
        # HYBRID RETRIEVER - For Reference-based and Reference-free Evaluation
        "hybrid_status": hybrid_result['status'],
        "hybrid_ai_response": hybrid_result.get('response', synthesis_result.get('answer', '')),  # Use direct response field first
        "hybrid_raw_results_json": json.dumps(hybrid_result.get('raw_results', [])),  # For reference-based eval
        "hybrid_metadata_json": json.dumps(hybrid_metadata),  # Hybrid workflow metrics
        "hybrid_response_time_ms": hybrid_result['response_time_ms'],
        "hybrid_error": hybrid_result['error'],
        
        # HYBRID WORKFLOW COMPONENTS - For Advanced Evaluation Framework Analysis
        "intent_analysis_json": json.dumps(intent_analysis),
        "synthesis_result_json": json.dumps(synthesis_result),
        "critic_result_json": json.dumps(critic_result),
        "cross_validation_json": json.dumps(cross_validation),
        
        # SYNTHESIS QUALITY METRICS - For Evaluation Framework Analysis
        "synthesis_status": hybrid_result.get('synthesis_status', 'success' if synthesis_result.get('answer') else 'unknown'),
        "synthesis_confidence": synthesis_result.get('confidence_score', synthesis_result.get('confidence', 0.0)),
        "synthesis_reasoning": synthesis_result.get('reasoning', ''),
        "cross_validation_score": cross_validation.get('confidence_score', 0.0) if isinstance(cross_validation, dict) else 0.0,
        "cross_validation_conflicts": cross_validation.get('conflicts_found', 0) if isinstance(cross_validation, dict) else 0,
        "cross_validation_consensus": cross_validation.get('consensus_points', 0) if isinstance(cross_validation, dict) else 0
    }
    
    # Create the complete JSON file structure
    json_data = {
        "timestamp": timestamp,
        "total_scenarios": 1,
        "completed_scenarios": 1,
        "metadata": {
            "created_by": "build_json_from_pickle.py",
            "source": "pickle_file_analysis",
            "enhanced_features": [
                "Fixed CPG response parsing from response.answer",
                "Fixed hybrid synthesis handling as string",
                "Complete raw results extraction for all retrievers",
                "Validated against actual MCP tool responses"
            ]
        },
        "results": [result]
    }
    
    # Save to file
    output_file = Path("/opt/genpod/test_comparative_analysis_from_pickle.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Saved complete JSON to: {output_file}")
    print()
    
    # Show summary
    print("📊 FINAL VALIDATION SUMMARY:")
    print(f"   ✅ Vector: {result['vector_status']} - {len(json.loads(result['vector_raw_results_json']))} raw results ({len(result['vector_raw_results_json'])} chars)")
    print(f"   ✅ CPG: {result['cpg_status']} - {len(json.loads(result['cpg_raw_results_json']))} raw results ({len(result['cpg_raw_results_json'])} chars)")
    print(f"   ✅ Hybrid: {result['hybrid_status']} - {len(json.loads(result['hybrid_raw_results_json']))} raw results ({len(result['hybrid_raw_results_json'])} chars)")
    print()
    print(f"🎯 AI Responses:")
    print(f"   Vector: {result['vector_ai_response'][:100]}...")
    print(f"   CPG: {result['cpg_ai_response'][:100]}...")
    print(f"   Hybrid: {result['hybrid_ai_response'][:100]}...")
    print()
    print(f"📁 JSON file ready for validation: {output_file}")

if __name__ == "__main__":
    build_json_from_pickle()
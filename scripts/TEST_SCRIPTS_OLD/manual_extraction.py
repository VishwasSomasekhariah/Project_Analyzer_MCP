#!/usr/bin/env python3

import json
import ast

def extract_results_manually(ai_response):
    """Manually extract results by parsing the structure"""
    results = []
    
    # Find each result object by looking for the pattern
    current_pos = 0
    
    while True:
        # Find the start of the next result object
        chunk_id_pos = ai_response.find('"chunk_id":', current_pos)
        if chunk_id_pos == -1:
            break
        
        # Find the opening brace for this object
        obj_start = ai_response.rfind('{', 0, chunk_id_pos)
        if obj_start == -1:
            break
        
        # Find the closing brace for this object
        brace_count = 0
        in_string = False
        escape_next = False
        obj_end = -1
        
        for i in range(obj_start, len(ai_response)):
            char = ai_response[i]
            
            if escape_next:
                escape_next = False
            elif char == '\\':
                escape_next = True
            elif char == '"' and not escape_next:
                in_string = not in_string
            elif not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        obj_end = i
                        break
        
        if obj_end == -1:
            break
        
        # Extract the object text
        obj_text = ai_response[obj_start:obj_end+1]
        
        # Try to extract key fields manually since JSON parsing fails
        result_obj = {}
        
        # Extract chunk_id
        chunk_id_match = ai_response[chunk_id_pos:chunk_id_pos+100]
        if '"unknown"' in chunk_id_match:
            result_obj['chunk_id'] = 'unknown'
        
        # Extract content (this is the tricky part)
        content_start = ai_response.find('"content":', obj_start)
        if content_start != -1:
            content_val_start = ai_response.find('"', content_start + 10) + 1
            
            # Find the end of the content string
            content_end = -1
            escape_count = 0
            for i in range(content_val_start, obj_end):
                if ai_response[i] == '\\':
                    escape_count += 1
                elif ai_response[i] == '"':
                    if escape_count % 2 == 0:  # Even number of escapes means the quote is not escaped
                        content_end = i
                        break
                    escape_count = 0
                else:
                    escape_count = 0
            
            if content_end != -1:
                content_raw = ai_response[content_val_start:content_end]
                # Basic cleanup of the content
                content_cleaned = content_raw.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
                result_obj['content'] = content_cleaned
        
        # Extract score
        score_pos = ai_response.find('"score":', obj_start)
        if score_pos != -1 and score_pos < obj_end:
            score_end = ai_response.find(',', score_pos)
            if score_end == -1:
                score_end = ai_response.find('}', score_pos)
            if score_end != -1:
                score_text = ai_response[score_pos+8:score_end].strip()
                try:
                    result_obj['score'] = float(score_text)
                except ValueError:
                    pass
        
        # Extract retrieval_method
        method_pos = ai_response.find('"retrieval_method":', obj_start)
        if method_pos != -1 and method_pos < obj_end:
            method_start = ai_response.find('"', method_pos + 19) + 1
            method_end = ai_response.find('"', method_start)
            if method_end != -1:
                result_obj['retrieval_method'] = ai_response[method_start:method_end]
        
        if result_obj:
            results.append(result_obj)
        
        current_pos = obj_end + 1
    
    return results

def main():
    with open('t001_scenario_test_result.json', 'r') as f:
        data = json.load(f)
    
    ai_response = data['vector_ai_response']
    print(f'AI Response length: {len(ai_response)}')
    
    results = extract_results_manually(ai_response)
    print(f'Extracted {len(results)} results!')
    
    if results:
        print('First result keys:', list(results[0].keys()))
        print('First result content preview:')
        if 'content' in results[0]:
            content = results[0]['content']
            print(repr(content[:200]) + "..." if len(content) > 200 else repr(content))
        
        print(f'\nFirst result score: {results[0].get("score", "N/A")}')
        print(f'First result retrieval method: {results[0].get("retrieval_method", "N/A")}')
    
    return results

if __name__ == "__main__":
    main()
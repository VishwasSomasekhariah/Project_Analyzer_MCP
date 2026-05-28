#!/usr/bin/env python3

import json
import codecs

def fix_json_string(json_str):
    """Fix JSON string with unescaped control characters"""
    # Replace common unescaped characters
    json_str = json_str.replace('\\', '\\\\')  # Escape backslashes first
    json_str = json_str.replace('\n', '\\n')   # Escape newlines
    json_str = json_str.replace('\t', '\\t')   # Escape tabs
    json_str = json_str.replace('\r', '\\r')   # Escape carriage returns
    json_str = json_str.replace('\b', '\\b')   # Escape backspace
    json_str = json_str.replace('\f', '\\f')   # Escape form feed
    return json_str

def extract_vector_raw_results(ai_response):
    """Extract raw results from vector AI response with embedded JSON"""
    # Find the results array
    results_pos = ai_response.find('"results":')
    if results_pos == -1:
        return []
    
    # Find the opening bracket for the results array
    bracket_pos = ai_response.find('[', results_pos)
    if bracket_pos == -1:
        return []
    
    # Find the matching closing bracket
    bracket_count = 0
    for i in range(bracket_pos, len(ai_response)):
        if ai_response[i] == '[':
            bracket_count += 1
        elif ai_response[i] == ']':
            bracket_count -= 1
            if bracket_count == 0:
                # Found the matching closing bracket
                results_array_str = ai_response[bracket_pos:i+1]
                
                # Fix the JSON string
                fixed_json = fix_json_string(results_array_str)
                
                try:
                    results_array = json.loads(fixed_json)
                    return results_array
                except json.JSONDecodeError as e:
                    print(f'Still failed to parse results array: {e}')
                    # Try a more aggressive approach - decode unicode escapes
                    try:
                        # Use codecs to decode unicode escapes
                        decoded_json = codecs.decode(fixed_json, 'unicode_escape')
                        results_array = json.loads(decoded_json)
                        return results_array
                    except Exception as e2:
                        print(f'Failed with codecs approach: {e2}')
                        return []
                break
    
    return []

def main():
    with open('t001_scenario_test_result.json', 'r') as f:
        data = json.load(f)
    
    ai_response = data['vector_ai_response']
    print(f'AI Response length: {len(ai_response)}')
    
    results = extract_vector_raw_results(ai_response)
    print(f'Extracted {len(results)} results!')
    
    if results:
        print('First result keys:', list(results[0].keys()) if results[0] else [])
        print('First result content preview:')
        if results[0] and 'content' in results[0]:
            content = results[0]['content']
            print(content[:200] + "..." if len(content) > 200 else content)
    
    return results

if __name__ == "__main__":
    main()
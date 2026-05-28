#!/usr/bin/env python3

import json
import re

def extract_results_carefully(ai_response):
    """Extract results array by carefully handling the JSON structure"""
    
    # Find the start of the results array
    results_start = ai_response.find('"results": [')
    if results_start == -1:
        return []
    
    # Find the actual start of the array
    array_start = ai_response.find('[', results_start)
    if array_start == -1:
        return []
    
    # Count brackets to find the end of the array
    pos = array_start
    bracket_count = 0
    in_string = False
    escape_next = False
    
    while pos < len(ai_response):
        char = ai_response[pos]
        
        if escape_next:
            escape_next = False
        elif char == '\\':
            escape_next = True
        elif char == '"' and not escape_next:
            in_string = not in_string
        elif not in_string:
            if char == '[':
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1
                if bracket_count == 0:
                    # Found the end of the array
                    array_content = ai_response[array_start:pos+1]
                    
                    # Try to parse it
                    try:
                        results = json.loads(array_content)
                        return results
                    except json.JSONDecodeError as e:
                        print(f'JSON parse error: {e}')
                        # Let's try to fix common issues
                        # Remove any problematic control characters from strings
                        fixed_content = re.sub(r'\\([^"\\bfnrt/])', r'\\\\\\1', array_content)
                        try:
                            results = json.loads(fixed_content)
                            return results
                        except json.JSONDecodeError as e2:
                            print(f'Still failed after fixing: {e2}')
                            return []
        
        pos += 1
    
    return []

def main():
    with open('t001_scenario_test_result.json', 'r') as f:
        data = json.load(f)
    
    ai_response = data['vector_ai_response']
    print(f'AI Response length: {len(ai_response)}')
    
    # Let's also examine what the raw JSON looks like around the problematic area
    results_pos = ai_response.find('"results":')
    if results_pos != -1:
        # Look at a sample of the JSON structure
        sample = ai_response[results_pos:results_pos+500]
        print('Sample around results:')
        for i, line in enumerate(sample.split('\n')[:10]):
            print(f'{i+1:2d}: {repr(line)}')
    
    results = extract_results_carefully(ai_response)
    print(f'\nExtracted {len(results)} results!')
    
    if results:
        print('First result keys:', list(results[0].keys()) if results[0] else [])
        print('Sample result content:')
        if results[0] and 'content' in results[0]:
            content = results[0]['content']
            print(repr(content[:100]) + "..." if len(content) > 100 else repr(content))
    
    return results

if __name__ == "__main__":
    main()
#!/usr/bin/env python3

import json

def main():
    with open('t001_scenario_test_result.json', 'r') as f:
        data = json.load(f)
    
    ai_response = data['vector_ai_response']
    print(f'AI Response length: {len(ai_response)}')
    print('\nFirst 500 chars:')
    print(repr(ai_response[:500]))
    print('\nLooking for JSON start...')
    
    json_start = ai_response.find('{')
    if json_start != -1:
        print(f'JSON starts at position: {json_start}')
        print('\nJSON snippet:')
        print(repr(ai_response[json_start:json_start+300]))
        
        # Try to extract the complete JSON
        brace_count = 0
        start_found = False
        
        for i, char in enumerate(ai_response):
            if char == '{':
                if not start_found:
                    json_start = i
                    start_found = True
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_found:
                    # Found complete JSON object
                    json_part = ai_response[json_start:i+1]
                    try:
                        embedded_json = json.loads(json_part)
                        if isinstance(embedded_json, dict) and "results" in embedded_json:
                            print(f'\nFound embedded JSON with {len(embedded_json["results"])} results!')
                            print('First result snippet:')
                            if embedded_json["results"]:
                                first_result = embedded_json["results"][0]
                                print(json.dumps(first_result, indent=2)[:500] + "...")
                            return embedded_json["results"]
                    except json.JSONDecodeError as e:
                        print(f'JSON decode error: {e}')
                        print(f'Problematic JSON part (first 200 chars):')
                        print(repr(json_part[:200]))
                        # Reset and continue looking for next JSON object
                        start_found = False
                        brace_count = 0
                        continue
    
    print('No valid JSON with results found')
    return []

if __name__ == "__main__":
    main()
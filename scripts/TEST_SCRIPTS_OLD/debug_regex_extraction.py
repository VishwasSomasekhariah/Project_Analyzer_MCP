#!/usr/bin/env python3

import json
import re

def main():
    with open('t001_scenario_test_result.json', 'r') as f:
        data = json.load(f)
    
    ai_response = data['vector_ai_response']
    print(f'AI Response length: {len(ai_response)}')
    
    # Look for the results array pattern
    results_pattern = r'"results":\s*\[(.*?)\]'
    
    # First, let's find where "results" appears
    results_pos = ai_response.find('"results":')
    if results_pos != -1:
        print(f'Found "results": at position {results_pos}')
        
        # Extract a snippet around the results section
        snippet_start = max(0, results_pos - 100)
        snippet_end = min(len(ai_response), results_pos + 1000)
        snippet = ai_response[snippet_start:snippet_end]
        print('Snippet around results section:')
        print(repr(snippet))
        
        # Try to find the bracket that opens the results array
        bracket_pos = ai_response.find('[', results_pos)
        if bracket_pos != -1:
            print(f'Found opening bracket at position {bracket_pos}')
            
            # Now find the matching closing bracket
            bracket_count = 0
            for i in range(bracket_pos, len(ai_response)):
                if ai_response[i] == '[':
                    bracket_count += 1
                elif ai_response[i] == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        # Found the matching closing bracket
                        results_array_str = ai_response[bracket_pos:i+1]
                        print(f'Found results array of length {len(results_array_str)}')
                        
                        # Try to parse just the array
                        try:
                            results_array = json.loads(results_array_str)
                            print(f'Successfully parsed {len(results_array)} results!')
                            
                            # Show first result
                            if results_array:
                                print('First result keys:', list(results_array[0].keys()))
                                return results_array
                        except json.JSONDecodeError as e:
                            print(f'Failed to parse results array: {e}')
                            print('First 500 chars of results array:')
                            print(repr(results_array_str[:500]))
                        break

    print('No results array found')
    return []

if __name__ == "__main__":
    main()
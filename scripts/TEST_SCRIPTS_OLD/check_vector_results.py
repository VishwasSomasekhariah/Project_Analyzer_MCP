#!/usr/bin/env python3
import json

with open('t001_scenario_test_result.json', 'r') as f:
    data = json.load(f)
    
vector_raw = data.get('vector_raw_results_json', '[]')
print(f'Vector raw results length: {len(vector_raw)}')

if vector_raw != '[]':
    results = json.loads(vector_raw) if isinstance(vector_raw, str) else vector_raw
    print(f'Number of vector results: {len(results)}')
    if results:
        print('First result keys:', list(results[0].keys()))
        print('First result content preview:')
        print(results[0].get('content', 'No content')[:100] + '...')
else:
    print('Vector raw results is still empty!')
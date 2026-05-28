#!/usr/bin/env python3
"""
Analyze CPG retrieval failures and empty responses
"""

import pandas as pd
import json

def analyze_cpg_failures():
    # Load the CSV file
    df = pd.read_csv('/opt/genpod/test_results/comparative_analysis_20250715_184459.csv')
    
    # Analyze CPG failures
    cpg_failures = 0
    cpg_empty_responses = 0
    cpg_short_responses = 0
    cpg_no_results = 0
    failed_queries = []
    
    for _, row in df.iterrows():
        cpg_response = str(row['cpg_response'])
        cpg_status = row['cpg_status']
        query_id = row['query_id']
        user_query = row['user_query']
        
        if cpg_status != 'success':
            cpg_failures += 1
            failed_queries.append({
                'query_id': query_id,
                'user_query': user_query,
                'status': cpg_status,
                'error': row.get('cpg_error', 'N/A')
            })
        elif len(cpg_response) < 50:
            cpg_short_responses += 1
            failed_queries.append({
                'query_id': query_id,
                'user_query': user_query,
                'issue': 'short_response',
                'response_length': len(cpg_response),
                'response': cpg_response[:100]
            })
        elif 'no results' in cpg_response.lower() or 'empty' in cpg_response.lower() or 'no data' in cpg_response.lower():
            cpg_no_results += 1
            failed_queries.append({
                'query_id': query_id,
                'user_query': user_query,
                'issue': 'no_results',
                'response': cpg_response[:200]
            })
    
    print(f'CPG Analysis Results:')
    print(f'Total scenarios: {len(df)}')
    print(f'CPG failures (status != success): {cpg_failures}')
    print(f'CPG short responses (<50 chars): {cpg_short_responses}')
    print(f'CPG no results responses: {cpg_no_results}')
    print(f'CPG success rate: {((len(df) - cpg_failures) / len(df)) * 100:.1f}%')
    
    print(f'\nFailed/Poor CPG Queries:')
    for i, failure in enumerate(failed_queries[:10]):  # Show first 10
        print(f'\n{i+1}. Query ID: {failure["query_id"]}')
        print(f'   Query: {failure["user_query"][:100]}...')
        if 'status' in failure:
            print(f'   Status: {failure["status"]}')
            print(f'   Error: {failure["error"]}')
        elif 'issue' in failure:
            print(f'   Issue: {failure["issue"]}')
            if 'response_length' in failure:
                print(f'   Response Length: {failure["response_length"]}')
            print(f'   Response: {failure["response"][:100]}...')
    
    # Analyze response patterns
    print(f'\nCPG Response Pattern Analysis:')
    avg_length = df['cpg_response'].str.len().mean()
    median_length = df['cpg_response'].str.len().median()
    print(f'Average CPG response length: {avg_length:.0f} chars')
    print(f'Median CPG response length: {median_length:.0f} chars')
    
    # Check for JSON responses
    json_responses = 0
    for _, row in df.iterrows():
        cpg_response = str(row['cpg_response'])
        if cpg_response.startswith('{') and cpg_response.endswith('}'):
            json_responses += 1
    
    print(f'JSON-formatted CPG responses: {json_responses}/{len(df)} ({(json_responses/len(df))*100:.1f}%)')

if __name__ == "__main__":
    analyze_cpg_failures()
#!/usr/bin/env python3
"""
Extract all queries from the comparative analysis CSV file
"""
import pandas as pd
import csv

# Increase CSV field size limit
csv.field_size_limit(1000000)

# Load the CSV file
csv_file = '/opt/Test_Suite_Benchmarking/properly_fixed_comparative_analysis_20250718_172420.csv'

# Read only the first 3 columns to extract queries
queries = []
with open(csv_file, 'r', encoding='utf-8') as file:
    reader = csv.reader(file)
    header = next(reader)  # Skip header
    
    for row in reader:
        if len(row) >= 3:
            query_id = row[0]
            user_query = row[1]
            query_category = row[2]
            
            queries.append({
                'query_id': query_id,
                'user_query': user_query,
                'query_category': query_category
            })

print(f"Extracted {len(queries)} queries:")
for i, query in enumerate(queries):
    print(f"{i+1}. {query['query_id']}: {query['user_query'][:100]}...")

# Save to a clean CSV for ground truth generation
df = pd.DataFrame(queries)
df.to_csv('/opt/Test_Suite_Benchmarking/queries_for_ground_truth.csv', index=False)
print(f"\nSaved queries to /opt/Test_Suite_Benchmarking/queries_for_ground_truth.csv")
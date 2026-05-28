#!/usr/bin/env python3
"""
Test CSV and Excel output functionality
"""

import pandas as pd
from pathlib import Path
from datetime import datetime

# Create sample data
data = [
    {
        "query_id": "T001",
        "user_query": "Test query 1",
        "vector_status": "success",
        "cpg_status": "success",
        "comprehensive_status": "success"
    },
    {
        "query_id": "T002", 
        "user_query": "Test query 2",
        "vector_status": "success",
        "cpg_status": "success",
        "comprehensive_status": "success"
    }
]

df = pd.DataFrame(data)

# Create output directory
output_dir = Path("/opt/genpod/test_results")
output_dir.mkdir(exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# Save to CSV
csv_file = output_dir / f"test_output_{timestamp}.csv"
df.to_csv(csv_file, index=False)

# Save to Excel
excel_file = output_dir / f"test_output_{timestamp}.xlsx"
try:
    df.to_excel(excel_file, index=False, engine='openpyxl')
    print(f"✅ Both formats saved successfully:")
    print(f"  📄 CSV: {csv_file}")
    print(f"  📊 Excel: {excel_file}")
except Exception as e:
    print(f"❌ Excel save failed: {e}")
    print(f"✅ CSV saved: {csv_file}")
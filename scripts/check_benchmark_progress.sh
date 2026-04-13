#!/bin/bash
echo "=== Benchmark Progress ==="
echo ""
echo "Completed runs:"
ls -1 benchmark_results_v6/run_*_output.json 2>/dev/null | wc -l
echo ""
echo "Latest activity:"
tail -20 benchmark_v6_with_query_plans.log | grep -E "RUN [0-9]|✅ Saved complete|Total data points|Approaches succeeded" || tail -20 benchmark_v6_with_query_plans.log

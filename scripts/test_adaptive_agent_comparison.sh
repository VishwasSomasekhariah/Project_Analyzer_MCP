#!/bin/bash
# Test script to compare AdaptiveQueryAgent vs existing workflow nodes

echo "====================================================================="
echo "Testing AdaptiveQueryAgent vs Workflow Nodes"
echo "====================================================================="
echo ""

echo "🔬 Test 1: Running with EXISTING workflow nodes (baseline)"
echo "---------------------------------------------------------------------"
export USE_ADAPTIVE_QUERY_AGENT=false
python3 test_parallel_with_token_tracking.py 2>&1 | tee test_results/baseline_workflow_nodes.log
echo ""
echo "✅ Baseline test complete. Results saved to test_results/baseline_workflow_nodes.log"
echo ""

echo "🤖 Test 2: Running with NEW AdaptiveQueryAgent (CoT agent)"
echo "---------------------------------------------------------------------"
export USE_ADAPTIVE_QUERY_AGENT=true
python3 test_parallel_with_token_tracking.py 2>&1 | tee test_results/adaptive_query_agent.log
echo ""
echo "✅ AdaptiveQueryAgent test complete. Results saved to test_results/adaptive_query_agent.log"
echo ""

echo "====================================================================="
echo "Comparison Summary"
echo "====================================================================="
echo ""
echo "Baseline (workflow nodes):"
grep "⏱️ Time:" test_results/baseline_workflow_nodes.log | tail -1
grep "Total tokens" test_results/baseline_workflow_nodes.log | tail -1
echo ""
echo "AdaptiveQueryAgent (CoT):"
grep "⏱️ Time:" test_results/adaptive_query_agent.log | tail -1
grep "Total tokens" test_results/adaptive_query_agent.log | tail -1
echo ""
echo "Check logs for detailed comparison:"
echo "  - test_results/baseline_workflow_nodes.log"
echo "  - test_results/adaptive_query_agent.log"

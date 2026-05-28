#!/usr/bin/env python3
"""
Test workflow with comprehensive tracing.

Captures all function inputs/outputs and saves to PKL for analysis.
"""

import asyncio
import pickle
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from functools import wraps
import traceback as tb

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core.workflow.adaptive_cpg_workflow import execute_adaptive_cpg_workflow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Tracing System
# =============================================================================

class ExecutionTracer:
    """Captures all function calls, inputs, and outputs."""

    def __init__(self):
        self.traces: List[Dict[str, Any]] = []
        self.current_trace_id = 0

    def trace_call(self,
                   function_name: str,
                   args: tuple,
                   kwargs: dict,
                   result: Any = None,
                   error: Exception = None,
                   duration_ms: float = None):
        """Record a function call trace."""
        trace = {
            'trace_id': self.current_trace_id,
            'timestamp': datetime.now().isoformat(),
            'function': function_name,
            'args': self._serialize_args(args),
            'kwargs': self._serialize_kwargs(kwargs),
            'result': self._serialize_result(result),
            'error': str(error) if error else None,
            'error_traceback': tb.format_exc() if error else None,
            'duration_ms': duration_ms
        }
        self.traces.append(trace)
        self.current_trace_id += 1
        return trace

    def _serialize_args(self, args: tuple) -> List[Any]:
        """Serialize args for storage."""
        serialized = []
        for arg in args:
            try:
                # Try to get a compact representation
                if hasattr(arg, '__dict__'):
                    serialized.append({
                        '_type': type(arg).__name__,
                        '_repr': repr(arg)[:200]
                    })
                else:
                    serialized.append(arg)
            except:
                serialized.append(f"<unserializable: {type(arg).__name__}>")
        return serialized

    def _serialize_kwargs(self, kwargs: dict) -> Dict[str, Any]:
        """Serialize kwargs for storage."""
        serialized = {}
        for key, value in kwargs.items():
            try:
                if isinstance(value, (str, int, float, bool, type(None))):
                    serialized[key] = value
                elif isinstance(value, (list, dict)):
                    # Truncate large collections
                    if isinstance(value, list) and len(value) > 10:
                        serialized[key] = {
                            '_type': 'list',
                            '_length': len(value),
                            '_sample': value[:3]
                        }
                    elif isinstance(value, dict) and len(value) > 10:
                        serialized[key] = {
                            '_type': 'dict',
                            '_length': len(value),
                            '_keys': list(value.keys())[:10]
                        }
                    else:
                        serialized[key] = value
                else:
                    serialized[key] = {
                        '_type': type(value).__name__,
                        '_repr': repr(value)[:200]
                    }
            except:
                serialized[key] = f"<unserializable: {type(value).__name__}>"
        return serialized

    def _serialize_result(self, result: Any) -> Any:
        """Serialize result for storage."""
        if result is None:
            return None

        try:
            # Handle different result types
            if isinstance(result, (str, int, float, bool)):
                return result
            elif isinstance(result, dict):
                # For state dicts, capture key info
                if 'current_node' in result:
                    return {
                        '_type': 'AgentState',
                        'current_node': result.get('current_node'),
                        'query': result.get('query', '')[:100],
                        'approach_packets': self._summarize_packets(result.get('approach_packets')),
                        'completed_subqueries': result.get('completed_subqueries', [])
                    }
                else:
                    # Generic dict - truncate if large
                    if len(result) > 20:
                        return {
                            '_type': 'dict',
                            '_length': len(result),
                            '_keys': list(result.keys())[:10],
                            '_sample': {k: result[k] for k in list(result.keys())[:3]}
                        }
                    return result
            elif isinstance(result, list):
                if len(result) > 20:
                    return {
                        '_type': 'list',
                        '_length': len(result),
                        '_sample': result[:3]
                    }
                return result
            else:
                return {
                    '_type': type(result).__name__,
                    '_repr': repr(result)[:200]
                }
        except:
            return f"<unserializable: {type(result).__name__}>"

    def _summarize_packets(self, packets_data: Any) -> Dict[str, Any]:
        """Summarize approach packets."""
        if not packets_data:
            return None

        if isinstance(packets_data, dict):
            packets = packets_data.get('packets', {})
            return {
                'total_packets': len(packets),
                'packet_ids': list(packets.keys())
            }
        return None

    def save(self, filepath: str):
        """Save traces to JSON file (more compatible than pickle)."""
        import json

        # Convert to JSON-friendly format
        json_filepath = filepath.replace('.pkl', '.json')

        with open(json_filepath, 'w') as f:
            json.dump({
                'traces': self.traces,
                'total_traces': len(self.traces),
                'timestamp': datetime.now().isoformat()
            }, f, indent=2, default=str)

        logger.info(f"💾 Saved {len(self.traces)} traces to {json_filepath}")

# Global tracer instance
tracer = ExecutionTracer()

# =============================================================================
# Tracing Decorators
# =============================================================================

def trace_async(func):
    """Decorator to trace async function calls."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        func_name = f"{func.__module__}.{func.__qualname__}"
        start = datetime.now()

        logger.info(f"📥 CALL: {func_name}")

        try:
            result = await func(*args, **kwargs)
            duration = (datetime.now() - start).total_seconds() * 1000

            tracer.trace_call(
                function_name=func_name,
                args=args,
                kwargs=kwargs,
                result=result,
                duration_ms=duration
            )

            logger.info(f"📤 RETURN: {func_name} (took {duration:.2f}ms)")
            return result

        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000

            tracer.trace_call(
                function_name=func_name,
                args=args,
                kwargs=kwargs,
                error=e,
                duration_ms=duration
            )

            logger.error(f"❌ ERROR: {func_name} - {e}")
            raise

    return wrapper

def trace_sync(func):
    """Decorator to trace sync function calls."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        func_name = f"{func.__module__}.{func.__qualname__}"
        start = datetime.now()

        logger.info(f"📥 CALL: {func_name}")

        try:
            result = func(*args, **kwargs)
            duration = (datetime.now() - start).total_seconds() * 1000

            tracer.trace_call(
                function_name=func_name,
                args=args,
                kwargs=kwargs,
                result=result,
                duration_ms=duration
            )

            logger.info(f"📤 RETURN: {func_name} (took {duration:.2f}ms)")
            return result

        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000

            tracer.trace_call(
                function_name=func_name,
                args=args,
                kwargs=kwargs,
                error=e,
                duration_ms=duration
            )

            logger.error(f"❌ ERROR: {func_name} - {e}")
            raise

    return wrapper

# =============================================================================
# Monkey Patch Workflow Nodes for Tracing
# =============================================================================

def patch_workflow_for_tracing():
    """Patch workflow nodes to add tracing."""
    from src.core.workflow import nodes
    from src.core.workflow import research_engine
    from src.core.workflow import adaptive_query_agent

    # Patch workflow nodes
    if hasattr(nodes.WorkflowNodes, 'decompose_query'):
        nodes.WorkflowNodes.decompose_query = trace_async(nodes.WorkflowNodes.decompose_query)

    if hasattr(nodes.WorkflowNodes, 'execute_batch_approaches'):
        nodes.WorkflowNodes.execute_batch_approaches = trace_async(nodes.WorkflowNodes.execute_batch_approaches)

    if hasattr(nodes.WorkflowNodes, 'check_sufficiency'):
        nodes.WorkflowNodes.check_sufficiency = trace_async(nodes.WorkflowNodes.check_sufficiency)

    if hasattr(nodes.WorkflowNodes, 'synthesize_response'):
        nodes.WorkflowNodes.synthesize_response = trace_async(nodes.WorkflowNodes.synthesize_response)

    # Patch research engine
    if hasattr(research_engine.ResearchEngine, '_decompose_query_phase0'):
        research_engine.ResearchEngine._decompose_query_phase0 = trace_async(
            research_engine.ResearchEngine._decompose_query_phase0
        )

    if hasattr(research_engine.ResearchEngine, '_analyze_dependencies'):
        research_engine.ResearchEngine._analyze_dependencies = trace_async(
            research_engine.ResearchEngine._analyze_dependencies
        )

    if hasattr(research_engine.ResearchEngine, '_build_approach_packets'):
        research_engine.ResearchEngine._build_approach_packets = trace_sync(
            research_engine.ResearchEngine._build_approach_packets
        )

    # Patch adaptive query agent
    if hasattr(adaptive_query_agent.AdaptiveQueryAgent, 'execute_approach'):
        adaptive_query_agent.AdaptiveQueryAgent.execute_approach = trace_async(
            adaptive_query_agent.AdaptiveQueryAgent.execute_approach
        )

    if hasattr(adaptive_query_agent.AdaptiveQueryAgent, '_cot_think_step'):
        adaptive_query_agent.AdaptiveQueryAgent._cot_think_step = trace_async(
            adaptive_query_agent.AdaptiveQueryAgent._cot_think_step
        )

    if hasattr(adaptive_query_agent.AdaptiveQueryAgent, '_cot_generate_query_step'):
        adaptive_query_agent.AdaptiveQueryAgent._cot_generate_query_step = trace_async(
            adaptive_query_agent.AdaptiveQueryAgent._cot_generate_query_step
        )

    if hasattr(adaptive_query_agent.AdaptiveQueryAgent, '_execute_query'):
        adaptive_query_agent.AdaptiveQueryAgent._execute_query = trace_async(
            adaptive_query_agent.AdaptiveQueryAgent._execute_query
        )

    if hasattr(adaptive_query_agent.AdaptiveQueryAgent, '_cot_analyze_results_step'):
        adaptive_query_agent.AdaptiveQueryAgent._cot_analyze_results_step = trace_async(
            adaptive_query_agent.AdaptiveQueryAgent._cot_analyze_results_step
        )

    if hasattr(adaptive_query_agent.AdaptiveQueryAgent, '_validate_premises_with_apoc'):
        adaptive_query_agent.AdaptiveQueryAgent._validate_premises_with_apoc = trace_async(
            adaptive_query_agent.AdaptiveQueryAgent._validate_premises_with_apoc
        )

    logger.info("✅ Workflow patched for tracing")

# =============================================================================
# Test Execution
# =============================================================================

async def run_test_workflow():
    """Run test workflow with tracing."""

    # Test query
    test_query = "Which specific classes are instantiated and returned by WorkerFactory.CreateWorkers()?"

    logger.info("="*80)
    logger.info("🚀 Starting Traced Workflow Execution")
    logger.info("="*80)
    logger.info(f"Query: {test_query}")
    logger.info("="*80)

    # Patch workflow for tracing
    patch_workflow_for_tracing()

    # Execute workflow
    try:
        result = await execute_adaptive_cpg_workflow(
            test_query,
            neo4j_config="/opt/genpod/neo4j_config.json"
        )

        logger.info("="*80)
        logger.info("✅ Workflow Completed Successfully")
        logger.info("="*80)

        # Print summary
        if isinstance(result, dict):
            logger.info(f"Response: {result.get('response', 'N/A')[:200]}...")
            logger.info(f"Status: {result.get('status', 'N/A')}")
            logger.info(f"Execution Time: {result.get('execution_time_ms', 0):.2f}ms")

        return result

    except Exception as e:
        logger.error("="*80)
        logger.error(f"❌ Workflow Failed: {e}")
        logger.error("="*80)
        logger.error(tb.format_exc())
        raise

async def main():
    """Main entry point."""

    try:
        # Run workflow
        result = await run_test_workflow()

        # Save traces
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trace_file = f"workflow_trace_{timestamp}.pkl"
        tracer.save(trace_file)

        logger.info("="*80)
        logger.info(f"📊 Trace Analysis")
        logger.info("="*80)
        logger.info(f"Total function calls: {len(tracer.traces)}")
        logger.info(f"Trace file: {trace_file}")
        logger.info("")
        logger.info("To analyze traces, run:")
        logger.info(f"  python3 analyze_workflow_trace.py {trace_file}")

        return 0

    except Exception as e:
        logger.error(f"Test failed: {e}")

        # Save traces even on failure
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trace_file = f"workflow_trace_FAILED_{timestamp}.pkl"
        tracer.save(trace_file)

        logger.info(f"Trace file saved: {trace_file}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

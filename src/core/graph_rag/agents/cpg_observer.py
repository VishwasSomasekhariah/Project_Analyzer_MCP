"""
CPG Observer Agent for the Graph RAG Multi-Agent system.

Passive observer that monitors the RAG system to identify CPG improvements.
Does NOT interfere with the main workflow - collects observations non-blockingly.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from src.core.graph_rag.core.config import LLMConfig
from src.core.graph_rag.core.models import (
    CPGIssue,
    ObserverMemory,
    ObserverReport,
    QueryObservation,
)


class CPGObserverAgent:
    """
    Passive observer that monitors the RAG system to identify CPG improvements.

    Does NOT interfere with the main workflow - collects observations non-blockingly.
    Has its own MCP session for exploration and persistent memory across sessions.

    Key Capabilities:
    1. Non-blocking observation collection via async queue
    2. Persistent memory across sessions (file-based JSON)
    3. Cypher exploration tools for CPG introspection
    4. Neo4j function/procedure discovery tools
    5. Pattern detection (empty results, errors, missing relationships)
    6. LLM-powered analysis and report generation
    """

    ANALYSIS_PROMPT = """You are a CPG Quality Analyst. Analyze query observations to identify improvements for the Code Property Graph.

OBSERVATIONS DATA:
{observations_summary}

CURRENT SCHEMA:
{schema_summary}

TASK: Analyze the patterns and identify:
1. Missing relationships that queries expect but don't exist
2. Missing properties that would be useful
3. Inconsistencies in the data model
4. Patterns of empty results indicating data gaps
5. Suggested improvements for the CPG builder

OUTPUT FORMAT (JSON):
{{
  "identified_issues": [
    {{
      "issue_type": "missing_relationship|missing_property|inconsistency|data_gap|pattern_suggestion",
      "severity": "high|medium|low",
      "description": "Clear description of the issue",
      "evidence": ["query patterns or observations as evidence"],
      "suggested_fix": "How to fix this in the CPG builder",
      "related_nodes": ["affected node types"],
      "related_relationships": ["affected relationships"]
    }}
  ],
  "improvement_suggestions": ["actionable suggestions for CPG enhancement"],
  "summary": "Executive summary of findings"
}}"""

    def __init__(
        self,
        mcp_session,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        memory_file: str = "cpg_observer_memory.json",
        max_memory_observations: int = 1000
    ):
        """
        Initialize the CPG Observer Agent.

        Args:
            mcp_session: Active MCP session for exploration
            openai_client: OpenAI client for analysis
            llm_config: LLM configuration
            memory_file: Path for persistent memory storage
            max_memory_observations: Maximum observations to keep in memory
        """
        self._session = mcp_session
        self._openai = openai_client
        self._llm_config = llm_config
        self._memory_file = Path(memory_file)
        self._max_observations = max_memory_observations
        self._logger = logging.getLogger(f"{__name__}.cpg_observer")

        # Async queue for non-blocking observation collection
        self._observation_queue: asyncio.Queue[QueryObservation] = asyncio.Queue()

        # Current session tracking
        self._current_session_id = str(uuid.uuid4())[:8]
        self._current_user_query: Optional[str] = None

        # Load persistent memory
        self._memory = self._load_memory()
        self._memory.session_count += 1

        # Build tools for CPG exploration
        self._tools = self._build_tools()

        self._logger.info(f"CPG Observer initialized (session: {self._current_session_id}, "
                         f"prior observations: {len(self._memory.observations)})")

    def _load_memory(self) -> ObserverMemory:
        """Load persistent memory from file"""
        if self._memory_file.exists():
            try:
                with open(self._memory_file, 'r') as f:
                    data = json.load(f)
                return ObserverMemory(**data)
            except Exception as e:
                self._logger.warning(f"Failed to load observer memory: {e}. Starting fresh.")
        return ObserverMemory()

    def save_memory(self):
        """Save memory to file for persistence"""
        try:
            # Trim observations if exceeding limit (keep most recent)
            if len(self._memory.observations) > self._max_observations:
                self._memory.observations = self._memory.observations[-self._max_observations:]

            with open(self._memory_file, 'w') as f:
                json.dump(self._memory.model_dump(), f, indent=2, default=str)
            self._logger.debug(f"Observer memory saved ({len(self._memory.observations)} observations)")
        except Exception as e:
            self._logger.error(f"Failed to save observer memory: {e}")

    def _build_tools(self) -> List[Dict]:
        """Build tools for CPG exploration"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "cpg_execute_query",
                    "description": "Execute a Cypher query to explore CPG structure and data",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Cypher query to execute"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cpg_get_schema",
                    "description": "Get the current CPG schema (node types, relationships, properties)",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cpg_count_nodes",
                    "description": "Count nodes by type in the CPG",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_type": {
                                "type": "string",
                                "description": "Node type to count (e.g., 'Type', 'Function'). Leave empty to count all types."
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cpg_list_functions",
                    "description": "List available Neo4j functions. Use substring filter to search for specific functions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filter_substring": {
                                "type": "string",
                                "description": "Optional substring to filter function names (e.g., 'apoc', 'string', 'list')"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cpg_list_procedures",
                    "description": "List available Neo4j procedures (stored procedures). Use substring filter to search for specific procedures.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filter_substring": {
                                "type": "string",
                                "description": "Optional substring to filter procedure names (e.g., 'apoc', 'db', 'meta')"
                            }
                        }
                    }
                }
            }
        ]

    async def _execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute observer's exploration tools"""
        try:
            if name == "cpg_execute_query":
                query = arguments.get("query", "")
                # Only allow read queries
                query_upper = query.upper()
                if any(kw in query_upper for kw in ["DELETE", "CREATE", "SET", "MERGE", "REMOVE", "DROP"]):
                    return json.dumps({"error": "Only read queries allowed for observer"})

                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Empty response"})

            elif name == "cpg_get_schema":
                # Get schema via APOC
                query = "CALL apoc.meta.schema() YIELD value RETURN value"
                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Schema not available"})

            elif name == "cpg_count_nodes":
                node_type = arguments.get("node_type")
                if node_type:
                    query = f"MATCH (n:{node_type}) RETURN count(n) as count"
                else:
                    query = "MATCH (n) RETURN labels(n)[0] as type, count(n) as count ORDER BY count DESC"
                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Count failed"})

            elif name == "cpg_list_functions":
                # SHOW FUNCTIONS with optional filter
                filter_substring = arguments.get("filter_substring", "")
                if filter_substring:
                    query = f"SHOW FUNCTIONS YIELD name WHERE name CONTAINS '{filter_substring}' RETURN name"
                else:
                    query = "SHOW FUNCTIONS YIELD name RETURN name LIMIT 100"
                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Failed to list functions"})

            elif name == "cpg_list_procedures":
                # SHOW PROCEDURES with optional filter
                filter_substring = arguments.get("filter_substring", "")
                if filter_substring:
                    query = f"SHOW PROCEDURES YIELD name WHERE name CONTAINS '{filter_substring}' RETURN name"
                else:
                    query = "SHOW PROCEDURES YIELD name RETURN name LIMIT 100"
                result = await self._session.call_tool("neo4j_execute_query", {"query": query})
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Failed to list procedures"})

            return json.dumps({"error": f"Unknown tool: {name}"})
        except Exception as e:
            self._logger.error(f"Observer tool error ({name}): {e}")
            return json.dumps({"error": str(e)})

    def set_current_query(self, user_query: str):
        """Set the current user query context for observations"""
        self._current_user_query = user_query

    def _extract_query_components(self, cypher_query: str) -> Tuple[List[str], List[str], List[str]]:
        """Extract node types, relationships, and properties from a Cypher query"""
        node_types = []
        relationships = []
        properties = []

        # Extract node types (pattern: (n:NodeType) or :NodeType)
        node_pattern = r':([A-Z][a-zA-Z0-9_]*)'
        node_matches = re.findall(node_pattern, cypher_query)
        node_types = list(set(node_matches))

        # Extract relationships (pattern: -[:REL_TYPE]-> or -[r:REL_TYPE]->)
        rel_pattern = r'\[:?([A-Z_]+)\]'
        rel_matches = re.findall(rel_pattern, cypher_query)
        relationships = list(set(rel_matches))

        # Extract properties (pattern: .property_name or {property: value})
        prop_pattern1 = r'\.([a-z_][a-zA-Z0-9_]*)'
        prop_pattern2 = r'\{([a-z_][a-zA-Z0-9_]*):'
        prop_matches = re.findall(prop_pattern1, cypher_query) + re.findall(prop_pattern2, cypher_query)
        properties = list(set(prop_matches))

        return node_types, relationships, properties

    def observe_query(
        self,
        cypher_query: str,
        result: str,
        agent_id: str,
        sub_query: Optional[str] = None,
        execution_time_ms: int = 0
    ):
        """
        Record an observation of a query execution.
        This method is NON-BLOCKING - it queues the observation for async processing.
        """
        try:
            # Parse result to determine if empty or error
            result_count = 0
            is_empty = False
            had_error = False
            error_message = None

            try:
                result_data = json.loads(result) if isinstance(result, str) else result
                if isinstance(result_data, dict):
                    if 'error' in result_data:
                        had_error = True
                        error_message = result_data.get('error', '')[:200]
                    elif 'results' in result_data:
                        result_count = len(result_data.get('results', []))
                        is_empty = result_count == 0
                    else:
                        # Try to count items
                        result_count = len(result_data) if isinstance(result_data, (list, dict)) else 1
                        is_empty = result_count == 0
                elif isinstance(result_data, list):
                    result_count = len(result_data)
                    is_empty = result_count == 0
            except (json.JSONDecodeError, TypeError):
                # If we can't parse, check for common error indicators
                if isinstance(result, str):
                    if 'error' in result.lower() or 'exception' in result.lower():
                        had_error = True
                        error_message = result[:200]
                    elif result.strip() in ('[]', '{}', '', 'null'):
                        is_empty = True

            # Extract query components
            node_types, relationships, properties = self._extract_query_components(cypher_query)

            # Create observation
            observation = QueryObservation(
                timestamp=datetime.utcnow().isoformat(),
                session_id=self._current_session_id,
                user_query=self._current_user_query or "",
                sub_query=sub_query,
                agent_id=agent_id,
                cypher_query=cypher_query,
                result_count=result_count,
                is_empty=is_empty,
                had_error=had_error,
                error_message=error_message,
                execution_time_ms=execution_time_ms,
                node_types_queried=node_types,
                relationships_queried=relationships,
                properties_accessed=properties
            )

            # Add to memory (non-blocking)
            self._memory.observations.append(observation)

            # Track patterns
            pattern_key = f"{','.join(sorted(node_types))}-{','.join(sorted(relationships))}"
            self._memory.query_patterns[pattern_key] = self._memory.query_patterns.get(pattern_key, 0) + 1

            # Track issues
            if is_empty:
                if cypher_query not in self._memory.empty_result_queries:
                    self._memory.empty_result_queries.append(cypher_query)
            if had_error:
                if cypher_query not in self._memory.error_queries:
                    self._memory.error_queries.append(cypher_query)

            self._logger.debug(f"Observed query from {agent_id}: empty={is_empty}, error={had_error}")

        except Exception as e:
            self._logger.error(f"Error recording observation: {e}")

    async def analyze_and_report(self, force: bool = False) -> Optional[ObserverReport]:
        """
        Analyze collected observations and generate an improvement report.
        Uses LLM to identify patterns and suggest improvements.

        Args:
            force: If True, generate report even with few observations
        """
        # Check if we have enough observations
        if len(self._memory.observations) < 5 and not force:
            self._logger.info("Not enough observations for analysis (need at least 5)")
            return None

        self._logger.info(f"Analyzing {len(self._memory.observations)} observations...")

        # Build observations summary for LLM
        empty_count = sum(1 for o in self._memory.observations if o.is_empty)
        error_count = sum(1 for o in self._memory.observations if o.had_error)
        total = len(self._memory.observations)

        # Collect common patterns
        all_node_types = {}
        all_relationships = {}
        all_properties = {}
        for obs in self._memory.observations:
            for nt in obs.node_types_queried:
                all_node_types[nt] = all_node_types.get(nt, 0) + 1
            for rel in obs.relationships_queried:
                all_relationships[rel] = all_relationships.get(rel, 0) + 1
            for prop in obs.properties_accessed:
                all_properties[prop] = all_properties.get(prop, 0) + 1

        # Get sample empty/error queries (most recent)
        sample_empty = self._memory.empty_result_queries[-5:] if self._memory.empty_result_queries else []
        sample_errors = self._memory.error_queries[-5:] if self._memory.error_queries else []

        observations_summary = f"""
Total Observations: {total}
Sessions: {self._memory.session_count}
Empty Result Rate: {(empty_count/total*100) if total > 0 else 0:.1f}%
Error Rate: {(error_count/total*100) if total > 0 else 0:.1f}%

Most Queried Node Types:
{json.dumps(dict(sorted(all_node_types.items(), key=lambda x: -x[1])[:10]), indent=2)}

Most Queried Relationships:
{json.dumps(dict(sorted(all_relationships.items(), key=lambda x: -x[1])[:10]), indent=2)}

Most Accessed Properties:
{json.dumps(dict(sorted(all_properties.items(), key=lambda x: -x[1])[:10]), indent=2)}

Sample Empty Result Queries:
{json.dumps(sample_empty, indent=2)}

Sample Error Queries:
{json.dumps(sample_errors, indent=2)}

Query Patterns (by frequency):
{json.dumps(dict(sorted(self._memory.query_patterns.items(), key=lambda x: -x[1])[:10]), indent=2)}
"""

        # Get current schema for context
        schema_summary = "Schema not available"
        try:
            schema_result = await self._execute_tool("cpg_get_schema", {})
            schema_summary = schema_result[:2000] if len(schema_result) > 2000 else schema_result
        except Exception as e:
            self._logger.warning(f"Failed to get schema for analysis: {e}")

        # Call LLM for analysis
        try:
            prompt = self.ANALYSIS_PROMPT.format(
                observations_summary=observations_summary,
                schema_summary=schema_summary
            )

            response = self._openai.chat.completions.create(
                model=self._llm_config.model,
                temperature=0.1,  # Low temp for analytical task
                messages=[
                    {"role": "system", "content": "You are a CPG Quality Analyst providing actionable recommendations."},
                    {"role": "user", "content": prompt}
                ]
            )

            content = response.choices[0].message.content

            # Parse LLM response
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                analysis = json.loads(content[start_idx:end_idx])

                # Create issues from analysis
                identified_issues = []
                for issue_data in analysis.get('identified_issues', []):
                    issue = CPGIssue(
                        issue_id=str(uuid.uuid4())[:8],
                        issue_type=issue_data.get('issue_type', 'pattern_suggestion'),
                        severity=issue_data.get('severity', 'medium'),
                        description=issue_data.get('description', ''),
                        evidence=issue_data.get('evidence', []),
                        suggested_fix=issue_data.get('suggested_fix'),
                        related_nodes=issue_data.get('related_nodes', []),
                        related_relationships=issue_data.get('related_relationships', []),
                        detected_at=datetime.utcnow().isoformat(),
                        occurrence_count=1
                    )
                    identified_issues.append(issue)

                # Create report
                report = ObserverReport(
                    report_id=str(uuid.uuid4())[:8],
                    generated_at=datetime.utcnow().isoformat(),
                    total_observations=total,
                    total_sessions=self._memory.session_count,
                    empty_result_rate=(empty_count/total*100) if total > 0 else 0,
                    error_rate=(error_count/total*100) if total > 0 else 0,
                    identified_issues=identified_issues,
                    query_patterns=dict(sorted(self._memory.query_patterns.items(), key=lambda x: -x[1])[:20]),
                    missing_relationships=[],  # Will be populated by issues
                    missing_properties=[],
                    improvement_suggestions=analysis.get('improvement_suggestions', []),
                    summary=analysis.get('summary', 'Analysis complete.')
                )

                # Update memory
                self._memory.identified_issues.extend(identified_issues)
                self._memory.last_analysis_timestamp = datetime.utcnow().isoformat()
                self._memory.last_report = report

                # Save memory
                self.save_memory()

                self._logger.info(f"Analysis complete: {len(identified_issues)} issues identified")
                return report

        except Exception as e:
            self._logger.error(f"LLM analysis failed: {e}")

        return None

    async def explore_cpg(self, exploration_query: str) -> str:
        """
        Explore the CPG using a natural language query.
        The observer can use this to investigate issues or answer questions about the CPG structure.
        """
        self._logger.info(f"Exploring CPG: {exploration_query}")

        messages = [
            {"role": "system", "content": """You are a CPG Explorer. Use the provided tools to answer questions about the Code Property Graph structure.
Available tools:
- cpg_execute_query: Execute Cypher queries
- cpg_get_schema: Get the CPG schema
- cpg_count_nodes: Count nodes by type
- cpg_list_functions: List available Neo4j functions (filter with substring)
- cpg_list_procedures: List available Neo4j procedures (filter with substring)

Be thorough but efficient. Use simple queries first, then more complex ones if needed."""},
            {"role": "user", "content": exploration_query}
        ]

        max_iterations = 5
        for _ in range(max_iterations):
            response = self._openai.chat.completions.create(
                model=self._llm_config.model,
                temperature=0.0,
                messages=messages,
                tools=self._tools,
                tool_choice="auto"
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                return msg.content or "Exploration complete."

            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": msg.tool_calls
            })

            for tool_call in msg.tool_calls:
                args = json.loads(tool_call.function.arguments)
                result = await self._execute_tool(tool_call.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

        return "Exploration reached iteration limit."

    def get_stats(self) -> Dict[str, Any]:
        """Get current observer statistics"""
        total = len(self._memory.observations)
        empty_count = sum(1 for o in self._memory.observations if o.is_empty)
        error_count = sum(1 for o in self._memory.observations if o.had_error)

        return {
            "session_id": self._current_session_id,
            "total_observations": total,
            "total_sessions": self._memory.session_count,
            "empty_result_count": empty_count,
            "error_count": error_count,
            "empty_result_rate": f"{(empty_count/total*100) if total > 0 else 0:.1f}%",
            "error_rate": f"{(error_count/total*100) if total > 0 else 0:.1f}%",
            "unique_patterns": len(self._memory.query_patterns),
            "identified_issues": len(self._memory.identified_issues),
            "last_analysis": self._memory.last_analysis_timestamp,
            "memory_file": str(self._memory_file)
        }

    def print_report(self, report: Optional[ObserverReport] = None):
        """Print a human-readable report"""
        report = report or self._memory.last_report
        if not report:
            print("No report available. Run analyze_and_report() first.")
            return

        print(f"\n{'='*70}")
        print("CPG OBSERVER REPORT")
        print(f"{'='*70}")
        print(f"Report ID: {report.report_id}")
        print(f"Generated: {report.generated_at}")
        print(f"\n--- STATISTICS ---")
        print(f"Total Observations: {report.total_observations}")
        print(f"Total Sessions: {report.total_sessions}")
        print(f"Empty Result Rate: {report.empty_result_rate:.1f}%")
        print(f"Error Rate: {report.error_rate:.1f}%")

        print(f"\n--- IDENTIFIED ISSUES ({len(report.identified_issues)}) ---")
        for issue in report.identified_issues:
            print(f"\n[{issue.severity.upper()}] {issue.issue_type}")
            print(f"  Description: {issue.description}")
            if issue.suggested_fix:
                print(f"  Suggested Fix: {issue.suggested_fix}")
            if issue.related_nodes:
                print(f"  Related Nodes: {', '.join(issue.related_nodes)}")

        print(f"\n--- IMPROVEMENT SUGGESTIONS ---")
        for i, suggestion in enumerate(report.improvement_suggestions, 1):
            print(f"{i}. {suggestion}")

        print(f"\n--- SUMMARY ---")
        print(report.summary)
        print(f"{'='*70}\n")


__all__ = ['CPGObserverAgent']

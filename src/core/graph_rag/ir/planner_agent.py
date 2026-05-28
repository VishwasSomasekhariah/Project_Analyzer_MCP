"""
IR Planner Agent - LLM-based QueryIR generation from natural language.

This agent translates natural language queries into structured QueryIR,
which can then be validated and compiled to Cypher without LLM hallucinations.

Architecture:
    User Query → [DynamicSchemaManager] → Schema Context
                                        ↓
    User Query + Schema Context → [IRPlannerAgent] → QueryIR
                                                   ↓
    QueryIR → [IRValidator] → [CypherCompiler] → Cypher

Key Benefits:
- Uses DynamicSchemaManager for schema context (not hardcoded)
- LLM only handles understanding, not Cypher syntax
- Schema-aware generation with full context
- Self-correction loop with validation feedback
- Deterministic Cypher output after IR is created

Security Considerations:
- All LLM output is validated before use
- Schema information is obtained from trusted source
- No direct Cypher generation by LLM
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from openai import OpenAI
from pydantic import ValidationError as PydanticValidationError

from src.core.graph_rag.agents.base_agent import BaseAgent
from src.core.graph_rag.core.config import LLMConfig, SystemConfig
from src.core.graph_rag.core.enums import AgentRole

from .models import (
    QueryIR,
    QueryIntent,
    TargetEntity,
    TraversalStep,
    TraversalPath,
    Projection,
    FilterCondition,
    FilterOperator,
    AggregationType,
    RelationshipDirection,
    OrderSpec,
    SortOrder,
    OutputFormat,
    OutputFormatType,
    ValidationResult,
)
from .context import SchemaInfo, IRContext
from .validators import IRValidator, IntentRuleEngine
from .compiler import CypherCompiler

if TYPE_CHECKING:
    from src.core.graph_rag.schema import DynamicSchemaManager


logger = logging.getLogger(__name__)


@dataclass
class IRPlanningResult:
    """Result of IR planning operation."""
    success: bool
    ir: Optional[QueryIR] = None
    cypher: Optional[str] = None
    validation_result: Optional[ValidationResult] = None
    error_message: Optional[str] = None
    attempts: int = 0
    raw_llm_responses: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "ir": self.ir.model_dump() if self.ir else None,
            "cypher": self.cypher,
            "validation_errors": [
                e.model_dump() for e in self.validation_result.errors
            ] if self.validation_result else [],
            "error_message": self.error_message,
            "attempts": self.attempts,
        }


class IRPlannerAgent(BaseAgent):
    """
    LLM-based agent that generates QueryIR from natural language queries.

    This agent is responsible for understanding user intent and translating
    it into a structured intermediate representation that can be deterministically
    compiled to Cypher.

    Features:
    - Uses DynamicSchemaManager for context-relevant schema
    - Self-correction with validation feedback
    - Configurable retry attempts
    - Full token tracking

    Usage:
        planner = IRPlannerAgent(
            openai_client=client,
            llm_config=config,
            config=sys_config,
            schema_manager=dynamic_schema_manager
        )
        result = await planner.execute(
            query="Find functions with cyclomatic complexity > 5",
            project_name="HelloWorldApp"
        )

        if result.success:
            cypher = result.cypher
    """

    MAX_RETRIES = 3

    def __init__(
        self,
        openai_client: OpenAI,
        llm_config: LLMConfig,
        config: SystemConfig,
        schema_manager: 'DynamicSchemaManager',
        tool_manager: Optional[Any] = None,
        intent_rules: Optional[IntentRuleEngine] = None,
        strict_validation: bool = True,
        agent_id: Optional[str] = None,
        use_tool_exploration: bool = True
    ):
        """
        Initialize the IR Planner Agent.

        Args:
            openai_client: OpenAI client instance
            llm_config: LLM configuration
            config: System configuration
            schema_manager: DynamicSchemaManager for schema queries
            tool_manager: Optional ToolManager for tool-driven exploration
            intent_rules: Optional intent rule engine for Layer 3 validation
            strict_validation: If True, unknown properties are errors
            agent_id: Optional unique identifier
            use_tool_exploration: If True, use tools to discover paths before IR generation
        """
        super().__init__(
            openai_client=openai_client,
            llm_config=llm_config,
            role=AgentRole.IR_PLANNER,
            config=config,
            agent_id=agent_id
        )

        self._schema_manager = schema_manager
        self._tool_manager = tool_manager
        self._use_tool_exploration = use_tool_exploration and tool_manager is not None

        # Build SchemaInfo from the schema manager
        self._schema_info = SchemaInfo.from_schema_manager(schema_manager)

        # Initialize intent rules with schema introspection
        self._intent_rules = intent_rules or IntentRuleEngine(self._schema_info)

        # Initialize validator with schema
        self._validator = IRValidator(
            schema=self._schema_info,
            intent_rules=self._intent_rules,
            strict_mode=strict_validation
        )

        self._compiler = CypherCompiler()

    async def execute(
        self,
        query: str,
        project_name: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> IRPlanningResult:
        """
        Generate and validate QueryIR from natural language query.

        Args:
            query: Natural language query to process
            project_name: Optional project name for filtering
            additional_context: Optional additional context for the LLM

        Returns:
            IRPlanningResult with success status, IR, and compiled Cypher
        """
        raw_responses: List[Dict[str, Any]] = []
        last_validation_result: Optional[ValidationResult] = None
        last_error: Optional[str] = None

        # Phase 1: Tool-driven exploration (if enabled)
        discovered_paths = {}
        if self._use_tool_exploration:
            self._logger.info("Starting tool-driven schema exploration...")
            discovered_paths = await self._explore_schema_with_tools(query, project_name)
            actual_paths = discovered_paths.get('paths', {})
            self._logger.info(f"Schema exploration complete. Discovered {len(actual_paths)} path(s)")
            for path_key, path_info in actual_paths.items():
                self._logger.info(f"  Discovered path: {path_key} (depth: {path_info.get('depth', '?')})")

        # Get schema context using DynamicSchemaManager (minimal if we did tool exploration)
        schema_context = await self._get_schema_context(query)

        # Add discovered paths to context
        if discovered_paths:
            schema_context['discovered_paths'] = discovered_paths

        for attempt in range(1, self.MAX_RETRIES + 1):
            self._logger.info(f"IR planning attempt {attempt}/{self.MAX_RETRIES}")

            try:
                # Generate IR from LLM
                ir_dict, raw_response = await self._generate_ir(
                    query=query,
                    project_name=project_name,
                    schema_context=schema_context,
                    additional_context=additional_context,
                    previous_errors=last_validation_result.errors if last_validation_result else None
                )
                raw_responses.append(raw_response)

                # Parse into Pydantic model
                ir = self._parse_ir_response(ir_dict)

                # Validate IR
                validation_result = self._validator.validate(ir)
                last_validation_result = validation_result

                if validation_result.valid:
                    # Success! Compile to Cypher
                    cypher = self._compiler.compile(ir)

                    self._logger.info(
                        f"IR planning succeeded on attempt {attempt}. "
                        f"Generated {len(ir.projections)} projections, "
                        f"{len(ir.filters)} filters"
                    )

                    return IRPlanningResult(
                        success=True,
                        ir=ir,
                        cypher=cypher,
                        validation_result=validation_result,
                        attempts=attempt,
                        raw_llm_responses=raw_responses
                    )
                else:
                    # Validation failed - will retry with error feedback
                    error_summary = "; ".join(e.message for e in validation_result.errors[:3])
                    self._logger.warning(
                        f"IR validation failed on attempt {attempt}: {error_summary}"
                    )
                    last_error = error_summary

            except PydanticValidationError as e:
                error_msg = f"IR structure error: {str(e)}"
                self._logger.warning(f"Pydantic validation error on attempt {attempt}: {error_msg}")
                last_error = error_msg

            except json.JSONDecodeError as e:
                error_msg = f"JSON parse error: {str(e)}"
                self._logger.warning(f"JSON decode error on attempt {attempt}: {error_msg}")
                last_error = error_msg

            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                self._logger.error(f"Error on attempt {attempt}: {error_msg}", exc_info=True)
                last_error = error_msg

        # All retries exhausted
        self._logger.error(f"IR planning failed after {self.MAX_RETRIES} attempts")
        return IRPlanningResult(
            success=False,
            validation_result=last_validation_result,
            error_message=last_error,
            attempts=self.MAX_RETRIES,
            raw_llm_responses=raw_responses
        )

    async def _explore_schema_with_tools(
        self,
        query: str,
        project_name: Optional[str]
    ) -> Dict[str, Any]:
        """
        Use tool calling to discover correct paths in the CPG.

        This method lets the LLM actively explore the schema by:
        1. Calling schema tools to discover relationships
        2. Executing Cypher queries to verify actual paths
        3. Building a map of discovered traversal paths

        Args:
            query: Natural language query to analyze
            project_name: Optional project name for filtering

        Returns:
            Dictionary with discovered path information
        """
        MAX_TOOL_CALLS = 10
        discovered_info = {
            'paths': {},
            'node_types': [],
            'tool_calls_made': []
        }

        # Build exploration prompt
        exploration_prompt = f"""You are exploring the CPG schema to understand how to answer this query:

Query: "{query}"
{f'Project: {project_name}' if project_name else ''}

Your task is to discover the ACTUAL structure of the CPG by querying the database.

## Phase 1: Discover Traversal Paths
Use neo4j_execute_query to find how nodes are connected:
   MATCH path = (p:Project)-[:CONTAINS*1..5]->(target)
   WHERE p.name = '{project_name or "HelloWorldApp"}'
   WITH path, [n in nodes(path) | labels(n)[0]] as node_labels
   RETURN DISTINCT node_labels, length(path) as depth
   ORDER BY depth
   LIMIT 10

## Phase 2: Check Available Properties (CRITICAL for metrics)
If the query asks for a metric or property (like "complexity", "dependencies", "size"), check if it exists:
   MATCH (n:Function) // or whatever node type
   WITH n LIMIT 1
   RETURN keys(n) as available_properties

## Phase 3: Explore Child Relationships (if metric not found as property)
If a metric doesn't exist as a stored property, explore what child nodes exist:
   MATCH (fn:Function)-[r]->(child)
   RETURN DISTINCT labels(child)[0] as child_type, type(r) as rel_type, count(*) as count

Then check what properties those children have:
   MATCH (child:Statement) // or other child type
   WITH child LIMIT 1
   RETURN keys(child) as properties

And check distinct values if relevant:
   MATCH (s:Statement)
   RETURN DISTINCT s.statement_type as type, count(*) as count

## Key Insight
Some metrics like "cyclomatic complexity" may NOT exist as stored properties.
You may need to COUNT child nodes or aggregate relationships to compute them.
Explore thoroughly before concluding what data is available.

Call neo4j_execute_query tools NOW to explore the schema structure."""

        messages = [
            {"role": "system", "content": """You are a schema explorer. Use tools to discover actual data structures in the CPG database.
Do not assume - verify by querying. When you've finished exploring, provide a SUMMARY of what you discovered including:
- Traversal paths (e.g., Project->File->Type)
- Available properties on relevant nodes
- Child relationships (e.g., Function CONTAINS Statement)
- Any relevant property values (e.g., statement_type values)
This summary will be used to plan the query."""},
            {"role": "user", "content": exploration_prompt}
        ]

        # Get tools from ToolManager
        tools = self._tool_manager.tools if self._tool_manager else []

        for iteration in range(MAX_TOOL_CALLS):
            try:
                response = self._openai.chat.completions.create(
                    model=self._llm_config.model,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None
                )

                message = response.choices[0].message

                # Check if we have tool calls
                if message.tool_calls:
                    messages.append(message)

                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            arguments = {}

                        self._logger.info(f"[Tool exploration] Calling: {tool_name}")
                        self._logger.info(f"[Tool exploration] Args: {arguments}")
                        discovered_info['tool_calls_made'].append({
                            'tool': tool_name,
                            'arguments': arguments
                        })

                        # Execute tool
                        try:
                            result = await self._tool_manager.execute_tool(tool_name, arguments)
                            self._logger.info(f"[Tool exploration] Result (first 500 chars): {result[:500]}")

                            # Parse path discovery results
                            if tool_name == 'neo4j_execute_query':
                                self._parse_path_discovery_result(result, discovered_info)
                                self._logger.info(f"[Tool exploration] Paths after parsing: {list(discovered_info['paths'].keys())}")

                        except Exception as e:
                            result = json.dumps({"error": str(e)})
                            self._logger.warning(f"Tool execution error: {e}")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                else:
                    # No more tool calls - LLM is done exploring
                    if message.content:
                        self._logger.info(f"Exploration complete. Summary captured.")
                        # Capture the LLM's exploration summary for use in IR planning
                        discovered_info['exploration_summary'] = message.content
                    break

            except Exception as e:
                self._logger.error(f"Error during schema exploration: {e}")
                break

        return discovered_info

    def _parse_path_discovery_result(self, result: str, discovered_info: Dict[str, Any]):
        """Parse path discovery Cypher results into structured path info."""
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                # Support both 'results' (neo4j MCP format) and 'data' keys
                rows = data.get('results') or data.get('data') or []
                for row in rows:
                    if 'node_labels' in row:
                        labels = row['node_labels']
                        depth = row.get('depth', len(labels) - 1)
                        path_key = '->'.join(labels)
                        if path_key not in discovered_info['paths']:
                            discovered_info['paths'][path_key] = {
                                'labels': labels,
                                'depth': depth,
                                'relationship': 'CONTAINS'  # Most common
                            }
                        # Track node types
                        for label in labels:
                            if label not in discovered_info['node_types']:
                                discovered_info['node_types'].append(label)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self._logger.debug(f"Could not parse path result: {e}")

    async def _get_schema_context(self, query: str) -> Dict[str, Any]:
        """
        Get schema context using DynamicSchemaManager.

        Uses the schema manager's get_context_for_query method which:
        1. Extracts types from the query
        2. Gets context-relevant schema
        3. Discovers paths between nodes

        Args:
            query: Natural language query

        Returns:
            Schema context dictionary with extracted types, schema, and paths
        """
        try:
            # Use DynamicSchemaManager's one-stop method
            context = await self._schema_manager.get_context_for_query(
                query_text=query,
                format='text',
                include_paths=True
            )

            self._logger.debug(
                f"Schema context extracted: {len(context.get('extracted_types', {}).get('node_types', []))} node types, "
                f"cache stats: {context.get('cache_stats', {})}"
            )

            return context

        except Exception as e:
            self._logger.warning(f"Failed to get schema context: {e}")
            return {
                'extracted_types': {'node_types': [], 'relationship_types': []},
                'schema_context': '',
                'paths_context': '',
                'cache_stats': {}
            }

    async def _generate_ir(
        self,
        query: str,
        project_name: Optional[str],
        schema_context: Dict[str, Any],
        additional_context: Optional[Dict[str, Any]],
        previous_errors: Optional[List[Any]]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Generate IR dictionary from LLM using structured output.

        Returns:
            Tuple of (IR dictionary, raw response for logging)
        """
        # Build the prompt with schema context from DynamicSchemaManager
        system_prompt = self._build_system_prompt(schema_context)
        user_prompt = self._build_user_prompt(
            query=query,
            project_name=project_name,
            additional_context=additional_context,
            previous_errors=previous_errors
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Use structured output format
        response = self._create_chat_completion(
            messages=messages,
            response_format=self._get_structured_response_format()
        )

        # Parse response
        content = response.choices[0].message.content
        ir_dict = json.loads(content)

        return ir_dict, {"messages": messages, "response": content}

    def _build_system_prompt(self, schema_context: Dict[str, Any]) -> str:
        """Build the system prompt with schema context from DynamicSchemaManager."""

        # Get schema text from the context
        schema_text = schema_context.get('schema_context', '')
        paths_text = schema_context.get('paths_context', '')
        extracted_types = schema_context.get('extracted_types', {})

        # Check for discovered paths from tool exploration (takes priority)
        discovered_paths = schema_context.get('discovered_paths', {})
        if discovered_paths and discovered_paths.get('paths'):
            # Build verified paths section from tool discovery
            paths_text = "## VERIFIED PATHS (from database query)\n\n"
            paths_text += "These paths were discovered by querying the actual database:\n\n"
            for path_key, path_info in discovered_paths['paths'].items():
                labels = path_info.get('labels', [])
                depth = path_info.get('depth', len(labels) - 1)
                paths_text += f"  {path_key} (depth: {depth})\n"
                # Build explicit traversal steps
                if len(labels) > 1:
                    paths_text += "  Traversal steps:\n"
                    for i in range(len(labels) - 1):
                        paths_text += f"    {i+1}. ({labels[i]})-[:CONTAINS]->({labels[i+1]})\n"
                paths_text += "\n"
            paths_text += "**YOU MUST use these exact paths for your traversal steps.**\n"

        # Include exploration summary if available (contains properties, child nodes, etc.)
        exploration_summary = ""
        if discovered_paths and discovered_paths.get('exploration_summary'):
            exploration_summary = f"""
## SCHEMA EXPLORATION FINDINGS

The following was discovered by querying the actual database structure:

{discovered_paths['exploration_summary']}

**Use these findings to determine how to answer the query - especially if metrics need to be computed from child nodes.**
"""

        return f"""You are an IR (Intermediate Representation) planning agent for a Code Property Graph (CPG) query system.

Your task is to translate natural language queries into a structured QueryIR format.
The IR will be validated and compiled to Cypher - you do NOT generate Cypher directly.

## Schema Context (from DynamicSchemaManager)

{schema_text}

{paths_text}
{exploration_summary}
## Extracted Types from Query
Node Types: {', '.join(extracted_types.get('node_types', [])) or 'None detected'}
Relationship Types: {', '.join(extracted_types.get('relationship_types', [])) or 'None detected'}

## QueryIR Structure

Generate a JSON object with these fields:

1. **intent** (required): Query intent type
   - "find": Retrieve entities matching criteria
   - "count": Count entities
   - "aggregate": Compute aggregations (sum, avg, etc.)
   - "path": Find paths between entities
   - "compare": Compare entities/metrics

2. **intent_subtype** (optional): More specific intent
   - For find: "by_name", "by_property", "by_relationship"
   - For aggregate: "cyclomatic_complexity", "dependency_count"

3. **targets** (required): Array of target entities
   - node_label: The label to match (MUST be from schema)
   - alias: A short alias for references (e.g., "fn", "cls")

4. **traversal** (optional): Path traversal specification
   - steps: Array of traversal steps
     - from_alias: Starting alias
     - relationship: Relationship type (MUST be from schema)
     - to_label: Target node label (MUST be from schema)
     - to_alias: Alias for traversed node
     - direction: "outgoing", "incoming", or "both"

5. **filters** (optional): Array of filter conditions
   - source_alias: Alias to filter on
   - property: Property name (MUST exist on node type per schema)
   - operator: "eq", "neq", "gt", "gte", "lt", "lte", "contains", "starts_with", "in", etc.
   - value: Filter value

6. **projections** (required): What to return
   - source_alias: Alias to project from
   - property: Property to return (null for entire node, MUST exist on node type)
   - output_name: Name in results
   - aggregation: null, "count", "sum", "avg", "min", "max", "collect"
   - distinct: true/false

7. **ordering** (optional): Sort specification
   - field: Output field name to sort by
   - direction: "asc" or "desc"

8. **limit** (optional): Maximum results (default 100)

## CRITICAL: Use Paths Context for Traversals

**You MUST consult the "Paths Context" section above to determine valid traversal paths.**

The paths context shows exactly how nodes are connected in the actual CPG database.
For example, if paths_context shows:
  `Project → Function: CONTAINS→CONTAINS→CONTAINS (depth 3)`
This means Project connects to Function through 3 CONTAINS hops (e.g., Project→File→Namespace→Function).

DO NOT assume direct relationships exist between nodes.
Always follow the exact path chains shown in paths_context.
Each relationship in the chain (e.g., CONTAINS→CONTAINS) represents one traversal step.

## Computing Derived Metrics

If a metric is NOT available as a stored property, you may be able to COMPUTE it:
1. Check the Schema Exploration Findings for available child nodes and properties
2. Use "aggregate" intent with "count" aggregation on child nodes
3. Filter child nodes by relevant property values if needed
4. Group results by parent node alias

Example pattern: To compute a metric from child nodes:
- Traverse to child nodes (e.g., Function → Statement)
- Apply filters on child properties (e.g., statement_type)
- Use count aggregation
- Include parent identifier in projections

## Important Rules

1. ONLY use node labels that exist in the schema context above
2. ONLY use relationship types that exist in the schema context above
3. ONLY use properties that exist on the respective node types
4. **ALWAYS derive traversal steps from paths_context - never assume direct connections**
5. Use meaningful aliases (e.g., "fn" for Function, "cls" for Class, "ns" for Namespace)
6. For project-scoped queries, start from Project and filter on Project.name
7. Use "outgoing" direction for CONTAINS relationships

## IR Format Template

```json
{{
  "intent": "<intent_type>",
  "targets": [
    {{"node_label": "<StartLabel>", "alias": "<alias>"}}
  ],
  "traversal": {{
    "steps": [
      // Build steps by following the path chain from paths_context
      // One step per relationship in the chain
    ]
  }},
  "filters": [
    {{"source_alias": "<alias>", "property": "<prop>", "operator": "<op>", "value": "<val>"}}
  ],
  "projections": [
    {{"source_alias": "<alias>", "property": "<prop>", "output_name": "<name>"}}
  ],
  "limit": 100
}}
```
"""

    def _build_user_prompt(
        self,
        query: str,
        project_name: Optional[str],
        additional_context: Optional[Dict[str, Any]],
        previous_errors: Optional[List[Any]]
    ) -> str:
        """Build the user prompt with query and context."""
        parts = [f"Generate QueryIR for this query:\n\n\"{query}\""]

        if project_name:
            parts.append(f"\nProject context: {project_name}")
            parts.append("(Include a filter on Project.name if querying within this project)")

        if additional_context:
            parts.append(f"\nAdditional context: {json.dumps(additional_context)}")

        if previous_errors:
            error_feedback = []
            for err in previous_errors[:5]:  # Limit error feedback
                if hasattr(err, 'message'):
                    error_feedback.append(f"- {err.message}")
                    if hasattr(err, 'suggestion') and err.suggestion:
                        error_feedback.append(f"  Suggestion: {err.suggestion}")

            if error_feedback:
                parts.append("\n## Previous Attempt Failed with Errors:")
                parts.extend(error_feedback)
                parts.append("\nPlease fix these issues in your response.")

        return "\n".join(parts)

    def _get_structured_response_format(self) -> Dict[str, Any]:
        """Get the JSON schema for structured output."""
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "query_ir",
                "strict": False,
                "schema": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "enum": ["find", "count", "aggregate", "traverse", "compare", "list", "existence"],
                            "description": "Query intent type"
                        },
                        "intent_subtype": {
                            "type": ["string", "null"],
                            "description": "More specific intent category"
                        },
                        "targets": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "node_label": {"type": "string"},
                                    "alias": {"type": "string"}
                                },
                                "required": ["node_label", "alias"],
                                "additionalProperties": False
                            },
                            "minItems": 1,
                            "description": "Target entities to match"
                        },
                        "traversal": {
                            "type": ["object", "null"],
                            "properties": {
                                "steps": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "from_alias": {"type": "string"},
                                            "relationship": {"type": "string"},
                                            "to_label": {"type": "string"},
                                            "to_alias": {"type": "string"},
                                            "direction": {
                                                "type": "string",
                                                "enum": ["outgoing", "incoming", "both"]
                                            },
                                            "relationship_alias": {"type": ["string", "null"]}
                                        },
                                        "required": ["from_alias", "relationship", "to_label", "to_alias", "direction", "relationship_alias"],
                                        "additionalProperties": False
                                    }
                                }
                            },
                            "required": ["steps"],
                            "additionalProperties": False
                        },
                        "filters": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source_alias": {"type": "string"},
                                    "property": {"type": "string"},
                                    "operator": {
                                        "type": "string",
                                        "enum": ["eq", "neq", "gt", "gte", "lt", "lte",
                                                "contains", "starts_with", "ends_with",
                                                "in", "not_in", "is_null", "is_not_null", "regex"]
                                    },
                                    "value": {},
                                    "case_insensitive": {"type": "boolean"}
                                },
                                "required": ["source_alias", "property", "operator", "value", "case_insensitive"],
                                "additionalProperties": False
                            }
                        },
                        "projections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "source_alias": {"type": "string"},
                                    "property": {"type": ["string", "null"]},
                                    "output_name": {"type": "string"},
                                    "aggregation": {
                                        "type": ["string", "null"],
                                        "enum": [None, "count", "count_distinct", "sum", "avg", "min", "max", "collect"]
                                    },
                                    "distinct": {"type": "boolean"}
                                },
                                "required": ["source_alias", "output_name", "property", "aggregation", "distinct"],
                                "additionalProperties": False
                            },
                            "minItems": 1
                        },
                        "ordering": {
                            "type": ["object", "null"],
                            "properties": {
                                "field": {"type": "string"},
                                "direction": {
                                    "type": "string",
                                    "enum": ["asc", "desc"]
                                }
                            },
                            "required": ["field", "direction"],
                            "additionalProperties": False
                        },
                        "limit": {
                            "type": ["integer", "null"],
                            "minimum": 1,
                            "maximum": 10000
                        },
                        "skip": {
                            "type": ["integer", "null"],
                            "minimum": 0
                        }
                    },
                    "required": ["intent", "intent_subtype", "targets", "traversal", "filters", "projections", "ordering", "limit", "skip"],
                    "additionalProperties": False
                }
            }
        }

    def _parse_ir_response(self, ir_dict: Dict[str, Any]) -> QueryIR:
        """
        Parse LLM response dictionary into QueryIR model.

        Handles mapping from JSON structure to Pydantic models,
        including enum conversions.
        """
        # Map intent string to enum
        intent_map = {
            "find": QueryIntent.FIND,
            "count": QueryIntent.COUNT,
            "aggregate": QueryIntent.AGGREGATE,
            "traverse": QueryIntent.TRAVERSE,
            "compare": QueryIntent.COMPARE,
            "list": QueryIntent.LIST,
            "existence": QueryIntent.EXISTENCE,
        }
        intent = intent_map.get(ir_dict.get("intent", "find"), QueryIntent.FIND)

        # Parse targets
        targets = [
            TargetEntity(
                node_label=t["node_label"],
                alias=t["alias"]
            )
            for t in ir_dict.get("targets", [])
        ]

        # Parse traversal
        traversal = None
        if ir_dict.get("traversal") and ir_dict["traversal"].get("steps"):
            direction_map = {
                "outgoing": RelationshipDirection.OUTGOING,
                "incoming": RelationshipDirection.INCOMING,
                "both": RelationshipDirection.BOTH,
            }
            steps = [
                TraversalStep(
                    from_alias=s["from_alias"],
                    relationship=s["relationship"],
                    to_label=s["to_label"],
                    to_alias=s["to_alias"],
                    direction=direction_map.get(s.get("direction", "outgoing"), RelationshipDirection.OUTGOING),
                    relationship_alias=s.get("relationship_alias")
                )
                for s in ir_dict["traversal"]["steps"]
            ]
            traversal = TraversalPath(steps=steps)

        # Parse filters
        operator_map = {
            "eq": FilterOperator.EQ,
            "neq": FilterOperator.NEQ,
            "gt": FilterOperator.GT,
            "gte": FilterOperator.GTE,
            "lt": FilterOperator.LT,
            "lte": FilterOperator.LTE,
            "contains": FilterOperator.CONTAINS,
            "starts_with": FilterOperator.STARTS_WITH,
            "ends_with": FilterOperator.ENDS_WITH,
            "in": FilterOperator.IN,
            "not_in": FilterOperator.NOT_IN,
            "is_null": FilterOperator.IS_NULL,
            "is_not_null": FilterOperator.IS_NOT_NULL,
            "regex": FilterOperator.REGEX,
        }
        filters = [
            FilterCondition(
                source_alias=f["source_alias"],
                property=f["property"],
                operator=operator_map.get(f.get("operator", "eq"), FilterOperator.EQ),
                value=f.get("value"),
                case_insensitive=f.get("case_insensitive", False)
            )
            for f in ir_dict.get("filters", [])
        ]

        # Parse projections
        aggregation_map = {
            None: None,
            "count": AggregationType.COUNT,
            "count_distinct": AggregationType.COUNT_DISTINCT,
            "sum": AggregationType.SUM,
            "avg": AggregationType.AVG,
            "min": AggregationType.MIN,
            "max": AggregationType.MAX,
            "collect": AggregationType.COLLECT,
        }
        projections = [
            Projection(
                source_alias=p["source_alias"],
                property=p.get("property"),
                output_name=p["output_name"],
                aggregation=aggregation_map.get(p.get("aggregation")),
                distinct=p.get("distinct", False)
            )
            for p in ir_dict.get("projections", [])
        ]

        # Parse ordering
        ordering = None
        if ir_dict.get("ordering"):
            direction_map = {
                "asc": SortOrder.ASC,
                "desc": SortOrder.DESC,
            }
            ordering = OrderSpec(
                field=ir_dict["ordering"]["field"],
                direction=direction_map.get(
                    ir_dict["ordering"].get("direction", "asc"),
                    SortOrder.ASC
                )
            )

        # Build QueryIR
        return QueryIR(
            intent=intent,
            intent_subtype=ir_dict.get("intent_subtype"),
            targets=targets,
            traversal=traversal,
            filters=filters,
            projections=projections,
            ordering=ordering,
            limit=ir_dict.get("limit"),
            skip=ir_dict.get("skip")
        )

    def refresh_schema(self) -> None:
        """
        Refresh the schema info from the schema manager.

        Call this if the schema has been updated and you want
        the planner to use the new schema.
        """
        self._schema_info = SchemaInfo.from_schema_manager(self._schema_manager)
        self._intent_rules = IntentRuleEngine(self._schema_info)
        self._validator = IRValidator(
            schema=self._schema_info,
            intent_rules=self._intent_rules,
            strict_mode=self._validator._strict_mode
        )
        self._logger.info("Schema refreshed from DynamicSchemaManager")

    def get_schema_summary(self) -> Dict[str, Any]:
        """Get a summary of the schema for debugging."""
        return {
            "node_labels": sorted(self._schema_info.node_labels),
            "relationship_types": sorted(self._schema_info.relationship_types),
            "connection_count": len(self._schema_info.valid_connections),
        }


__all__ = ['IRPlannerAgent', 'IRPlanningResult']

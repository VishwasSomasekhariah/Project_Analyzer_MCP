"""
CPG Discovery Agent - Discovers actual graph patterns using conversational APOC cache access.

This agent discovers real CPG structure through conversation with the APOC cache,
generating discovery queries dynamically using appropriate APOC procedures.

Key Principles:
1. Use APOC cache conversationally (ask for categories -> procedures -> signatures)
2. Generate discovery queries dynamically based on APOC procedures
3. Always scope by project_name (production-safe)
4. Use aggressive LIMITs (sample, don't exhaust)
5. Return actionable patterns for query generation
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

from .apoc_cache_tool import APOCCacheTool
from src.core.llm_service import LLMService, LLMModel

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class PathPattern:
    """Discovered path pattern from Project to target node."""
    pattern: str  # "Project -[:CONTAINS]-> File -[:CONTAINS]-> Function"
    relationship_types: List[str]
    hop_count: int
    example_query: str


@dataclass
class RelationshipPattern:
    """Discovered outgoing relationship pattern."""
    relationship_type: str
    target_node: str
    sample_count: int
    pattern: str  # "Function -[:CALLS]-> Function"


@dataclass
class CPGDiscoveryResult:
    """Complete discovery results for a node type."""
    node_type: str
    exists: bool
    sample_count: int
    properties: List[str]
    paths_from_project: List[PathPattern]
    outgoing_relationships: List[RelationshipPattern]
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def to_summary(self) -> str:
        """Format as plain text summary for LLM prompts (no unicode)."""
        lines = [f"[{self.node_type}]"]

        if not self.exists:
            lines.append("  Status: NOT FOUND in this project")
            lines.append(f"  Note: {self.node_type} nodes do not exist in the graph")
            return "\n".join(lines)

        lines.append(f"  Status: EXISTS ({self.sample_count} sampled)")

        if self.properties:
            props = ", ".join(self.properties)
            lines.append(f"  Properties: {props}")

        if self.paths_from_project:
            lines.append("  How to reach from Project:")
            for path in self.paths_from_project:  # ALL paths, no slicing
                lines.append(f"    - {path.pattern}")

        if self.outgoing_relationships:
            lines.append("  Outgoing relationships:")
            for rel in self.outgoing_relationships:  # ALL relationships, no slicing
                lines.append(f"    - {rel.pattern} (count: {rel.sample_count})")

        if self.notes:
            lines.append("  Notes:")
            for note in self.notes:
                lines.append(f"    - {note}")

        return "\n".join(lines)


# =============================================================================
# CPG Discovery Agent (Conversational)
# =============================================================================

class CPGDiscoveryAgent:
    """
    Discovers CPG patterns through conversational APOC cache queries.

    Uses the same conversational pattern as the validation agent:
    - Maintains conversation history
    - Asks APOC cache for relevant procedures incrementally
    - Generates discovery queries using discovered APOC procedures
    - Executes scoped, limited queries
    - Returns structured results
    """

    # Production safety limits
    SAMPLE_LIMIT = 10
    PATH_DEPTH_LIMIT = 4
    PROPERTY_SAMPLE = 5
    RELATIONSHIP_LIMIT = 20

    def __init__(
        self,
        llm_service: LLMService,
        cypher_server,
        apoc_cache_tool: Optional[APOCCacheTool] = None
    ):
        """
        Initialize CPG Discovery Agent.

        Args:
            llm_service: LLM service for conversation
            cypher_server: Cypher server for query execution
            apoc_cache_tool: APOC cache tool for metadata queries
        """
        self.llm_service = llm_service
        self.cypher_server = cypher_server
        self.cache_tool = apoc_cache_tool or APOCCacheTool()

        # Conversation history (text-based)
        self.conversation_history: List[Dict[str, str]] = []

    async def discover_patterns(
        self,
        target_entities: List[str],
        project_name: str,
        user_query: Optional[str] = None
    ) -> Dict[str, CPGDiscoveryResult]:
        """
        Discover CPG patterns for target entities through conversation.

        Args:
            target_entities: Node types to discover
            project_name: Project name for scoping
            user_query: Optional user query for context

        Returns:
            Dict mapping node_type -> CPGDiscoveryResult
        """
        logger.info(f"Discovering patterns for {target_entities} in '{project_name}'")

        # Reset conversation
        self.conversation_history = []

        # System instructions
        system_instructions = """You are a CPG discovery expert. You MUST use APOC procedures for discovery.

MANDATORY WORKFLOW:
1. FIRST ask: "Show me available categories"
2. I'll show you categories like: apoc.meta, apoc.path, apoc.nodes, etc.
3. THEN ask: "Show me procedures in apoc.meta" (or other relevant category)
4. I'll list ALL procedures in that category
5. THEN ask: "Show me the signature of apoc.meta.nodeTypeProperties" (or chosen procedure)
6. I'll show the signature
7. ONLY THEN generate queries using those APOC procedures

CRITICAL - Use APOC procedures for:
- Existence: apoc.meta.nodeTypeProperties() NOT basic MATCH
- Properties: apoc.meta.nodeTypeProperties()
- Paths: apoc.path.subgraphAll() or apoc.path.spanningTree()
- Relationships: apoc.meta.relTypeProperties()

DO NOT write basic MATCH queries. ALWAYS use APOC procedures.

Query requirements:
- Scope by project: MATCH (p:Project {name: $project_name})
- Use LIMIT 10 for samples
- Wrap in ```cypher ``` blocks

When done, say "Discovery complete"."""

        # Initial message with user query context
        context_line = f"\n\nUser Query Context: {user_query}" if user_query else ""

        initial_message = f"""I need to discover CPG patterns for these node types in project '{project_name}':
Target Entities: {', '.join(target_entities)}{context_line}

For each entity, I need to know:
1. Does it exist in this project?
2. What properties does it have?
3. How do I reach it from the Project node?
4. What relationships go out from it?

START by asking me for available APOC categories. Do NOT generate queries yet."""

        self.conversation_history.append({
            'role': 'system',
            'content': system_instructions
        })

        self.conversation_history.append({
            'role': 'user',
            'content': initial_message
        })

        # Conversation loop
        discovery_queries = await self._conversation_loop()

        if not discovery_queries:
            logger.warning("No discovery queries generated")
            return {}

        # Execute discovery queries and parse results
        results = await self._execute_and_parse(
            discovery_queries, target_entities, project_name
        )

        logger.info(f"Discovery complete for {len(results)} entities")
        return results

    async def _conversation_loop(self) -> List[Dict[str, str]]:
        """
        Conversational loop where agent queries APOC cache and generates discovery queries.

        Returns:
            List of discovery queries
        """
        max_turns = 10
        discovery_queries = []

        for turn in range(max_turns):
            logger.info(f"  Conversation turn {turn + 1}/{max_turns}")

            # Get AI response
            try:
                prompt = self._build_prompt_from_history()

                response = await self.llm_service.generate_response(
                    prompt=prompt,
                    model=LLMModel.GPT4O,
                    temperature=0.0,
                    max_tokens=4000
                )

                if response.error:
                    logger.error(f"  LLM error: {response.error}")
                    break

                ai_message = response.content

                # Add to conversation history
                self.conversation_history.append({
                    'role': 'assistant',
                    'content': ai_message
                })

                logger.info(f"  AI response: {ai_message[:500]}...")

                # Check if AI is requesting APOC cache information
                if self._is_requesting_categories(ai_message):
                    categories = self._handle_category_request()
                    self.conversation_history.append({
                        'role': 'user',
                        'content': categories
                    })
                    continue

                elif self._is_requesting_procedures(ai_message):
                    procedures = self._handle_procedure_request(ai_message)
                    self.conversation_history.append({
                        'role': 'user',
                        'content': procedures
                    })
                    continue

                elif self._is_requesting_signature(ai_message):
                    signature = self._handle_signature_request(ai_message)
                    self.conversation_history.append({
                        'role': 'user',
                        'content': signature
                    })
                    continue

                # Extract discovery queries
                queries = self._extract_queries(ai_message)
                if queries:
                    discovery_queries.extend(queries)

                    # Ask if done
                    self.conversation_history.append({
                        'role': 'user',
                        'content': "Got it. Are these all the discovery queries needed, or do you need more information?"
                    })
                    continue

                # Check if done
                if self._is_done(ai_message):
                    logger.info(f"  Conversation complete")
                    break

            except Exception as e:
                logger.error(f"  Conversation turn failed: {e}")
                break

        return discovery_queries

    def _build_prompt_from_history(self) -> str:
        """Build prompt from conversation history."""
        prompt_parts = []

        for msg in self.conversation_history:
            role = msg['role']
            content = msg['content']

            if role == 'system':
                prompt_parts.append(f"SYSTEM INSTRUCTIONS:\n{content}\n")
            elif role == 'user':
                prompt_parts.append(f"USER:\n{content}\n")
            elif role == 'assistant':
                prompt_parts.append(f"ASSISTANT:\n{content}\n")

        prompt_parts.append("ASSISTANT:")
        return "\n".join(prompt_parts)

    def _is_requesting_categories(self, message: str) -> bool:
        """Check if AI is asking for available categories."""
        keywords = ['what categories', 'available categories', 'list categories', 'show categories']
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in keywords)

    def _is_requesting_procedures(self, message: str) -> bool:
        """Check if AI is asking for procedures in a category."""
        keywords = ['procedures in', 'what procedures', 'show procedures', 'list procedures']
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in keywords)

    def _is_requesting_signature(self, message: str) -> bool:
        """Check if AI is asking for a procedure signature."""
        keywords = ['signature of', 'signature for', 'what is the signature', 'show signature']
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in keywords)

    def _is_done(self, message: str) -> bool:
        """Check if AI indicates it's done."""
        keywords = ['discovery complete', 'these are all', "that's all", 'no more', 'sufficient']
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in keywords)

    def _handle_category_request(self) -> str:
        """Handle request for available categories."""
        categories = self.cache_tool.get_category_summary()

        lines = ["Available APOC categories:"]
        for category, count in sorted(categories.items()):
            lines.append(f"  - {category}: {count} procedures")

        return "\n".join(lines)

    def _handle_procedure_request(self, message: str) -> str:
        """Handle request for procedures in a category."""
        message_lower = message.lower()

        # Find category name
        for category in self.cache_tool.get_all_category_names():
            if category.lower() in message_lower:
                procedures = self.cache_tool.get_procedures_in_category(category)

                lines = [f"Procedures in {category}:"]
                # Return ALL procedures (accuracy > cost)
                for proc_name in procedures:
                    lines.append(f"  - {proc_name}")

                lines.append(f"\nTotal: {len(procedures)} procedures in this category")
                return "\n".join(lines)

        # Category not found
        all_categories = ", ".join(self.cache_tool.get_all_category_names())
        return f"Could not identify the category. Please specify one of: {all_categories}"

    def _handle_signature_request(self, message: str) -> str:
        """Handle request for a procedure signature."""
        import re
        pattern = r'(apoc\.\w+\.\w+)'
        matches = re.findall(pattern, message)

        if matches:
            proc_name = matches[0]
            signature_info = self.cache_tool.get_procedure_signature(proc_name)

            if signature_info:
                return f"""Procedure: {signature_info['name']}
Signature: {signature_info['signature']}
Description: {signature_info['description']}
Type: {signature_info['type']}"""
            else:
                return f"Procedure {proc_name} not found in cache."

        return "Could not identify the procedure name. Please specify the full name (e.g., apoc.meta.schema)"

    def _extract_queries(self, message: str) -> List[Dict[str, str]]:
        """Extract Cypher queries from AI message."""
        queries = []

        import re
        pattern = r'```(?:cypher|sql)?\s*(.*?)```'
        matches = re.findall(pattern, message, re.DOTALL | re.IGNORECASE)

        for match in matches:
            query = match.strip()
            if query and ('MATCH' in query.upper() or 'CALL' in query.upper()):
                queries.append({
                    'query': query,
                    'purpose': 'Discovery query'
                })

        return queries

    async def _execute_and_parse(
        self,
        discovery_queries: List[Dict[str, str]],
        target_entities: List[str],
        project_name: str
    ) -> Dict[str, CPGDiscoveryResult]:
        """
        Execute discovery queries and parse into CPGDiscoveryResult objects.

        Intelligently maps query results to discovery categories:
        - Existence/count queries
        - Property discovery queries
        - Path discovery queries
        - Relationship discovery queries
        """
        logger.info(f"  Executing {len(discovery_queries)} discovery queries...")

        # Initialize results structure for each entity
        discovery_data = {}
        for entity in target_entities:
            discovery_data[entity] = {
                'exists': False,
                'sample_count': 0,
                'properties': set(),
                'paths': [],
                'relationships': [],
                'notes': []
            }

        # Execute each query and categorize results
        for i, query_info in enumerate(discovery_queries):
            query = query_info['query']
            logger.info(f"    Executing query {i+1}/{len(discovery_queries)}...")

            try:
                result = await self.cypher_server.execute_query(
                    query,
                    params={'project_name': project_name},
                    limit=self.SAMPLE_LIMIT
                )

                # Parse result based on query content
                self._parse_query_result(
                    query, result, target_entities, discovery_data
                )

            except Exception as e:
                logger.error(f"    Query {i+1} failed: {e}")
                # Add error note to relevant entities
                for entity in target_entities:
                    if entity in query.upper():
                        discovery_data[entity]['notes'].append(
                            f"Query failed: {str(e)[:100]}"
                        )

        # Convert aggregated data to CPGDiscoveryResult objects
        results = {}
        for entity in target_entities:
            data = discovery_data[entity]

            results[entity] = CPGDiscoveryResult(
                node_type=entity,
                exists=data['exists'],
                sample_count=data['sample_count'],
                properties=sorted(list(data['properties'])),
                paths_from_project=data['paths'],
                outgoing_relationships=data['relationships'],
                notes=data['notes']
            )

        return results

    def _parse_query_result(
        self,
        query: str,
        result: Dict[str, Any],
        target_entities: List[str],
        discovery_data: Dict[str, Dict]
    ) -> None:
        """
        Parse query result and update discovery_data.

        Intelligently categorizes results based on query structure and returned data.
        """
        data = result.get('data', [])
        if not data:
            return

        query_upper = query.upper()

        # Detect which entity this query is about
        relevant_entity = None
        for entity in target_entities:
            if entity.upper() in query_upper:
                relevant_entity = entity
                break

        if not relevant_entity:
            return

        entity_data = discovery_data[relevant_entity]

        # Parse based on returned columns
        first_row = data[0] if data else {}
        columns = list(first_row.keys())

        # 1. Count queries (existence check)
        if 'count' in columns:
            count = first_row.get('count', 0)
            entity_data['exists'] = count > 0
            entity_data['sample_count'] = count

        # 2. Property discovery (keys() or prop columns)
        if 'prop' in columns:
            for row in data:
                prop = row.get('prop')
                if prop:
                    entity_data['properties'].add(prop)

        # 3. Path discovery (rel_types or path patterns)
        if 'rel_types' in columns:
            for row in data:
                rel_types = row.get('rel_types', [])
                hop_count = row.get('hop_count', len(rel_types))

                if rel_types:
                    pattern = f"Project -[:{' -> :'.join(rel_types)}]-> {relevant_entity}"
                    path = PathPattern(
                        pattern=pattern,
                        relationship_types=rel_types,
                        hop_count=hop_count,
                        example_query=f"# Example path query\n{query[:200]}"
                    )
                    entity_data['paths'].append(path)

        # 4. Relationship discovery (rel_type, target_label)
        if 'rel_type' in columns and 'target_label' in columns:
            for row in data:
                rel_type = row.get('rel_type')
                target_label = row.get('target_label')
                count = row.get('count', 1)

                if rel_type and target_label:
                    pattern = f"{relevant_entity} -[:{rel_type}]-> {target_label}"
                    rel = RelationshipPattern(
                        relationship_type=rel_type,
                        target_node=target_label,
                        sample_count=count,
                        pattern=pattern
                    )
                    entity_data['relationships'].append(rel)

        # 5. Generic existence check (any data returned)
        if len(data) > 0 and not entity_data['exists']:
            entity_data['exists'] = True
            entity_data['sample_count'] = len(data)


# =============================================================================
# Convenience Function for Parallel Discovery
# =============================================================================

async def discover_cpg_patterns_parallel(
    target_entities_by_subquestion: Dict[str, List[str]],
    project_name: str,
    llm_service: LLMService,
    cypher_server
) -> Dict[str, Dict[str, CPGDiscoveryResult]]:
    """
    Discover CPG patterns for multiple sub-questions in parallel.

    Args:
        target_entities_by_subquestion: Map of sub_question_id -> target_entities
        project_name: Project name for scoping
        llm_service: LLM service for agents
        cypher_server: Single server or pool

    Returns:
        Map of sub_question_id -> (node_type -> CPGDiscoveryResult)
    """
    logger.info(f"Starting parallel CPG discovery for {len(target_entities_by_subquestion)} sub-questions...")

    is_pool = hasattr(cypher_server, 'acquire')

    if is_pool:
        logger.info("  Using server pool for parallel discovery")

        async def discover_for_subquestion(sq_id: str, entities: List[str]):
            """Discover patterns for one sub-question."""
            server = await cypher_server.acquire()
            try:
                agent = CPGDiscoveryAgent(llm_service, server)
                results = await agent.discover_patterns(entities, project_name)
                return (sq_id, results)
            finally:
                await cypher_server.release(server)

        tasks = [
            discover_for_subquestion(sq_id, entities)
            for sq_id, entities in target_entities_by_subquestion.items()
        ]

        results = await asyncio.gather(*tasks)
        return dict(results)

    else:
        logger.info("  Using single server for sequential discovery")

        results = {}
        for sq_id, entities in target_entities_by_subquestion.items():
            agent = CPGDiscoveryAgent(llm_service, cypher_server)
            discovery = await agent.discover_patterns(entities, project_name)
            results[sq_id] = discovery

        return results

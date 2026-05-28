#!/usr/bin/env python3
"""
CoT Agent with MCP Tools Test Script

This script tests a Chain-of-Thought agent that uses MCP tools directly
as OpenAI function calls. The agent can:
1. Search the codebase using fulltext search (local tool via Cypher)
2. Execute Cypher queries directly (MCP tool)
3. Execute batch Cypher queries (MCP tool)
4. Query schema using SchemaTools (local tools from DynamicSchemaManager)
"""

import asyncio
import json
import re
import time
from typing import Dict, List, Tuple
from openai import OpenAI
from mcp_use import MCPClient

# Import schema tools
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from src.core.workflow.schema_tools_langchain import create_schema_tools


class MCPCypherAdapter:
    """Adapts MCP session to the interface expected by DynamicSchemaManager"""

    def __init__(self, mcp_session):
        self.session = mcp_session

    async def execute_query(self, query: str, params: dict = None) -> dict:
        """Execute a Cypher query via MCP"""
        result = await self.session.call_tool('neo4j_execute_query', {'query': query})

        if hasattr(result, 'content') and result.content:
            import json
            raw = json.loads(result.content[0].text)
            return {
                'data': raw.get('results', raw.get('data', [])),
                'status': 'success' if not raw.get('error') else 'error',
                'error': raw.get('error')
            }
        return {'data': [], 'status': 'error', 'error': 'Empty response'}


def preprocess_fuzzy_term(term: str) -> str:
    """
    Preprocess search term for fuzzy fulltext search.

    Handles:
    - Dots: "Helper.FormatMessage" -> "Helper~ AND FormatMessage~"
    - Parentheses: "ProcessData()" -> "ProcessData~"
    - Spaces: "some func" -> "some~ AND func~"
    - Special chars: removed
    """
    # Remove parentheses and brackets
    term = re.sub(r'[(){}\[\]]', '', term)

    # Split on dots, spaces, underscores, and other delimiters
    parts = re.split(r'[.\s_\-:]+', term)

    # Filter empty parts and strip whitespace
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return ""

    # Create fuzzy search terms with AND
    fuzzy_parts = [f"{p}~" for p in parts]

    return " AND ".join(fuzzy_parts)


class MCPToolBridge:
    """Bridge MCP tools + local tools to OpenAI function calling format"""

    def __init__(self, config_path: str = "neo4j_config.json"):
        self.config_path = config_path
        self.client = None
        self.session = None
        self.tools = []
        self.tool_map = {}
        self.langchain_tools = {}  # LangChain tool instances by name
        self.schema_manager = None  # Store for schema access

    async def initialize(self):
        """Initialize MCP client, session, and schema tools"""
        # 1. Initialize MCP client
        self.client = MCPClient.from_config_file(self.config_path)

        with open(self.config_path) as f:
            config = json.load(f)
        server_name = list(config.get("mcpServers", {}).keys())[0]

        self.session = await self.client.create_session(server_name)

        # 2. Initialize DynamicSchemaManager and create LangChain tools
        print("Loading schema...")
        cypher_adapter = MCPCypherAdapter(self.session)

        # Load YAML schema
        import yaml
        yaml_schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
        with open(yaml_schema_path, 'r') as f:
            yaml_schema = yaml.safe_load(f)

        self.schema_manager = DynamicSchemaManager(
            cypher_server=cypher_adapter,
            yaml_schema=yaml_schema
        )
        await self.schema_manager.initialize_background()
        lc_tools = create_schema_tools(self.schema_manager)
        print(f"Schema loaded: {len(self.schema_manager._reconciled_schema.get('nodes', {}))} node types")
        print(f"LangChain tools created: {[t.name for t in lc_tools]}")

        # Store LangChain tools for execution
        for tool in lc_tools:
            self.langchain_tools[tool.name] = tool

        # 3. Build tool list
        self._build_tool_list()

    def _build_tool_list(self):
        """Build tool list: MCP tools + local tools"""

        # 1. Add MCP tools: neo4j_execute_query and neo4j_batch_execute_queries
        mcp_tools_to_add = ['neo4j_execute_query', 'neo4j_batch_execute_queries']

        for mcp_tool in self.session.tools:
            if mcp_tool.name in mcp_tools_to_add:
                params = mcp_tool.inputSchema.copy()
                params.pop('$defs', None)
                if 'properties' in params:
                    params['properties'] = {
                        k: v for k, v in params['properties'].items()
                        if k != 'ctx'
                    }

                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": mcp_tool.name,
                        "description": mcp_tool.description.strip() if mcp_tool.description else "",
                        "parameters": params
                    }
                }
                self.tools.append(openai_tool)
                self.tool_map[mcp_tool.name] = ('mcp', mcp_tool.name)

        # 2. Add local tool: search_codebase (uses fulltext index via Cypher)
        # COMMENTED OUT FOR TESTING SCHEMA-FIRST APPROACH
        # self.tools.append({
        #     "type": "function",
        #     "function": {
        #         "name": "search_codebase",
        #         "description": """Search the codebase for code elements by name using fulltext index.
        # Returns nodes matching the search term with their labels, names, and text content.
        # Searches across: name, text, value, body fields.
        #
        # Example: search_codebase("FormatMessage") finds Function and Statement nodes.
        # Example: search_codebase("WorkerA") finds the WorkerA function.""",
        #         "parameters": {
        #             "type": "object",
        #             "properties": {
        #                 "search_term": {
        #                     "type": "string",
        #                     "description": "The term to search for"
        #                 }
        #             },
        #             "required": ["search_term"]
        #         }
        #     }
        # })
        # self.tool_map['search_codebase'] = ('local', 'search_codebase')

        # 3. Convert LangChain tools to OpenAI format
        for name, lc_tool in self.langchain_tools.items():
            openai_tool = self._langchain_to_openai(lc_tool)
            self.tools.append(openai_tool)
            self.tool_map[name] = ('langchain', name)

    def _langchain_to_openai(self, lc_tool) -> Dict:
        """Convert a LangChain tool to OpenAI function format"""
        # Get the schema from LangChain tool
        if hasattr(lc_tool, 'args_schema') and lc_tool.args_schema:
            schema = lc_tool.args_schema.model_json_schema()
            properties = schema.get('properties', {})
            required = schema.get('required', [])
        else:
            properties = {}
            required = []

        return {
            "type": "function",
            "function": {
                "name": lc_tool.name,
                "description": lc_tool.description or "",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }

    def get_openai_tools(self) -> List[Dict]:
        """Get tools in OpenAI format"""
        return self.tools

    def get_reconciled_schema(self) -> Dict:
        """Get the reconciled schema for inclusion in system prompt"""
        if not self.schema_manager or not self.schema_manager._reconciled_schema:
            return {}
        return self.schema_manager._reconciled_schema

    async def execute_tool(self, name: str, arguments: Dict) -> str:
        """Execute a tool and return result"""
        tool_info = self.tool_map.get(name)

        if tool_info is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        tool_type, tool_name = tool_info

        try:
            if tool_type == 'mcp':
                # Execute MCP tool
                result = await self.session.call_tool(tool_name, arguments)
                if hasattr(result, 'content') and result.content:
                    return result.content[0].text
                return json.dumps({"error": "Empty MCP response"})

            elif tool_type == 'local':
                # Execute local tool
                if tool_name == 'search_codebase':
                    return await self._search_codebase(arguments.get('search_term', ''))
                else:
                    return json.dumps({"error": f"Unknown local tool: {tool_name}"})

            elif tool_type == 'langchain':
                # Execute LangChain tool
                lc_tool = self.langchain_tools.get(tool_name)
                if lc_tool:
                    result = lc_tool.invoke(arguments)
                    return json.dumps(result, indent=2)
                else:
                    return json.dumps({"error": f"LangChain tool not found: {tool_name}"})

        except Exception as e:
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})

    async def _search_codebase(self, search_term: str) -> str:
        """Execute fulltext search using FuzzySearchIdx via Cypher"""
        if not search_term:
            return json.dumps({"error": "Empty search term"})

        # Preprocess for fuzzy search (handles dots, spaces, special chars)
        processed = preprocess_fuzzy_term(search_term)
        if not processed:
            return json.dumps({
                "search_term": search_term,
                "processed_query": "",
                "found": False,
                "result_count": 0,
                "results": [],
                "error": "Could not parse search term"
            })

        # Same query as in schema_tools_langchain.py
        query = f"""
        CALL db.index.fulltext.queryNodes('FuzzySearchIdx', '{processed}')
        YIELD node, score
        WITH node, score,
             [p IN ['name','text','value','body']
              WHERE node[p] IS NOT NULL
              | p + ': ' + substring(toString(node[p]), 0, 150)
             ] AS presentProps
        WHERE score >= 0.5
        RETURN
          labels(node) AS labels,
          presentProps,
          id(node) AS id,
          score
        ORDER BY score DESC
        LIMIT 15
        """

        # Execute via MCP
        try:
            result = await self.session.call_tool('neo4j_execute_query', {'query': query})

            if hasattr(result, 'content') and result.content:
                raw = json.loads(result.content[0].text)
                raw_results = raw.get('results', raw.get('data', []))

                # Parse results like in schema_tools_langchain.py
                parsed_results = []
                for r in raw_results:
                    props = r.get('presentProps', [])
                    # Extract name from presentProps
                    name = None
                    for p in props:
                        if p.startswith('name:'):
                            name = p.split(':', 1)[1].strip()
                            break

                    parsed_results.append({
                        "labels": r.get('labels', []),
                        "name": name,
                        "properties": props,
                        "id": r.get('id'),
                        "score": round(r.get('score', 0), 2)
                    })

                return json.dumps({
                    "search_term": search_term,
                    "processed_query": processed,
                    "found": len(parsed_results) > 0,
                    "result_count": len(parsed_results),
                    "results": parsed_results
                }, indent=2)

            return json.dumps({
                "search_term": search_term,
                "processed_query": processed,
                "found": False,
                "result_count": 0,
                "results": []
            })

        except Exception as e:
            return json.dumps({
                "search_term": search_term,
                "processed_query": processed,
                "found": False,
                "result_count": 0,
                "results": [],
                "error": str(e)
            })


class CoTAgent:
    """Chain-of-Thought Agent with MCP tools"""

    def __init__(self, mcp_bridge: MCPToolBridge, model: str = "gpt-4o"):
        self.mcp = mcp_bridge
        self.model = model
        self.openai = OpenAI()
        self.max_iterations = 25

    async def run(self, question: str, system_prompt: str = None) -> Tuple[str, float, int]:
        """
        Run the agent on a question.

        Returns:
            Tuple of (answer, elapsed_time, iterations)
        """
        if system_prompt is None:
            system_prompt = self._default_system_prompt()

        # Append reconciled schema to system prompt
        # schema = self.mcp.get_reconciled_schema()
        # if schema:
        #     schema_json = json.dumps(schema, indent=2)
        #     system_prompt += f"\n\n## CPG Schema Reference\n\n```json\n{schema_json}\n```"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ]

        tools = self.mcp.get_openai_tools()

        print(f"\n{'='*70}")
        print(f"Question: {question}")
        print(f"{'='*70}")

        start = time.time()

        for iteration in range(self.max_iterations):
            print(f"\n🔄 Iteration {iteration + 1}")

            response = self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )

            msg = response.choices[0].message
            messages.append(msg)

            # Check if agent is done
            if msg.content and not msg.tool_calls:
                elapsed = time.time() - start
                print(f"\n✅ FINAL ANSWER ({elapsed:.2f}s):")
                print(msg.content)
                return (msg.content, elapsed, iteration + 1)

            # Execute tool calls
            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    fname = tool_call.function.name
                    fargs = json.loads(tool_call.function.arguments)

                    # Display tool call
                    args_preview = json.dumps(fargs)
                    if len(args_preview) > 80:
                        args_preview = args_preview[:200] + "..."
                    print(f"   🔧 {fname}({args_preview})")

                    # Execute
                    result_text = await self.mcp.execute_tool(fname, fargs)

                    # Display results summary
                    self._display_result(result_text)

                    # Add to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_text
                    })

        elapsed = time.time() - start
        return ("Max iterations reached", elapsed, self.max_iterations)

    def _display_result(self, result_text: str):
        """Display a summary of tool results"""
        try:
            data = json.loads(result_text)
            if isinstance(data, dict):
                if 'results' in data:
                    results = data['results']
                    print(f"   📊 {len(results)} results")
                    for r in results:
                        print(f"      → {r}")
                elif 'batch_results' in data:
                    print(f"   📊 {len(data['batch_results'])} batch results")
                elif 'success' in data:
                    print(f"   📊 success={data['success']}, count={data.get('count', 'N/A')}")
                else:
                    print(f"   📊 {data}")
            else:
                print(f"   📊 {data}")
        except json.JSONDecodeError:
            print(f"   📊 {result_text}")

    async def run_parallel_subqueries(self, original_question: str, subqueries: List[str]) -> Tuple[str, float, int]:
        """
        Run multiple sub-queries in parallel and synthesize results.

        Args:
            original_question: The original user question
            subqueries: List of sub-queries to run in parallel

        Returns:
            Tuple of (final_answer, total_time, total_iterations)
        """
        print(f"\n{'='*70}")
        print(f"PARALLEL EXECUTION: {len(subqueries)} sub-queries")
        print(f"Original Question: {original_question}")
        print(f"{'='*70}")

        start = time.time()

        # Create focused prompt for sub-queries
        subquery_prompt = """You are a focused code analysis agent. Answer the specific question using the Neo4j CPG.
Use schema tools to validate before querying. Be concise - return only the relevant findings.
If you find the answer, report it with evidence (node IDs, property values, code snippets).
If not found, explain what you tried and what you discovered."""

        # Run all sub-queries in parallel
        async def run_subquery(idx: int, sq: str):
            print(f"\n🔀 Starting Sub-query {idx + 1}: {sq[:60]}...")
            answer, elapsed, iterations = await self.run(sq, system_prompt=subquery_prompt)
            return {
                'index': idx,
                'subquery': sq,
                'answer': answer,
                'elapsed': elapsed,
                'iterations': iterations
            }

        # Execute in parallel
        tasks = [run_subquery(i, sq) for i, sq in enumerate(subqueries)]
        results = await asyncio.gather(*tasks)

        parallel_time = time.time() - start
        total_iterations = sum(r['iterations'] for r in results)

        # Display results summary
        print(f"\n{'='*70}")
        print("SUB-QUERY RESULTS")
        print(f"{'='*70}")
        for r in results:
            print(f"\n📋 Sub-query {r['index'] + 1}: {r['subquery'][:50]}...")
            print(f"   Time: {r['elapsed']:.2f}s, Iterations: {r['iterations']}")
            print(f"   Finding: {r['answer'][:200]}...")

        # Synthesize final answer
        print(f"\n{'='*70}")
        print("SYNTHESIZING FINAL ANSWER")
        print(f"{'='*70}")

        synthesis_prompt = f"""You are synthesizing findings from parallel sub-queries to answer the original question.

Original Question: {original_question}

Sub-query Findings:
"""
        for r in results:
            synthesis_prompt += f"\n--- Sub-query {r['index'] + 1}: {r['subquery']} ---\n{r['answer']}\n"

        synthesis_prompt += """
Based on these findings, provide a clear, concise answer to the original question.
Cite specific evidence (node IDs, property values, code) from the sub-query results."""

        # Use LLM to synthesize
        response = self.openai.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You synthesize findings from multiple queries into a coherent answer."},
                {"role": "user", "content": synthesis_prompt}
            ]
        )

        final_answer = response.choices[0].message.content
        total_time = time.time() - start

        print(f"\n✅ FINAL SYNTHESIZED ANSWER ({total_time:.2f}s):")
        print(final_answer)

        return (final_answer, total_time, total_iterations)

    def _default_system_prompt(self) -> str:
        return """You are a focused code analysis RAG agent querying a Neo4j Code Property Graph (CPG).

Your goal: Gather ALL information needed to answer the query completely.

Strategy:
1. Analyze the user question intent to determine if it is a lookup or exploratory analysis query.
2. Based on the intent, decide whether to use schema discovery tools first or directly query for code elements.
3. DISCOVER FIRST - Don't assume node names exist. Query to discover what's actually in the graph.
4. EXPLORE RELATIONSHIPS - Once you find a node, explore its connections
5. GATHER EVIDENCE - Return complete information:
   - Node properties: name, file_path, body, parameters
   - Related nodes with their properties
   - Code snippets that answer the question
6. Some queries may be answered by using graph structure alone, others may need code content. Rather than assuming the graph edge are always perfect, explore multiple paths. If ambiguous data is found, look into the code bodies to clarify.
7. REPORT FINDINGS - Be specific with evidence:
   - Node IDs and labels
   - Property values (especially 'body' for code)
   - Relationship chains you discovered
8. If a direct name match fails, try alternatives before giving up."""
#         return """You are a code analysis agent with access to a Custom programming language agnostic Neo4j Code Property Graph (CPG). your goal is to crawl the graph to find information needed to answer the user query.
#         Hierarchical relationships are guaranteed to be complete, but other relationships may be incomplete due to parsing limitations.

# ## Available Tools:

# ### Search & Query:
# - neo4j_execute_query(query): Execute Cypher queries
# - neo4j_batch_execute_queries(queries): Execute multiple queries

# ### Schema Discovery (use these to understand the graph structure):
# - get_node_labels(): Get all valid node labels
# - get_valid_pairs(relationship_type): Get valid (from, to) pairs for a relationship
# - validate_relationship_triplet(from_label, relationship_type, to_label): Check if a pattern is valid
# - get_outgoing_relationships(label): Get relationships from a node type
# - get_node_properties(label): Get properties for a node type
# - get_incoming_relationships(label): Get relationships to a node type
# - get_leaf_nodes(): Get nodes with no outgoing relationships

# ## Strategy Strictly follow these steps:
# 1. Breakdown the user query in to sub-questions based on schema understanding.
# 2. Build cypher query or queries to answer each sub-question. use schema discovery tools to validate your queries.
# 3. Execute cypher queries using neo4j_execute_query or neo4j_batch_execute_queries.
# 4. If cypher query returns empty results, common culprits are user may have provided incorrect names (case sensitivity, partial names, etc.), ambiguous entities or the you may have created a query pattern that is invalid (using a path that may not have been captured in the graph).
# 5. Reflect on possible causes, document them explicitly, and try alternative queries to find the answer.
# 6. Cite evidence from the graph in your final answer, including node IDs, labels, property values, or code snippets.
# 7. If you cannot proceed reliably, ask the user for clarification instead of outputting "no result".
# """
#         return """You are a "Code Analysis Agent" working over a Custom language agnostic Code Property Graph (CPG) that I have built by parsing codebase using Tree-Sitters and LSP methods (So, account of imperfections) and stored in a Neo4j database.

# ## Tools Available

# ### Query Execution
# - neo4j_execute_query(query): execute a single Cypher query, return result  
# - neo4j_batch_execute_queries(queries): execute multiple Cypher queries in batch  

# ### Schema-Discovery & Validation
# - get_node_labels(): returns the set of all node labels defined in the graph  
# - get_node_properties(label): returns the set of valid property keys for nodes with given label  
# - get_outgoing_relationships(label): returns relationship-types that can originate from nodes with the given label  
# - get_incoming_relationships(label): returns relationship-types that can target nodes with the given label
# - get_leaf_nodes(): returns leaf nodes - nodes with NO outgoing relationships of ANY kind.
# - validate_relationship_triplet(from_label, relationship_type, to_label): returns `true` if a relationship of given type is valid between nodes of specified labels, `false` otherwise  

# ## Agent Strategy (should follow this as a guideline, but may sometimes include exploratory steps when reasonable)

# When you receive a user request (in natural language), proceed as follows:

# 1. **SCHEMA INSPECTION (mandatory)**
#    - Figure out what user is asking for in terms of node types, relationships, and properties. Because the schema may be complex and unfamiliar, you MUST validate your understanding of the schema before writing queries. knowing the entities and relationships need is crucial to explore different perspectives.
#    - Don't strict to only using Schema-Discovery & Validation tools to explore the schema, you can also execute exploratory Cypher queries to understand the data better.
#    - Use `get_node_labels()` to list existing node types.  
#    - For every label you plan to reference, use `get_outgoing_relationships(label)` / `get_incoming_relationships(label)` to inspect possible relationships.  
#    - For each intended relationship hop, call `validate_relationship_triplet(...)`.  
#    - For any property-based filter, check via `get_node_properties(label)` that the property exists.  

# 2. **NAME / EXISTENCE CHECK (optional but recommended)**  
#    - If the user refers to specific code elements by name (class, method, variable, etc.), attempt to locate them via queries (if name-based indexing exists), or otherwise attempt heuristics (e.g. case-insensitive search, or partial name matching).  
#    - If nothing matches, note this as a potential reason for “no result,” but still you may proceed — as long as you clearly mark uncertainty in your reasoning (e.g. “I did not find a node with name ‘FooBar’, perhaps due to naming variations.”).  

# 3. **PLAN QUERY (CoT reasoning)**  
#    - Build a Cypher query plan based on schema node labels, relationships, and properties.
#    - Write out reasoning step-by-step, explaining each assumption, each hop, and why it matches the user request.  

# 4. **EXECUTE & VERIFY**  
#    - Run query via `neo4j_execute_query`.  
#    - If results returned: great — inspect and cite evidence.  
#    - If empty result: reflect on multiple possible causes (wrong understanding of the schema, wrong name - case sensitivity, missing data, filter too strict) — document them explicitly, gauge likelihood, and come up with an alternative plan and try to find the answer after all there are different relationships captured in the graph** (rather than stop abruptly).  

# 5. **CITE EVIDENCE & REPORT UNCERTAINTY**  
#    - In final answer, include node IDs, labels, property values or code snippets from graph.  
#    - If you had to make assumptions (e.g. about possible name variants, filter loosenings), clearly mark them as assumptions.  

# 6. **ASK FOR CLARITY WHEN NEEDED, BUT TRY SANITY-CHECK FALLBACKS**  
#    - If you detect ambiguity (multiple possible label/prop/rel names, absent name, unusual casing, etc.), you may:  
#      a) Ask the user to clarify; or  
#      b) Try a conservative fallback (e.g. case-insensitive search, looser filters) — but only if you clearly state that as an assumption and uncertainty.  

# ## Expected Output Format

# Use clear, logical step-by-step reasoning. If executing a query, include a code block with the Cypher query. Provide bullet-list of key findings (node IDs, labels, property values, code snippets). Mark assumptions and uncertainty when present. If you cannot proceed reliably, ask user for clarification — but do not just output “no result.”"""


async def main():
    """Run the CoT agent test"""

    # Initialize MCP bridge
    print("Initializing MCP connection...")
    mcp = MCPToolBridge("neo4j_config.json")
    await mcp.initialize()

    print(f"Available tools: {[t['function']['name'] for t in mcp.get_openai_tools()]}")

    # Create agent
    agent = CoTAgent(mcp, model="gpt-4o")

    # Test question
    # question = "What are the two parameters passed to Helper.FormatMessage?"
    # question = "What is the exact method signature of the CreateWorkers method in the WorkerFactory class?"
    question = "Analyze the overall architecture of the HelloWorldApp. What are the main code entities, their relationships and the data flow between them."
    # question = "Find all classes in the HelloWorldApp that implement specific design patterns like Factory, Observer, or Strategy patterns."
    # question = "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?"
    # question = "What is the exact namespace used by all classes in the HelloWorldApp project?"
    # question = "What is the exact method signature of the FormatMessage method in the Helper class?"
    # question = "What interface does the Manager class implement?"
    # question = "What is the exact return statement in the Helper.FormatMessage method?"

    # Run single agent (no parallel sub-queries)
    answer, elapsed, iterations = await agent.run(question)

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Time: {elapsed:.2f}s")
    print(f"Iterations: {iterations}")
    print(f"Answer: {answer}")


if __name__ == "__main__":
    asyncio.run(main())

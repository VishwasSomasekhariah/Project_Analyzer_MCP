# Project Analyzer Main MCP Server Project

## Project Overview
This is a Model Context Protocol (MCP) Server project focused on Project Analysis using Code Property Graphs (CPG) and Vectors. The project implements intelligent RAG (Retrieval-Augmented Generation) workflows for code understanding and analysis.
There are Two CLI's we use, `project-analyzer` and `codebase-vector-rag`.
`project-analyzer` CLI uses Neo4j MCP server in the backend, so that must be running.
`codebase-vector-rag` CLI uses Chroma MCP server but in stdio mode, so this comes up running run time.
Because project-analyzer communicates with Neo4j MCP server we must pass a Neo4j MCP Config file to the cli during execution so that it know where to send its requests.
Always use `mcp_use` module's MCPClient and MCPSession to communicate with the MCP servers.
Don't confuse database MCP servers with the Main Project Server and Any component we build as part of the main MCP server must only interact with the CLI tools and never with other MCP servers directly.
We must use LangGraph to implement RAG Agent Workflow to implement CPG only retriever and a Comprehesive analysis retriever. Vector retriever is complete, so no need for a LangGraph workflow there.

### Things to Keep in mind while building LangGraph App Workflows.
- Define a state schema (TypedDict/Pydantic/dataclass) listing allowed keys and each key’s reducer (e.g., overwrite, append, custom).
- Each node receives the current state and returns a partial update limited to schema keys; the engine merges updates via the configured reducers (including at branch joins).
- Branching executes nodes against a snapshot; their deltas merge deterministically by reducer, preventing clobbering.
- Use a checkpointer to persist state between steps/sessions for resumability and human-in-the-loop pauses.
- Returning a key not declared in the schema is treated as a schema violation; declare keys (and reducers) before writing to them.
- Keep nodes small and single-purpose; express transitions with explicit edge logic for readability and maintenance.

## Development Guidelines
- Adopt scalable, production-ready practices:
- Prefer modular, service-oriented design; avoid monolithic architectures.
- Gate all changes (features and bug fixes) behind feature flags to enable safe, incremental rollouts, side-by-side testing, and instant rollback.
- Keep the legacy path until the flagged implementation is fully validated; remove only after successful verification.  

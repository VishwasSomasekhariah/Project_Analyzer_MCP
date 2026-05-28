# import subprocess
# import yaml
# import os
# from mcp.server.fastmcp import FastMCP

# monitor_config: dict = {}

# def register_all_tools(mcp):
#     @mcp.tool()
#     async def project_analysis_tool(
#         project_path: str,
#         mappings_path: str = "parsing_utils/mappings.yaml",
#         queries_path: str = "parsing_utils/queries.yaml",
#         config_path: str = "configs/neo4j_mcp_config.yaml"
#     ) -> dict:
#         """
#         Invoke the project-analyzer CLI tool to analyze a project.
#         Args:
#             project_path: Path to the root of the project.
#             mappings_path: Path to the mappings YAML file.
#             queries_path: Path to the queries file.
#         Returns:
#             dict: Status of the CLI call and output.
#         """
#         import traceback

#         try:
#             cli_command = [
#                 "project-analyzer",
#                 "--project-path", project_path,
#                 "--mappings-path", mappings_path,
#                 "--queries-path", queries_path,
#                 "--config-file", config_path
#             ]

#             result = subprocess.run(
#                 cli_command,
#                 text=True,
#                 capture_output=True,
#                 check=False  # Let us handle errors ourselves
#             )

#             if result.returncode == 0:
#                 monitor_config.clear()
#                 monitor_config.update({
#                     "project_path": project_path,
#                     "mappings_path": mappings_path,
#                     "queries_path": queries_path,
#                     "supported_extensions": [".py",".js",".cs"],   # adjust to your needs
#                     "ignore_dirs": ["node_modules",".git","bin","obj"]
#                 })
#                 return {
#                     "status": "success",
#                     "stdout": result.stdout
#                 }
#             else:
#                 return {
#                     "status": "error",
#                     "error": result.stderr,
#                     "stdout": result.stdout,
#                     "returncode": result.returncode
#                 }
#         except Exception as e:
#             return {
#                 "status": "error",
#                 "step": "subprocess",
#                 "error": str(e),
#                 "traceback": traceback.format_exc()
#             }
    
#     @mcp.tool()
#     async def get_file_monitor_config() -> dict:
#         """
#         Called by the watcher to fetch the project_path and other settings.
#         """
#         return monitor_config

#     @mcp.tool()
#     async def process_file_changes(changed_files: list[str]) -> dict:
#         """
#         Called by the watcher when files change.
#         """
#         # You can re-trigger analysis here, or simply ack:
#         return {"status":"ack", "changed_files": changed_files}

# import subprocess
# import yaml
# import os
# from typing import Dict, Any, List
# from mcp.server.fastmcp import FastMCP
# from mcp.server.fastmcp.resources import Resource

# # Global state to store monitor configuration
# monitor_config: dict = {}

# def register_all_tools(mcp: FastMCP):
#     # Create a resource for project configuration
#     project_config_resource = Resource(
#         id="project-config",
#         name="Project Configuration",
#         description="Configuration for the project analyzer and file watcher",
#         content={"project_path": None, "analyzer_path": None}
#     )

#     # Register the resource with the MCP server
#     mcp.add_resource(project_config_resource)

#     @mcp.tool()
#     async def project_analysis_tool(
#         project_path: str,
#         mappings_path: str = "parsing_utils/mappings.yaml",
#         queries_path: str = "parsing_utils/queries.yaml",
#         config_path: str = "configs/neo4j_mcp_config.yaml"
#     ) -> dict:
#         """
#         Invoke the project-analyzer CLI tool to analyze a project.
        
#         Args:
#             project_path: Path to the root of the project.
#             mappings_path: Path to the mappings YAML file.
#             queries_path: Path to the queries file.
            
#         Returns:
#             dict: Status of the CLI call and output.
#         """
#         import traceback
        
#         try:
#             cli_command = [
#                 "project-analyzer",
#                 "--project-path", project_path,
#                 "--mappings-path", mappings_path,
#                 "--queries-path", queries_path,
#                 "--config-file", config_path
#             ]
            
#             result = subprocess.run(
#                 cli_command,
#                 text=True,
#                 capture_output=True,
#                 check=False  # Let us handle errors ourselves
#             )
            
#             if result.returncode == 0:
#                 # Update the resource content instead of global dict
#                 project_config_resource.content = {
#                     "project_path": project_path,
#                     "mappings_path": mappings_path,
#                     "queries_path": queries_path,
#                     "supported_extensions": [".py", ".js", ".cs"],
#                     "ignore_dirs": ["node_modules", ".git", "bin", "obj"]
#                 }
                
#                 return {
#                     "status": "success",
#                     "stdout": result.stdout
#                 }
#             else:
#                 return {
#                     "status": "error",
#                     "error": result.stderr,
#                     "stdout": result.stdout,
#                     "returncode": result.returncode
#                 }
                
#         except Exception as e:
#             return {
#                 "status": "error",
#                 "step": "subprocess",
#                 "error": str(e),
#                 "traceback": traceback.format_exc()
#             }
    
#     @mcp.tool()
#     async def get_file_monitor_config() -> dict:
#         """Called by the watcher to fetch the project_path and other settings."""
#         return project_config_resource.content
    
#     @mcp.tool()
#     async def set_project_path(project_path: str, analyzer_path: str = None) -> dict:
#         """Set the current project path for file monitoring"""
#         # Get current content
#         current_config = project_config_resource.content
        
#         # Update with new values
#         current_config["project_path"] = project_path
#         if analyzer_path:
#             current_config["analyzer_path"] = analyzer_path
            
#         # Set the updated content
#         project_config_resource.content = current_config
        
#         return {"status": "success", "project_path": project_path}
    
#     @mcp.tool()
#     async def process_file_changes(changed_files: list[str]) -> dict:
#         """
#         Called by the watcher when files change.
#         """
#         # You can re-trigger analysis here, or simply ack:
#         return {"status": "ack", "changed_files": changed_files}
    

# tools.py
import subprocess
import traceback
import os
import gc
import json
from typing import Dict, Any, List, Optional
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource

# Create a dictionary to store project configuration
_project_config = {
    "project_path": None,
    "mappings_path": None, 
    "queries_path": None,
    "supported_extensions": [".py", ".js", ".cs"],
    "ignore_dirs": ["node_modules", ".git", "bin", "obj"]
}

# Create a function that will be used by the FunctionResource
def get_project_config():
    """Returns the current project configuration"""
    return _project_config

# Create the resource using FunctionResource with the required 'fn' parameter
project_config_resource = FunctionResource(
    uri="resource://project-config",
    name="Project Configuration",
    description="Configuration for the project analyzer and file watcher",
    fn=get_project_config  # This was missing in your implementation
)

def register_all_tools(mcp: FastMCP):
    """Register all tools with the MCP server"""
    
    # Register the resource with the MCP serverI
    mcp.add_resource(project_config_resource)

    @mcp.tool()
    async def analyze_project_only(
        project_path: str,
        mappings_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
        queries_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
        config_path: str = "/opt/genpod/neo4j_config.json"
    ) -> dict:
        """
        Analyze project for CPG ONLY - sets up CPG-based file monitoring after completion.
        
        This tool performs ONLY CPG analysis using project-analyzer and then enables
        file monitoring for CPG-based change detection. Use this when you want 
        CPG-only analysis without vectorization.
        """
        try:
            # Run the project analyzer CLI using the new Click-based structure
            cli_command = [
                "project-analyzer",
                "--config-file", config_path,
                "analyze",
                "--project-path", project_path,
                "--mappings-path", mappings_path,
                "--queries-path", queries_path
            ]
            
            result = subprocess.run(
                cli_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )
            
            if result.returncode == 0:
                # Update project config AFTER CPG analysis completes to enable file monitoring
                # This signals that user wants CPG-based file monitoring
                _project_config.update({
                    "project_path": project_path,
                    "mappings_path": mappings_path,
                    "queries_path": queries_path,
                    "config_path": config_path,
                    "monitoring_mode": "cpg_only",
                    "supported_extensions": [".py", ".js", ".cs", ".java", ".cpp", ".c", ".h"],
                    "ignore_dirs": ["node_modules", ".git", "bin", "obj", ".venv", "__pycache__"]
                })
                
                return {
                    "status": "success",
                    "project_path": project_path,
                    "stdout": result.stdout,
                    "message": "CPG analysis completed successfully - CPG-based file monitoring enabled",
                    "monitoring_enabled": True,
                    "monitoring_mode": "cpg_only"
                }
            else:
                return {
                    "status": "error",
                    "error": result.stderr,
                    "stdout": result.stdout,
                    "returncode": result.returncode
                }
        except Exception as e:
            return {
                "status": "error",
                "step": "analyze_project_only",
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    @mcp.tool()
    async def get_file_monitor_config() -> dict:
        """Called by the watcher to fetch the project_path and other settings."""
        return _project_config

    @mcp.tool()
    async def set_project_path(project_path: str, analyzer_path: str = None) -> dict:
        """Set the current project path for file monitoring"""
        # Update with new values
        _project_config["project_path"] = project_path
        if analyzer_path:
            _project_config["analyzer_path"] = analyzer_path
        return {"status": "success", "project_path": project_path}

    @mcp.tool()
    async def process_file_changes(changed_files: list[str]) -> dict:
        """Called by the watcher when files change."""
        return {"status": "ack", "changed_files": changed_files}

    # ===== Individual CLI Tools (Modular Architecture) =====
    
    @mcp.tool()
    async def vectorize_codebase_only(
        input_dir: str,
        collection_name: str,
        enable_lsp: bool = True,
        enable_ai: bool = True,
        vector_db: str = "qdrant",
        config: str = None
    ) -> dict:
        """
        Vectorize codebase ONLY - sets up vector-based file monitoring after completion.

        This tool performs ONLY vectorization using genpod-semantic-rag and then enables
        file monitoring for vector-based change detection. Use this when you want
        vector-only analysis without CPG building.

        Args:
            input_dir: Directory containing source code files to process (required)
            collection_name: Vector database collection name (required)
            enable_lsp: Enable LSP integration for enhanced semantic analysis
            enable_ai: Enable AI summarization (default: True)
            vector_db: Vector database type - "chroma", "qdrant", or "weaviate" (default: "qdrant")
            config: Path to configuration file for vector database MCP settings
        """
        try:
            # Validate input directory
            if not os.path.exists(input_dir):
                return {
                    "status": "error",
                    "error": f"Input directory does not exist: {input_dir}"
                }

            # Build CLI command
            cli_command = [
                "genpod-semantic-rag", "preprocess",
                "--input-dir", input_dir,
                "--collection-name", collection_name,
                "--vector-db", vector_db
            ]

            # LSP integration
            if enable_lsp:
                cli_command.append("--enable-lsp")

            # AI summarization
            if enable_ai:
                cli_command.append("--enable-ai")

            # Configuration file
            if config and os.path.exists(config):
                cli_command.extend(["--config", config])
            
            # Execute command
            result = subprocess.run(
                cli_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )
            
            if result.returncode == 0:
                # Update project config AFTER vectorization completes to enable file monitoring
                # This signals that user wants vector-based file monitoring
                _project_config.update({
                    "project_path": input_dir,
                    "vectorization_collection": collection_name,
                    "monitoring_mode": "vector_only",
                    "supported_extensions": [".py", ".js", ".cs", ".java", ".cpp", ".c", ".h"],
                    "ignore_dirs": ["node_modules", ".git", "bin", "obj", ".venv", "__pycache__"]
                })
                
                return {
                    "status": "success",
                    "input_dir": input_dir,
                    "collection_name": collection_name,
                    "stdout": result.stdout,
                    "message": "Vectorization completed successfully - vector-based file monitoring enabled",
                    "monitoring_enabled": True,
                    "monitoring_mode": "vector_only"
                }
            else:
                return {
                    "status": "error",
                    "error": result.stderr,
                    "stdout": result.stdout,
                    "returncode": result.returncode
                }
                
        except Exception as e:
            return {
                "status": "error",
                "step": "vectorize_codebase_preprocess",
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    @mcp.tool()
    async def full_project_setup(
        project_path: str,
        collection_name: str,
        mappings_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
        queries_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
        vector_config: str = None,
        neo4j_config: str = "/opt/genpod/neo4j_config.json",
        vector_db: str = "qdrant",
        enable_lsp: bool = True,
        enable_ai: bool = True
    ) -> dict:
        """
        Complete project setup - vectorization + CPG analysis + comprehensive monitoring.

        This orchestrated workflow performs:
        1. Vectorize codebase using genpod-semantic-rag
        2. Analyze project for CPG using project-analyzer
        3. Enable comprehensive file monitoring (both vector + CPG)

        Use this when you want full analysis capabilities with comprehensive monitoring.

        Args:
            project_path: Path to the project root
            collection_name: Vector database collection name
            mappings_path: Path to mappings YAML file
            queries_path: Path to queries directory
            vector_config: Optional config file for vector operations
            neo4j_config: Config file for Neo4j connections
            vector_db: Vector database type - "chroma", "qdrant", or "weaviate" (default: "qdrant")
            enable_lsp: Enable LSP integration for vectorization
            enable_ai: Enable AI summarization for vectorization
        """
        try:
            workflow_results = {
                "steps": {},
                "status": "in_progress",
                "project_path": project_path,
                "collection_name": collection_name
            }

            # Step 1: Vectorize codebase (without setting project_path)
            workflow_results["steps"]["1_vectorization"] = {"status": "running"}

            vector_command = [
                "genpod-semantic-rag", "preprocess",
                "--input-dir", project_path,
                "--collection-name", collection_name,
                "--vector-db", vector_db
            ]

            if enable_lsp:
                vector_command.append("--enable-lsp")
            if enable_ai:
                vector_command.append("--enable-ai")
            if vector_config and os.path.exists(vector_config):
                vector_command.extend(["--config", vector_config])
            
            vector_result = subprocess.run(
                vector_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )
            
            if vector_result.returncode != 0:
                workflow_results["steps"]["1_vectorization"] = {
                    "status": "failed",
                    "error": vector_result.stderr
                }
                return {
                    "status": "error",
                    "step": "vectorization",
                    "error": vector_result.stderr,
                    "partial_results": workflow_results
                }
            
            workflow_results["steps"]["1_vectorization"] = {"status": "completed"}
            
            # Step 2: CPG Analysis (without setting project_path)
            workflow_results["steps"]["2_cpg_analysis"] = {"status": "running"}
            
            cpg_command = [
                "project-analyzer",
                "--config-file", neo4j_config,
                "analyze",
                "--project-path", project_path,
                "--mappings-path", mappings_path,
                "--queries-path", queries_path
            ]
            
            cpg_result = subprocess.run(
                cpg_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )
            
            if cpg_result.returncode != 0:
                workflow_results["steps"]["2_cpg_analysis"] = {
                    "status": "failed", 
                    "error": cpg_result.stderr
                }
                return {
                    "status": "error",
                    "step": "cpg_analysis",
                    "error": cpg_result.stderr,
                    "partial_results": workflow_results
                }
            
            workflow_results["steps"]["2_cpg_analysis"] = {"status": "completed"}
            
            # Step 3: Enable comprehensive monitoring (AFTER both complete)
            workflow_results["steps"]["3_enable_monitoring"] = {"status": "running"}
            
            _project_config.update({
                "project_path": project_path,
                "vectorization_collection": collection_name,
                "mappings_path": mappings_path,
                "queries_path": queries_path,
                "config_path": neo4j_config,
                "monitoring_mode": "comprehensive",
                "supported_extensions": [".py", ".js", ".cs", ".java", ".cpp", ".c", ".h"],
                "ignore_dirs": ["node_modules", ".git", "bin", "obj", ".venv", "__pycache__"]
            })
            
            workflow_results["steps"]["3_enable_monitoring"] = {"status": "completed"}
            workflow_results["status"] = "success"
            
            return {
                "status": "success",
                "project_path": project_path,
                "collection_name": collection_name,
                "message": "Full project setup completed - comprehensive monitoring enabled",
                "monitoring_enabled": True,
                "monitoring_mode": "comprehensive",
                "workflow_results": workflow_results,
                "capabilities": ["vector_search", "cpg_analysis", "llm_integration"]
            }
            
        except Exception as e:
            return {
                "status": "error",
                "step": "full_project_setup",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "partial_results": workflow_results if 'workflow_results' in locals() else None
            }
    
    @mcp.tool()
    async def configure_llm_service(
        provider: str = "openai",
        cache_ttl: int = 1800,
        openai_api_key: str = None,
        anthropic_api_key: str = None
    ) -> dict:
        """
        Configure the LLM service settings.
        
        Args:
            provider: Primary LLM provider (openai, anthropic)
            cache_ttl: Cache time-to-live in seconds (default: 30 minutes)
            openai_api_key: OpenAI API key (optional, uses env var if not provided)
            anthropic_api_key: Anthropic API key (optional, uses env var if not provided)
        """
        try:
            # Update project config with LLM settings
            _project_config.update({
                "llm_provider": provider,
                "llm_cache_ttl": cache_ttl
            })
            
            # Store API keys in environment if provided
            if openai_api_key:
                os.environ["OPENAI_API_KEY"] = openai_api_key
            if anthropic_api_key:
                os.environ["ANTHROPIC_API_KEY"] = anthropic_api_key
            
            return {
                "status": "success",
                "configuration": {
                    "provider": provider,
                    "cache_ttl": cache_ttl,
                    "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
                    "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY"))
                },
                "message": "LLM service configured successfully"
            }
            
        except Exception as e:
            return {
                "status": "error",
                "step": "configure_llm",
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    @mcp.tool()
    async def llm_service_health_check() -> dict:
        """
        Check the health and availability of LLM services.
        """
        try:
            from core.llm_service import LLMService
            
            llm_service = LLMService()
            usage_stats = llm_service.get_usage_stats()
            
            return {
                "status": "success",
                "llm_service_status": "available",
                "providers_available": usage_stats["available_providers"],
                "configuration": {
                    "preferred_provider": _project_config.get("llm_provider", "not_configured"),
                    "cache_ttl": _project_config.get("llm_cache_ttl", 1800),
                    "openai_available": bool(os.getenv("OPENAI_API_KEY")),
                    "anthropic_available": bool(os.getenv("ANTHROPIC_API_KEY"))
                },
                "usage_statistics": usage_stats
            }
            
        except Exception as e:
            return {
                "status": "error",
                "llm_service_status": "unavailable",
                "error": str(e),
                "message": "LLM service is not properly configured or accessible"
            }
    
    @mcp.tool()
    async def query_vector_only(
        query: str,
        collection_name: str,
        max_results: int = 10,
        config: str = None,
        output_format: str = "json",
        vector_db: str = "qdrant",
        enable_reasoning: bool = True,
        max_branches: int = 2
    ) -> dict:
        """
        Query vectorized codebase ONLY - pure vector search with no side effects.

        This tool performs ONLY vector querying using genpod-semantic-rag without
        affecting project configuration or file monitoring. Use this for pure
        vector searches without triggering any monitoring changes.

        Args:
            query: Natural language query to search for (required)
            collection_name: Vector database collection name (required)
            max_results: Maximum number of results to return (default: 10)
            config: Path to configuration file for vector database MCP settings
            output_format: Output format - "json" for structured data, "text" for human-readable (default: "json")
            vector_db: Vector database type - "chroma", "qdrant", or "weaviate" (default: "qdrant")
            enable_reasoning: Enable Tree of Thought + Chain of Thought reasoning (default: True)
            max_branches: Maximum reasoning branches for ToT (default: 2, only used if enable_reasoning=True)
        """
        try:
            # Build CLI command - config must come before subcommand
            cli_command = ["genpod-semantic-rag"]

            # Configuration file comes first (before subcommand)
            if config and os.path.exists(config):
                cli_command.extend(["--config", config])

            # Add subcommand and query
            cli_command.extend(["query", query])
            cli_command.extend(["--collection-name", collection_name])
            cli_command.extend(["--max-results", str(max_results)])
            cli_command.extend(["--vector-db", vector_db])

            # Add reasoning flags
            if enable_reasoning:
                cli_command.append("--reasoning")
                cli_command.extend(["--max-branches", str(max_branches)])

            # Add output format if specified
            if output_format:
                cli_command.extend(["--output-format", output_format])
            
            # Execute command
            result = subprocess.run(
                cli_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )
            
            if result.returncode == 0:
                # Parse response based on output format
                if output_format == "json":
                    try:
                        # Parse JSON response from CLI
                        json_response = json.loads(result.stdout)

                        # Map CLI response keys to MCP tool response format
                        # CLI returns: "response", "query", "results", "reasoning_trace", "reasoning_metrics", etc.
                        # MCP expects: "ai_response", "query", "raw_results"
                        return {
                            "status": "success",
                            "query": json_response.get("query", query),
                            "collection_name": collection_name,
                            "ai_response": json_response.get("response", ""),  # Map "response" to "ai_response"
                            "raw_results": json_response.get("results", []),    # Map "results" to "raw_results"
                            "metadata": {
                                "total_results": json_response.get("total_results", 0),
                                "processing_time": json_response.get("processing_time", 0),
                                "confidence_score": json_response.get("confidence_score"),
                                "has_diagram": json_response.get("has_diagram", False),
                                "reasoning_used": json_response.get("reasoning_used", False),
                                "reasoning_metrics": json_response.get("reasoning_metrics"),
                                "diagram_content": json_response.get("diagram_content")
                            },
                            "reasoning_trace": json_response.get("reasoning_trace"),  # Include full reasoning trace
                            "full_response": result.stdout
                        }
                    except json.JSONDecodeError:
                        # Fallback if JSON parsing fails
                        return {
                            "status": "success",
                            "query": query,
                            "collection_name": collection_name,
                            "ai_response": result.stdout,
                            "raw_results": [],
                            "metadata": {},
                            "full_response": result.stdout,
                            "note": "JSON parsing failed, using raw output"
                        }
                else:
                    # Text format - return as-is
                    return {
                        "status": "success",
                        "query": query,
                        "collection_name": collection_name,
                        "ai_response": result.stdout,
                        "raw_results": [],
                        "metadata": {},
                        "full_response": result.stdout
                    }
            else:
                return {
                    "status": "error",
                    "error": result.stderr,
                    "stdout": result.stdout,
                    "returncode": result.returncode
                }
                
        except Exception as e:
            return {
                "status": "error",
                "step": "query_vector_only",
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    @mcp.tool()
    async def query_pageindex_only(
        query: str,
        project_path: str = "/opt/HelloWorldApp",
        mcts_iterations: int = 20,
        config: str = "/opt/genpod/qdrant_config.json",
        output_format: str = "json"
    ) -> dict:
        """
        Query codebase using PageIndex retriever - MCTS-based file tree navigation.

        Uses genpod-semantic-rag with --retriever pageindex to navigate the project
        file hierarchy with Monte Carlo Tree Search instead of vector similarity.
        Best for structural, direct-lookup, and quantitative queries.

        Args:
            query: Natural language query to search for (required)
            project_path: Absolute path to the project root (default: /opt/HelloWorldApp)
            mcts_iterations: Number of MCTS search iterations (default: 20)
            config: Path to genpod-semantic-rag config file (default: /opt/genpod/qdrant_config.json)
            output_format: Output format - "json" or "text" (default: "json")
        """
        try:
            cli_command = ["genpod-semantic-rag"]

            if config and os.path.exists(config):
                cli_command.extend(["--config", config])

            cli_command.extend(["query", query])
            cli_command.extend(["--retriever", "pageindex"])
            cli_command.extend(["--project-path", project_path])
            cli_command.extend(["--mcts-iterations", str(mcts_iterations)])

            if output_format:
                cli_command.extend(["--output-format", output_format])

            result = subprocess.run(
                cli_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )

            if result.returncode == 0:
                if output_format == "json":
                    try:
                        json_response = json.loads(result.stdout)
                        cli_metadata = json_response.get("metadata", {})
                        validation = cli_metadata.get("validation", {})
                        entity_grounding = validation.get("entity_grounding", {})
                        return {
                            "status": "success",
                            "query": json_response.get("query", query),
                            "project_path": project_path,
                            "ai_response": json_response.get("response", ""),
                            "raw_results": json_response.get("results", []),
                            "metadata": {
                                "total_results": json_response.get("total_results", 0),
                                "processing_time": json_response.get("processing_time", 0),
                                "confidence_score": json_response.get("confidence_score"),
                                "mcts_iterations": mcts_iterations,
                                # flattened from metadata.validation
                                "faithfulness_score": validation.get("faithfulness_score"),
                                "coverage_score": validation.get("coverage_score"),
                                "unsupported_claims": validation.get("unsupported_claims", []),
                                "uncovered_topics": validation.get("uncovered_topics", []),
                                "hallucinated_count": entity_grounding.get("hallucinated_count"),
                                "hallucinated_entities": entity_grounding.get("hallucinated_entities", []),
                                "answer_identifiers": entity_grounding.get("answer_identifiers"),
                                "symbol_table_size": entity_grounding.get("symbol_table_size"),
                            },
                            "full_response": result.stdout
                        }
                    except json.JSONDecodeError:
                        return {
                            "status": "success",
                            "query": query,
                            "project_path": project_path,
                            "ai_response": result.stdout,
                            "raw_results": [],
                            "metadata": {},
                            "full_response": result.stdout,
                            "note": "JSON parsing failed, using raw output"
                        }
                else:
                    return {
                        "status": "success",
                        "query": query,
                        "project_path": project_path,
                        "ai_response": result.stdout,
                        "raw_results": [],
                        "metadata": {},
                        "full_response": result.stdout
                    }
            else:
                return {
                    "status": "error",
                    "error": result.stderr,
                    "stdout": result.stdout,
                    "returncode": result.returncode
                }

        except Exception as e:
            return {
                "status": "error",
                "step": "query_pageindex_only",
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    @mcp.tool()
    async def query_cpg_rag(
        user_query: str,
        project_name: str = "HelloWorldApp",
        config_path: str = "/opt/genpod/neo4j_config.json",
        schema_path: str = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        llm_model: str = "gpt-4o",
        max_cot_iterations: int = 15,
        max_verifier_iterations: int = 10,
        max_parallel_workers: int = 5,
        parallel_agents: bool = True,
        enable_verification: bool = True,
        enable_entity_resolution: bool = True,
        enable_observer: bool = False,
        use_4_agent_team: bool = True,
        four_agent_max_iterations: int = 3
    ) -> dict:
        """
        Multi-Agent CPG RAG Query with Tree-of-Thought / Chain-of-Thought Reasoning

        This tool uses a multi-agent system for intelligent code analysis.

        TWO WORKFLOW OPTIONS:

        1. 4-Agent Team (default, use_4_agent_team=True):
           - Thinker: Analyzes sub-query and generates Cypher queries with reasoning
           - ThinkingValidator: Validates reasoning quality and approach
           - CypherValidator: Validates Cypher syntax and schema compliance
           - ExecutorVerifier: Executes queries and verifies results

        2. Legacy CoT+Verifier (use_4_agent_team=False):
           - ToT Orchestrator decomposes queries into sub-queries
           - Multiple CoT Agents execute sub-queries in parallel
           - Verification Agent independently validates findings

        WORKFLOW: Query -> Decompose -> Entity Resolution -> [4-Agent Team OR CoT Agents] -> Verify -> Synthesize

        Args:
            user_query: Natural language question about the code (REQUIRED)
            project_name: Project identifier in Neo4j database (default: HelloWorldApp)
            config_path: Neo4j MCP configuration file path
            schema_path: YAML schema file path for CPG structure
            llm_model: LLM model to use (default: gpt-4o)
            max_cot_iterations: Max iterations per CoT agent (default: 15)
            max_verifier_iterations: Max iterations for verification (default: 10)
            max_parallel_workers: Max concurrent CoT agents per phase (default: 5)
            parallel_agents: Run CoT agents in parallel (default: True)
            enable_verification: Enable claim verification (default: True)
            enable_entity_resolution: Enable entity name resolution (default: True)
            enable_observer: Enable CPG Observer for quality tracking (default: False)
            use_4_agent_team: Use 4-agent team workflow (default: True)
            four_agent_max_iterations: Max iterations for 4-agent team per sub-query (default: 3)

        Returns:
            dict: Contains 'response' with answer, citations, confidence, and token usage

        Example Usage:
            "What classes are defined in this project?"
            "Analyze the architecture of HelloWorldApp"
            "How does WorkerFactory create workers?"
        """
        system = None  # Track for cleanup in finally block
        try:
            import logging
            import time
            logger = logging.getLogger(__name__)

            start_time = time.time()
            logger.info(f"Starting Multi-Agent CPG RAG for: {user_query}")

            # Import from the new graph_rag module
            from src.core.graph_rag import MultiAgentCoT, SystemConfig

            # Create configuration
            # Use neo4j-only MCP config for Claude SDK fallback (no qdrant needed for CPG RAG)
            config = SystemConfig(
                mcp_config_path=config_path,
                yaml_schema_path=schema_path,
                llm_model=llm_model,
                max_cot_iterations=max_cot_iterations,
                max_verifier_iterations=max_verifier_iterations,
                max_parallel_workers=max_parallel_workers,
                parallel_cot_agents=parallel_agents,
                verification_enabled=enable_verification,
                entity_resolution_enabled=enable_entity_resolution,
                # 4-Agent Team configuration
                use_4_agent_team=use_4_agent_team,
                four_agent_max_iterations=four_agent_max_iterations,
                # Fallback configuration - only neo4j MCP server for CPG queries
                fallback_mcp_config_path="/opt/genpod/fallback_agent/neo4j_only_mcp_config.json",
            )

            # Initialize and run the multi-agent system
            system = MultiAgentCoT(config, enable_observer=enable_observer)
            await system.initialize()

            # Execute the query
            response = await system.run(user_query)

            # Convert ProductionResponse to dict format for MCP compatibility
            # Extract citations as list of dicts
            citations_list = []
            for citation in response.citations:
                citations_list.append({
                    "claim": citation.claim,
                    "source_file": citation.source_file,
                    "source_line": citation.source_line,
                    "source_location": citation.source_location,
                    "entity_name": citation.entity_name,
                    "entity_type": citation.entity_type,
                    "evidence": citation.evidence,
                    "verification_status": citation.verification_status.value if citation.verification_status else None,
                    "verification_explanation": citation.verification_explanation,
                    "discovery_query": citation.discovery_query,
                    "verification_query": citation.verification_query,
                    "cot_agent_id": citation.cot_agent_id,
                    "confidence": citation.confidence.value if citation.confidence else None
                })

            # Build token usage dict
            token_usage = {}
            if response.token_usage:
                token_usage = {
                    "total_tokens": response.token_usage.total_tokens,
                    "total_prompt_tokens": response.token_usage.total_prompt_tokens,
                    "total_completion_tokens": response.token_usage.total_completion_tokens,
                    "call_count": response.token_usage.call_count,
                    "by_agent_role": response.token_usage.by_agent_role or {}
                }

            # Determine workflow type based on configuration
            workflow_type = "4_agent_team" if use_4_agent_team else "multi_agent_tot_cot"

            return {
                "status": "success",
                "tool_name": "query_cpg_rag",
                "workflow_type": workflow_type,
                "user_query": user_query,
                "project_name": project_name,

                # Main Results
                "response": {
                    "answer": response.answer,
                    "confidence": response.confidence.value,
                    "status": "success"
                },

                # Citations with verification status
                "citations": citations_list,
                "raw_results": citations_list,  # For backwards compatibility

                # Verification summary
                "verified_count": response.verified_count,
                "unverified_count": response.unverified_count,
                "total_citations": len(citations_list),

                # Execution metadata
                "sub_queries_count": response.sub_queries_count,
                "llm_calls_count": response.llm_calls_count,
                "execution_time_ms": response.execution_time_ms,

                # Token usage (transparency)
                "token_usage": token_usage,
                "total_tokens_used": token_usage.get("total_tokens", 0),
                "total_input_tokens": token_usage.get("total_prompt_tokens", 0),
                "total_output_tokens": token_usage.get("total_completion_tokens", 0),

                # Agent metadata
                "agent_workflow": workflow_type,
                "agent_metadata": {
                    "llm_model": llm_model,
                    "max_cot_iterations": max_cot_iterations,
                    "parallel_agents": parallel_agents,
                    "verification_enabled": enable_verification,
                    "entity_resolution_enabled": enable_entity_resolution,
                    "observer_enabled": enable_observer,
                    "use_4_agent_team": use_4_agent_team,
                    "four_agent_max_iterations": four_agent_max_iterations
                },

                # Configuration used
                "cli_parameters_used": {
                    "config_path": config_path,
                    "schema_path": schema_path,
                    "llm_model": llm_model
                },

                "message": f"{'4-Agent Team' if use_4_agent_team else 'Multi-Agent CoT'} CPG RAG completed successfully ({response.execution_time_ms}ms)"
            }

        except ImportError as e:
            import traceback
            return {
                "status": "error",
                "tool_name": "query_cpg_rag",
                "error": f"Multi-Agent graph_rag module not available: {e}",
                "traceback": traceback.format_exc(),
                "fallback_suggestion": "Check that src.core.graph_rag is properly installed",
                "user_query": user_query
            }
        except Exception as e:
            import traceback
            return {
                "status": "error",
                "tool_name": "query_cpg_rag",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "user_query": user_query,
                "project_name": project_name,
                "message": f"Multi-Agent CPG RAG failed: {str(e)}"
            }
        finally:
            # Gracefully shutdown the multi-agent system to prevent cancel scope errors
            # This ensures MCP sessions are properly cleaned up before garbage collection
            if system:
                try:
                    await system.shutdown()
                except Exception:
                    pass  # Suppress cleanup errors - connections will close anyway
                
    @mcp.tool()
    async def query_hybrid_rag(
        user_query: str,
        project_name: str = "HelloWorldApp",
        project_path: str = "/opt/HelloWorldApp",
        mcts_iterations: int = 20,
        collection_name: str = "helloworldapp-benchmarking",
        config_path: str = "/opt/genpod/neo4j_config.json",
        schema_path: str = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        vector_config_path: str = None,
        vector_db: str = "qdrant",
        enable_reasoning: bool = True,
        max_branches: int = 2,
        max_results: int = 100,
        llm_model: str = "gpt-4o",
        max_cot_iterations: int = 15,
        max_verifier_iterations: int = 10,
        parallel_agents: bool = True,
        enable_verification: bool = True,
        enable_entity_resolution: bool = True,
        batch_size: int = 5,
        max_context_limit: int = 100000,
        use_4_agent_team: bool = True,
        four_agent_max_iterations: int = 3,
        retriever_combination: str = "pageindex_vector_graph"
    ) -> dict:
        """
        🚀 HYBRID RAG: Advanced code analysis combining Vector and CPG retrievers

        This tool provides the most comprehensive code analysis by combining:
        1. 🧠 Intent analysis for optimal retrieval strategy
        2. 🔍 Parallel Vector (semantic) and CPG (structural) retrieval
        3. 🔗 Intelligent result combination with cross-validation
        4. 🧠 Chain-of-thought synthesis with evidence grading
        5. 🎯 Critic validation for hallucination and faithfulness checking
        6. ⚡ Smart context management and fallback strategies

        CPG WORKFLOW OPTIONS (controlled by use_4_agent_team):
        - 4-Agent Team (default): Thinker → ThinkingValidator → CypherValidator → ExecutorVerifier
        - Legacy CoT+Verifier: ToT Orchestrator → CoT Agents → Verification Agent

        BEST FOR: Complex queries requiring both semantic understanding and structural analysis
        WORKFLOW: Intent Analysis → Parallel Retrieval → Cross-Validation → Synthesis → Validation

        Args:
            user_query: Natural language query about the codebase
            project_name: Name of the project being analyzed
            project_path: Path to the project root for PageIndex retrieval (default: /opt/HelloWorldApp)
            mcts_iterations: MCTS iterations for PageIndex search (default: 20)
            collection_name: Vector database collection for vector search
            config_path: Neo4j configuration for CPG queries
            schema_path: YAML schema file path for CPG structure
            vector_config_path: MCP config path for vector database (Qdrant/Chroma/Weaviate)
            vector_db: Vector database type - "chroma", "qdrant", or "weaviate" (default: "qdrant")
            enable_reasoning: Enable Tree of Thought + Chain of Thought reasoning (default: True)
            max_branches: Maximum reasoning branches for ToT (default: 2)
            max_results: Maximum results per retriever
            llm_model: LLM model to use (default: gpt-4o)
            max_cot_iterations: Max iterations per CoT agent (default: 15)
            max_verifier_iterations: Max iterations for verification (default: 10)
            parallel_agents: Run CoT agents in parallel (default: True)
            enable_verification: Enable claim verification (default: True)
            enable_entity_resolution: Enable entity name resolution (default: True)
            batch_size: Batch size for context management
            max_context_limit: Maximum context window size
            use_4_agent_team: Use 4-agent team workflow for CPG (default: True)
            four_agent_max_iterations: Max iterations for 4-agent team per sub-query (default: 3)
            retriever_combination: Which retrievers to run after PageIndex.
                "pageindex_vector_graph" — pageindex then vector + graph (default)
                "pageindex_vector"       — pageindex then vector only
                "pageindex_graph"        — pageindex then graph only
                "pageindex_and_graph"    — pageindex and graph in parallel (no reformulation)
                "pageindex_and_vector"   — pageindex and vector in parallel (no reformulation)

        Returns:
            dict: Comprehensive analysis with synthesis, validation, and raw results

        Example Queries:
            "What is the overall architecture of this codebase?"
            "How many methods call Console.WriteLine and what patterns do they follow?"
            "Show me the main design patterns and their implementations"
            "Find all database interactions and explain the data flow"
        """
        try:
            import logging
            logger = logging.getLogger(__name__)
            
            logger.info(f"🚀 Starting Hybrid RAG analysis for: {user_query}")
            
            # Import the hybrid workflow directly
            from src.core.hybrid_workflow_V2 import HybridRAGWorkflow
            # from src.core.llm_service import LLMService  # OLD: No fallback
            from src.core.resilient_llm_service import ResilientLLMService  # NEW: With Claude SDK fallback

            # Initialize services with Claude SDK fallback (enabled by default)
            # For rollback: uncomment LLMService import above and use: llm_service = LLMService({})
            llm_service = ResilientLLMService({})  # With Claude SDK fallback
            
            # Create workflow instance
            workflow = HybridRAGWorkflow()
            
            # Configure hybrid analysis
            hybrid_config = {
                # PageIndex retrieval config (primary path)
                "pageindex_config": {
                    "project_path": project_path,
                    "mcts_iterations": mcts_iterations,
                },

                # Vector retrieval config
                "vector_config": {
                    "collection_name": collection_name,
                    "vector_db": vector_db,
                    "config_path": vector_config_path,  # MCP config for vector database
                    "max_results": max_results,
                    "enable_reasoning": enable_reasoning,
                    "max_branches": max_branches
                },

                # CPG retrieval config (for Multi-Agent CoT via graph_rag)
                "cpg_config": {
                    "config_path": config_path,
                    "schema_path": schema_path,
                    "llm_model": llm_model,
                    "max_agent_iterations": max_cot_iterations,
                    "max_verifier_iterations": max_verifier_iterations,
                    "parallel_agents": parallel_agents,
                    "enable_verification": enable_verification,
                    "enable_entity_resolution": enable_entity_resolution,
                    # 4-Agent Team configuration
                    "use_4_agent_team": use_4_agent_team,
                    "four_agent_max_iterations": four_agent_max_iterations
                },

                # Context management
                "batch_size": batch_size,
                "max_context_limit": max_context_limit,

                # Retriever combination
                "retriever_combination": retriever_combination,
            }
            
            # Execute hybrid workflow directly
            workflow_result = await workflow.run_analysis(
                user_query=user_query,
                llm_service=llm_service,
                config=hybrid_config
            )

            # Release LLM cache and run GC after each query
            llm_service.clear_cache()
            gc.collect()

            if workflow_result.get("status") == "success":
                logger.info("✅ Hybrid RAG analysis completed successfully")

                # Extract nested results for flattening
                synthesis = workflow_result.get("synthesis", {})
                raw_results_nested = workflow_result.get("raw_results", {})
                performance = workflow_result.get("performance", {})

                # Get the main response text
                main_response = synthesis.get("answer", "") if isinstance(synthesis, dict) else str(synthesis)

                # Flatten raw results for benchmarking
                vector_raw_results = raw_results_nested.get("vector_results", []) if isinstance(raw_results_nested, dict) else []
                cpg_raw_results = raw_results_nested.get("cpg_results", []) if isinstance(raw_results_nested, dict) else []
                combined_results = raw_results_nested.get("combined_results", []) if isinstance(raw_results_nested, dict) else []

                # Use combined_results if available, otherwise merge vector + cpg
                flat_raw_results = combined_results if combined_results else vector_raw_results + cpg_raw_results

                # Format response for MCP compatibility and benchmarking
                return {
                    "status": "success",
                    "tool_name": "query_hybrid_rag",
                    "analysis_type": "hybrid_rag",
                    "user_query": user_query,
                    "project_name": project_name,
                    "collection_name": collection_name,

                    # Main Results (consistent with other tools for benchmarking)
                    "response": main_response,
                    "ai_response": main_response,  # Alias for compatibility
                    "details": synthesis.get("details", "") if isinstance(synthesis, dict) else "",
                    "synthesis": synthesis,  # Keep original dict for detailed access
                    "synthesis_status": synthesis.get("status", "success") if isinstance(synthesis, dict) else "success",

                    # Raw Results for Benchmarking (ESSENTIAL for reference-based metrics)
                    # Flattened format expected by benchmark script
                    "raw_results": flat_raw_results,
                    "vector_raw_results": vector_raw_results,
                    "cpg_raw_results": cpg_raw_results,

                    # Hybrid-Specific Metadata (minimal for benchmarking)
                    "synthesis_strategy": synthesis.get("strategy_used", "") if isinstance(synthesis, dict) else "",
                    "synthesis_confidence": synthesis.get("confidence", 0.0) if isinstance(synthesis, dict) else 0.0,
                    "cross_validation": synthesis.get("cross_validation", {}) if isinstance(synthesis, dict) else {},
                    "intent_analysis": workflow_result.get("intent_analysis", {}),

                    # Quality Validation (for evaluation)
                    "critic_validation": workflow_result.get("critic_validation", {}),

                    # Performance (for benchmarking) - flattened
                    "total_execution_time": performance.get("total_execution_time", 0.0),
                    "vector_execution_time": performance.get("vector_execution_time", 0.0),
                    "cpg_execution_time": performance.get("cpg_execution_time", 0.0),

                    # Retrieval metadata for detailed analysis
                    "retrieval_results": workflow_result.get("retrieval_results", {}),

                    # Full Individual RAG Responses (for running hybrid-only and extracting individual results)
                    # These contain complete responses from each retriever as if run independently
                    "pageindex_full_response": workflow_result.get("pageindex_full_response", {}),
                    "vector_full_response": workflow_result.get("vector_full_response", {}),
                    "cpg_full_response": workflow_result.get("cpg_full_response", {}),

                    "message": "✅ Hybrid RAG analysis completed successfully"
                }
            else:
                logger.error(f"❌ Hybrid RAG analysis failed: {workflow_result.get('error', 'Unknown error')}")
                return {
                    "status": "error", 
                    "tool_name": "query_hybrid_rag",
                    "error": workflow_result.get("error", "Hybrid workflow failed"),
                    "user_query": user_query,
                    "project_name": project_name,
                    "collection_name": collection_name,
                    "partial_results": {
                        "synthesis": workflow_result.get("synthesis", {}),
                        "raw_results": workflow_result.get("raw_results", {}),
                        "performance": workflow_result.get("performance", {})
                    },
                    "message": f"❌ Hybrid RAG failed: {workflow_result.get('error', 'Unknown error')}"
                }
                
        except ImportError as e:
            logger.error(f"❌ Hybrid RAG workflow import failed: {e}")
            return {
                "status": "error",
                "tool_name": "query_hybrid_rag", 
                "error": f"Hybrid RAG workflow not available: {e}",
                "fallback_suggestions": [
                    "Use query_cpg_rag for CPG-only analysis",
                    "Use query_vector_only for vector-only analysis", 
                    "Use query_comprehensive_rag for basic hybrid analysis"
                ],
                "user_query": user_query,
                "project_name": project_name,
                "collection_name": collection_name
            }
        except Exception as e:
            import traceback
            logger.error(f"❌ Hybrid RAG analysis failed: {e}")
            return {
                "status": "error",
                "tool_name": "query_hybrid_rag",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "user_query": user_query,
                "project_name": project_name,
                "collection_name": collection_name,
                "message": f"❌ Hybrid RAG failed with exception: {str(e)}"
            }

    @mcp.tool()
    async def query_hybrid_fast_rag(
        user_query: str,
        project_path: str = "/opt/HelloWorldApp",
        mcts_iterations: int = 20,
        collection_name: str = "HelloWorldApp_pageindex_v3",
        neo4j_config_path: str = "/opt/genpod/neo4j_config.json",
        qdrant_config_path: str = "/opt/genpod/qdrant_config.json",
        schema_path: str = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml",
        max_hops: int = 5,
        max_results: int = 5,
    ) -> dict:
        """
        🚀 HYBRID FAST RAG: Multi-hop orchestrator for quick, precise code analysis.

        An orchestrator LLM dynamically routes queries across three database agents
        in a multi-hop trajectory — querying PageIndex, Vector, and Graph databases
        in whatever order and combination best answers the question.

        USE THIS TOOL WHEN:
        - You need a faster response than query_hybrid_rag
        - The query benefits from multi-hop reasoning across databases
        - You want the orchestrator to decide the retrieval strategy adaptively

        USE query_hybrid_rag WHEN:
        - You need the most comprehensive analysis (full synthesis + critic validation)
        - Query complexity requires the full multi-agent CPG workflow

        AGENTS:
        - PageIndex: file hierarchy navigation via MCTS
        - Vector: semantic search via Qdrant MCP (direct tool call)
        - Graph: schema-aware CPG queries via Neo4j MCP (ReAct loop with schema tools)

        Args:
            user_query: Natural language question about the codebase
            project_path: Path to project root for PageIndex
            mcts_iterations: MCTS iterations for PageIndex (default: 20)
            collection_name: Qdrant collection for vector search
            neo4j_config_path: Neo4j MCP server config
            qdrant_config_path: Qdrant MCP server config
            schema_path: CPG schema YAML for graph agent
            max_hops: Maximum orchestrator hops before forcing synthesis (default: 5)
            max_results: Max results per vector search (default: 5)

        Returns:
            dict with answer, hop_count, hops (trajectory), error_log
        """
        try:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"🚀 Hybrid Fast RAG starting: {user_query}")

            from src.core.hybrid_fast_workflow import HybridFastWorkflow

            workflow = HybridFastWorkflow(max_hops=max_hops)

            config = {
                "project_path": project_path,
                "mcts_iterations": mcts_iterations,
                "collection_name": collection_name,
                "neo4j_config_path": neo4j_config_path,
                "qdrant_config_path": qdrant_config_path,
                "schema_path": schema_path,
                "max_results": max_results,
            }

            result = await workflow.run_analysis(user_query=user_query, config=config)

            logger.info(f"✅ Hybrid Fast RAG complete: {result.get('hop_count', 0)} hops")
            return result

        except Exception as e:
            import traceback
            logger.error(f"❌ Hybrid Fast RAG failed: {e}")
            return {
                "status": "error",
                "tool_name": "query_hybrid_fast_rag",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "user_query": user_query,
            }

    # # ===== [LEGACY] Pure Query Tools (No Side Effects) =====
    
    # @mcp.tool()
    # async def query_cpg_only(
    #     cypher_query: str = None,
    #     config_path: str = "configs/neo4j_mcp_config.yaml",
    #     max_results: int = 100,
    #     user_query: str = None,
    #     enable_synthesis: bool = True,
    #     enable_advanced_rag: bool = True
    # ) -> dict:
    #     """
    #     Enhanced CPG querying with entity-driven subgraph retrieval and intelligent synthesis.
        
    #     This tool supports both traditional Cypher queries and advanced semantic queries
    #     using entity extraction, subgraph planning, and intent-based synthesis.
        
    #     Args:
    #         cypher_query: Direct Cypher query to execute (optional if user_query provided)
    #         config_path: Path to Neo4j MCP configuration
    #         max_results: Maximum number of results to return
    #         user_query: Natural language query for semantic analysis (optional)
    #         enable_synthesis: Whether to synthesize results with LLM (default: True)
    #         enable_advanced_rag: Whether to use advanced Graph RAG features (default: True)
    #     """
    #     try:
    #         # NEW ADVANCED RAG WORKFLOW
    #         if enable_advanced_rag and user_query and not cypher_query:
    #             print(f"🔍 DEBUG - Starting Enhanced RAG workflow for query: {user_query}")
    #             try:
    #                 # Import advanced RAG components
    #                 from src.core.entity_extraction_service import EntityExtractionService
    #                 from src.core.subgraph_planner import SubgraphPlanner
    #                 from src.core.graph_query_executor import GraphQueryExecutor
    #                 from src.core.content_reranker import ContentReranker
    #                 from src.core.llm_service import LLMService
                    
    #                 # Initialize LLM service
    #                 llm_service = LLMService({
    #                     "cache_ttl": _project_config.get("llm_cache_ttl", 1800)
    #                 })
                    
    #                 # Step 1: Create graph executor for entity extraction
    #                 executor = GraphQueryExecutor()
                    
    #                 # Step 2: Extract entities from user query (with graph access)
    #                 entity_service = EntityExtractionService(llm_service, graph_executor=executor)
    #                 entities = await entity_service.extract_entities(user_query)
    #                 print(f"🔍 DEBUG - Extracted entities: {entities}")
                    
    #                 # Step 3: Plan subgraph retrieval strategy
    #                 planner = SubgraphPlanner()
    #                 plan = await planner.plan_retrieval(entities, user_query)
    #                 print(f"🔍 DEBUG - Retrieval plan: {plan}")
                    
    #                 # Step 4: Execute planned subgraph queries
    #                 print(f"🔍 DEBUG - About to execute subgraph retrieval with config: {config_path}")
    #                 raw_results = await executor.execute_subgraph_retrieval(plan, config_path)
    #                 print(f"🔍 DEBUG - Raw results received: {raw_results}")
                    
    #                 # Step 4: Rerank results by relevance
    #                 reranker = ContentReranker()
    #                 ranked_context = await reranker.rerank_subgraph_results(
    #                     raw_results.get("combined_results", []), 
    #                     entities,
    #                     entities  # Pass entities as intent context
    #                 )
                    
    #                 # Step 5: Synthesize targeted response
    #                 if enable_synthesis:
    #                     final_answer = await llm_service.synthesize_targeted_response(
    #                         ranked_context, user_query, entities
    #                     )
                        
    #                     # MAINTAIN BACKWARD COMPATIBILITY: Use original format structure
    #                     return {
    #                         "status": "success",
    #                         "cypher_query": raw_results.get("executed_queries", ["Advanced RAG query"])[0] if raw_results.get("executed_queries") else "Advanced RAG multi-query",
    #                         "raw_results": raw_results.get("combined_results", []),
    #                         "synthesis": final_answer.get("answer", ""),
    #                         "synthesis_status": "success",
    #                         "synthesis_metadata": final_answer.get("metadata", {}),
    #                         "analysis_type": "advanced_rag",
    #                         # ENHANCED FIELDS (new additions)
    #                         "workflow": "advanced_rag",
    #                         "entities_extracted": entities,
    #                         "retrieval_plan": plan,
    #                         "intent_detected": final_answer.get("intent_detected", {}),
    #                         "advanced_rag_metadata": {
    #                             "raw_results_count": raw_results.get("total_nodes", 0),
    #                             "ranked_results_count": ranked_context.get("top_k_selected", 0),
    #                             "query_execution": raw_results.get("query_performance", {}),
    #                             "ranking_metadata": ranked_context.get("ranking_metadata", {})
    #                         }
    #                     }
    #                 else:
    #                     # Return raw ranked results without synthesis
    #                     return {
    #                         "status": "success",
    #                         "workflow": "advanced_rag_no_synthesis",
    #                         "entities_extracted": entities,
    #                         "retrieval_plan": plan,
    #                         "raw_results": raw_results,
    #                         "ranked_results": ranked_context,
    #                         "synthesis_enabled": False
    #                     }
                        
    #             except Exception as advanced_error:
    #                 print(f"🚨 DEBUG - Advanced RAG failed with error: {str(advanced_error)}")
    #                 print(f"🚨 DEBUG - Error type: {type(advanced_error).__name__}")
    #                 import traceback
    #                 print(f"🚨 DEBUG - Full traceback: {traceback.format_exc()}")
    #                 # Advanced RAG failed, fall back to basic query generation
    #                 try:
    #                     from src.core.llm_service import LLMService
    #                     llm_service = LLMService({
    #                         "cache_ttl": _project_config.get("llm_cache_ttl", 1800)
    #                     })
                        
    #                     # Generate basic Cypher query from user query
    #                     cypher_result = await llm_service.generate_cypher_query(
    #                         {"user_query": user_query}, user_query
    #                     )
                        
    #                     if cypher_result and cypher_result.get("primary_query"):
    #                         cypher_query = cypher_result["primary_query"]
    #                     else:
    #                         return {
    #                             "status": "error",
    #                             "error": f"Advanced RAG failed and could not generate fallback query: {str(advanced_error)}",
    #                             "fallback_attempted": True
    #                         }
    #                 except Exception as fallback_error:
    #                     return {
    #                         "status": "error",
    #                         "error": f"Both advanced RAG and fallback failed: Advanced={str(advanced_error)}, Fallback={str(fallback_error)}",
    #                         "advanced_rag_error": str(advanced_error),
    #                         "fallback_error": str(fallback_error)
    #                     }
            
    #         # EXISTING CYPHER QUERY WORKFLOW (enhanced)
    #         if not cypher_query:
    #             return {
    #                 "status": "error",
    #                 "error": "Either cypher_query or user_query must be provided"
    #             }
            
    #         # Execute the CPG query
    #         cli_command = [
    #             "project-analyzer",
    #             "--config-file", config_path,
    #             "query",
    #             "--cypher", cypher_query,
    #             "--limit", str(max_results),
    #             "--output-format", "json"
    #         ]
            
    #         result = subprocess.run(
    #             cli_command,
    #             text=True,
    #             capture_output=True,
    #             check=False,
    #             cwd=os.getcwd()
    #         )
            
    #         # Process query results
    #         if result.returncode == 0:
    #             try:
    #                 parsed_results = json.loads(result.stdout)
    #                 query_result = {
    #                     "status": "success",
    #                     "results": parsed_results
    #                 }
    #             except json.JSONDecodeError:
    #                 query_result = {
    #                     "status": "success",
    #                     "results": result.stdout,
    #                     "note": "Raw output (not JSON)"
    #                 }
    #         else:
    #             query_result = {
    #                 "status": "error",
    #                 "error": result.stderr,
    #                 "stdout": result.stdout,
    #                 "returncode": result.returncode
    #             }
            
    #         # If synthesis is disabled or query failed, return raw results
    #         if not enable_synthesis or query_result["status"] == "error":
    #             return {
    #                 **query_result,
    #                 "cypher_query": cypher_query,
    #                 "synthesis_enabled": False
    #             }
            
    #         # If synthesis is enabled and we have a user query, synthesize results
    #         if user_query:
    #             try:
    #                 from core.llm_service import LLMService
                    
    #                 llm_service = LLMService({
    #                     "cache_ttl": _project_config.get("llm_cache_ttl", 1800)
    #                 })
                    
    #                 # Format CPG results for synthesis
    #                 cpg_results = [{
    #                     "cypher_query": cypher_query,
    #                     "purpose": "User-provided CPG query",
    #                     "status": query_result["status"],
    #                     "result": query_result.get("results", query_result.get("error", ""))
    #                 }]
                    
    #                 # Synthesize comprehensive response
    #                 synthesis_result = await llm_service.synthesize_comprehensive_response(
    #                     user_query=user_query,
    #                     vector_results="No vector search performed (CPG-only analysis)",
    #                     cpg_results=cpg_results,
    #                     max_tokens=2000
    #                 )
                    
    #                 return {
    #                     "status": "success",
    #                     "cypher_query": cypher_query,
    #                     "raw_results": query_result["results"],
    #                     "synthesis": synthesis_result.get("synthesis", "Synthesis failed"),
    #                     "synthesis_status": synthesis_result.get("status", "unknown"),
    #                     "synthesis_metadata": synthesis_result.get("metadata", {}),
    #                     "analysis_type": "cpg_with_synthesis"
    #                 }
                    
    #             except ImportError:
    #                 # LLM service not available, return raw results with note
    #                 return {
    #                     **query_result,
    #                     "cypher_query": cypher_query,
    #                     "synthesis_enabled": False,
    #                     "synthesis_note": "LLM service not available for synthesis"
    #                 }
    #             except Exception as synthesis_error:
    #                 # Synthesis failed, return raw results with error
    #                 return {
    #                     **query_result,
    #                     "cypher_query": cypher_query,
    #                     "synthesis_enabled": False,
    #                     "synthesis_error": str(synthesis_error)
    #                 }
    #         else:
    #             # No user query provided, return raw results with note
    #             return {
    #                 **query_result,
    #                 "cypher_query": cypher_query,
    #                 "synthesis_enabled": False,
    #                 "synthesis_note": "No user_query provided for synthesis context"
    #             }
                
    #     except Exception as e:
    #         return {
    #             "status": "error", 
    #             "step": "query_cpg_only",
    #             "error": str(e),
    #             "traceback": traceback.format_exc()
    #         }

    # ===== Orchestrated Workflow Tools =====
    
    
    # ===== LLM-Powered Comprehensive Analysis Tools =====
    
    # @mcp.tool()
    # async def comprehensive_code_analysis(
    #     user_query: str,
    #     project_path: str,
    #     collection_name: str,
    #     vector_config: str = None,
    #     neo4j_config: str = "configs/neo4j_mcp_config.yaml",
    #     max_vector_results: int = 10,
    #     max_graph_results: int = 50,
    #     max_final_results: int = 20,
    #     vector_weight: float = 0.4,
    #     graph_weight: float = 0.6,
    #     use_hybrid_retrieval: bool = True,
    #     llm_provider: str = "openai"
    # ) -> dict:
    #     """
    #     Enhanced comprehensive code analysis using hybrid retrieval (Vector + Enhanced Graph RAG).
        
    #     NEW HYBRID WORKFLOW:
    #     1. Entity extraction & intent classification (Enhanced RAG)
    #     2. Parallel retrieval: Vector search + Enhanced Graph RAG  
    #     3. Cross-modal fusion with intelligent deduplication
    #     4. Hybrid reranking using multiple relevance signals
    #     5. Multi-modal synthesis combining both approaches
        
    #     Args:
    #         user_query: Natural language query for code analysis
    #         project_path: Path to the project being analyzed
    #         collection_name: ChromaDB collection name for vector search
    #         vector_config: Optional config file for vector search
    #         neo4j_config: Config file for Neo4j connections
    #         max_vector_results: Maximum results from vector search
    #         max_graph_results: Maximum results from Enhanced Graph RAG
    #         max_final_results: Maximum results after hybrid fusion
    #         vector_weight: Weight for vector search results (0.0-1.0)
    #         graph_weight: Weight for graph RAG results (0.0-1.0)
    #         use_hybrid_retrieval: Whether to use new hybrid approach
    #         llm_provider: LLM provider to use (openai, anthropic)
    #     """
    #     try:
    #         if use_hybrid_retrieval:
    #             # NEW HYBRID RETRIEVAL APPROACH
    #             from src.core.hybrid_retrieval_service import HybridRetrievalService
                
    #             # Initialize hybrid retrieval service
    #             hybrid_service = HybridRetrievalService({
    #                 "vector_weight": vector_weight,
    #                 "graph_weight": graph_weight,
    #                 "fusion_threshold": 0.3
    #             })
                
    #             # Execute comprehensive hybrid retrieval
    #             hybrid_result = await hybrid_service.comprehensive_retrieve(
    #                 user_query=user_query,
    #                 vector_params={
    #                     "collection_name": collection_name,
    #                     "max_results": max_vector_results,
    #                     "config": vector_config
    #                 },
    #                 graph_params={
    #                     "config_path": neo4j_config,
    #                     "max_results": max_graph_results
    #                 },
    #                 max_results=max_final_results
    #             )
                
    #             # Extract raw results for benchmarking compatibility (directly from hybrid service)
    #             vector_raw_results = hybrid_result.get("vector_raw_results", [])
    #             graph_raw_results = hybrid_result.get("cpg_raw_results", [])
                
    #             # Return hybrid results in comprehensive analysis format with RAW RESULTS
    #             return {
    #                 "status": hybrid_result.get("status", "success"),
    #                 "analysis_type": "hybrid_comprehensive_analysis",
    #                 "user_query": user_query,
    #                 "project_path": project_path,
    #                 "workflow": "hybrid_vector_graph_rag",
                    
    #                 # RAW RESULTS FOR BENCHMARKING (crucial for reference-based metrics)
    #                 "vector_raw_results": vector_raw_results,
    #                 "cpg_raw_results": graph_raw_results,
    #                 "hybrid_results": hybrid_result.get("hybrid_results", []),  # Fix: Add missing top-level hybrid_results
                    
    #                 # TOP-LEVEL SYNTHESIS AND ENTITIES (for test compatibility)
    #                 "synthesis": hybrid_result.get("synthesis", ""),
    #                 "entities_extracted": hybrid_result.get("entities_extracted", {}),
                    
    #                 "results": {
    #                     "entities_extracted": hybrid_result.get("entities_extracted", {}),
    #                     "intent_detected": hybrid_result.get("intent_detected", {}),
    #                     "retrieval_performance": hybrid_result.get("retrieval_results", {}),
    #                     "synthesis": hybrid_result.get("synthesis", ""),
    #                     "synthesis_metadata": hybrid_result.get("synthesis_metadata", {}),
    #                     "performance_metrics": hybrid_result.get("performance", {}),
                        
    #                     "summary": {
    #                         "total_sources": len(hybrid_result.get("hybrid_results", [])),
    #                         "vector_sources": hybrid_result.get("retrieval_results", {}).get("vector", {}).get("count", 0),
    #                         "graph_sources": hybrid_result.get("retrieval_results", {}).get("graph", {}).get("count", 0),
    #                         "vector_raw_count": len(vector_raw_results),
    #                         "cpg_raw_count": len(graph_raw_results),
    #                         "fusion_applied": True,
    #                         "hybrid_reranking": True,
    #                         "multi_modal_synthesis": True
    #                     }
    #                 },
    #                 "message": f"Hybrid analysis completed: {hybrid_result.get('retrieval_results', {}).get('vector', {}).get('count', 0)} vector + {hybrid_result.get('retrieval_results', {}).get('graph', {}).get('count', 0)} graph sources → {len(hybrid_result.get('hybrid_results', []))} final results"
    #             }
                
    #         else:
    #             # FALLBACK TO LEGACY APPROACH (for backward compatibility)
    #             from src.core.llm_service import LLMService
                
    #             # Initialize LLM service
    #             llm_service = LLMService({
    #                 "preferred_provider": llm_provider,
    #                 "cache_ttl": 1800  # 30 minutes
    #             })
                
    #             # Legacy approach: Basic vector + CPG synthesis
    #             return {
    #                 "status": "success",
    #                 "analysis_type": "legacy_comprehensive_analysis", 
    #                 "user_query": user_query,
    #                 "project_path": project_path,
    #                 "workflow": "legacy_vector_cpg_synthesis",
    #                 "results": {
    #                     "message": "Legacy mode - use hybrid_retrieval=True for enhanced analysis",
    #                     "recommendation": "Set use_hybrid_retrieval=True to enable Enhanced Graph RAG with vector fusion"
    #                 },
    #                 "message": "Legacy analysis mode. Enable hybrid_retrieval for enhanced capabilities."
    #             }
                
    #     except Exception as e:
    #         return {
    #             "status": "error",
    #             "analysis_type": "comprehensive_code_analysis", 
    #             "error": str(e),
    #             "user_query": user_query,
    #             "project_path": project_path,
    #             "message": f"Comprehensive analysis failed: {str(e)}"
    #         }
            
    #         # ========== LEGACY CODE BELOW - TO BE REMOVED AFTER TESTING ==========
    #         # TODO: Remove this entire legacy implementation once hybrid retrieval is tested and verified
            
    #         # Step 1: Vector search using genpod-semantic-rag
    #         analysis_results["steps"]["1_vector_search"] = {"status": "running"}
            
    #         vector_result = await query_vector_only(
    #             query=user_query,
    #             collection_name=collection_name,
    #             max_results=max_vector_results,
    #             config=vector_config
    #         )
            
    #         if vector_result["status"] != "success":
    #             return {
    #                 "status": "error",
    #                 "step": "vector_search",
    #                 "error": vector_result.get("error", "Vector search failed"),
    #                 "partial_results": analysis_results
    #             }
            
    #         analysis_results["steps"]["1_vector_search"] = {
    #             "status": "completed",
    #             "result_count": len(vector_result.get("raw_results", [])) if isinstance(vector_result.get("raw_results"), list) else 1,
    #             "raw_output": vector_result.get("raw_results", [])
    #         }
            
    #         # Step 2: LLM filtering and analysis
    #         if use_llm_filtering:
    #             analysis_results["steps"]["2_llm_filtering"] = {"status": "running"}
                
    #             filtered_results = await llm_service.filter_code_results(
    #                 vector_results=str(vector_result.get("raw_results", [])),
    #                 query=user_query
    #             )
                
    #             if "error" in filtered_results:
    #                 analysis_results["steps"]["2_llm_filtering"] = {
    #                     "status": "failed",
    #                     "error": filtered_results["error"],
    #                     "fallback": "proceeding_with_raw_results"
    #                 }
    #                 # Continue with raw results
    #                 filtered_data = {"raw_results": vector_result["results"]}
    #             else:
    #                 analysis_results["steps"]["2_llm_filtering"] = {
    #                     "status": "completed",
    #                     "llm_metadata": filtered_results.get("llm_metadata", {}),
    #                     "key_concepts": filtered_results.get("key_concepts", []),
    #                     "suggested_targets": filtered_results.get("suggested_cypher_targets", [])
    #                 }
    #                 filtered_data = filtered_results
    #         else:
    #             filtered_data = {"raw_results": vector_result["results"]}
    #             analysis_results["steps"]["2_llm_filtering"] = {
    #                 "status": "skipped",
    #                 "reason": "LLM filtering disabled"
    #             }
            
    #         # Step 3: Generate and execute Cypher queries with error feedback loop
    #         analysis_results["steps"]["3_cypher_generation"] = {"status": "running"}
            
    #         # Initialize retry tracking
    #         max_retries = 3
    #         successful_queries = []
    #         retry_history = []
            
    #         # Try to generate and execute queries with error feedback
    #         for attempt in range(max_retries + 1):  # 0, 1, 2, 3 (total 4 attempts)
    #             try:
    #                 # Generate queries (with error feedback on retries)
    #                 if attempt == 0:
    #                     # First attempt - no error feedback
    #                     cypher_data = await llm_service.generate_cypher_query(
    #                         filtered_results=filtered_data,
    #                         user_query=user_query
    #                     )
    #                 else:
    #                     # Retry with error feedback from previous attempts
    #                     error_feedback = {
    #                         "previous_queries": [h["query"] for h in retry_history],
    #                         "previous_errors": [h["error"] for h in retry_history],
    #                         "retry_attempt": attempt,
    #                         "instructions": "The previous queries failed. Please fix the syntax and logic errors. Make sure to use proper Neo4j Cypher syntax and match the available node types and properties."
    #                     }
                        
    #                     cypher_data = await llm_service.generate_cypher_query(
    #                         filtered_results=filtered_data,
    #                         user_query=user_query,
    #                         error_feedback=error_feedback
    #                     )
                    
    #                 # Check if query generation failed
    #                 if "error" in cypher_data:
    #                     retry_history.append({
    #                         "attempt": attempt,
    #                         "query": "generation_failed",
    #                         "error": cypher_data["error"],
    #                         "type": "generation_error"
    #                     })
    #                     continue
                    
    #                 # Extract queries to test
    #                 queries_to_test = []
    #                 if "primary_query" in cypher_data:
    #                     queries_to_test.append(("primary", cypher_data["primary_query"]))
    #                 if "supporting_queries" in cypher_data:
    #                     for i, sq in enumerate(cypher_data["supporting_queries"]):
    #                         # Handle both string and object formats
    #                         if isinstance(sq, dict) and "query" in sq:
    #                             # Supporting query is an object with query and explanation
    #                             queries_to_test.append((f"supporting_{i}", sq["query"]))
    #                         elif isinstance(sq, str):
    #                             # Supporting query is a string
    #                             queries_to_test.append((f"supporting_{i}", sq))
    #                         else:
    #                             # Invalid format, skip this query
    #                             continue
                    
    #                 if not queries_to_test:
    #                     retry_history.append({
    #                         "attempt": attempt,
    #                         "query": "no_queries_generated",
    #                         "error": "LLM did not generate any queries",
    #                         "type": "generation_error"
    #                     })
    #                     continue
                    
    #                 # Test each generated query
    #                 attempt_successful = True
    #                 attempt_errors = []
                    
    #                 for query_type, query in queries_to_test:
    #                     try:
    #                         query_result = await query_cpg_only(
    #                             cypher_query=query,
    #                             config_path=neo4j_config,
    #                             max_results=max_cpg_results
    #                         )
                            
    #                         if query_result["status"] == "success":
    #                             successful_queries.append({
    #                                 "query_type": query_type,
    #                                 "cypher_query": query,
    #                                 "status": "success",
    #                                 "results": query_result.get("results", ""),
    #                                 "attempt": attempt
    #                             })
    #                         else:
    #                             # Query execution failed
    #                             error_msg = query_result.get("error", "Unknown query execution error")
    #                             attempt_errors.append({
    #                                 "query": query,
    #                                 "error": error_msg,
    #                                 "type": "execution_error"
    #                             })
    #                             attempt_successful = False
                        
    #                     except Exception as e:
    #                         # Exception during query execution
    #                         attempt_errors.append({
    #                             "query": query,
    #                             "error": str(e),
    #                             "type": "execution_exception"
    #                         })
    #                         attempt_successful = False
                    
    #                 # If we have at least one successful query, we can proceed
    #                 if successful_queries:
    #                     # Record this attempt's status
    #                     analysis_results["steps"]["3_cypher_generation"] = {
    #                         "status": "completed",
    #                         "attempt": attempt,
    #                         "llm_metadata": cypher_data.get("llm_metadata", {}),
    #                         "query_explanation": cypher_data.get("query_explanation", {}),
    #                         "successful_queries": len(successful_queries),
    #                         "queries": [q["cypher_query"] for q in successful_queries],
    #                         "retry_history": retry_history
    #                     }
    #                     break
    #                 else:
    #                     # All queries failed, record for next retry
    #                     for error_info in attempt_errors:
    #                         retry_history.append({
    #                             "attempt": attempt,
    #                             "query": error_info["query"],
    #                             "error": error_info["error"],
    #                             "type": error_info["type"]
    #                         })
                
    #             except Exception as e:
    #                 # Unexpected error during the entire attempt
    #                 retry_history.append({
    #                     "attempt": attempt,
    #                     "query": "unexpected_error",
    #                     "error": str(e),
    #                     "type": "system_error"
    #                 })
            
    #         # If no successful queries after all retries, fall back to basic queries
    #         if not successful_queries:
    #             analysis_results["steps"]["3_cypher_generation"] = {
    #                 "status": "failed_all_retries",
    #                 "max_retries": max_retries,
    #                 "retry_history": retry_history,
    #                 "fallback": "using_basic_queries",
    #                 "queries": []
    #             }
                
    #             # Execute basic fallback queries
    #             basic_queries = [
    #                 "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 10",
    #                 "MATCH (c:Class) RETURN c.name, c.file_path LIMIT 10",
    #                 "MATCH (t:Type) RETURN t.name, t.file_path LIMIT 10"
    #             ]
                
    #             for i, query in enumerate(basic_queries):
    #                 try:
    #                     query_result = await query_cpg_only(
    #                         cypher_query=query,
    #                         config_path=neo4j_config,
    #                         max_results=max_cpg_results
    #                     )
    #                     successful_queries.append({
    #                         "query_type": f"basic_fallback_{i}",
    #                         "cypher_query": query,
    #                         "status": query_result["status"],
    #                         "results": query_result.get("results", ""),
    #                         "error": query_result.get("error"),
    #                         "attempt": "fallback"
    #                     })
    #                 except Exception as e:
    #                     successful_queries.append({
    #                         "query_type": f"basic_fallback_{i}",
    #                         "cypher_query": query,
    #                         "status": "error",
    #                         "error": str(e),
    #                         "attempt": "fallback"
    #                     })
                
    #             # Update cypher generation step with fallback queries
    #             analysis_results["steps"]["3_cypher_generation"]["queries"] = [q["cypher_query"] for q in successful_queries]
            
    #         # Step 4: Aggregate CPG query results with proper raw data extraction
    #         cpg_raw_results = []
    #         for query_result in successful_queries:
    #             if query_result.get("status") == "success":
    #                 # Extract raw results from the CPG query response
    #                 raw_data = query_result.get("results", {})
    #                 if isinstance(raw_data, str):
    #                     try:
    #                         # Try to parse JSON response from project-analyzer
    #                         parsed_data = json.loads(raw_data)
    #                         if isinstance(parsed_data, list):
    #                             cpg_raw_results.extend(parsed_data)
    #                         elif isinstance(parsed_data, dict):
    #                             cpg_raw_results.append(parsed_data)
    #                     except json.JSONDecodeError:
    #                         # If not JSON, treat as text result
    #                         cpg_raw_results.append({
    #                             "query": query_result.get("cypher_query", ""),
    #                             "result_text": raw_data,
    #                             "query_type": query_result.get("query_type", "unknown")
    #                         })
    #                 elif isinstance(raw_data, (list, dict)):
    #                     # Already structured data
    #                     if isinstance(raw_data, list):
    #                         cpg_raw_results.extend(raw_data)
    #                     else:
    #                         cpg_raw_results.append(raw_data)
            
    #         analysis_results["steps"]["4_cpg_queries"] = {
    #             "status": "completed",
    #             "total_queries_attempted": len(retry_history) + len(successful_queries),
    #             "successful_queries": len([q for q in successful_queries if q["status"] == "success"]),
    #             "failed_queries": len([q for q in successful_queries if q["status"] != "success"]),
    #             "results": successful_queries,
    #             "raw_results": cpg_raw_results  # Add extracted raw results
    #         }
            
    #         cpg_results = successful_queries  # For backward compatibility
            
    #         # Step 5: Final comprehensive synthesis
    #         successful_query_count = len([r for r in cpg_results if r.get("status") == "success"])
    #         analysis_results["steps"]["5_synthesis"] = {"status": "running"}
            
    #         # Perform comprehensive synthesis using both vector and CPG results
    #         try:
    #             synthesis_result = await llm_service.synthesize_comprehensive_response(
    #                 user_query=user_query,
    #                 vector_results=vector_result.get("raw_results", []),
    #                 cpg_results=cpg_results,
    #                 max_tokens=2000
    #             )
    #             comprehensive_response = synthesis_result.get("synthesis", "Synthesis failed")
                
    #             analysis_results["steps"]["5_synthesis"] = {
    #                 "status": "completed",
    #                 "comprehensive_response": comprehensive_response,
    #                 "synthesis_metadata": synthesis_result.get("metadata", {}),
    #                 "summary": {
    #                     "vector_search_results": len(vector_result.get("results", [])) if isinstance(vector_result.get("results"), list) else 1,
    #                     "llm_filtering_applied": use_llm_filtering and "error" not in filtered_data,
    #                     "cypher_queries_generated": len(cpg_results),
    #                     "successful_cpg_queries": successful_query_count,
    #                     "analysis_complete": True,
    #                     "synthesis_generated": True,
    #                     "synthesis_status": synthesis_result.get("status", "unknown")
    #                 }
    #             }
                
    #         except Exception as synthesis_error:
    #             analysis_results["steps"]["5_synthesis"] = {
    #                 "status": "failed",
    #                 "synthesis_error": str(synthesis_error),
    #                 "summary": {
    #                     "vector_search_results": len(vector_result.get("results", [])) if isinstance(vector_result.get("results"), list) else 1,
    #                     "llm_filtering_applied": use_llm_filtering and "error" not in filtered_data,
    #                     "cypher_queries_generated": len(cpg_results),
    #                     "successful_cpg_queries": successful_query_count,
    #                     "analysis_complete": True,
    #                     "synthesis_generated": False
    #                 }
    #             }
            
    #         analysis_results["status"] = "success"
            
    #         return {
    #             "status": "success",
    #             "analysis_type": "comprehensive_vector_cpg_analysis",
    #             "results": analysis_results,
    #             "message": f"Analysis completed: {len([r for r in cpg_results if r.get('status') == 'success'])}/{len(cpg_results)} CPG queries successful"
    #         }
            
    #         # ========== END OF LEGACY CODE - TO BE REMOVED AFTER TESTING ==========
            
    #     except Exception as e:
    #         return {
    #             "status": "error",
    #             "step": "comprehensive_analysis", 
    #             "error": str(e),
    #             "traceback": traceback.format_exc(),
    #             "partial_results": analysis_results if 'analysis_results' in locals() else None
    #         }

    # ===== LLM Management and Configuration Tools =====

    # ===== NEW ADAPTIVE CPG TOOL - FOR VALIDATION =====
    
    # @mcp.tool()
    # async def query_cpg_adaptive(
    #     user_query: str = None,
    #     cypher_query: str = None,
    #     project_name: str = "HelloWorldApp", 
    #     config_path: str = "/opt/genpod/neo4j_config.json",
    #     project_path: str = "/opt/HelloWorldApp/",
    #     mappings_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
    #     queries_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
    #     max_results: int = 100,
    #     enable_discovery: bool = True,
    #     enable_synthesis: bool = True,
    #     enable_advanced_rag: bool = True
    # ) -> dict:
    #     """
    #     NEW: Enhanced CPG querying with adaptive discovery instead of rigid templates.
        
    #     This replaces the rigid template approach in query_cpg_only with:
    #     1. Phase 1: Schema-aware structural discovery (no entity assumptions)
    #     2. Phase 2: Query-driven targeted expansion (based on discovered reality)
    #     3. Phase 3: Critic-driven validation (iterative sufficiency checking)
    #     4. Fault-tolerant identifier extraction (name/alias/value fallback)
        
    #     Args:
    #         user_query: Natural language query for semantic analysis (optional if cypher_query provided)
    #         cypher_query: Direct Cypher query to execute (optional if user_query provided)
    #         project_name: Name of project in Neo4j database for discovery scoping
    #         config_path: Path to Neo4j MCP configuration (default: /opt/genpod/neo4j_config.json)
    #         project_path: Path to project root - stored as metadata (default: /opt/HelloWorldApp/)
    #         mappings_path: Path to mappings YAML - stored as metadata (default: project_analyzer mappings.yaml)
    #         queries_path: Path to queries directory - stored as metadata (default: project_analyzer final_queries)
    #         max_results: Maximum number of results to return per phase
    #         enable_discovery: Whether to use adaptive discovery (default: True)
    #         enable_synthesis: Whether to synthesize results with LLM (default: True)
    #         enable_advanced_rag: Whether to use advanced Graph RAG features (default: True)
        
    #     Note: Only config_path is used for CLI query execution. Other paths are stored as metadata.
    #     """
    #     try:
    #         import logging
    #         logger = logging.getLogger(__name__)
            
    #         # BACKWARD COMPATIBILITY: Handle direct cypher_query execution (like query_cpg_only)
    #         if cypher_query and not enable_discovery:
    #             logger.info(f"🔧 Executing direct Cypher query (backward compatibility mode)")
                
    #             from src.core.graph_query_executor import GraphQueryExecutor
    #             executor = GraphQueryExecutor()
                
    #             query_info = {
    #                 "cypher": cypher_query,
    #                 "type": "direct_cypher",
    #                 "purpose": "Direct Cypher query execution"
    #             }
                
    #             result = await executor._execute_single_query(
    #                 query_info, config_path, "direct_cypher_query"
    #             )
                
    #             if result["status"] != "success":
    #                 return {
    #                     "status": "error",
    #                     "cypher_query": cypher_query,
    #                     "error": result.get("error", "Direct Cypher query execution failed"),
    #                     "user_query": user_query,
    #                     "analysis_type": "direct_cypher"
    #                 }
                
    #             raw_results = result.get("results", [])
                
    #             # Apply synthesis if requested and user_query provided
    #             if enable_synthesis and user_query:
    #                 try:
    #                     from src.core.llm_service import LLMService
    #                     llm_service = LLMService({"cache_ttl": 1800})
                        
    #                     synthesis_result = await llm_service.synthesize_targeted_response(
    #                         raw_results, user_query, {}
    #                     )
                        
    #                     return {
    #                         "status": "success",
    #                         "cypher_query": cypher_query,
    #                         "raw_results": raw_results,
    #                         "synthesis": synthesis_result.get("answer", ""),
    #                         "synthesis_status": "success",
    #                         "analysis_type": "direct_cypher_with_synthesis",
    #                         "workflow": "backward_compatibility"
    #                     }
    #                 except Exception as synthesis_error:
    #                     logger.warning(f"Synthesis failed: {synthesis_error}")
                        
    #             return {
    #                 "status": "success",
    #                 "cypher_query": cypher_query,
    #                 "raw_results": raw_results,
    #                 "synthesis_enabled": False,
    #                 "analysis_type": "direct_cypher",
    #                 "workflow": "backward_compatibility"
    #             }
            
    #         # INPUT VALIDATION: Require either user_query or cypher_query
    #         if not user_query and not cypher_query:
    #             return {
    #                 "status": "error",
    #                 "error": "Either user_query or cypher_query must be provided",
    #                 "analysis_type": "input_validation_error"
    #             }
            
    #         if enable_discovery and user_query:
    #             logger.info(f"🔍 Starting LangGraph-based adaptive CPG workflow for: {user_query}")
                
    #             # Use LangGraph Agent Workflow instead of hardcoded phases
    #             try:
    #                 from src.core.adaptive_cpg_agent_workflow import execute_adaptive_cpg_workflow
                    
    #                 workflow_result = await execute_adaptive_cpg_workflow(
    #                     user_query=user_query,
    #                     project_name=project_name,
    #                     neo4j_config=config_path,
    #                     project_path=project_path,
    #                     mappings_path=mappings_path,
    #                     queries_path=queries_path,
    #                     max_iterations=5
    #                 )
                    
    #                 if workflow_result.get("status") == "success":
    #                     return {
    #                         "status": "success",
    #                         "response": workflow_result.get("response", ""),
    #                         "discovered_data": workflow_result.get("discovered_data", []),
    #                         "query_history": workflow_result.get("query_history", []),
    #                         "final_results": workflow_result.get("final_results", []),
    #                         "analysis_type": "langgraph_agent_workflow",
    #                         "workflow": workflow_result.get("workflow", "langgraph_agent"),
    #                         "agent_metadata": workflow_result.get("agent_metadata", {}),
    #                         "iterations_used": workflow_result.get("iterations_used", 0),
    #                         "intent_analysis": workflow_result.get("intent", {}),
    #                         "synthesis_enabled": True,
    #                         "has_synthesis": bool(workflow_result.get("response"))
    #                     }
    #                 else:
    #                     return {
    #                         "status": "error",
    #                         "error": workflow_result.get("error", "Agent workflow failed"),
    #                         "analysis_type": "langgraph_agent_error",
    #                         "partial_results": workflow_result.get("discovered_data", [])
    #                     }
                        
    #             except ImportError as e:
    #                 logger.warning(f"LangGraph not available, falling back to legacy approach: {e}")
    #                 # Fall back to the existing implementation
    #                 pass
    #             except Exception as e:
    #                 logger.error(f"Agent workflow failed: {e}")
    #                 return {
    #                     "status": "error",
    #                     "error": f"Agent workflow failed: {e}",
    #                     "analysis_type": "langgraph_agent_error"
    #                 }
                
    #             # LEGACY FALLBACK: Original hardcoded approach (if LangGraph fails)
    #             logger.info("📋 Falling back to legacy discovery approach")
                
    #             from src.core.graph_query_executor import GraphQueryExecutor
    #             executor = GraphQueryExecutor()
                
    #             # OPTIMIZED: Separate node discovery and relationship discovery to avoid context explosion
    #             # Based on user testing: separate queries work better than universal discovery
                
    #             # Phase 1A: Node Discovery Query (tested: 38 rows, manageable)
    #             node_discovery_query = f"""
    #             MATCH (n)
    #             WHERE labels(n)[0] IN ['Project', 'File', 'Type', 'Function', 'Namespace', 'Variable']
    #                 AND (n.project_name = '{project_name}' OR n.project_name IS NULL)
    #             RETURN DISTINCT
    #                 labels(n)[0] AS node_type,
    #                 COALESCE(n.name, n.alias, n.value, "anonymous_" + n.type_kind, "truly_anonymous") AS name,
    #                 n.file_path,
    #                 n.type_kind,
    #                 -- Fault tolerance indicators
    #                 CASE
    #                     WHEN n.name IS NULL AND n.alias IS NOT NULL THEN "uses_alias_as_primary"
    #                     WHEN n.name IS NULL AND n.value IS NOT NULL THEN "uses_value_as_primary"
    #                     ELSE "standard_naming"
    #                 END AS naming_pattern
    #             ORDER BY node_type, name
    #             LIMIT {max_results}
    #             """
                
    #             # Phase 1B: Relationship Discovery Query (tested: 30 rows, manageable)
    #             relationship_discovery_query = f"""
    #             MATCH (a)-[r]->(b)
    #             WHERE labels(a)[0] IN ['Type', 'Function'] 
    #                 AND labels(b)[0] IN ['Type', 'Function']
    #                 AND type(r) IN ['CONTAINS', 'CALLS', 'INHERITS_FROM', 'IMPLEMENTS']
    #                 AND (a.project_name = '{project_name}' OR a.project_name IS NULL)
    #             RETURN DISTINCT
    #                 COALESCE(a.name, a.alias, a.value) AS source,
    #                 type(r) AS relationship, 
    #                 COALESCE(b.name, b.alias, b.value) AS target,
    #                 a.file_path AS source_file,
    #                 b.file_path AS target_file
    #             ORDER BY source, target
    #             LIMIT {max_results}
    #             """
                
    #             # Execute Phase 1A: Node Discovery with limit detection
    #             logger.info("📋 Phase 1A: Node discovery")
    #             node_info = {
    #                 "cypher": node_discovery_query,
    #                 "type": "node_discovery",
    #                 "purpose": "Phase 1A: Discover project nodes"
    #             }
                
    #             node_result = await executor._execute_single_query(
    #                 node_info, config_path, "node_discovery"
    #             )
                
    #             if node_result["status"] != "success":
    #                 return {
    #                     "status": "error",
    #                     "phase": "node_discovery",
    #                     "error": node_result.get("error", "Node discovery failed"),
    #                     "user_query": user_query
    #                 }
                
    #             discovered_nodes = node_result.get("results", [])
    #             logger.info(f"✅ Discovered {len(discovered_nodes)} nodes")
                
    #             # Limit detection for nodes: check if we hit the limit
    #             nodes_limit_reached = len(discovered_nodes) >= max_results
    #             more_nodes_available = False
                
    #             if nodes_limit_reached:
    #                 # Check if there are more nodes beyond the limit
    #                 count_nodes_query = f"""
    #                 MATCH (n)
    #                 WHERE labels(n)[0] IN ['Project', 'File', 'Type', 'Function', 'Namespace', 'Variable']
    #                     AND (n.project_name = '{project_name}' OR n.project_name IS NULL)
    #                 RETURN count(DISTINCT n) AS total_nodes
    #                 """
                    
    #                 count_info = {"cypher": count_nodes_query, "type": "count_check", "purpose": "Check total node count"}
    #                 count_result = await executor._execute_single_query(count_info, config_path, "count_check")
                    
    #                 if count_result["status"] == "success" and count_result.get("results"):
    #                     total_nodes = count_result["results"][0].get("total_nodes", len(discovered_nodes))
    #                     more_nodes_available = total_nodes > max_results
    #                     logger.info(f"🔍 Limit detection: {len(discovered_nodes)}/{total_nodes} nodes retrieved, more_available={more_nodes_available}")
                
    #             # Execute Phase 1B: Relationship Discovery with limit detection
    #             logger.info("🔗 Phase 1B: Relationship discovery")
    #             rel_info = {
    #                 "cypher": relationship_discovery_query,
    #                 "type": "relationship_discovery", 
    #                 "purpose": "Phase 1B: Discover project relationships"
    #             }
                
    #             rel_result = await executor._execute_single_query(
    #                 rel_info, config_path, "relationship_discovery"
    #             )
                
    #             discovered_relationships = []
    #             more_relationships_available = False
    #             rels_limit_reached = False
                
    #             if rel_result["status"] == "success":
    #                 discovered_relationships = rel_result.get("results", [])
    #                 logger.info(f"✅ Discovered {len(discovered_relationships)} relationships")
                    
    #                 # Limit detection for relationships
    #                 rels_limit_reached = len(discovered_relationships) >= max_results
    #                 if rels_limit_reached:
    #                     count_rels_query = f"""
    #                     MATCH (a)-[r]->(b)
    #                     WHERE labels(a)[0] IN ['Type', 'Function'] 
    #                         AND labels(b)[0] IN ['Type', 'Function']
    #                         AND type(r) IN ['CONTAINS', 'CALLS', 'INHERITS_FROM', 'IMPLEMENTS']
    #                         AND (a.project_name = '{project_name}' OR a.project_name IS NULL)
    #                     RETURN count(DISTINCT r) AS total_relationships
    #                     """
                        
    #                     count_rels_info = {"cypher": count_rels_query, "type": "count_check", "purpose": "Check total relationship count"}
    #                     count_rels_result = await executor._execute_single_query(count_rels_info, config_path, "count_rels_check")
                        
    #                     if count_rels_result["status"] == "success" and count_rels_result.get("results"):
    #                         total_rels = count_rels_result["results"][0].get("total_relationships", len(discovered_relationships))
    #                         more_relationships_available = total_rels > max_results
    #                         logger.info(f"🔍 Limit detection: {len(discovered_relationships)}/{total_rels} relationships retrieved, more_available={more_relationships_available}")
    #             else:
    #                 logger.warning("Relationship discovery failed, proceeding with nodes only")
                
    #             # Combine discovery results
    #             structure_map = []
                
    #             # Add nodes to structure map
    #             for node in discovered_nodes:
    #                 structure_map.append({
    #                     "source_type": node.get("node_type"),
    #                     "source_name": node.get("name"),
    #                     "source_path": node.get("file_path"),
    #                     "source_semantic": node.get("type_kind"),
    #                     "naming_pattern": node.get("naming_pattern"),
    #                     "relationship": None,  # Nodes don't have relationships in this format
    #                     "target_type": None,
    #                     "target_name": None,
    #                     "target_path": None,
    #                     "target_semantic": None,
    #                     "discovery_phase": "node_discovery"
    #                 })
                
    #             # Add relationships to structure map
    #             for rel in discovered_relationships:
    #                 structure_map.append({
    #                     "source_type": "Type/Function",  # Inferred from relationship query
    #                     "source_name": rel.get("source"),
    #                     "source_path": rel.get("source_file"),
    #                     "source_semantic": None,
    #                     "naming_pattern": "standard_naming",
    #                     "relationship": rel.get("relationship"),
    #                     "target_type": "Type/Function",
    #                     "target_name": rel.get("target"),
    #                     "target_path": rel.get("target_file"),
    #                     "target_semantic": None,
    #                     "discovery_phase": "relationship_discovery"
    #                 })
                
    #             if not structure_map:
    #                 return {
    #                     "status": "error",
    #                     "phase": "discovery",
    #                     "error": f"No project structure found for '{project_name}'. Ensure project is loaded into Neo4j.",
    #                     "user_query": user_query
    #                 }
                
    #             # Phase 2: Query-Driven Targeted Expansion
    #             logger.info("🎯 Phase 2: Generating targeted expansion based on user query and discovered structure")
                
    #             # Load schema for query generation
    #             import yaml
    #             schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
    #             try:
    #                 with open(schema_path, 'r') as f:
    #                     schema_content = yaml.safe_load(f)
    #                 schema_text = yaml.dump(schema_content, indent=2)
    #             except Exception as schema_error:
    #                 logger.warning(f"Could not load schema: {schema_error}")
    #                 schema_text = "Schema not available"
                
    #             # Extract entities and intents from user query
    #             from src.core.llm_service import LLMService
    #             llm_service = LLMService({"cache_ttl": 1800})
                
    #             # Analyze user query with discovered structure context AND schema
    #             entity_extraction_prompt = f"""
    #             User Query: {user_query}
                
    #             Graph Database Schema:
    #             {schema_text}
                
    #             Discovered Project Structure (ACTUAL data from graph):
    #             {json.dumps(structure_map[:20], indent=2)}
                
    #             Based on the user query, the graph schema, and the ACTUAL discovered project structure above:
    #             1. What specific entities (classes, methods, files) are being asked about
    #             2. What type of information is needed (structure, dependencies, implementation)
    #             3. Which discovered entities are most relevant
    #             4. What schema attributes should be included in expansion queries
                
    #             Respond in JSON:
    #             {{
    #                 "relevant_entities": [list of entity names found in discovery],
    #                 "query_intent": "architectural|dependency|implementation|relationship",
    #                 "information_needed": [list of specific information types],
    #                 "expansion_targets": [list of specific nodes to expand],
    #                 "required_attributes": [list of schema attributes needed for the query]
    #             }}
    #             """
                
    #             try:
    #                 entity_analysis = await llm_service.generate_response(
    #                     prompt=entity_extraction_prompt,
    #                     system_prompt="You are a code analysis expert. Extract entities and intent from queries using discovered project structure.",
    #                     max_tokens=500,
    #                     temperature=0.1
    #                 )
                    
    #                 if entity_analysis and entity_analysis.content:
    #                     try:
    #                         analysis_data = json.loads(entity_analysis.content)
    #                     except json.JSONDecodeError:
    #                         analysis_data = {"relevant_entities": [], "query_intent": "architectural"}
    #                 else:
    #                     analysis_data = {"relevant_entities": [], "query_intent": "architectural"}
                        
    #             except Exception as e:
    #                 logger.warning(f"Entity analysis failed: {e}")
    #                 analysis_data = {"relevant_entities": [], "query_intent": "architectural"}
                
    #             # Phase 2: Generate targeted expansion strategy based on Phase 1 discoveries
    #             expansion_targets = analysis_data.get("expansion_targets", [])
    #             query_intent = analysis_data.get("query_intent", "architectural")
    #             required_attributes = analysis_data.get("required_attributes", [])
    #             relevant_entities = analysis_data.get("relevant_entities", [])
                
    #             logger.info("🎯 Phase 2: Generating targeted expansion strategy based on Phase 1 discoveries")
                
    #             # Extract discovered entities from Phase 1 for targeted expansion
    #             discovered_types = [r for r in structure_map if r.get("source_type") == "Type"]
    #             discovered_functions = [r for r in structure_map if r.get("source_type") == "Function"]
    #             discovered_files = [r for r in structure_map if r.get("source_type") == "File"]
                
    #             logger.info(f"📊 Phase 1 discovered: {len(discovered_types)} types, {len(discovered_functions)} functions, {len(discovered_files)} files")
                
    #             # Schema-guided expansion strategy generation
    #             expansion_strategy_prompt = f"""
    #             Based on Phase 1 discovery results and user query, determine the targeted expansion strategy:
                
    #             USER QUERY: {user_query}
    #             QUERY INTENT: {query_intent}
                
    #             PHASE 1 DISCOVERIES (what actually exists in the graph):
    #             - Types found: {[t.get("source_name") for t in discovered_types[:10]]}
    #             - Functions found: {[f.get("source_name") for f in discovered_functions[:10]]}
    #             - Files found: {[f.get("source_name") for f in discovered_files[:10]]}
                
    #             SCHEMA ATTRIBUTES AVAILABLE:
    #             {schema_text}
                
    #             Based on the user query and what was ACTUALLY discovered in Phase 1:
    #             1. Which specific discovered entities should we expand?
    #             2. What schema attributes do we need for those entities?
    #             3. What type of targeted expansion is needed?
                
    #             Respond in JSON:
    #             {{
    #                 "expansion_strategy": "specific_entities|relationship_details|implementation_details|architectural_overview",
    #                 "target_entities": [list of specific entity names from discoveries to expand],
    #                 "required_schema_attributes": [list of specific schema attributes needed],
    #                 "expansion_focus": "description of what to expand and why"
    #             }}
    #             """
                
    #             try:
    #                 strategy_response = await llm_service.generate_response(
    #                     prompt=expansion_strategy_prompt,
    #                     system_prompt="You are analyzing Phase 1 discovery results to plan targeted Phase 2 expansion. Use ONLY discovered entities, never fabricate.",
    #                     max_tokens=400,
    #                     temperature=0.1
    #                 )
                    
    #                 if strategy_response and strategy_response.content:
    #                     try:
    #                         strategy_data = json.loads(strategy_response.content)
    #                     except json.JSONDecodeError:
    #                         strategy_data = {"expansion_strategy": "architectural_overview", "target_entities": []}
    #                 else:
    #                     strategy_data = {"expansion_strategy": "architectural_overview", "target_entities": []}
                        
    #             except Exception as strategy_error:
    #                 logger.warning(f"Strategy generation failed: {strategy_error}")
    #                 strategy_data = {"expansion_strategy": "architectural_overview", "target_entities": []}
                
    #             # Generate targeted expansion query based on strategy and schema
    #             expansion_strategy = strategy_data.get("expansion_strategy", "architectural_overview")
    #             target_entities = strategy_data.get("target_entities", [])
    #             required_schema_attrs = strategy_data.get("required_schema_attributes", [])
                
    #             logger.info(f"🔧 Expansion strategy: {expansion_strategy}, targeting: {target_entities}")
                
    #             # Build schema-informed targeted expansion query
    #             if expansion_strategy == "specific_entities" and target_entities:
    #                 # Target specific entities discovered in Phase 1
    #                 entity_filter = " OR ".join([f"COALESCE(t.name, t.alias, t.value) = '{entity}'" for entity in target_entities[:5]])
    #                 expansion_query = f"""
    #                 MATCH (t:Type)
    #                 WHERE 
    #                     (t.project_name = '{project_name}' OR NOT EXISTS(t.project_name))
    #                     AND ({entity_filter})
    #                 OPTIONAL MATCH (t)-[:CONTAINS]->(f:Function)
    #                 OPTIONAL MATCH (t)-[r:INHERITS_FROM|IMPLEMENTS]->(base:Type)
    #                 RETURN 
    #                     COALESCE(t.name, t.alias, t.value) AS name,
    #                     t.type_kind,
    #                     t.file_path,
    #                     t.body,
    #                     t.base_list,
    #                     t.fields,
    #                     t.modifier,
    #                     collect(DISTINCT {{
    #                         name: COALESCE(f.name, f.alias),
    #                         body: f.body,
    #                         parameters: f.parameters,
    #                         return_type: f.return_type
    #                     }}) AS functions,
    #                     collect(DISTINCT {{
    #                         relationship: type(r),
    #                         target: COALESCE(base.name, base.alias, base.value)
    #                     }}) AS inheritance_info
    #                 ORDER BY name
    #                 LIMIT {max_results}
    #                 """
    #             elif expansion_strategy == "relationship_details" or query_intent == "dependency":
    #                 # Focus on relationships between discovered entities
    #                 discovered_names = [r.get("source_name") for r in structure_map[:15] if r.get("source_name") and r.get("source_name") != "truly_anonymous"]
    #                 name_filter = " OR ".join([f"COALESCE(a.name, a.alias, a.value) = '{name}' OR COALESCE(b.name, b.alias, b.value) = '{name}'" for name in discovered_names[:10]])
    #                 expansion_query = f"""
    #                 MATCH (a)-[r]->(b)
    #                 WHERE 
    #                     (a.project_name = '{project_name}' OR NOT EXISTS(a.project_name))
    #                     AND labels(a)[0] IN ['Type', 'Function']
    #                     AND labels(b)[0] IN ['Type', 'Function'] 
    #                     AND ({name_filter})
    #                 RETURN 
    #                     labels(a)[0] AS source_type,
    #                     COALESCE(a.name, a.alias, a.value) AS source_name,
    #                     a.file_path AS source_file,
    #                     type(r) AS relationship,
    #                     labels(b)[0] AS target_type,
    #                     COALESCE(b.name, b.alias, b.value) AS target_name,
    #                     b.file_path AS target_file
    #                 ORDER BY source_name, target_name
    #                 LIMIT {max_results}
    #                 """
    #             elif expansion_strategy == "implementation_details" or query_intent == "implementation":
    #                 # Get implementation details for discovered types
    #                 discovered_type_names = [t.get("source_name") for t in discovered_types[:10] if t.get("source_name") and t.get("source_name") != "truly_anonymous"]
    #                 if discovered_type_names:
    #                     type_filter = " OR ".join([f"COALESCE(t.name, t.alias, t.value) = '{name}'" for name in discovered_type_names])
    #                     expansion_query = f"""
    #                     MATCH (t:Type)
    #                     WHERE 
    #                         (t.project_name = '{project_name}' OR NOT EXISTS(t.project_name))
    #                         AND ({type_filter})
    #                     OPTIONAL MATCH (t)-[:CONTAINS]->(f:Function)
    #                     OPTIONAL MATCH (t)-[:CONTAINS]->(v:Variable)
    #                     RETURN 
    #                         COALESCE(t.name, t.alias, t.value) AS type_name,
    #                         t.type_kind,
    #                         t.file_path,
    #                         t.body,
    #                         t.fields,
    #                         t.base_list,
    #                         collect(DISTINCT {{
    #                             name: COALESCE(f.name, f.alias),
    #                             body: f.body,
    #                             parameters: f.parameters,
    #                             return_type: f.return_type,
    #                             modifier: f.modifier
    #                         }}) AS functions,
    #                         collect(DISTINCT {{
    #                             name: COALESCE(v.name, v.alias, v.value),
    #                             type_kind: v.type_kind,
    #                             initial_value: v.initial_value,
    #                             access_modifier: v.access_modifier
    #                         }}) AS variables
    #                     ORDER BY type_name
    #                     LIMIT {max_results}
    #                     """
    #                 else:
    #                     # Fallback if no types discovered
    #                     expansion_query = f"""
    #                     MATCH (n)
    #                     WHERE (n.project_name = '{project_name}' OR NOT EXISTS(n.project_name))
    #                     RETURN labels(n)[0] AS node_type, COALESCE(n.name, n.alias, n.value) AS name, n.file_path
    #                     LIMIT {max_results}
    #                     """
    #             else:
    #                 # Default: architectural overview of discovered entities
    #                 expansion_query = f"""
    #                 MATCH (t:Type)
    #                 WHERE 
    #                     (t.project_name = '{project_name}' OR NOT EXISTS(t.project_name))
    #                     AND COALESCE(t.name, t.alias, t.value) IS NOT NULL
    #                 RETURN 
    #                     COALESCE(t.name, t.alias, t.value) AS name,
    #                     t.type_kind,
    #                     t.file_path,
    #                     t.base_list,
    #                     t.modifier,
    #                     t.access_modifier,
    #                     CASE
    #                         WHEN t.name IS NULL AND t.alias IS NOT NULL THEN "using_alias_identifier"
    #                         ELSE "standard_identifier"
    #                     END AS identifier_source
    #                 ORDER BY name
    #                 LIMIT {max_results}
    #                 """
                
    #             logger.info(f"🔧 Executing targeted expansion for intent: {query_intent}")
                
    #             expansion_info = {
    #                 "cypher": expansion_query,
    #                 "type": "targeted_expansion",
    #                 "purpose": f"Phase 2: Targeted expansion for {query_intent}"
    #             }
                
    #             expansion_result = await executor._execute_single_query(
    #                 expansion_info, config_path, "targeted_expansion"
    #             )
                
    #             if expansion_result["status"] != "success":
    #                 logger.warning("Targeted expansion failed, using discovery results")
    #                 final_results = structure_map
    #                 executed_query = discovery_query
    #             else:
    #                 final_results = expansion_result.get("results", [])
    #                 executed_query = expansion_query
    #                 logger.info(f"✅ Retrieved {len(final_results)} targeted results")
                
    #             # Phase 3: Critic Validation Step
    #             logger.info("🎭 Phase 3: Critic validation for response accuracy")
                
    #             # Use our proper critic validation system
    #             from src.core.enhanced_query_executor import QueryCritic, QueryResult
                
    #             critic = QueryCritic(llm_service)
                
    #             # Convert results to QueryResult format for critic
    #             query_results = [
    #                 QueryResult(
    #                     query_id="discovery_query",
    #                     status="success",
    #                     results=structure_map,
    #                     execution_time=0.0,
    #                     validation_status="completed",
    #                     sufficiency_score=1.0,
    #                     missing_requirements=[],
    #                     suggested_expansions=[]
    #                 ),
    #                 QueryResult(
    #                     query_id="targeted_expansion", 
    #                     status="success",
    #                     results=final_results,
    #                     execution_time=0.0,
    #                     validation_status="completed",
    #                     sufficiency_score=1.0,
    #                     missing_requirements=[],
    #                     suggested_expansions=[]
    #                 )
    #             ]
                
    #             # Determine intent for critic assessment
    #             critic_intent = "architectural_analysis"
    #             if query_intent == "dependency":
    #                 critic_intent = "dependency_analysis"
    #             elif query_intent == "implementation":
    #                 critic_intent = "implementation_details"
                
    #             critic_analysis = await critic.assess_sufficiency(user_query, query_results, critic_intent)
                
    #             logger.info(f"🎭 Critic assessment: sufficient={critic_analysis.is_sufficient}, confidence={critic_analysis.confidence_score:.2f}")
                
    #             # Collect all raw results from all executed queries for benchmarking
    #             all_raw_results = {
    #                 "discovery_query_results": structure_map,
    #                 "targeted_expansion_results": final_results,
    #                 "combined_results": final_results  # Main results for compatibility
    #             }
                
    #             # All executed queries for benchmarking
    #             executed_queries = [
    #                 {
    #                     "query_type": "node_discovery",
    #                     "cypher": node_discovery_query,
    #                     "purpose": "Phase 1A: Node discovery",
    #                     "result_count": len(discovered_nodes),
    #                     "status": "success",
    #                     "limit_reached": nodes_limit_reached,
    #                     "more_data_available": more_nodes_available
    #                 },
    #                 {
    #                     "query_type": "relationship_discovery",
    #                     "cypher": relationship_discovery_query, 
    #                     "purpose": "Phase 1B: Relationship discovery",
    #                     "result_count": len(discovered_relationships),
    #                     "status": "success" if rel_result["status"] == "success" else "failed",
    #                     "limit_reached": rels_limit_reached if rel_result["status"] == "success" else False,
    #                     "more_data_available": more_relationships_available
    #                 },
    #                 {
    #                     "query_type": "targeted_expansion", 
    #                     "cypher": executed_query,
    #                     "purpose": f"Phase 2: Targeted expansion for {query_intent}",
    #                     "result_count": len(final_results),
    #                     "status": "success"
    #                 }
    #             ]
                
    #             # Synthesis with critic validation if requested  
    #             if enable_synthesis and (final_results or structure_map):
    #                 logger.info("🧠 Synthesizing response with critic-validated data")
                    
    #                 # Use discovery results as fallback when targeted expansion fails
    #                 synthesis_data = final_results if final_results else structure_map
                    
    #                 synthesis_prompt = f"""
    #                 User Query: {user_query}
                    
    #                 Retrieved CPG Data (ACTUAL project data, critic-validated):
    #                 Discovery Results: {json.dumps(structure_map[:10], indent=2)}
                    
    #                 Primary Results: {json.dumps(synthesis_data[:15], indent=2)}
                    
    #                 Critic Assessment: sufficient={critic_analysis.is_sufficient}, confidence={critic_analysis.confidence_score:.2f}
    #                 Missing aspects: {critic_analysis.missing_aspects}
                    
    #                 IMPORTANT: Use ONLY the actual retrieved data above. Do NOT fabricate or hallucinate any Java classes, MainClass, HelperClass, etc. 
    #                 The retrieved data shows the REAL project structure discovered from the graph database. Base your answer entirely on what was actually found.
    #                 If the critic identified missing aspects, acknowledge them but don't fabricate data to fill gaps.
                    
    #                 Answer the user's question using only the retrieved data.
    #                 """
                    
    #                 try:
    #                     synthesis_result = await llm_service.generate_response(
    #                         prompt=synthesis_prompt,
    #                         system_prompt="You are a code analysis expert. Answer using ONLY the provided retrieved data. Never fabricate or hallucinate information. If data is insufficient, say so explicitly.",
    #                         max_tokens=1000,
    #                         temperature=0.1
    #                     )
                        
    #                     synthesis = synthesis_result.content if synthesis_result else "Synthesis failed"
                        
    #                     # Validate synthesis against retrieved data using critic
    #                     synthesis_validation = await critic._llm_based_assessment(
    #                         user_query, query_results, critic_intent
    #                     )
                        
    #                 except Exception as synthesis_error:
    #                     synthesis = f"Synthesis unavailable: {synthesis_error}. Raw results: Found {len(final_results)} code elements."
    #                     synthesis_validation = None
                    
    #                 # Response structure compatible with existing benchmarking
    #                 return {
    #                     "status": "success",
    #                     "cypher_query": executed_query,  # Primary query for compatibility
    #                     "raw_results": final_results,    # Primary results for compatibility
    #                     "synthesis": synthesis,
    #                     "synthesis_status": "success",
    #                     "analysis_type": "adaptive_cpg_with_synthesis",
    #                     "workflow": "adaptive_discovery",
                        
    #                     # ALL RAW RESULTS for benchmarking (key addition)
    #                     "all_raw_results": all_raw_results,
    #                     "executed_queries": executed_queries,
                        
    #                     # Critic validation metadata
    #                     "critic_validation": {
    #                         "is_sufficient": critic_analysis.is_sufficient,
    #                         "confidence_score": critic_analysis.confidence_score,
    #                         "missing_aspects": critic_analysis.missing_aspects,
    #                         "reasoning": critic_analysis.reasoning,
    #                         "synthesis_validation": synthesis_validation
    #                     },
                        
    #                     # Discovery metadata (preserving existing structure)
    #                     "discovery_metadata": {
    #                         "structural_relationships_found": len(structure_map),
    #                         "targeted_results_retrieved": len(final_results),
    #                         "query_intent_detected": query_intent,
    #                         "entity_analysis": analysis_data,
    #                         "naming_patterns_detected": list(set([r.get("naming_pattern", "standard") for r in structure_map[:10]])),
    #                         "fault_tolerance_applied": True,
    #                         "phases_completed": 3,
    #                         "critic_validated": True,
    #                         # NEW: Limit detection metadata
    #                         "limit_detection": {
    #                             "nodes_discovered": len(discovered_nodes),
    #                             "nodes_limit_reached": nodes_limit_reached,
    #                             "more_nodes_available": more_nodes_available,
    #                             "relationships_discovered": len(discovered_relationships),
    #                             "relationships_limit_reached": rels_limit_reached if rel_result["status"] == "success" else False,
    #                             "more_relationships_available": more_relationships_available,
    #                             "total_structure_elements": len(structure_map),
    #                             "completeness_assessment": "partial" if (more_nodes_available or more_relationships_available) else "complete"
    #                         }
    #                     }
    #                 }
    #             else:
    #                 # Raw results with critic validation
    #                 return {
    #                     "status": "success",
    #                     "cypher_query": executed_query,
    #                     "raw_results": final_results,
    #                     "synthesis_enabled": False,
    #                     "analysis_type": "adaptive_cpg_raw",
    #                     "workflow": "adaptive_discovery",
                        
    #                     # ALL RAW RESULTS for benchmarking (key addition)
    #                     "all_raw_results": all_raw_results,
    #                     "executed_queries": executed_queries,
                        
    #                     # Critic validation metadata
    #                     "critic_validation": {
    #                         "is_sufficient": critic_analysis.is_sufficient,
    #                         "confidence_score": critic_analysis.confidence_score,
    #                         "missing_aspects": critic_analysis.missing_aspects,
    #                         "reasoning": critic_analysis.reasoning
    #                     },
                        
    #                     # Discovery metadata
    #                     "discovery_metadata": {
    #                         "structural_relationships_found": len(structure_map),
    #                         "targeted_results_retrieved": len(final_results),
    #                         "query_intent_detected": query_intent,
    #                         "fault_tolerance_applied": True,
    #                         "phases_completed": 3,
    #                         "critic_validated": True,
    #                         # NEW: Limit detection metadata
    #                         "limit_detection": {
    #                             "nodes_discovered": len(discovered_nodes),
    #                             "nodes_limit_reached": nodes_limit_reached,
    #                             "more_nodes_available": more_nodes_available,
    #                             "relationships_discovered": len(discovered_relationships),
    #                             "relationships_limit_reached": rels_limit_reached if rel_result["status"] == "success" else False,
    #                             "more_relationships_available": more_relationships_available,
    #                             "total_structure_elements": len(structure_map),
    #                             "completeness_assessment": "partial" if (more_nodes_available or more_relationships_available) else "complete"
    #                         }
    #                     }
    #                 }
                    
    #         elif cypher_query and enable_discovery:
    #             # HYBRID MODE: Execute provided cypher_query with discovery metadata
    #             logger.info(f"🔧 Executing provided Cypher query in hybrid mode")
                
    #             from src.core.graph_query_executor import GraphQueryExecutor
    #             executor = GraphQueryExecutor()
                
    #             query_info = {
    #                 "cypher": cypher_query,
    #                 "type": "hybrid_cypher",
    #                 "purpose": "Provided Cypher query with discovery context"
    #             }
                
    #             result = await executor._execute_single_query(
    #                 query_info, config_path, "hybrid_cypher_query"
    #             )
                
    #             if result["status"] != "success":
    #                 return {
    #                     "status": "error",
    #                     "cypher_query": cypher_query,
    #                     "error": result.get("error", "Hybrid Cypher query execution failed"),
    #                     "user_query": user_query,
    #                     "analysis_type": "hybrid_cypher"
    #                 }
                
    #             raw_results = result.get("results", [])
                
    #             return {
    #                 "status": "success",
    #                 "cypher_query": cypher_query,
    #                 "raw_results": raw_results,
    #                 "synthesis_enabled": False,
    #                 "analysis_type": "hybrid_cypher",
    #                 "workflow": "hybrid_discovery_enabled"
    #             }
                
    #         else:
    #             # Fallback to basic query generation (like original query_cpg_only)
    #             logger.info("📎 Using fallback basic query generation")
                
    #             if not user_query:
    #                 return {
    #                     "status": "error", 
    #                     "error": "user_query is required for basic query generation",
    #                     "analysis_type": "input_validation_error"
    #                 }
                
    #             from src.core.llm_service import LLMService
    #             llm_service = LLMService({"cache_ttl": 1800})
                
    #             cypher_result = await llm_service.generate_cypher_query(
    #                 {"user_query": user_query}, user_query
    #             )
                
    #             if not cypher_result or not cypher_result.get("primary_query"):
    #                 return {
    #                     "status": "error",
    #                     "error": "Could not generate basic Cypher query",
    #                     "user_query": user_query
    #                 }
                
    #             # Execute basic query
    #             from src.core.graph_query_executor import GraphQueryExecutor
    #             executor = GraphQueryExecutor()
                
    #             query_info = {
    #                 "cypher": cypher_result["primary_query"],
    #                 "type": "basic_query",
    #                 "purpose": "Basic CPG query"
    #             }
                
    #             result = await executor._execute_single_query(
    #                 query_info, config_path, "basic_cpg_query"
    #             )
                
    #             if result["status"] != "success":
    #                 return {
    #                     "status": "error",
    #                     "cypher_query": cypher_result["primary_query"],
    #                     "error": result.get("error", "Basic query execution failed"),
    #                     "user_query": user_query
    #                 }
                
    #             raw_results = result.get("results", [])
                
    #             return {
    #                 "status": "success",
    #                 "cypher_query": cypher_result["primary_query"],
    #                 "raw_results": raw_results,
    #                 "synthesis_enabled": False,
    #                 "analysis_type": "basic_cpg",
    #                 "workflow": "basic_fallback"
    #             }
                
    #     except Exception as e:
    #         import traceback
    #         return {
    #             "status": "error",
    #             "error": str(e),
    #             "traceback": traceback.format_exc(),
    #             "user_query": user_query,
    #             "project_name": project_name,
    #             "message": f"Adaptive CPG query failed: {str(e)}"
    #         }

    # ==========================================================================
    # DEPRECATED: Old LangGraph-based query_cpg_rag (kept for rollback)
    # ==========================================================================
    # @mcp.tool()
    # async def query_cpg_rag(
    #     user_query: str,
    #     project_name: str = "HelloWorldApp",
    #     config_path: str = "/opt/genpod/neo4j_config.json",
    #     project_path: str = "/opt/HelloWorldApp/",
    #     mappings_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
    #     queries_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
    #     max_results: int = 100,
    #     max_agent_iterations: int = 10
    # ) -> dict:
    #     """
    #     🔍 CLEAR PURPOSE: Enhanced CPG Query with LangGraph Agent-Based RAG
        
    #     This tool uses LangGraph agents to intelligently analyze code queries:
    #     1. 🤖 Agent-based query understanding and planning
    #     2. 🔍 Adaptive discovery of actual project structure
    #     3. 🎯 Smart query generation based on discovered reality
    #     4. 📊 Critic validation and iterative improvement
    #     5. 🧠 LLM synthesis of comprehensive answers
        
    #     WORKFLOW: User Query → Agent Analysis → Smart Discovery → Targeted Queries → Validation → Synthesis
        
    #     Args:
    #         user_query: Natural language question about the code (REQUIRED)
    #         project_name: Project identifier in Neo4j database (default: HelloWorldApp)
    #         config_path: Neo4j configuration file path (default: /opt/genpod/neo4j_config.json)
    #         project_path: Project root path - metadata only (default: /opt/HelloWorldApp/)
    #         mappings_path: Mappings YAML path - metadata only (default: project_analyzer mappings)  
    #         queries_path: Queries directory path - metadata only (default: project_analyzer queries)
    #         max_results: Maximum results per query phase (default: 100)
    #         max_agent_iterations: Maximum agent workflow iterations (default: 10)
            
    #     Returns:
    #         dict: Contains 'response' (synthesized answer), 'discovered_data', 'query_history', and agent metadata
            
    #     Example Usage:
    #         "What classes are defined in this project?"
    #         "How does the main method work?"
    #         "Show me all the function dependencies"
    #     """
    #     try:
    #         import logging
    #         logger = logging.getLogger(__name__)
            
    #         logger.info(f"🔍 Starting Enhanced CPG RAG analysis for: {user_query}")
            
    #         # Use the LangGraph agent workflow
    #         from src.core.adaptive_cpg_agent_workflow import execute_adaptive_cpg_workflow
            
    #         workflow_result = await execute_adaptive_cpg_workflow(
    #             user_query=user_query,
    #             project_name=project_name,
    #             neo4j_config=config_path,
    #             project_path=project_path,
    #             mappings_path=mappings_path,
    #             queries_path=queries_path,
    #             max_iterations=max_agent_iterations
    #         )
            
    #         if workflow_result.get("status") == "success":
    #             # Extract response string and structure it for compatibility
    #             response_text = workflow_result.get("response", "")

    #             return {
    #                 "status": "success",
    #                 "tool_name": "query_cpg_rag",
    #                 "workflow_type": "langgraph_agent_rag",
    #                 "user_query": user_query,
    #                 "project_name": project_name,

    #                 # Main Results - Structure response as dict for proper extraction by analysis scripts
    #                 "response": {
    #                     "answer": response_text,
    #                     "details": "",  # Can be populated if workflow provides additional details
    #                     "confidence": 0.8,  # Default confidence - can be enhanced later
    #                     "status": "success"
    #                 },
    #                 "query_history": workflow_result.get("query_history", []),
    #                 "final_results": workflow_result.get("final_results", []),

    #                 # Filtered discovered data (relevant data points identified by synthesis)
    #                 "raw_results": workflow_result.get("raw_results", []),

    #                 # Debug/Internal Tracking
    #                 "raw_query_results": workflow_result.get("raw_query_results", []),
    #                 "all_executed_queries": workflow_result.get("all_executed_queries", []),

    #                 # Agent Metadata
    #                 "agent_workflow": workflow_result.get("workflow", "langgraph_agent"),
    #                 "agent_metadata": workflow_result.get("agent_metadata", {}),
    #                 "iterations_used": workflow_result.get("iterations_used", 0),
    #                 "intent_analysis": workflow_result.get("intent", {}),

    #                 # Query Refinement Tracking (NEW)
    #                 "approach_statuses": workflow_result.get("approach_statuses", {}),
    #                 "failed_approaches": workflow_result.get("failed_approaches", []),

    #                 # Per-Approach Execution Traces (NEW) - Contains query history, citations, reasoning trail
    #                 "approach_execution_traces": workflow_result.get("approach_execution_traces", {}),
    #                 "approach_raw_results": workflow_result.get("approach_raw_results", {}),

    #                 # Token Utilization Tracking (NEW)
    #                 "total_tokens_used": workflow_result.get("total_tokens_used", 0),
    #                 "total_input_tokens": workflow_result.get("total_input_tokens", 0),
    #                 "total_output_tokens": workflow_result.get("total_output_tokens", 0),
    #                 "total_estimated_cost_usd": workflow_result.get("total_estimated_cost_usd", 0.0),
    #                 # Per-step token breakdown
    #                 "discovery_research_tokens": workflow_result.get("discovery_research_tokens", 0),
    #                 "think_tokens": workflow_result.get("think_tokens", 0),
    #                 "generate_tokens": workflow_result.get("generate_tokens", 0),
    #                 "rethink_tokens": workflow_result.get("rethink_tokens", 0),
    #                 "diagnostics_tokens": workflow_result.get("diagnostics_tokens", 0),
    #                 "refinement_tokens": workflow_result.get("refinement_tokens", 0),
    #                 "sufficiency_check_tokens": workflow_result.get("sufficiency_check_tokens", 0),
    #                 "synthesis_tokens": workflow_result.get("synthesis_tokens", 0),
    #                 # Efficiency metrics
    #                 "tokens_per_approach": workflow_result.get("tokens_per_approach", {}),
    #                 "cost_per_approach": workflow_result.get("cost_per_approach", {}),
    #                 # Model tracking
    #                 "models_used": workflow_result.get("models_used", []),
    #                 "llm_call_history": workflow_result.get("llm_call_history", []),

    #                 # Configuration
    #                 "cli_parameters_used": {
    #                     "config_path": config_path,
    #                     "project_path": project_path,
    #                     "mappings_path": mappings_path,
    #                     "queries_path": queries_path,
    #                     "max_results": max_results
    #                 },

    #                 "message": f"✅ Enhanced CPG RAG completed successfully using LangGraph agents"
    #             }
    #         else:
    #             return {
    #                 "status": "error",
    #                 "tool_name": "query_cpg_rag",
    #                 "error": workflow_result.get("error", "Agent workflow failed"),
    #                 "user_query": user_query,
    #                 "project_name": project_name,
    #                 "partial_results": workflow_result.get("discovered_data", []),
    #                 "raw_query_results": workflow_result.get("raw_query_results", []),
    #                 "all_executed_queries": workflow_result.get("all_executed_queries", []),
    #                 "message": f"❌ Enhanced CPG RAG failed: {workflow_result.get('error', 'Unknown error')}"
    #             }
                
    #     except ImportError as e:
    #         return {
    #             "status": "error",
    #             "tool_name": "query_cpg_rag",
    #             "error": f"LangGraph agent workflow not available: {e}",
    #             "fallback_suggestion": "Use query_cpg_only tool for basic CPG queries",
    #             "user_query": user_query
    #         }
    #     except Exception as e:
    #         import traceback
    #         return {
    #             "status": "error",
    #             "tool_name": "query_cpg_rag", 
    #             "error": str(e),
    #             "traceback": traceback.format_exc(),
    #             "user_query": user_query,
    #             "project_name": project_name,
    #             "message": f"❌ Enhanced CPG RAG failed with exception: {str(e)}"
    #         }

    # ==========================================================================
    # END DEPRECATED
    # ==========================================================================

    # @mcp.tool()
    # async def query_comprehensive_rag(
    #     user_query: str,
    #     project_name: str = "HelloWorldApp",
    #     collection_name: str = "helloworldapp-benchmarking",
    #     config_path: str = "/opt/genpod/neo4j_config.json",
    #     project_path: str = "/opt/HelloWorldApp/",
    #     mappings_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
    #     queries_path: str = "/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
    #     max_results: int = 100,
    #     max_agent_iterations: int = 10
    # ) -> dict:
    #     """
    #     🔍 COMPREHENSIVE RAG: Vector Search + CPG Analysis with LangGraph Agent Workflow
        
    #     This tool provides the most comprehensive RAG analysis by combining:
    #     1. 🔍 Vector RAG: Semantic understanding using embeddings with validated AI responses
    #     2. 🕸️  CPG RAG: Structural relationships using Code Property Graph with agent discovery
    #     3. 🤖 LangGraph Agents: Intelligent workflow orchestration and routing
    #     4. 🧠 Cross-validation: Prevents hallucination by validating between data sources
    #     5. 📊 Intent-based routing: Architectural queries get vector search first, then enhanced CPG
        
    #     WORKFLOW: 
    #     Intent Analysis → Vector RAG (if architectural) → Enhanced CPG Discovery → Cross-validation → Synthesis
        
    #     Differentiates from previous implementations by using the new workflow-based approach
    #     instead of the older template-based or basic RAG implementations.
        
    #     Args:
    #         user_query: Natural language query about the codebase (required)
    #         project_name: Name of the project for CPG analysis (default: "HelloWorldApp")
    #         collection_name: Vector collection name (default: "helloworldapp-benchmarking")
    #         config_path: Path to Neo4j configuration file
    #         project_path: Root path of the project to analyze
    #         mappings_path: Path to parsing mappings configuration
    #         queries_path: Path to query templates
    #         max_results: Maximum CPG results to return
    #         max_agent_iterations: Maximum workflow iterations for discovery
            
    #     Returns:
    #         dict: Comprehensive RAG results with both vector and CPG insights
    #     """
        
    #     try:
    #         import logging
    #         logger = logging.getLogger(__name__)
            
    #         logger.info(f"🔍 Starting Comprehensive RAG for: {user_query}")
    #         logger.info(f"📊 Project: {project_name}, Collection: {collection_name}")
            
    #         # Use the comprehensive analysis workflow
    #         from src.core.comprehensive_analysis_agent_workflow import ComprehensiveAnalysisAgentWorkflow
            
    #         workflow = ComprehensiveAnalysisAgentWorkflow()
    #         workflow_result = await workflow.run_workflow(
    #             user_query=user_query,
    #             project_name=project_name,
    #             neo4j_config=config_path,
    #             collection_name=collection_name,
    #             max_iterations=max_agent_iterations
    #         )
            
    #         if workflow_result.get("status") == "success":
    #             return {
    #                 "status": "success",
    #                 "tool_name": "query_comprehensive_rag",
    #                 "workflow_type": "comprehensive_vector_cpg_rag_workflow",
    #                 "user_query": user_query,
    #                 "project_name": project_name,
    #                 "collection_name": collection_name,
                    
    #                 # Main Results - Combined RAG insights
    #                 "response": workflow_result.get("response", ""),
    #                 "vector_rag_results": workflow_result.get("vector_search_results", []),
    #                 "vector_ai_response": workflow_result.get("vector_ai_response", ""),
    #                 "vector_metadata": workflow_result.get("vector_metadata", {}),
    #                 "cpg_rag_results": workflow_result.get("discovered_data", []),
                    
    #                 # Workflow Metadata
    #                 "agent_metadata": workflow_result.get("agent_metadata", {}),
    #                 "validation_metadata": workflow_result.get("validation_metadata", {}),
    #                 "vector_discovered_entities": workflow_result.get("vector_discovered_entities", []),
                    
    #                 # Raw data for validation
    #                 "raw_results": workflow_result.get("raw_results", []),
    #                 "executed_queries": workflow_result.get("executed_queries", []),
                    
    #                 # RAG quality indicators
    #                 "data_sources": {
    #                     "vector_rag": len(workflow_result.get("vector_search_results", [])) > 0,
    #                     "cpg_rag": len(workflow_result.get("discovered_data", [])) > 0,
    #                     "cross_validated": workflow_result.get("validation_metadata", {}).get("hallucination_detected") == False
    #                 },
                    
    #                 "message": f"✅ Comprehensive RAG completed successfully with {len(workflow_result.get('vector_search_results', []))} vector results and {len(workflow_result.get('discovered_data', []))} CPG results"
    #             }
    #         else:
    #             # Return error with diagnostic info
    #             return {
    #                 "status": "error", 
    #                 "tool_name": "query_comprehensive_rag",
    #                 "error": workflow_result.get("error", "Unknown workflow error"),
    #                 "workflow_type": "comprehensive_vector_cpg_rag_workflow",
    #                 "user_query": user_query,
    #                 "project_name": project_name,
    #                 "collection_name": collection_name,
    #                 "diagnostic_info": {
    #                     "workflow_available": True,
    #                     "config_path": config_path,
    #                     "project_path": project_path
    #                 },
    #                 "message": f"❌ Comprehensive RAG failed: {workflow_result.get('error', 'Unknown error')}"
    #             }
                
    #     except ImportError as e:
    #         logger.error(f"❌ Comprehensive RAG workflow import failed: {e}")
    #         return {
    #             "status": "error",
    #             "tool_name": "query_comprehensive_rag",
    #             "error": f"Comprehensive RAG workflow not available: {e}",
    #             "fallback_suggestions": [
    #                 "Use query_cpg_rag for CPG-only workflow RAG",
    #                 "Use query_vector_only for vector-only RAG"
    #             ],
    #             "user_query": user_query,
    #             "project_name": project_name,
    #             "collection_name": collection_name
    #         }
    #     except Exception as e:
    #         import traceback
    #         logger.error(f"❌ Comprehensive RAG failed: {e}")
    #         return {
    #             "status": "error",
    #             "tool_name": "query_comprehensive_rag",
    #             "error": str(e),
    #             "traceback": traceback.format_exc(),
    #             "user_query": user_query,
    #             "project_name": project_name,
    #             "collection_name": collection_name,
    #             "message": f"❌ Comprehensive RAG failed with exception: {str(e)}"
    #         }

    
# from mcp.server.fastmcp import FastMCP
# import yaml
# import os

# def register_all_tools(mcp):
#     @mcp.tool()
#     async def project_analysis_tool(
#         project_path: str,
#         mappings_path: str = "parsing_utils/mappings.yaml",
#         queries_path: str = "parsing_utils/queries.yaml"
#     ) -> dict:
#         """
#         Analyze a code project: parse with tree-sitter, enrich with LSP, build CPG, and upload to Neo4j.
#         Args:
#             project_path: Path to the root of the project.
#             mappings_path: Path to the mappings YAML file.
#             queries_path: Path to the queries file.
#         Returns:
#             dict: Status and summary of the analysis.
#         """
#         import traceback

#         try:
#             with open(mappings_path, 'r') as mappings_file:
#                 mappings = yaml.safe_load(mappings_file)

#             analyzer = ProjectAnalyzer(mappings=mappings, queries_path=queries_path)

#             try:
#                 await analyzer.analyze_project(project_path)
#             except Exception as e:
#                 return {
#                     "status": "error",
#                     "step": "analyze_project",
#                     "error": str(e),
#                     "traceback": traceback.format_exc()
#                 }

#             try:
#                 await analyzer.bring_context_using_lsp(project_path)
#             except Exception as e:
#                 return {
#                     "status": "error",
#                     "step": "bring_context_using_lsp",
#                     "error": str(e),
#                     "traceback": traceback.format_exc()
#                 }
            
#             try:
#                 await analyzer.upload_to_neo4j_memory()
#                 print("After upload_to_neo4j_memory")
#             except Exception as e:
#                 return {
#                     "status": "error",
#                     "step": "upload_to_neo4j_memory",
#                     "error": str(e),
#                     "traceback": traceback.format_exc()
#                 }

#             total_nodes, total_edges = 0, 0
#             if hasattr(analyzer, "generated_graph_nodes"):
#                 for file_graph in analyzer.generated_graph_nodes.values():
#                     total_nodes += len(file_graph.get("nodes", []))
#                     total_edges += len(file_graph.get("relationships", []))
#             return {
#                 "status": "success",
#                 "nodes": total_nodes,
#                 "edges": total_edges
#             }

#         except Exception as e:
#             # Catch any error in the overall tool logic (including YAML loading, etc.)
#             return {
#                 "status": "error",
#                 "step": "overall",
#                 "error": str(e),
#                 "traceback": traceback.format_exc()
#             }

#     # Add future tools here, e.g.:
#     # @mcp.tool()
#     # async def new_tool(...): ...

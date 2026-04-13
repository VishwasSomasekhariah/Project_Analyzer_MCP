# # # src/server.py
# # from mcp.server.fastmcp import FastMCP
# # from starlette.applications import Starlette
# # from starlette.routing import Mount
# # import uvicorn
# # import asyncio

# # mcp = FastMCP("Project Analyzer MCP Server")

# # # Register your tools here or import from tools.py
# # from src.project_analyzer.tools import register_all_tools

# # register_all_tools(mcp)

# # app = Starlette(
# #     routes=[
# #         Mount("/", app=mcp.sse_app()),
# #     ]
# # )

# # async def main():
# #     uvicorn.run(app, host="0.0.0.0", port=8001)

# # if __name__ == "__main__":
# #     asyncio.run(main())

# # src/server.py
# import os
# import logging
# import asyncio
# from typing import Any, Dict, List

# from mcp.server.fastmcp import FastMCP
# from mcp.server import NotificationOptions, Server
# from mcp.server.models import InitializationOptions
# import mcp.server.stdio

# # Import your tools and tool registration function
# from src.project_analyzer_tool.tools import register_all_tools  # Make sure tools.py exports register_tools(server)

# # Set up logging
# logger = logging.getLogger('project_analyzer_mcp')
# logger.setLevel(logging.INFO)

# async def main():
#     logger.info("Starting Project Analyzer MCP Server (stdio transport)")

#     # Create MCP server
#     server = FastMCP("project-analyzer-mcp")

#     # Register all your tools (from tools.py)
#     register_all_tools(server)

#     # Start stdio server loop
#     async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
#         logger.info("Project Analyzer MCP Server running on stdio")
#         await server._mcp_server.run(
#             read_stream,
#             write_stream,
#             server._mcp_server.create_initialization_options(),
#         )

# if __name__ == "__main__":
#     import cProfile
#     import pstats

#     profiler = cProfile.Profile()
#     try:
#         profiler.enable()
#         asyncio.run(main())
#     finally:
#         profiler.disable()
#         profiler.dump_stats("/opt/genpod/server.prof")
#         print("✅ server.prof saved.")

# # src/server.py
# import os
# import logging
# import argparse

# from starlette.applications import Starlette
# from starlette.routing    import Mount
# import uvicorn

# from mcp.server.fastmcp   import FastMCP
# from src.project_analyzer_tool.tools import register_all_tools

# # ——————————————————————————————————————————————————————————
# # 1) Create your FastMCP app and register tools
# # ——————————————————————————————————————————————————————————
# mcp = FastMCP("project-analyzer-server")   # <-- new name here
# register_all_tools(mcp)

# app = Starlette(routes=[ Mount("/", app=mcp.sse_app()) ])

# # ——————————————————————————————————————————————————————————
# # 2) Configure logging
# # ——————————————————————————————————————————————————————————
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s %(levelname)s %(name)s: %(message)s"
# )
# logger = logging.getLogger("project_analyzer_server")  # <-- updated logger name

# # ——————————————————————————————————————————————————————————
# # 3) Parse host & port from ENV or CLI
# # ——————————————————————————————————————————————————————————
# def get_args():
#     p = argparse.ArgumentParser(description="Project Analyzer Server (HTTP/SSE MCP)")
#     p.add_argument(
#         "--host", "-H",
#         default=os.getenv("PROJECT_ANALYZER_MCP_HOST", "0.0.0.0"),
#         help="Host to bind"
#     )
#     p.add_argument(
#         "--port", "-P",
#         type=int,
#         default=int(os.getenv("PROJECT_ANALYZER_MCP_HTTP_PORT", "9001")),
#         help="Port to bind"
#     )
#     return p.parse_args()

# def main():
#     args = get_args()
#     logger.info(f"Starting Project Analyzer Server on {args.host}:{args.port}")
#     uvicorn.run(app, host=args.host, port=args.port, log_level="info")

# if __name__ == "__main__":
#     main()

# # src/server.py
# import os
# import logging
# import asyncio
# from typing import Any, Dict, List
# import uvicorn
# from starlette.applications import Starlette
# from starlette.routing import Route, Mount
# from starlette.responses import JSONResponse

# from mcp.server.fastmcp import FastMCP
# from mcp.server import NotificationOptions, Server
# from mcp.server.models import InitializationOptions
# import mcp.server.stdio

# # Import your tools and tool registration function
# from src.project_analyzer_tool.tools import register_all_tools, monitor_config

# # Set up logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger('project_analyzer_mcp')
# logger.setLevel(logging.INFO)

# # HTTP endpoint to get project path
# async def get_project_info(request):
#     return JSONResponse(monitor_config)

# # Create Starlette app for HTTP endpoints
# routes = [
#     Route("/project-info", get_project_info, methods=["GET"])
# ]
# app = Starlette(routes=routes)

# async def run_stdio_server(mcp_server):
#     """Run the stdio server transport"""
#     logger.info("Starting Project Analyzer MCP Server (stdio transport)")
#     async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
#         logger.info("Project Analyzer MCP Server running on stdio")
#         await mcp_server._mcp_server.run(
#             read_stream,
#             write_stream,
#             mcp_server._mcp_server.create_initialization_options(),
#         )

# async def run_http_server():
#     """Run the HTTP server transport"""
#     logger.info("Starting Project Analyzer MCP Server (HTTP transport)")
#     config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info")
#     server = uvicorn.Server(config)
#     await server.serve()

# async def main():
#     logger.info("Starting Project Analyzer MCP Server with dual transport")

#     # Create MCP server
#     server = FastMCP("project-analyzer-mcp")

#     # Register all your tools (from tools.py)
#     register_all_tools(server)

#     # Add MCP SSE app to the Starlette routes
#     app.routes.append(Mount("/mcp", app=server.sse_app()))
    
#     # Create tasks for both transports
#     stdio_task = asyncio.create_task(run_stdio_server(server))
#     http_task = asyncio.create_task(run_http_server())
    
#     # Wait for both servers to complete (they should run indefinitely)
#     await asyncio.gather(stdio_task, http_task)

# if __name__ == "__main__":
#     import cProfile
#     import pstats

#     profiler = cProfile.Profile()
#     try:
#         profiler.enable()
#         asyncio.run(main())
#     finally:
#         profiler.disable()
#         profiler.dump_stats("/opt/genpod/server.prof")
#         print("✅ server.prof saved.")

# server.py
import os
import logging
import asyncio
from pathlib import Path
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from src.project_analyzer_tool.tools import register_all_tools, project_config_resource

# Configure production logging with rotation
from src.core.logging_config import setup_logging, cleanup_old_logs

# Setup logging with rotation (10MB per file, keep last 5 files)
logger = setup_logging(
    log_dir=Path("/opt/genpod/logs"),
    max_bytes=10 * 1024 * 1024,  # 10MB per file
    backup_count=5,  # Keep last 5 files
    console_level=logging.INFO,
    file_level=logging.DEBUG,
    enable_debug_file=False  # Set to True for extra debugging
)

# Cleanup old logs on startup (keep last 7 days)
cleanup_old_logs(days_to_keep=7)

# Create FastMCP server with explicit configuration
mcp = FastMCP(
    "mcp-analysis-server",
    ping_interval=30,  # Send keep-alive pings every 30 seconds
    ping_timeout=60    # Consider connection dead after 60 seconds without response
)

# Register all tools
register_all_tools(mcp)

# Create a simple endpoint to check project configuration
async def get_project_config(request):
    return JSONResponse(project_config_resource.fn())

# Create SSE transport with explicit message path
transport = SseServerTransport("/messages/")

# Define handler function for SSE connections
async def handle_sse(request):
    try:
        async with transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1], mcp._mcp_server.create_initialization_options()
            )
    except BaseExceptionGroup as eg:
        # Suppress known MCP cancel scope cleanup errors (GitHub issues: python-sdk#521, pydantic-ai#2355)
        # This occurs when parallel MCP tool calls (like CoT agents) create nested SSE connections
        # that get cleaned up from different task contexts. The error is benign - responses are
        # already successfully returned, this only affects cleanup.
        import logging
        logger = logging.getLogger(__name__)

        # Check the FULL exception representation (includes all nested exceptions)
        full_exc_str = repr(eg).lower()
        if "cancel scope" in full_exc_str or "cancel_scope" in full_exc_str:
            # This is the known benign cleanup error - suppress it
            logger.debug("Suppressed cancel scope cleanup error - this is expected with parallel MCP tool calls")
        else:
            # Unknown error - re-raise
            raise

class TransportASGI:
    def __init__(self, transport):
        self.transport = transport
    async def __call__(self, scope, receive, send):
        await self.transport.handle_post_message(scope, receive, send)

app = Starlette(
    routes=[
        Route("/project-config", get_project_config, methods=["GET"]),
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages", app=TransportASGI(transport)),
    ]
)
# Create Starlette app with proper routes
# app = Starlette(
#     routes=[
#         Route("/project-config", get_project_config, methods=["GET"]),
#         Route("/sse", endpoint=handle_sse),
#         Mount("/messages", app=transport.handle_post_message)
#     ]
# )

# Server startup function
async def run_server():
    """Run server with HTTP/SSE transport"""
    import uvicorn
    
    # Configure uvicorn server
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=9000,
        timeout_keep_alive=3600,  # Keep connections alive longer
        log_level="info"
    )
    
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(run_server())

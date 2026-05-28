# tester.py

# import asyncio
# import time
# from fastmcp import Client
# from fastmcp.client.transports import SSETransport

# PROJECT_ANALYZER_MCP_URL = "http://localhost:8001/sse"

# async def main():
#     async with Client(transport=SSETransport(PROJECT_ANALYZER_MCP_URL)) as pa_client:
#         # List available tools
#         tools = await pa_client.list_tools()
#         print("Available tools:", [tool.name for tool in tools])
        

#         start = time.time()
#         # Call analyze_project (adjust arguments as needed)
#         try:
#             result = await pa_client.call_tool(
#                 "project_analysis_tool",
#                 arguments={
#                     "project_path": "/opt/booking-modular-monolith",
#                     "mappings_path": "/opt/genpod/parsing_utils/mappings.yaml",
#                     "queries_path": "/opt/genpod/parsing_utils/queries.yaml"
#                 },
#                 _return_raw_result = True
#             )
#         except Exception as e:
#             print("Error calling project_analysis_tool:", str(e))
#             return
#         end = time.time()
#         print(f"Execution time: {end - start:.6f} seconds")
#         print("analyze_project result:", result)

# if __name__ == "__main__":
#     asyncio.run(main())


# import asyncio
# from mcp import ClientSession, StdioServerParameters
# from mcp.client.stdio import stdio_client
# import cProfile
# import pstats
# # import sys
# # print(sys.path)

# async def main():
#     # Use the CLI entrypoint installed by your package
#     server_params = StdioServerParameters(
#         command="python",  # or whatever your CLI is named
#         args=["-m","src"],
#         env=None
#     )

#     async with stdio_client(server_params) as (read, write):
#         async with ClientSession(read, write) as session:
#             await session.initialize()
#             tools_response = await session.list_tools()
#             print("Available tools:", [tool.name for tool in tools_response.tools])
#             result = await session.call_tool(
#                 "project_analysis_tool",
#                 arguments={
#                     "project_path": "/opt/booking-modular-monolith",
#                     "mappings_path": "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml",
#                     "queries_path": "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries"
#                 }
#             )
#             print("project_analysis result:", result)

# if __name__ == "__main__":
#     asyncio.run(main())

#!/usr/bin/env python3
#tester.py
import asyncio
import time
import logging
import json
import tempfile
import os

from mcp_use import MCPClient

# ——— Configuration —————————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Point at your SSE transport
MCP_SERVER_URL = "http://localhost:9000/sse"


def unwrap_content(result):
    """
    The mcp_use client returns result.content as a list of TextContent objects.
    We pull out the first element, take its .text and JSON-decode it if possible.
    """
    raw = result.content
    if isinstance(raw, list) and raw:
        raw = raw[0]
    # If it has a .text attribute, attempt to parse JSON out of it
    if hasattr(raw, "text"):
        try:
            return json.loads(raw.text)
        except json.JSONDecodeError:
            return raw.text
    return raw


async def main():
    logger.info(f"Connecting to MCP server at {MCP_SERVER_URL}")

    # 1) Write a temporary MCP config file that points at /sse
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as tf:
        cfg = {
            "mcpServers": {
                "project-analyzer-server": {
                    "type": "http",
                    "url": MCP_SERVER_URL
                }
            }
        }
        json.dump(cfg, tf)
        config_path = tf.name

    try:
        # 2) Create the client & session
        client = MCPClient.from_config_file(config_path)
        session = await client.create_session("project-analyzer-server")

        # 3) Pre-set project_path so that any watcher will unblock immediately
        logger.info("Setting project_path on server...")
        resp = await session.call_tool(
            "set_project_path",
            {"project_path": "/opt/HelloWorldApp"}
        )
        payload = unwrap_content(resp)
        logger.info("set_project_path → %s", payload)

        # 4) Now invoke the heavy analysis tool
        logger.info("Calling project_analysis_tool…")
        t0 = time.time()
        analysis_result = await session.call_tool(
            "project_analysis_tool",
            arguments={
                "project_path":  "/opt/HelloWorldApp",
                "mappings_path": "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml",
                "queries_path":  "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries",
                "config_path":   "/opt/genpod/neo4j_config.json"
            }
        )
        query_db_result = await session.call_tool(
            "query_cpg",
            arguments={
                "query":  "Give me all the functions that abc class object call in xyz file"
            }
        )
        duration = time.time() - t0
        logger.info("Analysis took %.2f seconds", duration)

        # 5) Unwrap and inspect
        result_payload = unwrap_content(analysis_result)
        logger.info("project_analysis_tool → %s", result_payload)

        status = result_payload.get("status")
        if status == "success":
            logger.info("✓ Analysis succeeded")
            logger.info("STDOUT:\n%s", result_payload.get("stdout", "").strip())
        else:
            logger.error("✗ Analysis failed: %s", result_payload.get("error", "<no error>"))

    except Exception as e:
        logger.exception("Error during MCP interaction")
    finally:
        # Clean up
        try:
            os.unlink(config_path)
        except OSError:
            pass
        await client.close_session("project-analyzer-server")


if __name__ == "__main__":
    asyncio.run(main())




# import asyncio
# import json
# from mcp import ClientSession
# from mcp.client.sse import sse_client

# async def main():
#     sse_url = "http://host.docker.internal:8001/sse"

#     try:
#         # 1) Open an SSE transport to your MCP server
#         async with sse_client(sse_url) as (read_stream, write_stream):
#             # 2) Create and initialize our session
#             session = ClientSession(read_stream, write_stream)
#             await session.initialize()

#             # 3) List tools
#             tools_resp = await session.list_tools()
#             print("Available tools:", [t.name for t in tools_resp.tools])

#             # 4) Call your tool (with config_file!)
#             call_result = await session.call_tool(
#                 "project_analysis_tool",
#                 arguments={
#                     "project_path":   "/opt/HelloWorldApp",
#                     "mappings_path":  "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml",
#                     "queries_path":   "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries",
#                     "config_file": "/opt/genpod/neo4j_config.json"
#                 }
#             )

#             # 5) Unwrap and pretty-print
#             content = call_result.content
#             print("project_analysis_tool result:")
#             print(json.dumps(content, indent=2))

#             # 6) Clean up
#             await session.close()

#     except Exception as e:
#         print("❌ Test failed with exception:")
#         import traceback
#         traceback.print_exc()

# if __name__ == "__main__":
#     asyncio.run(main())

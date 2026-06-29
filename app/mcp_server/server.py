"""
The real MCP server — speaks the Model Context Protocol so Claude,
GPT-4o, or any MCP-aware AI can discover and call tools natively.

It does NOT know about UOM, Dimitri, HR, or any specific project.
At startup it loads whatever is in the registry and answers two MCP
requests generically:

  list_tools  -> describe every registry entry as an MCP tool
  call_tool   -> look the name up in the registry, dispatch dynamically

There is no per-tool branch anywhere in this file. Add a thousand more
tools to the registry and this file never changes.

Run directly (stdio transport, e.g. for Claude Desktop):
    python -m app.mcp_server.server
"""
from __future__ import annotations

import json
import logging

import mcp.types as types
from mcp.server import Server

from app.mcp_server.dispatcher import ToolExecutionError, execute_tool
from app.mcp_server.registry import ToolDefinition, get_tool, load_tools

logger = logging.getLogger(__name__)

server = Server("registry-mcp-server")

_REGISTRY: dict[str, ToolDefinition] = load_tools()


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """
    Generic discovery handler — describes whatever is currently in the
    registry. An AI client calls this once to learn every available tool,
    its description, and its parameter schema.
    """
    return [
        types.Tool(
            name=tool.tool_name,
            description=f"[{tool.project}] {tool.description}",
            inputSchema=tool.parameters,
        )
        for tool in _REGISTRY.values()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """
    Generic dispatch handler — the ONLY routing logic in the whole server
    is "look the name up in the registry". Whatever the registry says
    about that tool (its URL, method, auth, project, resource group)
    is what gets called. No if/else chain, no Switch statement.
    """
    tool = get_tool(name, _REGISTRY)
    if tool is None:
        logger.warning("Unknown tool requested: %s", name)
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "mcp_status": "error",
                "error_type": "unknown_tool",
                "tool_name": name,
                "available_tools": list(_REGISTRY.keys()),
            }),
        )]

    try:
        result = await execute_tool(tool, arguments or {})
        payload = {
            "mcp_status": "success",
            "tool_name": tool.tool_name,
            "project": tool.project,
            "result": result,
        }
    except ToolExecutionError as exc:
        logger.error("Tool failed | tool=%s detail=%s", exc.tool_name, exc.detail)
        payload = {
            "mcp_status": "error",
            "tool_name": exc.tool_name,
            "backend_status_code": exc.status_code,
            "message": exc.detail,
        }

    return [types.TextContent(type="text", text=json.dumps(payload))]


async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)
    logger.info("Starting registry-driven MCP server with %d tool(s): %s",
                len(_REGISTRY), ", ".join(_REGISTRY.keys()))
    asyncio.run(_run_stdio())

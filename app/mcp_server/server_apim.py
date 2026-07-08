"""
APIM-backed MCP server with JSON fallback.

Priority:
  1. APIM dynamic discovery (reads live from Azure APIM Management API)
  2. JSON fallback (tools_registry.json) — used when APIM auth is unavailable

This means the server is always functional:
  - With APIM credentials  → tools list updates automatically when APIs are added to APIM
  - Without APIM credentials → falls back to tools_registry.json exactly like the original server
"""
from __future__ import annotations

import json
import logging

import mcp.types as types
from mcp.server import Server

from app.mcp_server import apim_dynamic
from app.mcp_server.dispatcher import ToolExecutionError, execute_tool
from app.mcp_server.registry import ToolDefinition, get_tool, load_tools

logger = logging.getLogger(__name__)

server = Server("registry-mcp-server")

# APIM-discovered tools cache — refreshed on every tools/list call
_apim_tools: list[dict] = []

# JSON fallback registry — loaded once at startup
_json_registry: dict[str, ToolDefinition] = load_tools()


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    global _apim_tools

    # Try APIM dynamic discovery first
    try:
        _apim_tools = await apim_dynamic.fetch_tools()
        if _apim_tools:
            logger.info("APIM dynamic: returning %d tools", len(_apim_tools))
            return [
                types.Tool(
                    name=t["name"],
                    description=t["description"],
                    inputSchema=t["inputSchema"],
                )
                for t in _apim_tools
            ]
    except Exception as exc:
        logger.warning("APIM discovery failed, falling back to JSON registry: %s", exc)

    # Fallback to tools_registry.json
    logger.info("JSON fallback: returning %d tools from registry", len(_json_registry))
    return [
        types.Tool(
            name=tool.tool_name,
            description=f"[{tool.project}] {tool.description}",
            inputSchema=tool.parameters,
        )
        for tool in _json_registry.values()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    arguments = arguments or {}

    # If we have APIM tools cached, try APIM routing first
    if _apim_tools:
        apim_tool = next((t for t in _apim_tools if t["name"] == name), None)
        if apim_tool:
            try:
                result = await apim_dynamic.call_tool(name, arguments, _apim_tools)
                return [types.TextContent(type="text", text=result)]
            except Exception as exc:
                logger.warning("APIM tool call failed for %s: %s", name, exc)

    # Fallback to JSON registry dispatcher
    tool = get_tool(name, _json_registry)
    if tool is None:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "mcp_status": "error",
                "error_type": "unknown_tool",
                "tool_name": name,
                "available_tools": list(_json_registry.keys()),
            }),
        )]

    try:
        result = await execute_tool(tool, arguments)
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

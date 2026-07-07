"""
APIM-backed MCP server.

Uses apim_dynamic.py to discover tools live from Azure API Management instead
of reading a static tools_registry.json file.

Key difference vs server.py:
  server.py    → reads tools_registry.json on startup (static, redeploy to update)
  server_apim.py → reads APIM Management API on each tools/list call (dynamic)

Adding a new API to APIM and tagging it "mcp-enabled" makes it appear here
within seconds — no code change, no redeploy needed.
"""
from __future__ import annotations

import logging

from mcp.server import Server
from mcp.types import Tool, TextContent

from app.mcp_server import apim_dynamic

logger = logging.getLogger(__name__)

server = Server("apim-mcp-gateway")

# Cache of tools fetched from APIM — refreshed on every tools/list call.
# In production, add a TTL cache (e.g. 60 seconds) to avoid hammering the
# Azure Management API on every agent request.
_tools_cache: list[dict] = []


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    global _tools_cache

    logger.info("Fetching tool list from APIM...")
    _tools_cache = await apim_dynamic.fetch_tools()
    logger.info("APIM returned %d tools", len(_tools_cache))

    return [
        Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["inputSchema"],
        )
        for t in _tools_cache
        # Strip _meta — not part of the MCP spec
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info("Tool call: %s  args=%s", name, arguments)

    if not _tools_cache:
        # tools/list was not called first — fetch on demand
        await handle_list_tools()

    try:
        result = await apim_dynamic.call_tool(name, arguments, _tools_cache)
        return [TextContent(type="text", text=result)]
    except ValueError as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]
    except Exception as exc:
        logger.exception("Tool call failed: %s", exc)
        return [TextContent(type="text", text=f"Error calling {name}: {exc}")]

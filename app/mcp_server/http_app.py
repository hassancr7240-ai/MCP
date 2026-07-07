"""
HTTP transport for the registry-driven MCP server.

Exposes two transports:
  /sse + /messages/  — Legacy SSE transport (Claude Desktop, dashboard client)
  /mcp               — Streamable HTTP transport (Copilot Studio, modern clients)

Run directly:
    uvicorn app.mcp_server.http_app:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import logging

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from app.mcp_server.server import server

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Legacy SSE transport — backward compat for Claude Desktop and dashboard
_sse = SseServerTransport("/messages/")


async def _handle_sse(request: Request) -> None:
    async with _sse.connect_sse(request.scope, request.receive, request._send) as (
        read_stream,
        write_stream,
    ):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


routes = [
    Route("/sse", endpoint=_handle_sse),
    Mount("/messages/", app=_sse.handle_post_message),
]

# Streamable HTTP transport — for Copilot Studio and modern MCP clients
try:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    _session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=False,
        stateless=True,
    )
    routes.append(Mount("/mcp", app=_session_manager.handle_request))
    logger.info("Streamable HTTP transport enabled at /mcp")
except (ImportError, AttributeError) as exc:
    logger.warning("Streamable HTTP transport not available: %s", exc)


app = Starlette(routes=routes)

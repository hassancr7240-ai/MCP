"""
HTTP transport for the APIM-backed MCP server.

Run standalone:
    uvicorn app.mcp_server.http_app_apim:app --host 0.0.0.0 --port 8081

Endpoints:
  POST /mcp   — Streamable HTTP (Copilot Studio, modern clients)
  GET  /sse   — Legacy SSE transport (Claude Desktop, dashboard)
  POST /messages/

This server differs from http_app.py only in which MCP server instance it
wraps: server_apim.server reads tools live from Azure APIM instead of
tools_registry.json.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from app.mcp_server.server_apim import server

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_sse = SseServerTransport("/apim-messages/")


async def _handle_sse(request: Request) -> None:
    async with _sse.connect_sse(request.scope, request.receive, request._send) as (
        read_stream,
        write_stream,
    ):
        await server.run(read_stream, write_stream, server.create_initialization_options())


routes = [
    Route("/sse", endpoint=_handle_sse),
    Mount("/apim-messages/", app=_sse.handle_post_message),
]

_session_manager = None
try:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    _session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=False,
        stateless=True,
    )
    routes.append(Mount("/mcp", app=_session_manager.handle_request))
    logger.info("APIM-backed Streamable HTTP transport enabled at /mcp")
except (ImportError, AttributeError) as exc:
    logger.warning("Streamable HTTP transport not available: %s", exc)


@asynccontextmanager
async def lifespan(app):
    if _session_manager is not None:
        async with _session_manager.run():
            logger.info("APIM-backed StreamableHTTPSessionManager running")
            yield
    else:
        yield


app = Starlette(routes=routes, lifespan=lifespan)

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
import os
from contextlib import asynccontextmanager

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.mcp_server import apim_dynamic
from app.mcp_server.server_apim import server

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Wire Application Insights if connection string is set in environment.
# Set APPLICATIONINSIGHTS_CONNECTION_STRING on the App Service to activate.
_ai_connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
if _ai_connection_string:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=_ai_connection_string)
        logger.info("Application Insights monitoring enabled")
    except ImportError:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is set but "
            "azure-monitor-opentelemetry is not installed — monitoring inactive"
        )

_sse = SseServerTransport("/apim-messages/")


async def _handle_sse(request: Request) -> None:
    async with _sse.connect_sse(request.scope, request.receive, request._send) as (
        read_stream,
        write_stream,
    ):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def _handle_health(request: Request) -> JSONResponse:
    """
    Health check endpoint.
    Returns server status, cached tool count, and cache freshness.
    Useful for Azure App Service health probes and manual verification.
    """
    cache = apim_dynamic.get_cache_info()
    return JSONResponse({
        "status": "ok",
        "apim_name": apim_dynamic.APIM_NAME,
        "apim_base_url": apim_dynamic.APIM_BASE_URL,
        "mcp_tag": apim_dynamic.MCP_TAG,
        "require_tag": apim_dynamic.APIM_REQUIRE_TAG,
        "tool_count": cache["tool_count"],
        "cache_age_seconds": cache["cache_age_seconds"],
        "cache_fresh": cache["cache_fresh"],
        "cache_ttl_seconds": cache["cache_ttl_seconds"],
    })


routes = [
    Route("/health", endpoint=_handle_health),
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

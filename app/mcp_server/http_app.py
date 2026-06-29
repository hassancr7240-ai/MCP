"""
HTTP/SSE transport for the registry-driven MCP server.

stdio transport (server.py) is for local Claude Desktop config.
This module exposes the exact same `server` over HTTP+SSE so it can be
deployed to Azure (Container App / App Service / Function App with a
custom handler) and reached remotely by any MCP-aware client — this is
what "publish via MCP" means in production: one HTTP endpoint that an
AI client connects to, discovers every registered tool, and calls
whichever one it needs, regardless of which project that tool's API
actually lives in.

Run directly:
    uvicorn app.mcp_server.http_app:app --host 0.0.0.0 --port 8080

Then point an MCP client at:
    http://<host>:8080/sse
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


app = Starlette(
    routes=[
        Route("/sse", endpoint=_handle_sse),
        Mount("/messages/", app=_sse.handle_post_message),
    ],
)

"""
Dynamic dispatcher — executes ANY registered tool by reading its
definition from the registry. There is no per-tool branch here.

This single function can call a Logic App in one resource group, a
Function App in another, or a plain REST API behind APIM — because it
never hardcodes a target. It only follows what the registry entry says.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.mcp_server.registry import ToolDefinition

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    def __init__(self, tool_name: str, status_code: int | None, detail: str):
        self.tool_name = tool_name
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{tool_name} failed ({status_code}): {detail}")


async def execute_tool(tool: ToolDefinition, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Looks up nothing about *which* tool this is — only reads `tool`'s
    own definition and calls whatever it points to. Add a thousand more
    tools to the registry and this function never changes.
    """
    headers: dict[str, str] = {}
    if tool.auth_key_value:
        headers[tool.auth_header] = tool.auth_key_value
    else:
        logger.warning(
            "No auth key found for tool=%s (env var %s not set) — calling without auth header",
            tool.tool_name, tool.auth_key_env,
        )

    request_kwargs: dict[str, Any] = {"headers": headers}
    if tool.param_location == "query":
        request_kwargs["params"] = arguments
    else:
        headers["Content-Type"] = "application/json"
        request_kwargs["json"] = arguments

    logger.info(
        "Dispatching tool=%s project=%s method=%s url=%s",
        tool.tool_name, tool.project, tool.method, tool.target_url,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(tool.method, tool.target_url, **request_kwargs)
        except httpx.RequestError as exc:
            raise ToolExecutionError(tool.tool_name, None, f"connection error: {exc}") from exc

    if response.status_code >= 300:
        raise ToolExecutionError(tool.tool_name, response.status_code, response.text)

    try:
        return response.json()
    except ValueError:
        return {"raw_response": response.text}

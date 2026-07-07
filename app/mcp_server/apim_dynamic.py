"""
APIM Dynamic Registry — reads tool definitions live from Azure API Management.

This replaces tools_registry.json. Instead of a static JSON file that requires
a redeploy when APIs change, this module queries APIM at runtime:

  - tools/list  → fetches APIs tagged "mcp-enabled" from APIM Management API
  - tools/call  → routes the call to the APIM gateway endpoint

HOW TO TAG AN API IN APIM:
  Azure Portal → APIM → APIs → [your API] → Tags → add "mcp-enabled"
  The MCP server sees it in the next tools/list call — no code change, no redeploy.

AUTHENTICATION:
  Local dev  : uses az login credentials (AzureCliCredential)
  Azure prod : uses App Service Managed Identity (DefaultAzureCredential)

ENVIRONMENT VARIABLES:
  AZURE_SUBSCRIPTION_ID   Azure subscription that hosts APIM
  APIM_RESOURCE_GROUP     Resource group of the APIM instance
  APIM_SERVICE_NAME       APIM service name (e.g. apim-dev-intg)
  APIM_BASE_URL           APIM gateway URL (e.g. https://apim-dev-intg.azure-api.net)
  APIM_MCP_TAG            Tag to filter APIs (default: mcp-enabled)
  APIM_SUBSCRIPTION_KEY   Subscription key sent on every tool call (x-api-key header)
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "ea51059b-b5f5-4a86-ae78-6fbf365d1c89")
RESOURCE_GROUP = os.getenv("APIM_RESOURCE_GROUP", "rg-dev-integrationTeam")
APIM_NAME = os.getenv("APIM_SERVICE_NAME", "apim-dev-intg")
APIM_BASE_URL = os.getenv("APIM_BASE_URL", "https://apim-dev-intg.azure-api.net").rstrip("/")
MCP_TAG = os.getenv("APIM_MCP_TAG", "mcp-enabled")
APIM_SUBSCRIPTION_KEY = os.getenv("APIM_SUBSCRIPTION_KEY", "")

_MGMT_BASE = (
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}"
    f"/resourceGroups/{RESOURCE_GROUP}"
    f"/providers/Microsoft.ApiManagement/service/{APIM_NAME}"
)
_API_VERSION = "2022-08-01"


def _get_bearer_token() -> str:
    """Return an Azure Management API bearer token.

    Tries AzureCliCredential first (local dev), then DefaultAzureCredential
    (Managed Identity on Azure App Service / Container).
    """
    try:
        from azure.identity import AzureCliCredential
        token = AzureCliCredential().get_token("https://management.azure.com/.default")
        return token.token
    except Exception:
        pass

    from azure.identity import DefaultAzureCredential
    token = DefaultAzureCredential().get_token("https://management.azure.com/.default")
    return token.token


def _tool_name(api_name: str, op_name: str) -> str:
    """Build a valid MCP tool name from APIM identifiers."""
    raw = f"{api_name}__{op_name}".lower()
    return "".join(c if c.isalnum() or c == "_" else "_" for c in raw)[:64]


def _build_input_schema(operation: dict) -> dict:
    """
    Build an MCP inputSchema from an APIM operation definition.

    APIM operations can define request parameters (query, path, header) and a
    request body. We map those to JSON Schema properties here.
    """
    props: dict[str, Any] = {}
    required: list[str] = []

    request = operation.get("properties", {}).get("request") or {}

    # Query / path parameters
    for param in request.get("queryParameters", []) + request.get("headers", []):
        name = param.get("name", "")
        if not name:
            continue
        props[name] = {
            "type": param.get("type", "string"),
            "description": param.get("description", name),
        }
        if param.get("required", False):
            required.append(name)

    # Template (path) parameters
    for param in operation.get("properties", {}).get("templateParameters", []) or []:
        name = param.get("name", "")
        if not name:
            continue
        props[name] = {
            "type": param.get("type", "string"),
            "description": param.get("description", f"Path parameter: {name}"),
        }
        if param.get("required", True):
            required.append(name)

    # Request body (take first representation)
    representations = request.get("representations", [])
    if representations:
        body_schema = representations[0].get("schema", {})
        if body_schema:
            return {
                "type": "object",
                "properties": body_schema.get("properties", props),
                "required": body_schema.get("required", required),
            }

    return {"type": "object", "properties": props, "required": required}


def _operation_to_tool(api: dict, operation: dict) -> dict:
    """Convert an APIM API + operation pair into an MCP tool definition."""
    api_props = api.get("properties", {})
    op_props = operation.get("properties", {})

    api_id = api.get("name", "")
    op_id = operation.get("name", "")
    api_path = api_props.get("path", "").strip("/")
    op_path = op_props.get("urlTemplate", "").strip("/")
    method = op_props.get("method", "GET").upper()

    full_path = f"/{api_path}/{op_path}".replace("//", "/")
    url = f"{APIM_BASE_URL}{full_path}"

    description = (
        op_props.get("description")
        or f"{api_props.get('displayName', api_id)}: {op_props.get('displayName', op_id)}"
    )

    return {
        "name": _tool_name(api_id, op_id),
        "description": description,
        "inputSchema": _build_input_schema(operation),
        # _meta is not part of MCP spec but used internally for routing
        "_meta": {
            "api_id": api_id,
            "op_id": op_id,
            "method": method,
            "url": url,
        },
    }


async def fetch_tools() -> list[dict]:
    """
    Query APIM Management REST API and return all MCP tool definitions.

    Filters to APIs tagged with APIM_MCP_TAG (default: "mcp-enabled").
    If no tagged APIs exist, falls back to ALL APIs so the POC still works.
    """
    try:
        token = _get_bearer_token()
    except Exception as exc:
        logger.error("Cannot get Azure token for APIM discovery: %s", exc)
        return []

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=20) as client:
        # Fetch all APIs
        resp = await client.get(
            f"{_MGMT_BASE}/apis?api-version={_API_VERSION}", headers=headers
        )
        resp.raise_for_status()
        all_apis = resp.json().get("value", [])

        # Filter to tagged APIs; fall back to all if none tagged
        tagged = [
            a for a in all_apis
            if MCP_TAG in (a.get("properties", {}).get("tags") or [])
        ]
        apis = tagged or all_apis

        logger.info(
            "APIM discovery: %d total APIs, %d with tag '%s' → using %d",
            len(all_apis), len(tagged), MCP_TAG, len(apis),
        )

        tools: list[dict] = []
        for api in apis:
            api_id = api.get("name", "")
            try:
                ops_resp = await client.get(
                    f"{_MGMT_BASE}/apis/{api_id}/operations?api-version={_API_VERSION}",
                    headers=headers,
                )
                ops_resp.raise_for_status()
                for op in ops_resp.json().get("value", []):
                    tools.append(_operation_to_tool(api, op))
            except Exception as exc:
                logger.warning("Skipping API %s: %s", api_id, exc)

        return tools


async def call_tool(tool_name: str, arguments: dict, tools: list[dict]) -> str:
    """
    Execute a tool by routing the call to the appropriate APIM endpoint.

    Returns the raw response body as a string.
    """
    # Find the tool
    tool = next((t for t in tools if t["name"] == tool_name), None)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name}")

    meta = tool["_meta"]
    method = meta["method"]
    url = meta["url"]

    headers: dict[str, str] = {}
    if APIM_SUBSCRIPTION_KEY:
        headers["Ocp-Apim-Subscription-Key"] = APIM_SUBSCRIPTION_KEY
        headers["x-api-key"] = APIM_SUBSCRIPTION_KEY

    async with httpx.AsyncClient(timeout=30) as client:
        if method == "GET":
            resp = await client.get(url, params=arguments, headers=headers)
        else:
            resp = await client.request(method, url, json=arguments, headers=headers)

        return resp.text

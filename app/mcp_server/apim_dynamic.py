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
  APIM_MCP_TAG            Tag to whitelist APIs (default: mcp-enabled)
  APIM_MCP_EXCLUDE_TAG    Tag to blocklist APIs (default: mcp-excluded)
  APIM_SUBSCRIPTION_KEY   Subscription key sent on every tool call (x-api-key header)
  APIM_EXCLUDED_APIS      Comma-separated exact API names to block (no redeploy needed)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "ea51059b-b5f5-4a86-ae78-6fbf365d1c89")
RESOURCE_GROUP = os.getenv("APIM_RESOURCE_GROUP", "rg-dev-integrationTeam")
APIM_NAME = os.getenv("APIM_SERVICE_NAME", "apim-dev-intg")
APIM_BASE_URL = os.getenv("APIM_BASE_URL", "https://apim-dev-intg.azure-api.net").rstrip("/")
MCP_TAG = os.getenv("APIM_MCP_TAG", "mcp-enabled")
MCP_EXCLUDE_TAG = os.getenv("APIM_MCP_EXCLUDE_TAG", "mcp-excluded")
APIM_SUBSCRIPTION_KEY = os.getenv("APIM_SUBSCRIPTION_KEY", "")

# When True: zero tagged APIs → return zero tools (production safe).
# When False (default): zero tagged APIs → return all APIs (POC mode).
APIM_REQUIRE_TAG = os.getenv("APIM_REQUIRE_TAG", "true").lower() == "true"

# Comma-separated list of exact APIM API names to block from MCP tool list.
# Set APIM_EXCLUDED_APIS=api_name_1,api_name_2 on AApp Service — no code change needed.
_EXCLUDED_EXACT: frozenset[str] = frozenset(
    x.strip() for x in os.getenv("APIM_EXCLUDED_APIS", "").split(",") if x.strip()
)

# How long (seconds) to keep the tool list in memory before re-fetching.
# On cache miss or refresh failure, stale cache is served instead of empty.
_CACHE_TTL = int(os.getenv("APIM_CACHE_TTL_SECONDS", "600"))  # 10 minutes

_tool_cache: list[dict] = []
_cache_timestamp: float = 0.0

# System-to-system EDI/B2B APIs — not meant for AI interaction, excluded from tool list
_EXCLUDED_PREFIXES = (
    "o2c_",          # Order-to-Cash EDI inbound callbacks
    "p2p_",          # Procure-to-Pay EDI callbacks
    "p2m_",          # Procure-to-Manufacture EDI
    "b2b_",          # B2B/EDI integrations
    "echo_api",      # APIM test/echo API
    "testblob",      # Test blob API
    "fourkites_",    # FourKites inbound webhook
    "fap_dev_",      # Live tracking event ingest (inbound)
    "3pl_ofc_",      # 3PL inbound callbacks
    "fn_dev_edi_",   # EDI function app inbounds
)
_MAX_TOOLS = 70

_MGMT_BASE = (
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}"
    f"/resourceGroups/{RESOURCE_GROUP}"
    f"/providers/Microsoft.ApiManagement/service/{APIM_NAME}"
)
_API_VERSION = "2022-08-01"


def get_cache_info() -> dict:
    """Return current cache state — used by the /health endpoint."""
    age = round(time.time() - _cache_timestamp, 1) if _cache_timestamp else None
    return {
        "tool_count": len(_tool_cache),
        "cache_age_seconds": age,
        "cache_fresh": age is not None and age < _CACHE_TTL,
        "cache_ttl_seconds": _CACHE_TTL,
        "require_tag": APIM_REQUIRE_TAG,
        "exclude_tag": MCP_EXCLUDE_TAG,
        "excluded_exact_count": len(_EXCLUDED_EXACT),
    }


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


async def _discover_tools() -> list[dict]:
    """
    Inner discovery function — calls management.azure.com and builds tool list.
    Called by fetch_tools(); do not call directly.
    """
    token = _get_bearer_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{_MGMT_BASE}/apis?api-version={_API_VERSION}", headers=headers
        )
        resp.raise_for_status()
        all_apis = resp.json().get("value", [])

        # Fetch APIs tagged with mcp-enabled via /tagResources?$filter=tag/name eq '...'
        # This is the correct APIM endpoint — /tags/{id}/apis returns 404 when used as a filter.
        tag_resp = await client.get(
            f"{_MGMT_BASE}/tagResources?api-version={_API_VERSION}"
            f"&$filter=tag/name eq '{MCP_TAG}'",
            headers=headers,
        )
        if tag_resp.status_code == 200:
            tagged_names = {
                r["api"]["name"]
                for r in tag_resp.json().get("value", [])
                if r.get("api") and r["api"].get("name")
            }
        else:
            logger.warning("Could not fetch tagged APIs (status %d) — treating as empty", tag_resp.status_code)
            tagged_names = set()

        tagged = [a for a in all_apis if a.get("name") in tagged_names]

        # APIM_REQUIRE_TAG=true  → production mode: tagged only, empty if none tagged
        # APIM_REQUIRE_TAG=false → POC mode: fall back to all APIs when none tagged
        if APIM_REQUIRE_TAG:
            candidate_apis = tagged
        else:
            candidate_apis = tagged or all_apis

        # Fetch excluded tag list the same way
        exclude_resp = await client.get(
            f"{_MGMT_BASE}/tagResources?api-version={_API_VERSION}"
            f"&$filter=tag/name eq '{MCP_EXCLUDE_TAG}'",
            headers=headers,
        )
        if exclude_resp.status_code == 200:
            excluded_names = {
                r["api"]["name"]
                for r in exclude_resp.json().get("value", [])
                if r.get("api") and r["api"].get("name")
            }
        else:
            excluded_names = set()

        apis = [
            a for a in candidate_apis
            if not any(
                a.get("name", "").lower().replace("-", "_").startswith(p)
                for p in _EXCLUDED_PREFIXES
            )
            and a.get("name", "") not in excluded_names
            and a.get("name", "") not in _EXCLUDED_EXACT
        ]

        logger.info(
            "APIM discovery: %d total, %d tagged, %d after all filters, require_tag=%s",
            len(all_apis), len(tagged), len(apis), APIM_REQUIRE_TAG,
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

        if len(tools) > _MAX_TOOLS:
            logger.warning("Tool count %d exceeds limit %d — truncating", len(tools), _MAX_TOOLS)
            tools = tools[:_MAX_TOOLS]

        return tools


async def fetch_tools() -> list[dict]:
    """
    Return MCP tool definitions, using an in-memory cache to avoid hitting
    management.azure.com on every request.

    Cache TTL is controlled by APIM_CACHE_TTL_SECONDS (default 600 = 10 min).
    If discovery fails and a stale cache exists, the stale cache is returned
    so Copilot Studio stays functional during transient Azure outages.
    """
    global _tool_cache, _cache_timestamp

    # Serve from cache if still fresh
    if _tool_cache and (time.time() - _cache_timestamp) < _CACHE_TTL:
        logger.info("APIM cache hit: returning %d cached tools (age %.0fs)",
                    len(_tool_cache), time.time() - _cache_timestamp)
        return _tool_cache

    # Attempt fresh discovery
    try:
        tools = await _discover_tools()
        _tool_cache = tools
        _cache_timestamp = time.time()
        logger.info("APIM discovery complete: %d tools cached", len(_tool_cache))
        return _tool_cache
    except Exception as exc:
        logger.error("APIM discovery failed: %s", exc)
        if _tool_cache:
            logger.warning(
                "Returning stale cache (%d tools, age %.0fs) — Azure unreachable",
                len(_tool_cache), time.time() - _cache_timestamp,
            )
            return _tool_cache
        logger.error("No cache available — returning empty tool list")
        return []


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

        if resp.is_error:
            logger.warning("APIM call failed | tool=%s status=%d url=%s", tool_name, resp.status_code, url)
            return (
                f'{{"error": true, "status_code": {resp.status_code}, '
                f'"tool": "{tool_name}", "detail": {resp.text!r}}}'
            )

        return resp.text

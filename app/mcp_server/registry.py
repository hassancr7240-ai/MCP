"""
Tool registry — the single source of truth for "which tool maps to which backend".

Today this loads from a JSON file. Tomorrow it can load from Azure Table
Storage / Cosmos DB with the exact same shape — nothing else in the server
needs to change. That swap point is `load_tools()`.

This is what makes the server "loosely coupled": the dispatcher and the
MCP protocol layer never know or care whether a tool is a Logic App in
rg-dev-IntegrationTeamAI, a Function App in rg-hr-prod, or a plain REST API.
They just read `target_url`, `method`, `auth_header`, etc. from here.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REGISTRY_FILE = Path(__file__).parent / "tools_registry.json"


@dataclass(frozen=True)
class ToolDefinition:
    tool_name: str
    description: str
    project: str
    method: str
    target_url: str
    auth_header: str
    auth_key_env: str
    param_location: str          # "query" | "body"
    parameters: dict[str, Any]   # JSON-schema describing the tool's arguments

    @property
    def auth_key_value(self) -> str | None:
        """Resolves the real secret at call time — never stored on the object."""
        return os.getenv(self.auth_key_env)


def load_tools() -> dict[str, ToolDefinition]:
    """
    Loads every tool definition from the registry file.
    Returns empty dict if file is missing — APIM dynamic discovery is the primary source.
    """
    if not _REGISTRY_FILE.exists():
        return {}
    raw = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    tools: dict[str, ToolDefinition] = {}
    for entry in raw.get("tools", []):
        defn = ToolDefinition(
            tool_name=entry["tool_name"],
            description=entry["description"],
            project=entry.get("project", "unknown"),
            method=entry["method"].upper(),
            target_url=entry["target_url"],
            auth_header=entry["auth_header"],
            auth_key_env=entry["auth_key_env"],
            param_location=entry.get("param_location", "query"),
            parameters=entry.get("parameters", {"type": "object", "properties": {}}),
        )
        tools[defn.tool_name] = defn

    logger.info(
        "Loaded %d tool(s) from registry: %s",
        len(tools), ", ".join(f"{t.tool_name} ({t.project})" for t in tools.values()),
    )
    return tools


def get_tool(tool_name: str, registry: dict[str, ToolDefinition]) -> ToolDefinition | None:
    return registry.get(tool_name)

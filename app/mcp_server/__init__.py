"""
Registry-driven MCP server.

Unlike a hardcoded router (Switch/if-else per tool), this server loads
tool definitions from a data registry at startup and dispatches every
call dynamically based on what the registry says — regardless of which
project, resource group, Logic App, Function App, or API the tool
actually lives behind.

Adding a new tool = add one entry to the registry. No code change.
"""

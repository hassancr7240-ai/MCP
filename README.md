# Registry-Driven MCP Server

A registry-driven Model Context Protocol (MCP) server deployed on Azure that dynamically routes AI tool calls to backend APIs (Logic Apps, Function Apps, APIM endpoints) based on a JSON configuration file.

## Architecture

```
Any MCP Client (chatbot, RAG pipeline, Copilot Studio)
        |
        v
registry-mcp-server (Azure App Service)
        |
        v
tools_registry.json (defines tools + backend URLs)
        |
        v
Backend APIs (APIM, Logic Apps, Function Apps)
```

## Project Structure

```
app/
  mcp_server/
    http_app.py           - Entry point, /sse endpoint (Starlette + SSE transport)
    server.py             - MCP protocol handler (list_tools, call_tool)
    registry.py           - Reads tools_registry.json, registers tools dynamically
    dispatcher.py         - Routes tool calls to correct backend API
    tools_registry.json   - Config: tool definitions and backend mappings

dashboard/
    app.py                - Chat UI (FastAPI + Anthropic Claude API)
    Dockerfile            - Dashboard container build
    requirements.txt      - Dashboard dependencies

Dockerfile              - MCP server container build
requirements.txt        - MCP server dependencies
docker-compose.yml      - Local development setup
test_mcp.py             - Quick MCP connection test script
tests/                  - Unit tests
```

## Tech Stack

| Technology | Purpose |
|---|---|
| Python 3.12 | Server language |
| mcp 1.1.2 | MCP protocol library (Anthropic) |
| Starlette | Web framework for /sse endpoint |
| uvicorn | ASGI server |
| FastAPI | Dashboard chat UI |
| anthropic SDK | Claude AI for dashboard chat (not used in MCP server) |
| Docker | Containerization |
| Azure App Service | Hosting (B1 Linux) |
| Azure Container Registry | Docker image storage |

## Azure Resources

All resources are in resource group `rg-dev-IntegrationTeamAI` (West US 2), subscription `Niagara Development`.

| Resource | Type | Purpose |
|---|---|---|
| registry-mcp-server | App Service | The MCP server |
| mcp-dashboard-demo | App Service | Demo chat dashboard |
| acrregistrymcp | Container Registry | Docker image storage |
| asp-registry-mcp | App Service Plan | Hosting plan (B1 Linux) |

## Environment Variables

### MCP Server (registry-mcp-server)

| Variable | Purpose |
|---|---|
| APIM_UOM_DEV_KEY | API key for UOM-Dev backend |
| APIM_DIMITRI_UAT_KEY | API key for Dimitri-UAT backend |

### Dashboard (mcp-dashboard-demo)

| Variable | Purpose |
|---|---|
| ANTHROPIC_API_KEY | Claude API key for chat AI brain |

All keys are stored as Azure App Service environment variables (Settings > Environment variables in Portal), not in code.

## Currently Registered Tools

| Tool | Backend | Method | Description |
|---|---|---|---|
| uom_conversion | APIM Dev (UOM service) | GET | Get unit-of-measure conversion for a product item |
| update_order_request | APIM UAT (Dimitri service) | POST | Update a sales order's reason code, date, and appointment type |

## Adding a New Tool

1. Add an entry to `app/mcp_server/tools_registry.json`:

```json
{
  "tool_name": "check_inventory",
  "description": "Check inventory levels for a product",
  "project": "Inventory",
  "method": "GET",
  "target_url": "https://my-function-app.azurewebsites.net/api/check",
  "auth_header": "x-functions-key",
  "auth_key_env": "FUNC_INVENTORY_KEY",
  "param_location": "query",
  "parameters": {
    "type": "object",
    "properties": {
      "productId": { "type": "string", "description": "Product ID" }
    },
    "required": ["productId"]
  }
}
```

2. Add the API key as an environment variable on the App Service:
   Portal > registry-mcp-server > Settings > Environment variables > add `FUNC_INVENTORY_KEY`

3. Rebuild and restart:

```bash
az acr build --registry acrregistrymcp --image registry-mcp-server:latest --file Dockerfile .
az webapp restart --name registry-mcp-server --resource-group rg-dev-IntegrationTeamAI
```

No code changes required. Every connected client sees the new tool automatically.

## How It Works

1. Client connects to `https://registry-mcp-server.azurewebsites.net/sse`
2. Client sends `list_tools` - server returns all tools from `tools_registry.json`
3. Client sends `call_tool` with tool name + parameters
4. `dispatcher.py` looks up the tool config (URL, method, auth key)
5. Makes real HTTP call to the backend API with proper authentication
6. Returns the backend response to the client

## Running Locally

```bash
pip install -r requirements.txt
uvicorn app.mcp_server.http_app:app --host 0.0.0.0 --port 8000
```

Test connection:

```bash
python test_mcp.py
```

## Deployment

The server is deployed as a Docker container via Azure Container Registry.

```bash
# Build image in ACR (cloud build, no local Docker needed)
az acr build --registry acrregistrymcp --image registry-mcp-server:latest --file Dockerfile .

# Restart App Service to pull latest image
az webapp restart --name registry-mcp-server --resource-group rg-dev-IntegrationTeamAI
```

## Live URLs

| URL | Purpose |
|---|---|
| https://registry-mcp-server.azurewebsites.net/sse | MCP server endpoint (for systems) |
| https://mcp-dashboard-demo.azurewebsites.net/ | Demo dashboard (for humans) |

## Next Steps

- Add Azure AD authentication on the MCP endpoint
- Move API keys to Azure Key Vault
- Set up CI/CD pipeline from Azure DevOps
- Register additional tools as new backends come online
- Optionally swap Claude for Azure OpenAI in the dashboard

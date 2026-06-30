# Registry-Driven MCP Server

A registry-driven Model Context Protocol (MCP) server deployed on Azure that dynamically routes AI tool calls to backend APIs (APIM, Logic Apps, Function Apps) based on a JSON configuration file — no hardcoded routing logic.

> **Branch:** All active development lives on `development`. The `main` branch is protected and merged only after review.

---

## Architecture

```
Any MCP Client
(Claude Desktop / Copilot Studio / Custom Chatbot / RAG Pipeline)
        |
        |  SSE connection (MCP protocol)
        v
registry-mcp-server  (Azure App Service — Docker container)
  ├── http_app.py       → /sse endpoint, accepts MCP connections
  ├── server.py         → MCP protocol: list_tools, call_tool handlers
  ├── registry.py       → reads tools_registry.json, registers tools dynamically
  ├── dispatcher.py     → routes tool call to correct backend API (no hardcoding)
  └── tools_registry.json → SINGLE SOURCE OF TRUTH: all tools, URLs, auth keys
        |
        |  Real HTTP calls (GET/POST with API keys)
        v
Backend APIs
  ├── APIM Dev  (UOM conversion service)
  └── APIM UAT  (Dimitri order update service)

mcp-dashboard-demo  (separate Azure App Service)
  └── dashboard/app.py  → chat UI that connects to MCP server + calls Claude API
```

**Key design principle:** `dispatcher.py` contains zero tool-specific logic. It reads the tool config from `tools_registry.json` and constructs the HTTP call generically. Adding a new tool = editing one JSON file only.

---

## Project Structure

```
app/
  mcp_server/
    http_app.py           Entry point — /sse endpoint (Starlette + MCP SSE transport)
    server.py             MCP protocol handler (list_tools, call_tool)
    registry.py           Reads tools_registry.json, registers all tools at startup
    dispatcher.py         Generic HTTP dispatcher — routes any tool call to its backend
    tools_registry.json   Config file: tool definitions, backend URLs, auth key references

dashboard/
    app.py                Chat UI (FastAPI + Anthropic Claude API)
    Dockerfile            Dashboard container build
    requirements.txt      Dashboard Python dependencies

Dockerfile              MCP server container build
requirements.txt        MCP server Python dependencies
test_mcp.py             Quick MCP connection smoke test
```

---

## Tech Stack

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.12 | Server language |
| mcp | 1.1.2 | MCP protocol library (Anthropic) |
| Starlette | (via mcp) | Web framework for /sse endpoint |
| uvicorn | 0.32.1 | ASGI server |
| FastAPI | 0.115.6 | Dashboard chat UI |
| anthropic SDK | 0.40.0 | Claude AI for dashboard chat only |
| Docker | latest | Containerization |
| Azure App Service | B1 Linux | Hosting |
| Azure Container Registry | acrregistrymcp | Docker image storage |

---

## Azure Resources

All resources are in resource group `rg-dev-IntegrationTeamAI` (West US 2), subscription `Niagara Development`.

| Resource | Type | Purpose |
|---|---|---|
| `registry-mcp-server` | App Service | The MCP server (tools, routing, APIM calls) |
| `mcp-dashboard-demo` | App Service | Demo chat dashboard (Claude AI + chat UI) |
| `acrregistrymcp` | Container Registry | Stores Docker images for both services |
| `asp-registry-mcp` | App Service Plan | Shared B1 Linux hosting plan |

---

## Environment Variables

All keys are stored as Azure App Service environment variables (Portal → App Service → Settings → Environment variables). **Never in code or committed files.**

### MCP Server (`registry-mcp-server`)

| Variable | Purpose |
|---|---|
| `APIM_UOM_DEV_KEY` | API key for UOM Dev backend (referenced by `tools_registry.json`) |
| `APIM_DIMITRI_UAT_KEY` | API key for Dimitri UAT backend (referenced by `tools_registry.json`) |
| `WEBSITES_PORT` | Must be `8080` — matches the container's listening port |

### Dashboard (`mcp-dashboard-demo`)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key — used only by the dashboard chatbot, not by the MCP server |
| `WEBSITES_PORT` | Must be `8080` |

---

## Currently Registered Tools

Defined in `app/mcp_server/tools_registry.json`:

| Tool | Backend | Method | Environment | Description |
|---|---|---|---|---|
| `uom_conversion` | APIM Dev | GET | DEV | Get unit-of-measure conversion for a product item |
| `update_order_request` | APIM UAT | POST | UAT | Update a sales order's reason code, date, and appointment type |

---

## How It Works (Full Flow)

1. **Client connects** to `https://registry-mcp-server.azurewebsites.net/sse` (SSE = persistent HTTP connection)
2. **Client sends `initialize`** — MCP handshake
3. **Client sends `list_tools`** — server reads `tools_registry.json`, returns all tool definitions with parameters
4. **Client sends `call_tool`** with a tool name and arguments (e.g. `uom_conversion`, `{itemNumber: "100123", orgCode: "MAS"}`)
5. **`dispatcher.py`** looks up the tool config: finds the `target_url`, `method`, `auth_header`, and the env var name for the API key
6. **`dispatcher.py`** makes a real HTTP call to the backend (APIM, Logic App, Function App) with the correct auth header
7. **Backend returns data**, dispatcher sends it back through MCP to the client
8. **Client (AI model)** uses the data to formulate a response

**SSE explained:** Server-Sent Events keeps one HTTP connection open for the whole session. Normal REST closes after each request. SSE lets the MCP server and client exchange multiple messages (initialize, list_tools, call_tool, results) over one persistent connection.

---

## Local Setup

### Prerequisites

- Python 3.12+
- API keys for the backends (or set dummy values for testing MCP flow only)

### Install and run

```bash
git clone <repo-url>
cd MCP
git checkout development

pip install -r requirements.txt

# Set API keys as environment variables (Windows PowerShell)
$env:APIM_UOM_DEV_KEY = "your-key-here"
$env:APIM_DIMITRI_UAT_KEY = "your-key-here"

# Run the MCP server locally on port 8000
uvicorn app.mcp_server.http_app:app --host 0.0.0.0 --port 8000
```

### Test the MCP connection

```bash
python test_mcp.py
```

Expected output:
```
AVAILABLE TOOLS:
 - uom_conversion : Get the unit-of-measure conversion value for a product item from the UOM service.
 - update_order_request : Update a sales order's reason code, requested date and appointment type via the Dimitri order service.
```

### Run the dashboard locally

```bash
cd dashboard
pip install -r requirements.txt

$env:ANTHROPIC_API_KEY = "your-anthropic-key"

# Dashboard connects to the LIVE Azure MCP server by default
uvicorn app:app --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080` to use the chat interface.

---

## Adding a New Tool

**No code changes required.** Only edit `tools_registry.json`.

### 1. Add the tool entry to `app/mcp_server/tools_registry.json`

```json
{
  "tool_name": "check_inventory",
  "description": "Check inventory levels for a product at a warehouse",
  "project": "Inventory-Dev",
  "method": "GET",
  "target_url": "https://apim-dev-intg.azure-api.net/api/dev/inventory/v1/check",
  "auth_header": "x-api-key",
  "auth_key_env": "APIM_INVENTORY_DEV_KEY",
  "param_location": "query",
  "parameters": {
    "type": "object",
    "properties": {
      "productId":    { "type": "string", "description": "Product ID to check" },
      "warehouseCode":{ "type": "string", "description": "Warehouse code, e.g. WH01" }
    },
    "required": ["productId", "warehouseCode"]
  }
}
```

### 2. Add the API key as an environment variable

Azure Portal → `registry-mcp-server` → Settings → Environment variables → Add:
- Name: `APIM_INVENTORY_DEV_KEY`
- Value: `<the actual API key>`

### 3. Rebuild and restart

```bash
az acr build --registry acrregistrymcp --image registry-mcp-server:latest --file Dockerfile .
az webapp restart --name registry-mcp-server --resource-group rg-dev-IntegrationTeamAI
```

Every connected MCP client automatically sees the new tool — no client-side changes needed.

---

## Migrating a Tool Between Environments (DEV → UAT → PROD)

The system is designed so environment migration = JSON edit only.

### Scenario: `uom_conversion` is in DEV today. UAT is ready. Move it.

**Step 1 — Update `tools_registry.json`:**

```json
// Before (DEV)
"target_url": "https://apim-dev-intg.azure-api.net/api/dev/uom/v1/uomConversion",
"auth_key_env": "APIM_UOM_DEV_KEY",

// After (UAT)
"target_url": "https://apim-uat-intg.azure-api.net/uat/api/uom/v1/uomConversion",
"auth_key_env": "APIM_UOM_UAT_KEY",
```

**Step 2 — Add the UAT API key to App Service:**

Portal → `registry-mcp-server` → Environment variables → Add `APIM_UOM_UAT_KEY`

**Step 3 — Rebuild and restart:**

```bash
az acr build --registry acrregistrymcp --image registry-mcp-server:latest --file Dockerfile .
az webapp restart --name registry-mcp-server --resource-group rg-dev-IntegrationTeamAI
```

Done. No Python code touched.

### Deploying the whole MCP server to a new environment (e.g. full PROD deployment)

| Step | What to do |
|---|---|
| 1. Create resource group | `rg-prod-IntegrationTeamAI` in target region |
| 2. Create ACR or reuse | Push same image or build fresh |
| 3. Create App Service Plan | B2/B3 for production load |
| 4. Create App Service (Linux, Docker) | Point to same ACR image |
| 5. Set environment variables | PROD API keys, `WEBSITES_PORT=8080` |
| 6. Update `tools_registry.json` | Change all `target_url` values to PROD APIM endpoints |
| 7. Rebuild image | `az acr build ...` |
| 8. Restart App Service | `az webapp restart ...` |

The dashboard can optionally stay in DEV/UAT pointing to the PROD MCP server — just update `MCP_URL` in `dashboard/app.py`.

---

## Switching AI Provider (Claude → OpenAI or Azure OpenAI)

**The MCP server (`app/` folder) has zero AI code.** It only does HTTP routing. No changes needed there.

Only `dashboard/app.py` uses an AI model. Here is exactly what changes:

### Current (Anthropic Claude)

```python
import anthropic

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=_cached_tool_schemas,
    messages=messages,
)
# stop_reason is "end_turn" or "tool_use"
# tool blocks: block.type == "tool_use", block.name, block.input, block.id
```

### After (OpenAI GPT-4o)

```python
from openai import OpenAI

client = OpenAI(api_key=OPENAI_API_KEY)
response = client.chat.completions.create(
    model="gpt-4o",
    tools=[{"type": "function", "function": t} for t in _cached_tool_schemas],
    messages=messages,
)
# stop_reason is "stop" or "tool_calls"
# tool blocks: choice.message.tool_calls[i].function.name / .arguments / .id
```

### After (Azure OpenAI)

```python
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint="https://your-resource.openai.azure.com",
    api_version="2024-02-01"
)
# Same API as OpenAI above, just different client init
```

### Summary of code changes for provider swap

| Change | Anthropic | OpenAI / Azure OpenAI |
|---|---|---|
| Import | `import anthropic` | `from openai import OpenAI` |
| Client init | `anthropic.Anthropic(api_key=...)` | `OpenAI(api_key=...)` |
| Model name | `claude-sonnet-4-6` | `gpt-4o` |
| Tool schema format | `{"name": ..., "description": ..., "input_schema": {...}}` | `{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}` |
| Stop reason | `"end_turn"` / `"tool_use"` | `"stop"` / `"tool_calls"` |
| Accessing tool calls | `block.type == "tool_use"` | `choice.message.tool_calls` |
| Tool input | `block.input` (dict) | `json.loads(tool_call.function.arguments)` |
| Env var | `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` |

The MCP server, `tools_registry.json`, dispatcher, and all Azure infrastructure stay identical.

---

## Deployment

The server is deployed as a Docker container via Azure Container Registry. No local Docker installation required — the build happens in the cloud.

### Build and deploy MCP server

```bash
# Build the Docker image in ACR (cloud-side build)
az acr build --registry acrregistrymcp --image registry-mcp-server:latest --file Dockerfile .

# Restart App Service to pull the new image
az webapp restart --name registry-mcp-server --resource-group rg-dev-IntegrationTeamAI
```

### Build and deploy Dashboard

```bash
az acr build --registry acrregistrymcp --image mcp-dashboard:latest --file dashboard/Dockerfile ./dashboard

az webapp restart --name mcp-dashboard-demo --resource-group rg-dev-IntegrationTeamAI
```

### Verify deployment

```bash
# Check MCP server health
curl https://registry-mcp-server.azurewebsites.net/health

# Check App Service logs
az webapp log tail --name registry-mcp-server --resource-group rg-dev-IntegrationTeamAI
```

---

## Live URLs

| URL | Purpose | Who uses it |
|---|---|---|
| `https://registry-mcp-server.azurewebsites.net/sse` | MCP server endpoint | AI systems (Claude Desktop, Copilot Studio, code) |
| `https://registry-mcp-server.azurewebsites.net/health` | Health check | Monitoring, Azure health probe |
| `https://mcp-dashboard-demo.azurewebsites.net/` | Demo chat dashboard | Humans — testing and demonstration |

---

## Connecting Claude Desktop to the Live MCP Server

Add to Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "niagara-mcp": {
      "url": "https://registry-mcp-server.azurewebsites.net/sse",
      "transport": "sse"
    }
  }
}
```

After saving and restarting Claude Desktop, the tools (`uom_conversion`, `update_order_request`) appear automatically in Claude's tool list.

---

## Next Steps

- Add Azure AD authentication on the `/sse` MCP endpoint (currently open)
- Move API keys from App Service env vars to Azure Key Vault
- Set up CI/CD pipeline: Azure DevOps → ACR → App Service on push to `main`
- Register additional tools as new APIM endpoints come online
- Optionally migrate dashboard AI from Claude to Azure OpenAI (see provider swap section above)
- Promote MCP server to UAT/PROD resource groups when backends are promoted

# Niagara MCP Server — APIM Dynamic Discovery

An MCP (Model Context Protocol) server deployed on Azure that dynamically reads all APIs from Azure API Management and exposes them as AI tools to Copilot Studio. No hardcoding. No static files. APIM is the single source of truth.

> **Branch:** Active development on `development`. `main` is protected.

---

## How It Works

```
Copilot Studio (user types plain English)
        |
        |  MCP protocol — Streamable HTTP
        v
registry-mcp-server  (Azure App Service — Docker container)
  ├── http_app_apim.py   → exposes /mcp endpoint, accepts Copilot Studio connections
  ├── server_apim.py     → MCP protocol: handles tools/list and tools/call
  ├── apim_dynamic.py    → reads all APIs live from APIM Management API, filters, routes
  ├── registry.py        → fallback only (returns empty if tools_registry.json missing)
  ├── dispatcher.py      → fallback HTTP dispatcher for registry-based tools
  └── apim_poc/policy.xml → APIM native gateway policy (POC reference, not active)
        |
        |  Real HTTP calls with subscription key
        v
Azure API Management (apim-dev-intg)
  ├── Function Apps  (fn-dev-bark, fn-dev-dimitri-getshipmentfromwms, fn-dev-purchase-orders ...)
  ├── Logic Apps     (dimitri-otmtodimitriupdate, ebs-to-dimitri, service-cloud-integration ...)
  └── REST APIs      (livetracking-getShipments, uomconversiontoerp, otmgenericapi ...)
```

---

## Code Files

| File | What it does |
|---|---|
| `app/mcp_server/apim_dynamic.py` | Core. Authenticates via Managed Identity, calls `management.azure.com`, reads all 56 APIs, filters out EDI/B2B prefixes, converts each operation to MCP tool format, routes tool calls to correct APIM endpoint |
| `app/mcp_server/server_apim.py` | MCP protocol layer. Handles `tools/list` (calls apim_dynamic) and `tools/call` (routes to apim_dynamic or fallback) |
| `app/mcp_server/http_app_apim.py` | Web server. Exposes `/mcp` Streamable HTTP endpoint for Copilot Studio and `/sse` legacy endpoint |
| `app/mcp_server/registry.py` | Fallback only. Loads tools from `tools_registry.json` if it exists. File is deleted — returns empty dict |
| `app/mcp_server/dispatcher.py` | Fallback HTTP dispatcher. Used only if APIM discovery fails |
| `apim_poc/policy.xml` | APIM native gateway approach (Plan A / POC). Documents rate limiting, JWT auth, and CORS policies |

---

## API Discovery Logic (apim_dynamic.py)

1. Authenticates using App Service **Managed Identity** — no passwords, no hardcoded credentials
2. Calls `management.azure.com` → reads all **56 APIs** from `apim-dev-intg`
3. Checks for `mcp-enabled` tag — if any API is tagged, shows only tagged ones. If none tagged, shows all
4. Filters out EDI/B2B system callbacks by prefix: `o2c_`, `p2p_`, `b2b_`, `echo_api`, `fourkites_`, `fap_dev_`, `3pl_ofc_`, `fn_dev_edi_`
5. Converts remaining **53 business tools** to MCP format with name, description, and input schema from APIM metadata
6. Returns to Copilot Studio — happens live on every session, no caching

Any new Logic App or Function App published to APIM automatically appears in Copilot Studio on the next session. Zero code change, zero redeploy.

---

## Security Controls

| Control | Status |
|---|---|
| Managed Identity — no credentials in code | Active |
| All secrets in App Service env vars — never in code or git | Active |
| APIM audit logging via Azure Monitor | Active automatically |
| EDI/B2B filter — AI cannot see system integration endpoints | Active |
| `mcp-enabled` tag — whitelist specific APIs for AI access | Ready — APIM admin adds tags |
| Rate limiting — 100 calls/min per subscription | Ready — one line in policy.xml |
| JWT Azure AD authentication on /mcp endpoint | Ready — one line in policy.xml |

---

## Tech Stack

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11 | Server language |
| MCP SDK | 1.28.1 | MCP protocol |
| Starlette | 0.41.3 | Web framework |
| Uvicorn | 0.32.1 | ASGI server |
| HTTPX | 0.28.1 | Async HTTP calls to APIM |
| Azure Identity SDK | ≥1.15.0 | Managed Identity authentication |
| Docker | — | Containerization |
| Azure App Service | — | Hosting |
| Azure Container Registry | acrregistrymcp | Docker image storage |
| APIM Management API | 2022-08-01 | Dynamic API discovery |

---

## Azure Resources

Resource group: `rg-dev-IntegrationTeamAI` — Subscription: `Niagara Development`

| Resource | Type | Purpose |
|---|---|---|
| `registry-mcp-server` | App Service | MCP server — live at azurewebsites.net |
| `acrregistrymcp` | Container Registry | Docker image storage |
| `apim-dev-intg` | API Management | Source of all 56 APIs |

---

## Environment Variables (App Service)

| Variable | Purpose |
|---|---|
| `AZURE_SUBSCRIPTION_ID` | Azure subscription hosting APIM |
| `APIM_RESOURCE_GROUP` | Resource group of APIM instance |
| `APIM_SERVICE_NAME` | APIM name — currently `apim-dev-intg` |
| `APIM_BASE_URL` | APIM gateway URL |
| `APIM_SUBSCRIPTION_KEY` | Subscription key for All APIs product — sent on every tool call |
| `APIM_MCP_TAG` | Tag filter — default `mcp-enabled` |

---

## Live URLs

| URL | Purpose |
|---|---|
| `https://registry-mcp-server.azurewebsites.net/mcp` | MCP endpoint — Copilot Studio connects here |
| `https://registry-mcp-server.azurewebsites.net/sse` | Legacy SSE endpoint |
| `https://apim-dev-intg.azure-api.net` | APIM gateway |

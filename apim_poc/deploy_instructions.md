# APIM Native MCP Gateway — Deploy Instructions

This deploys APIM itself as the MCP server using `policy.xml`.
No Python server. No App Service. APIM handles the MCP protocol.

## Prerequisites
- Contributor access to `apim-dev-intg` in `rg-dev-integrationTeam`
- Azure CLI logged in: `az login`

## Step 1 — Create Named Values (Secrets) in APIM

```bash
# UOM Dev API key
az rest --method PUT \
  --uri "https://management.azure.com/subscriptions/ea51059b-b5f5-4a86-ae78-6fbf365d1c89/resourceGroups/rg-dev-integrationTeam/providers/Microsoft.ApiManagement/service/apim-dev-intg/namedValues/apim-uom-dev-key?api-version=2022-08-01" \
  --body '{"properties":{"displayName":"apim-uom-dev-key","value":"28f1c7898b6448deac73ab1b08ffd18e","secret":true}}'

# Dimitri UAT API key  
az rest --method PUT \
  --uri "https://management.azure.com/subscriptions/ea51059b-b5f5-4a86-ae78-6fbf365d1c89/resourceGroups/rg-dev-integrationTeam/providers/Microsoft.ApiManagement/service/apim-dev-intg/namedValues/apim-dimitri-uat-key?api-version=2022-08-01" \
  --body '{"properties":{"displayName":"apim-dimitri-uat-key","value":"a175849a08ab494496a3a50b8b1f15bd","secret":true}}'
```

## Step 2 — Create the MCP Gateway API

```bash
az rest --method PUT \
  --uri "https://management.azure.com/subscriptions/ea51059b-b5f5-4a86-ae78-6fbf365d1c89/resourceGroups/rg-dev-integrationTeam/providers/Microsoft.ApiManagement/service/apim-dev-intg/apis/niagara-mcp-gateway?api-version=2022-08-01" \
  --body '{
    "properties": {
      "displayName": "Niagara MCP Gateway",
      "description": "MCP protocol endpoint — exposes APIM APIs as tools for AI agents (Copilot Studio, Claude)",
      "path": "mcp-gateway",
      "protocols": ["https"],
      "subscriptionRequired": true
    }
  }'
```

## Step 3 — Create the POST /mcp Operation

```bash
az rest --method PUT \
  --uri "https://management.azure.com/subscriptions/ea51059b-b5f5-4a86-ae78-6fbf365d1c89/resourceGroups/rg-dev-integrationTeam/providers/Microsoft.ApiManagement/service/apim-dev-intg/apis/niagara-mcp-gateway/operations/post-mcp?api-version=2022-08-01" \
  --body '{
    "properties": {
      "displayName": "MCP Endpoint",
      "method": "POST",
      "urlTemplate": "/mcp",
      "description": "Accepts MCP protocol messages (initialize, tools/list, tools/call)"
    }
  }'
```

## Step 4 — Apply the Policy

```bash
POLICY_XML=$(cat apim_poc/policy.xml | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")

az rest --method PUT \
  --uri "https://management.azure.com/subscriptions/ea51059b-b5f5-4a86-ae78-6fbf365d1c89/resourceGroups/rg-dev-integrationTeam/providers/Microsoft.ApiManagement/service/apim-dev-intg/apis/niagara-mcp-gateway/operations/post-mcp/policies/policy?api-version=2022-08-01" \
  --body "{\"properties\":{\"format\":\"xml\",\"value\":$POLICY_XML}}"
```

## Step 5 — Create a Subscription Key for the MCP Gateway

In Azure Portal → APIM → Subscriptions → + Add:
- Name: `niagara-mcp-gateway-key`
- Scope: API → Niagara MCP Gateway

Or CLI:
```bash
az rest --method PUT \
  --uri "https://management.azure.com/subscriptions/ea51059b-b5f5-4a86-ae78-6fbf365d1c89/resourceGroups/rg-dev-integrationTeam/providers/Microsoft.ApiManagement/service/apim-dev-intg/subscriptions/niagara-mcp-gateway?api-version=2022-08-01" \
  --body '{"properties":{"displayName":"niagara-mcp-gateway","scope":"/apis/niagara-mcp-gateway","state":"active"}}'
```

## Step 6 — Test the Endpoint

```bash
# Initialize
curl -X POST https://apim-dev-intg.azure-api.net/mcp-gateway/mcp \
  -H "Content-Type: application/json" \
  -H "Ocp-Apim-Subscription-Key: <YOUR_KEY>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}'

# List tools
curl -X POST https://apim-dev-intg.azure-api.net/mcp-gateway/mcp \
  -H "Content-Type: application/json" \
  -H "Ocp-Apim-Subscription-Key: <YOUR_KEY>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Call uom_conversion
curl -X POST https://apim-dev-intg.azure-api.net/mcp-gateway/mcp \
  -H "Content-Type: application/json" \
  -H "Ocp-Apim-Subscription-Key: <YOUR_KEY>" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"uom_conversion","arguments":{"itemNumber":"AS54888","orgCode":"MAS"}}}'
```

## Connect Copilot Studio to APIM MCP

In Power Automate Custom Connector:
- Scheme: HTTPS
- Host: `apim-dev-intg.azure-api.net`
- Base URL: `/mcp-gateway/mcp`
- Add header: `Ocp-Apim-Subscription-Key: <key>`

## Governance Features (Already Active — No Extra Code)

| Feature | How |
|---|---|
| Rate limiting | Add `rate-limit-by-key` policy to `policy.xml` |
| Azure AD auth | Uncomment `validate-jwt` block in `policy.xml` |
| API key auth | Subscription key required on `/mcp-gateway` |
| Request logging | Azure Monitor / App Insights — automatic |
| Per-consumer quotas | APIM Products + Subscription tiers |
| New tool = zero redeploy | Add another `<when>` in `tools/list` and `tools/call` |

# =============================================================
# MCP Azure System — Setup Script
# Run this ONCE to create all Azure resources and fill your .env
# Usage: .\setup.ps1
# Requires: Azure CLI installed  (winget install Microsoft.AzureCLI)
# =============================================================

param(
    [string]$ResourceGroup  = "mcp-rg",
    [string]$Location       = "eastus",
    [string]$AppName        = "mcp-azure-server",
    [string]$KeyVaultName   = "mcp-kv-$(-join ((65..90) | Get-Random -Count 6 | ForEach-Object {[char]$_}))",
    [string]$StorageName    = "mcpblob$(-join ((97..122) | Get-Random -Count 6 | ForEach-Object {[char]$_}))",
    [string]$SqlServerName  = "mcp-sql-$(-join ((97..122) | Get-Random -Count 6 | ForEach-Object {[char]$_}))",
    [string]$AOAIName       = "mcp-aoai-$(-join ((97..122) | Get-Random -Count 6 | ForEach-Object {[char]$_}))"
)

function Write-Step { param([string]$msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK   { param([string]$msg) Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "    WARN: $msg" -ForegroundColor Yellow }

# ── Check Azure CLI ──────────────────────────────────────────────────────────
Write-Step "Checking Azure CLI..."
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "Azure CLI not found. Install it:" -ForegroundColor Red
    Write-Host "  winget install Microsoft.AzureCLI" -ForegroundColor Yellow
    exit 1
}
Write-OK "Azure CLI found."

# ── Login ────────────────────────────────────────────────────────────────────
Write-Step "Logging in to Azure..."
az account show > $null 2>&1
if ($LASTEXITCODE -ne 0) { az login }
$SUBSCRIPTION = (az account show --query id -o tsv)
$TENANT_ID    = (az account show --query tenantId -o tsv)
Write-OK "Subscription: $SUBSCRIPTION  Tenant: $TENANT_ID"

# ── Resource Group ───────────────────────────────────────────────────────────
Write-Step "Creating resource group '$ResourceGroup'..."
az group create --name $ResourceGroup --location $Location --output none
Write-OK "Resource group ready."

# ── App Registration (Azure AD) ───────────────────────────────────────────────
Write-Step "Creating Azure AD App Registration..."
$APP_JSON = az ad app create --display-name $AppName --output json | ConvertFrom-Json
$CLIENT_ID = $APP_JSON.appId
az ad sp create --id $CLIENT_ID --output none
$SECRET_JSON = az ad app credential reset --id $CLIENT_ID --output json | ConvertFrom-Json
$CLIENT_SECRET = $SECRET_JSON.password
az ad app update --id $CLIENT_ID --identifier-uris "api://$CLIENT_ID" --output none
Write-OK "App Registration created. Client ID: $CLIENT_ID"

# Set App Roles
$roles = @"
[
  {"displayName":"Admin","id":"00000000-0000-0000-0000-000000000001","isEnabled":true,"description":"Full admin access","value":"Admin"},
  {"displayName":"Manager","id":"00000000-0000-0000-0000-000000000002","isEnabled":true,"description":"Manager access","value":"Manager"},
  {"displayName":"Engineer","id":"00000000-0000-0000-0000-000000000003","isEnabled":true,"description":"Engineer access","value":"Engineer"},
  {"displayName":"Technician","id":"00000000-0000-0000-0000-000000000004","isEnabled":true,"description":"Technician access","value":"Technician"}
]
"@
$roles | Out-File -FilePath "approles.json" -Encoding utf8
az ad app update --id $CLIENT_ID --app-roles @approles.json --output none
Remove-Item "approles.json"
Write-OK "App roles created: Admin, Manager, Engineer, Technician"

# ── Key Vault ─────────────────────────────────────────────────────────────────
Write-Step "Creating Key Vault '$KeyVaultName'..."
az keyvault create --name $KeyVaultName --resource-group $ResourceGroup --location $Location --output none
$KV_URL = (az keyvault show --name $KeyVaultName --query properties.vaultUri -o tsv)
az keyvault set-policy --name $KeyVaultName --spn $CLIENT_ID --secret-permissions get list --output none
Write-OK "Key Vault: $KV_URL"

# Store client secret in KV
az keyvault secret set --vault-name $KeyVaultName --name "azure-client-secret" --value $CLIENT_SECRET --output none
Write-OK "azure-client-secret stored in Key Vault."

# ── Azure OpenAI ──────────────────────────────────────────────────────────────
Write-Step "Creating Azure OpenAI resource '$AOAIName'..."
$aoai_result = az cognitiveservices account create `
    --name $AOAIName --resource-group $ResourceGroup `
    --kind OpenAI --sku S0 --location $Location --yes --output json 2>&1
if ($LASTEXITCODE -eq 0) {
    $AOAI_ENDPOINT = (az cognitiveservices account show --name $AOAIName --resource-group $ResourceGroup --query properties.endpoint -o tsv)
    $AOAI_KEY = (az cognitiveservices account keys list --name $AOAIName --resource-group $ResourceGroup --query key1 -o tsv)
    az keyvault secret set --vault-name $KeyVaultName --name "openai-api-key" --value $AOAI_KEY --output none
    Write-OK "Azure OpenAI endpoint: $AOAI_ENDPOINT"
    Write-Warn "You still need to deploy the gpt-4o model manually in Azure OpenAI Studio."
    Write-Warn "Go to: https://oai.azure.com/ > Deployments > Create > gpt-4o"
} else {
    Write-Warn "Azure OpenAI creation skipped or failed. Add OPENAI_API_KEY manually."
    $AOAI_ENDPOINT = "https://your-aoai.openai.azure.com/"
    $AOAI_KEY = ""
}

# ── Azure SQL Database ────────────────────────────────────────────────────────
Write-Step "Creating Azure SQL Server '$SqlServerName'..."
$SQL_ADMIN_PASS = "McpAdmin@$(Get-Random -Maximum 9999)!"
az sql server create `
    --name $SqlServerName --resource-group $ResourceGroup `
    --location $Location --admin-user sqladmin `
    --admin-password $SQL_ADMIN_PASS --output none
az sql server firewall-rule create `
    --server $SqlServerName --resource-group $ResourceGroup `
    --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 --output none
az sql db create `
    --server $SqlServerName --resource-group $ResourceGroup `
    --name pm-history --service-objective S1 --output none
$SQL_HOST = "$SqlServerName.database.windows.net"
az keyvault secret set --vault-name $KeyVaultName --name "sql-password" --value $SQL_ADMIN_PASS --output none
Write-OK "SQL Server: $SQL_HOST"

# ── Azure Blob Storage ────────────────────────────────────────────────────────
Write-Step "Creating Storage Account '$StorageName'..."
az storage account create `
    --name $StorageName --resource-group $ResourceGroup `
    --sku Standard_LRS --allow-blob-public-access false --output none
az storage container create `
    --account-name $StorageName --name pm-documents --public-access off --output none
$BLOB_URL = "https://$StorageName.blob.core.windows.net"
Write-OK "Blob Storage: $BLOB_URL"

# ── App Insights ──────────────────────────────────────────────────────────────
Write-Step "Creating Application Insights..."
$ai_result = az monitor app-insights component create `
    --app mcp-insights --resource-group $ResourceGroup `
    --location $Location --output json 2>&1
if ($LASTEXITCODE -eq 0) {
    $AI_CONN = ($ai_result | ConvertFrom-Json).connectionString
    Write-OK "App Insights configured."
} else {
    Write-Warn "App Insights creation failed. Add manually."
    $AI_CONN = ""
}

# ── Write .env ────────────────────────────────────────────────────────────────
Write-Step "Writing .env file with real Azure credentials..."
$envContent = @"
# Generated by setup.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm')
# All secrets also stored in Key Vault: $KV_URL

APP_ENV=development
LOG_LEVEL=DEBUG
MAX_RETRIES=3
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
DEV_BYPASS_AUTH=false

AZURE_TENANT_ID=$TENANT_ID
AZURE_CLIENT_ID=$CLIENT_ID
AZURE_CLIENT_SECRET=$CLIENT_SECRET
JWT_AUDIENCE=api://$CLIENT_ID

KEY_VAULT_URL=$KV_URL

BLOB_ACCOUNT_URL=$BLOB_URL
BLOB_CONTAINER_NAME=pm-documents

SQL_SERVER=$SQL_HOST
SQL_DATABASE=pm-history
SQL_USERNAME=sqladmin
SQL_PASSWORD=$SQL_ADMIN_PASS

FTP_HOST=sftp
FTP_PORT=22
FTP_USERNAME=pm-app
FTP_PASSWORD=dev-password

OPENAI_API_KEY=$AOAI_KEY
OPENAI_API_BASE=$AOAI_ENDPOINT
OPENAI_DEPLOYMENT=gpt-4o
GEMINI_API_KEY=
LLAMA_BASE_URL=http://host.docker.internal:11434/v1

APPLICATIONINSIGHTS_CONNECTION_STRING=$AI_CONN
"@

$envContent | Out-File -FilePath ".env" -Encoding utf8
Write-OK ".env written."

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host "`n" + ("=" * 60) -ForegroundColor Cyan
Write-Host "  SETUP COMPLETE" -ForegroundColor Green
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host ""
Write-Host "  Tenant ID:        $TENANT_ID"
Write-Host "  Client ID:        $CLIENT_ID"
Write-Host "  Key Vault:        $KV_URL"
Write-Host "  SQL Server:       $SQL_HOST"
Write-Host "  Blob Storage:     $BLOB_URL"
Write-Host ""
Write-Host "  NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. Add GEMINI_API_KEY to .env (get from https://aistudio.google.com/app/apikey)"
Write-Host "  2. Deploy gpt-4o in Azure OpenAI Studio: https://oai.azure.com/"
Write-Host "  3. Run the DB schema: apply sql/schema.sql to your Azure SQL database"
Write-Host "  4. Assign Azure AD roles to your users in Enterprise Applications"
Write-Host "  5. docker compose up --build"
Write-Host ""

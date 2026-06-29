# MCP Azure System - Production FastAPI Server

A production-ready Model Context Protocol (MCP) server on Azure.

---

## Required API Keys and Secrets

### 1. Azure AD (REQUIRED)

| Variable | How to Get |
|----------|-----------|
| AZURE_TENANT_ID | Azure Portal > Azure Active Directory > Overview > Tenant ID |
| AZURE_CLIENT_ID | Azure Portal > App Registrations > your app > Application (client) ID |
| AZURE_CLIENT_SECRET | App Registration > Certificates & secrets > New client secret |
| JWT_AUDIENCE | Set to: api://<AZURE_CLIENT_ID> |

Create the App Registration:

    az ad app create --display-name mcp-azure-server
    az ad sp create --id <APP_ID>
    az ad app credential reset --id <APP_ID>

Then expose the API:
Azure Portal > App Registrations > your app > Expose an API > Set Application ID URI = api://<APP_ID>

---

### 2. Azure Key Vault (REQUIRED in production)

| Variable | How to Get |
|----------|-----------|
| KEY_VAULT_URL | Azure Portal > Key Vaults > your vault > Vault URI (e.g. https://mcp-kv.vault.azure.net/) |

    az keyvault create --name mcp-kv --resource-group mcp-rg --location eastus
    az keyvault set-policy --name mcp-kv --spn <AZURE_CLIENT_ID> --secret-permissions get list

Store these secrets in Key Vault (production only):

    az keyvault secret set --vault-name mcp-kv --name openai-api-key   --value "sk-..."
    az keyvault secret set --vault-name mcp-kv --name gemini-api-key   --value "AIza..."
    az keyvault secret set --vault-name mcp-kv --name sql-password     --value "YourDBPass!"
    az keyvault secret set --vault-name mcp-kv --name azure-client-secret --value "..."

---

### 3. Azure OpenAI / GPT-4o (PRIMARY AI MODEL)

| Variable | How to Get |
|----------|-----------|
| OPENAI_API_KEY | Azure Portal > Azure OpenAI > your resource > Keys and Endpoint > Key 1 |
| OPENAI_API_BASE | Same page > Endpoint (e.g. https://yourname.openai.azure.com/) |
| OPENAI_DEPLOYMENT | Azure OpenAI Studio > Deployments > your deployment name |

Deploy the model:

    az cognitiveservices account deployment create ^
      --resource-group mcp-rg --name your-aoai-resource ^
      --deployment-name gpt-4o --model-name gpt-4o ^
      --model-version "2024-02-01" --sku-capacity 10 --sku-name Standard

---

### 4. Google Gemini 1.5 Pro (FALLBACK AI MODEL)

| Variable | How to Get |
|----------|-----------|
| GEMINI_API_KEY | Go to https://aistudio.google.com/app/apikey and click Create API key |

Note: Gemini is only used when GPT-4o fails. Per architecture, no user PII is sent externally.

---

### 5. Llama 3.1 70B (SELF-HOSTED - internal network only)

| Variable | Value |
|----------|-------|
| LLAMA_BASE_URL | http://<internal-vm-ip>:8080/v1  (never a public URL) |

Local dev mock (no GPU needed):

    docker run -d -p 8080:8080 ollama/ollama
    docker exec <container_id> ollama pull llama3.1

---

### 6. Azure Blob Storage

| Variable | How to Get |
|----------|-----------|
| BLOB_ACCOUNT_URL | Azure Portal > Storage Accounts > your account > Primary endpoint (Blob service) |
| BLOB_CONTAINER_NAME | pm-documents |

    az storage account create --name mcpstorage --resource-group mcp-rg --sku Standard_LRS --allow-blob-public-access false
    az storage container create --account-name mcpstorage --name pm-documents --public-access off

---

### 7. Azure SQL Database

| Variable | How to Get |
|----------|-----------|
| SQL_SERVER | Azure Portal > SQL Servers > your server > Server name (e.g. mcp-sql.database.windows.net) |
| SQL_DATABASE | pm-history |
| SQL_USERNAME | pm-app-user |
| SQL_PASSWORD | Store in Key Vault as sql-password |

    az sql server create --name mcp-sql --resource-group mcp-rg --location eastus --admin-user sqladmin --admin-password "Admin@Pass123!"
    az sql db create --server mcp-sql --resource-group mcp-rg --name pm-history --service-objective S1
    az sql server firewall-rule create --server mcp-sql --resource-group mcp-rg --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0

Then run sql/schema.sql to create tables.

---

### 8. Azure Application Insights

| Variable | How to Get |
|----------|-----------|
| APPLICATIONINSIGHTS_CONNECTION_STRING | Azure Portal > Application Insights > Overview > Connection String |

    az monitor app-insights component create --app mcp-insights --resource-group mcp-rg --location eastus

---

### 9. SFTP Server (internal only, no public access)

| Variable | Value |
|----------|-------|
| FTP_HOST | Internal VNet hostname or IP |
| FTP_PORT | 22 |
| FTP_USERNAME | pm-app |
| FTP_PASSWORD | Store in Key Vault as ftp-password |

---

## Running Locally with Docker Compose (Recommended)

Requires: Docker Desktop

Step 1 - Configure .env

    copy .env.example .env
    # Edit .env and fill in at minimum:
    #   AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, JWT_AUDIENCE
    #   OPENAI_API_KEY, OPENAI_API_BASE, OPENAI_DEPLOYMENT
    #   GEMINI_API_KEY

Step 2 - Start all services

    docker compose up --build

This starts:
  - API server at http://localhost:8000
  - SQL Server at localhost:1433
  - Azure Blob emulator (Azurite) at localhost:10000
  - SFTP server at localhost:2222

Step 3 - Initialize database

    docker compose exec sqlserver /opt/mssql-tools/bin/sqlcmd -S localhost -U sa -P "Dev@Password123!" -Q "CREATE DATABASE [pm-history]"
    docker compose exec sqlserver /opt/mssql-tools/bin/sqlcmd -S localhost -U sa -P "Dev@Password123!" -d pm-history -i /docker-entrypoint-initdb.d/schema.sql

Step 4 - Open Swagger UI

    http://localhost:8000/docs

Click Authorize, paste your Azure AD JWT token, then test any endpoint.

---

## Running Without Docker (Pure Python)

Requires: Python 3.12+, ODBC Driver 18 for SQL Server

Windows install for ODBC Driver 18:
https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    copy .env.example .env
    # fill in .env values
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Run tests:

    pytest tests/ -v

---

## Deploying to Azure (Production)

Step 1 - Create infrastructure

    az group create --name mcp-rg --location eastus
    az appservice plan create --name mcp-plan --resource-group mcp-rg --sku B1 --is-linux
    az webapp create --name mcp-azure-server --resource-group mcp-rg --plan mcp-plan
    az webapp identity assign --name mcp-azure-server --resource-group mcp-rg
    # Copy principalId from output then:
    az keyvault set-policy --name mcp-kv --object-id <principalId> --secret-permissions get list

Step 2 - Set GitHub Actions secrets

Go to: GitHub repo > Settings > Secrets > Actions

| Secret | Value |
|--------|-------|
| AZURE_CREDENTIALS | Output of: az ad sp create-for-rbac --sdk-auth --role contributor |
| ACR_LOGIN_SERVER | yourregistry.azurecr.io |
| ACR_USERNAME | Your ACR username |
| ACR_PASSWORD | Your ACR password |
| KEY_VAULT_URL | https://mcp-kv.vault.azure.net/ |
| AZURE_TENANT_ID | Your tenant ID |
| AZURE_CLIENT_ID | Your client ID |
| JWT_AUDIENCE | api://your-client-id |
| APPINSIGHTS_CONN | App Insights connection string |

Step 3 - Push to main to trigger CI/CD

    git init
    git add .
    git commit -m "initial production deployment"
    git remote add origin https://github.com/your-org/mcp-azure.git
    git push origin main

CI/CD pipeline: Bandit security scan > pytest > Docker build > az webapp deploy > health check

---

## API Endpoints

| Method | Path | Auth Required | Min Role |
|--------|------|:---:|---------|
| GET | / | No | - |
| GET | /health | No | - |
| GET | /me | JWT | Any |
| GET | /docs | No (dev only) | - |
| GET | /mcp/v1/tools | JWT | Any |
| POST | /mcp/v1/tools/call | JWT | Per-tool (see below) |
| POST | /mcp/v1/chat | JWT | Any (enforced per tool) |

Call a tool directly:

    curl -X POST http://localhost:8000/mcp/v1/tools/call ^
      -H "Authorization: Bearer <TOKEN>" ^
      -H "Content-Type: application/json" ^
      -d "{\"tool_name\":\"check_pm_status\",\"parameters\":{\"machine_id\":\"M001\"},\"request_id\":\"r1\"}"

Agentic chat (AI picks the right tool automatically):

    curl -X POST http://localhost:8000/mcp/v1/chat ^
      -H "Authorization: Bearer <TOKEN>" ^
      -H "Content-Type: application/json" ^
      -d "{\"message\":\"What is the PM status of machine M001?\",\"preferred_model\":\"auto\"}"

Get a test token:

    az account get-access-token --resource api://<AZURE_CLIENT_ID> --query accessToken -o tsv

---

## Role-Based Access Per Tool

| Role | check_pm_status | get_machine_list | save_pm_record | generate_document | query_database |
|------|:-:|:-:|:-:|:-:|:-:|
| Technician | YES | YES | YES | NO | NO |
| Engineer | YES | YES | YES | YES | YES |
| Manager | YES | YES | YES | YES | YES |
| Admin | YES | YES | YES | YES | YES |

Assign roles:
Azure Portal > App Registrations > your app > App roles > Create role
Then: Enterprise Applications > your app > Users and groups > Assign role to user

---

## Troubleshooting

| Error | Solution |
|-------|---------|
| 401 Invalid token | Verify JWT_AUDIENCE equals api://<CLIENT_ID> exactly, including the api:// prefix |
| 403 Forbidden | User does not have the required App Role assigned in Azure AD |
| KeyVault unavailable | Run az login locally; in prod verify Managed Identity is assigned to Key Vault |
| pyodbc.OperationalError | Install ODBC Driver 18 for SQL Server; check SQL Server firewall allows your IP |
| Docker SQL startup fails | SQL Server takes ~30s; wait then re-run the schema init commands |
| GPT-4o returns 404 | OPENAI_DEPLOYMENT must match exactly the deployment name in Azure OpenAI Studio |
| Gemini 429 rate limit | Expected in dev; model router auto-falls back to Llama |
| HTTPS redirect loop | Set APP_ENV=development locally; HTTPS redirect only activates in production |

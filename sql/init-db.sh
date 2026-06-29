#!/bin/bash
set -e
echo "==> Waiting for SQL Server..."
until /opt/mssql-tools18/bin/sqlcmd -S sqlserver -U sa -P "Dev@Password123!" -C -Q "SELECT 1" > /dev/null 2>&1; do
    echo "   SQL not ready, retrying in 3s..."
    sleep 3
done
echo "==> Creating database pm-history..."
/opt/mssql-tools18/bin/sqlcmd -S sqlserver -U sa -P "Dev@Password123!" -C \
    -Q "IF NOT EXISTS (SELECT name FROM sys.databases WHERE name=N'pm-history') CREATE DATABASE [pm-history]"
echo "==> Applying schema..."
/opt/mssql-tools18/bin/sqlcmd -S sqlserver -U sa -P "Dev@Password123!" -C \
    -d pm-history -i /schema.sql
echo "==> Database ready."

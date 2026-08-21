<#
.SYNOPSIS
    Resync the local test PostgreSQL DB (port 9876) from the prod DB schema (port 5432).

.DESCRIPTION
    Dumps the public schema from prod (schema-only, no data), wipes the test DB's
    public schema, and restores. Verifies zero drift at the end.

    Idempotent. Safe to re-run any time prod schema changes.

.PARAMETER ProdHost
    Prod DB host. Default: 127.0.0.1

.PARAMETER ProdPort
    Prod DB port. Default: 5432

.PARAMETER TestHost
    Test DB host. Default: 127.0.0.1

.PARAMETER TestPort
    Test DB port. Default: 9876

.PARAMETER Database
    Database name on both. Default: postgres

.PARAMETER User
    Postgres user on both. Default: postgres

.PARAMETER Password
    Postgres password on both. Default: postgres

.PARAMETER PgBin
    Folder containing pg_dump.exe / psql.exe.
    Default: "C:\Program Files\PostgreSQL\18\bin"

.PARAMETER DumpFile
    Where to write the schema dump.
    Default: <repo>\genai_tools\prod_schema.sql

.EXAMPLE
    .\genai_tools\sync_test_db.ps1
#>

[CmdletBinding()]
param(
    [string]$ProdHost = "127.0.0.1",
    [int]   $ProdPort = 5432,
    [string]$TestHost = "127.0.0.1",
    [int]   $TestPort = 9876,
    [string]$Database = "postgres",
    [string]$User     = "postgres",
    [string]$Password = "postgres",
    [string]$PgBin    = "C:\Program Files\PostgreSQL\18\bin",
    [string]$DumpFile = (Join-Path $PSScriptRoot "prod_schema.sql")
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# -------- Safety: never sync TO prod --------
if ($TestPort -eq 5432 -and ($TestHost -eq "127.0.0.1" -or $TestHost -eq "localhost")) {
    throw "REFUSED: TestPort=5432 and TestHost=$TestHost. That is prod. Will not wipe."
}

# -------- Locate tools --------
$pgDump = Join-Path $PgBin "pg_dump.exe"
$psql   = Join-Path $PgBin "psql.exe"
foreach ($exe in @($pgDump, $psql)) {
    if (-not (Test-Path $exe)) { throw "Not found: $exe (set -PgBin)" }
}

$env:PGPASSWORD = $Password

# -------- 1. Dump prod schema --------
Write-Step "Dumping prod schema from ${ProdHost}:${ProdPort} -> $DumpFile"
& $pgDump -h $ProdHost -p $ProdPort -U $User `
    --schema-only --no-owner --no-acl --schema=public `
    -f $DumpFile $Database
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
Write-Host "    dump size: $((Get-Item $DumpFile).Length) bytes"

# Strip the lone "CREATE SCHEMA public;" line (we re-create it ourselves below)
(Get-Content $DumpFile) `
    | Where-Object { $_ -notmatch '^\s*CREATE SCHEMA public;\s*$' } `
    | Set-Content $DumpFile

# -------- 2. Wipe test DB public schema --------
Write-Step "Wiping public schema on test DB ${TestHost}:${TestPort}"
& $psql -h $TestHost -p $TestPort -U $User -d $Database -v ON_ERROR_STOP=1 `
    -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO $User; GRANT ALL ON SCHEMA public TO public;"
if ($LASTEXITCODE -ne 0) { throw "psql wipe failed with exit code $LASTEXITCODE" }

# -------- 3. Restore --------
Write-Step "Restoring schema into ${TestHost}:${TestPort}"
& $psql -h $TestHost -p $TestPort -U $User -d $Database -v ON_ERROR_STOP=1 -q -f $DumpFile
if ($LASTEXITCODE -ne 0) { throw "psql restore failed with exit code $LASTEXITCODE" }

# -------- 4. Verify zero drift --------
Write-Step "Verifying schema parity"
$verify = @"
SELECT table_name || '.' || column_name || ':' || data_type || ':' || is_nullable || ':' || COALESCE(column_default, '')
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
"@
$prodCols = & $psql -h $ProdHost -p $ProdPort -U $User -d $Database -t -A -c $verify
$testCols = & $psql -h $TestHost -p $TestPort -U $User -d $Database -t -A -c $verify
$diff = Compare-Object $prodCols $testCols
if ($diff) {
    Write-Host "DRIFT DETECTED:" -ForegroundColor Red
    $diff | ForEach-Object { Write-Host "  $($_.SideIndicator) $($_.InputObject)" }
    throw "Schema drift remains after restore."
}

Write-Host ""
Write-Host "Test DB ${TestHost}:${TestPort} now matches prod schema (${ProdHost}:${ProdPort})." -ForegroundColor Green

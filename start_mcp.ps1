# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
param(
    [string]$Python = (Join-Path $PSScriptRoot '.build\mcp-python\Scripts\python.exe'),
    [string]$HubUrl = 'http://127.0.0.1:8000',
    [int]$Port = 3001,
    [string]$CredentialFile = (Join-Path $PSScriptRoot ".build\mcp-auth\token.dpapi"),
    [string]$PolicyFile = (Join-Path $PSScriptRoot ".build\mcp-auth\policy.json"),
    [string]$AuditFile = (Join-Path $PSScriptRoot ".build\mcp-auth\security-audit.jsonl")
)
$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $Python)) {
    throw 'MCP Python runtime missing. Create the approved project environment first, or pass -Python.'
}
& $Python -B (Join-Path $PSScriptRoot 'hub\mcp_auth.py') check --credential-file $CredentialFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -B (Join-Path $PSScriptRoot 'hub\mcp_readonly.py') --hub-url $HubUrl --port $Port --credential-file $CredentialFile --policy-file $PolicyFile --audit-file $AuditFile
exit $LASTEXITCODE

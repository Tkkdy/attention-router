# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('status','off','read-only','arm-write')]
    [string]$Action,
    [string]$Minutes = '120',
    [string]$Python = (Join-Path $PSScriptRoot '.build\mcp-python\Scripts\python.exe'),
    [string]$PolicyFile = (Join-Path $PSScriptRoot '.build\mcp-auth\policy.json')
)
$ErrorActionPreference = 'Stop'
if ($Action -eq 'arm-write' -and ($Minutes -notmatch '^[0-9]+$' -or $Minutes.Length -gt 4 -or [int]$Minutes -lt 1 -or [int]$Minutes -gt 1440)) {
    throw 'Minutes must be an integer from 1 through 1440.'
}
& $Python -B (Join-Path $PSScriptRoot 'hub\mcp_policy.py') $Action --policy-file $PolicyFile --minutes $Minutes
exit $LASTEXITCODE

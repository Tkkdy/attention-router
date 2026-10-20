# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
param(
    [string]$ArduinoCli = 'arduino-cli',
    [string]$LibraryDirectory,
    [string]$ConfigFile
)
$ErrorActionPreference = 'Stop'
$arguments = @()
if ($ConfigFile) { $arguments += @('--config-file', $ConfigFile) }
$arguments += @('compile', '--fqbn', 'esp32:esp32:esp32', '--build-path', (Join-Path $PSScriptRoot '.build\firmware'))
if ($LibraryDirectory) { $arguments += @('--libraries', $LibraryDirectory) }
$arguments += (Join-Path $PSScriptRoot 'firmware\esp32_dashboard')
& $ArduinoCli @arguments
exit $LASTEXITCODE

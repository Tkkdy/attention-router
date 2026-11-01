# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-FileCopyrightText: 2026 flowersea123
# SPDX-License-Identifier: MIT
param(
    [string]$ArduinoCli = 'arduino-cli',
    [string]$LibraryDirectory,
    [string]$ConfigFile,
    [ValidateSet('esp32-gdey042z98', 'esp32s3-gdem042f52')]
    [string]$HardwareProfile = 'esp32-gdey042z98'
)
$ErrorActionPreference = 'Stop'
$arguments = @()
if ($ConfigFile) { $arguments += @('--config-file', $ConfigFile) }
$fqbn = 'esp32:esp32:esp32'
$panel = '1'
if ($HardwareProfile -eq 'esp32s3-gdem042f52') {
    $fqbn = 'esp32:esp32:esp32s3'
    $panel = '2'
}
$arguments += @('compile', '--fqbn', $fqbn, '--build-path', (Join-Path $PSScriptRoot '.build\firmware'),
    '--build-property', "compiler.cpp.extra_flags=-DDASHBOARD_PANEL=$panel")
if ($LibraryDirectory) { $arguments += @('--libraries', $LibraryDirectory) }
$arguments += (Join-Path $PSScriptRoot 'firmware\esp32_dashboard')
& $ArduinoCli @arguments
exit $LASTEXITCODE

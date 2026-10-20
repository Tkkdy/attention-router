# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
param(
    [string]$Python = (Join-Path $PSScriptRoot '.build\mcp-python\Scripts\python.exe'),
    [string]$CredentialFile = (Join-Path $PSScriptRoot '.build\mcp-auth\token.dpapi'),
    [switch]$Rotate,
    [switch]$ShowForManualEntry
)
$ErrorActionPreference = 'Stop'
$operation = if ($Rotate) { 'rotate' } else { 'init' }
& $Python -B (Join-Path $PSScriptRoot 'hub\mcp_auth.py') $operation --credential-file $CredentialFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (!$ShowForManualEntry) { exit 0 }
# Only the human invokes this local window; never write the value to a stream.
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.Windows.Forms
try {
    $encrypted = [IO.File]::ReadAllBytes($CredentialFile)
    $plainBytes = [Security.Cryptography.ProtectedData]::Unprotect($encrypted, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    $form = New-Object Windows.Forms.Form
    $form.Text = 'MCP credential - local manual entry only'
    $form.Width = 690
    $form.Height = 200
    $form.StartPosition = 'CenterScreen'
    $label = New-Object Windows.Forms.Label
    $label.Text = 'Copy only into the connector secure credential field. Never paste into chat.'
    $label.SetBounds(15, 15, 640, 35)
    $field = New-Object Windows.Forms.TextBox
    $field.SetBounds(15, 55, 640, 30)
    $field.ReadOnly = $true
    $field.UseSystemPasswordChar = $true
    $field.Text = 'Bearer ' + [Text.Encoding]::ASCII.GetString($plainBytes)
    [Array]::Clear($plainBytes, 0, $plainBytes.Length)
    $toggle = New-Object Windows.Forms.CheckBox
    $toggle.Text = 'Reveal locally for manual entry'
    $toggle.SetBounds(15, 100, 350, 25)
    $toggle.Add_CheckedChanged({ $field.UseSystemPasswordChar = !$toggle.Checked })
    $form.Controls.AddRange(@($label, $field, $toggle))
    [void]$form.ShowDialog()
} catch {
    throw 'Cannot display local credential for this Windows user.'
} finally {
    if ($plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
    if ($field) { $field.Text = ''; $field.Dispose() }
    if ($form) { $form.Dispose() }
}

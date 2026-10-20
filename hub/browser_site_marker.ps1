# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
param([long]$WindowHandle)
$ErrorActionPreference = 'Stop'
try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$WindowHandle)
    # Address-bar controls only. Never read documents, history or conversation nodes.
    $conditions = [System.Windows.Automation.Condition[]]@(
        (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'addressEditBox')),
        (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '地址和搜索栏')),
        (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, 'Address and search bar'))
    )
    $names = New-Object System.Windows.Automation.OrCondition -ArgumentList (,$conditions)
    $edit = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit)
    $match = New-Object System.Windows.Automation.AndCondition($names, $edit)
    $bar = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $match)
    if ($null -eq $bar) { exit }
    $value = ([System.Windows.Automation.ValuePattern]$bar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)).Current.Value
    if ($value -notmatch '^https?://') { $value = 'https://' + $value }
    $uri = [Uri]$value
    # Output only the allowlisted site marker; paths, queries and other domains never leave this process.
    if ($uri.Scheme -eq 'https' -and $uri.Host -in @('chatgpt.com','chat.openai.com') -and -not $uri.UserInfo) {
        [Console]::Write('chatgpt_web')
    }
} catch { exit }

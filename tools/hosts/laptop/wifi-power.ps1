<#
.SYNOPSIS
    Turns off the laptop wifi adapter's power saving, idempotently (issue #382, row 1b).

.DESCRIPTION
    The laptop's TP-Link Wireless Nano USB Adapter ("Wi-Fi 2") dropped the WPA key exchange 160 times on
    2026-10-01 (event 11006). Three settings, each written only when it differs, each under ShouldProcess
    so `-WhatIf` prints the plan and changes nothing:

      1. AllowComputerToTurnOffDevice Disabled: Set-NetAdapterPowerManagement has no such parameter and
         Disable-NetAdapterPowerManagement left it Enabled (2026-10-02), so root\wmi MSPower_DeviceEnable.Enable = $false
      2. USB selective suspend off on AC and DC of the active plan:
         powercfg /setacvalueindex + /setdcvalueindex SCHEME_CURRENT <USB subgroup> <USB selective suspend> 0,
         then powercfg /setactive SCHEME_CURRENT
      3. The driver's own power-saving advanced property, when it exposes one (Set-NetAdapterAdvancedProperty);
         this driver (Realtek 1030.52.1216.2025) exposes none today, so the step is a no-op there.

    Run by tools\hosts\install.ps1 -Host laptop; also runnable alone: powershell -File wifi-power.ps1 [-WhatIf]
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$AdapterName = 'Wi-Fi 2'
)

$ErrorActionPreference = 'Stop'
# powercfg aliases are SUB_USB / USBSELECTIVESUSPEND; the GUIDs are what the registry holds.
$usbSubgroup = '2a737441-1930-4402-8d77-b2bebba308a3'
$usbSelectiveSuspend = '48e6b7a6-50f5-4782-a5d4-53bb8f07e226'

# 1. adapter power management
$pm = Get-NetAdapterPowerManagement -Name $AdapterName
if ($pm.AllowComputerToTurnOffDevice -ne 'Disabled') {
    if ($PSCmdlet.ShouldProcess($AdapterName, 'MSPower_DeviceEnable.Enable = $false (AllowComputerToTurnOffDevice Disabled)')) {
        $inst = Get-CimInstance -Namespace root\wmi -ClassName MSPower_DeviceEnable |
            Where-Object { $_.InstanceName -like ((Get-NetAdapter -Name $AdapterName).PnPDeviceID + '*') }
        foreach ($i in $inst) { $i.Enable = $false; Set-CimInstance -InputObject $i }
    }
}
if ($pm.SelectiveSuspend -eq 'Enabled') {
    if ($PSCmdlet.ShouldProcess($AdapterName, 'Set-NetAdapterPowerManagement -SelectiveSuspend Disabled')) {
        Set-NetAdapterPowerManagement -Name $AdapterName -SelectiveSuspend Disabled
    }
}

# 2. USB selective suspend, AC and DC of the active plan
$changed = $false
foreach ($kind in @('ac', 'dc')) {
    if ($PSCmdlet.ShouldProcess("SCHEME_CURRENT ($kind)", "powercfg /set${kind}valueindex $usbSubgroup $usbSelectiveSuspend 0")) {
        powercfg "/set${kind}valueindex" SCHEME_CURRENT $usbSubgroup $usbSelectiveSuspend 0
        $changed = $true
    }
}
if ($changed -and $PSCmdlet.ShouldProcess('SCHEME_CURRENT', 'powercfg /setactive SCHEME_CURRENT')) {
    powercfg /setactive SCHEME_CURRENT
}

# 3. the driver's power-saving advanced property, if any (setting it resets the adapter briefly)
$prop = Get-NetAdapterAdvancedProperty -Name $AdapterName -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match 'Power Sav' -or $_.RegistryKeyword -match 'PowerSav|PwrSav' }
foreach ($p in $prop) {
    $off = $p.ValidDisplayValues | Where-Object { $_ -match '^(Off|Disabled?)$' } | Select-Object -First 1
    if ($off -and $p.DisplayValue -ne $off) {
        if ($PSCmdlet.ShouldProcess($AdapterName, "Set-NetAdapterAdvancedProperty '$($p.DisplayName)' = $off")) {
            Set-NetAdapterAdvancedProperty -Name $AdapterName -DisplayName $p.DisplayName -DisplayValue $off
        }
    }
}

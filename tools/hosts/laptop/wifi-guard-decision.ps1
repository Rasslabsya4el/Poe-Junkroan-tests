# tools/hosts/laptop/wifi-guard-decision.ps1 (#1188): the pure decision of the laptop Wi-Fi guard.
#
# Dot-sourcing this file defines Get-WifiGuardAction and runs nothing else. The function has no network,
# no adapter and no clock: the caller checks the internet, does the adapter disable / 10 s / enable /
# wait, and calls the function again with the new state and the new check result.
#
# Actions:
#   ok      internet is up and no drop is in progress: nothing to do
#   wait    a drop is in progress and has not yet lasted ThresholdMinutes (or it just started)
#   toggle  the drop has lasted ThresholdMinutes or more: the caller cycles the Wi-Fi adapter, then calls again
#   done    internet is back after a drop: the caller logs it; the state is reset (Toggles back to 0)
#
# Toggles has no cap and no growing pause: a still-failing check yields 'toggle' again at once.

function Get-WifiGuardAction {
    param(
        [hashtable]$State,
        [Parameter(Mandatory = $true)][bool]$InternetOk,
        [Parameter(Mandatory = $true)][datetime]$Now,
        [int]$ThresholdMinutes = 15
    )

    $since = $null
    $toggles = 0
    if ($null -ne $State) {
        $since = $State['NoInternetSince']
        if ($null -ne $State['Toggles']) {
            $toggles = [int]$State['Toggles']
        }
    }

    if ($InternetOk) {
        if ($null -eq $since) {
            return @{ Action = 'ok'; State = @{ NoInternetSince = $null; Toggles = $toggles } }
        }
        return @{ Action = 'done'; State = @{ NoInternetSince = $null; Toggles = 0 } }
    }

    if ($null -eq $since) {
        return @{ Action = 'wait'; State = @{ NoInternetSince = $Now; Toggles = $toggles } }
    }

    $since = [datetime]$since
    $elapsed = $Now - $since
    if ($elapsed.TotalMinutes -ge $ThresholdMinutes) {
        return @{ Action = 'toggle'; State = @{ NoInternetSince = $since; Toggles = $toggles + 1 } }
    }
    return @{ Action = 'wait'; State = @{ NoInternetSince = $since; Toggles = $toggles } }
}

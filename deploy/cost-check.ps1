<#
  Money check. Run every Sunday, or before you leave the project for a few days.
  Usage: .\deploy\cost-check.ps1

  What it shows:
    - cash balance and debt (BSS API lives in cn-north-1, not cn-north-4)
    - whether the ECS is still powered on
    - one clear warning line

  Note: the CNY 50 voucher is NOT included in these numbers.
  Check the voucher balance and expiry date in the console:
    console -> Fees / Cost Center -> Coupons
#>
param([switch]$Quiet)

$hcloud = 'D:\huaweicloud-cli-windows-amd64\hcloud.exe'
if (-not (Test-Path $hcloud)) {
  $c = Get-Command hcloud -ErrorAction SilentlyContinue
  if ($c) { $hcloud = $c.Source }
}
if (-not $hcloud -or -not (Test-Path $hcloud)) { Write-Host 'hcloud not found' -ForegroundColor Red; exit 1 }

$Region    = 'cn-north-4'
$BssRegion = 'cn-north-1'
$ServerId  = 'dcad3551-7743-4abd-9043-e51b8acb44a2'

function J($t) { ($t | Out-String) -replace '(?s)^[^{]*', '' | ConvertFrom-Json }

$cash = 0.0
try {
  $bal = J (& $hcloud BSS ShowCustomerAccountBalances --cli-region=$BssRegion 2>$null)
  $cash = ($bal.account_balances | Measure-Object -Property amount -Sum).Sum
  $debt = [double]$bal.debt_amount
} catch {
  Write-Host 'balance query failed (network?), check the console manually' -ForegroundColor Yellow
  $debt = -1
}

$state = 'unknown'
try {
  $s = (J (& $hcloud ECS ListServersDetails --cli-region=$Region 2>$null)).servers |
       Where-Object { $_.id -eq $ServerId } | Select-Object -First 1
  if ($s) { $state = $s.status } else { $state = 'none (deleted, 0 CNY/day)' }
} catch { }

if (-not $Quiet) {
  Write-Host ('cash balance : CNY {0}' -f $cash)
  Write-Host ('debt         : CNY {0}' -f $debt)
  Write-Host ('ECS state    : {0}' -f $state)
  Write-Host ''
}

if ($debt -gt 0) {
  Write-Host '!! IN DEBT. Pay it in the console. Debt -> 15d grace -> 15d retention -> resources released and DATA DELETED.' -ForegroundColor Red
}
elseif ($cash -le 0) {
  Write-Host 'Cash is 0: only the voucher stands between you and debt. Check voucher balance + expiry today.' -ForegroundColor Yellow
}
else {
  Write-Host 'OK' -ForegroundColor Green
}

if ($state -eq 'ACTIVE') {
  Write-Host 'ECS is running: if you are not testing right now, run  .\deploy\ecs-ctl.ps1 stop' -ForegroundColor Yellow
}

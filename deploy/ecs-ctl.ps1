<#
  codecraft ECS control (B owns this file)
  Usage:
    .\deploy\ecs-ctl.ps1 status    # show power state
    .\deploy\ecs-ctl.ps1 start     # power on, then wait for HTTP 200
    .\deploy\ecs-ctl.ps1 stop      # power off (compute billing pauses)
    .\deploy\ecs-ctl.ps1 url       # check http://<ip>/ until it answers
    .\deploy\ecs-ctl.ps1 ssh       # open a shell as root

  Cost rule: STOP it whenever you are not actively testing.
  Stopping saves CPU/memory; the 40G disk and the EIP keep billing (~1 CNY/day).
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet('status', 'start', 'stop', 'url', 'ssh')]
  [string]$Action = 'status'
)

$ErrorActionPreference = 'Continue'

# ---- fixed facts (change here only) ----
$Region    = 'cn-north-4'
$ProjectId = '01a12f4d281a7548ae83bc03e0dc0801'
$ServerId  = 'dcad3551-7743-4abd-9043-e51b8acb44a2'
$PublicIp  = '121.36.108.46'
$KeyPath   = Join-Path $env:USERPROFILE '.ssh\codecraft.pem'

# runtime.json is written by ecs-create.ps1 after a rebuild; it overrides the ids above
$rt = Join-Path $PSScriptRoot 'runtime.json'
if (Test-Path $rt) {
  try {
    $r = Get-Content $rt -Raw | ConvertFrom-Json
    if ($r.serverId) { $ServerId = $r.serverId }
    if ($r.publicIp) { $PublicIp = $r.publicIp }
  } catch { }
}

$hcloud = 'D:\huaweicloud-cli-windows-amd64\hcloud.exe'
if (-not (Test-Path $hcloud)) {
  $cmd = Get-Command hcloud -ErrorAction SilentlyContinue
  if ($cmd) { $hcloud = $cmd.Source }
}
if (-not $hcloud -or -not (Test-Path $hcloud)) {
  Write-Host 'hcloud not found. Set $hcloud at the top of this script.' -ForegroundColor Red
  exit 1
}

function Get-Server {
  $raw = & $hcloud ECS ListServersDetails --cli-region=$Region 2>$null | Out-String
  $json = ($raw -replace '(?s)^[^{]*', '') | ConvertFrom-Json
  $json.servers | Where-Object { $_.id -eq $ServerId } | Select-Object -First 1
}

function Wait-State([string]$want, [int]$timeoutSec = 180) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $s = Get-Server
    if ($s -and $s.status -eq $want) { return $true }
    Start-Sleep -Seconds 5
  }
  return $false
}

function Test-Url([int]$maxTry = 15) {
  for ($i = 0; $i -lt $maxTry; $i++) {
    $code = & curl.exe -s -o NUL -m 6 -w '%{http_code}' "http://$PublicIp/" 2>$null
    Write-Host ("  http://{0}/ -> {1}" -f $PublicIp, $code)
    if ($code -eq '200') { return $true }
    Start-Sleep -Seconds 6
  }
  return $false
}

switch ($Action) {
  'status' {
    $s = Get-Server
    if (-not $s) {
      Write-Host 'no ECS exists right now (deleted to save money).' -ForegroundColor Yellow
      Write-Host 'rebuild it with:  .\deploy\ecs-create.ps1' -ForegroundColor Yellow
      exit 1
    }
    Write-Host ("name   : {0}" -f $s.name)
    Write-Host ("status : {0}" -f $s.status)
    Write-Host ("public : http://{0}/" -f $PublicIp)
    if ($s.status -ne 'ACTIVE') { Write-Host 'NOTE: stopped -> compute is not billed, disk+EIP still are.' -ForegroundColor Yellow }
  }
  'stop' {
    if (-not (Get-Server)) { Write-Host 'no ECS exists - nothing to stop.' -ForegroundColor Yellow; exit 0 }
    Write-Host 'stopping...'
    & $hcloud ECS BatchStopServers --cli-region=$Region --os-stop.type=SOFT --os-stop.servers.1.id=$ServerId 2>&1 | Out-Null
    if (Wait-State 'SHUTOFF') { Write-Host 'stopped. compute billing paused (disk + EIP still billed).' -ForegroundColor Green }
    else { Write-Host 'stop timed out, check console' -ForegroundColor Red }
  }
  'start' {
    if (-not (Get-Server)) { Write-Host 'no ECS exists. Run .\deploy\ecs-create.ps1 first.' -ForegroundColor Yellow; exit 1 }
    Write-Host 'starting...'
    & $hcloud ECS BatchStartServers --cli-region=$Region --os-start.servers.1.id=$ServerId 2>&1 | Out-Null
    if (-not (Wait-State 'ACTIVE')) { Write-Host 'start timed out, check console' -ForegroundColor Red; exit 1 }
    Write-Host 'ACTIVE. ECS status != service ready: nginx needs ~20-40s more.' -ForegroundColor Yellow
    if (Test-Url) { Write-Host 'page is up.' -ForegroundColor Green } else { Write-Host 'page did not answer, check nginx: .\deploy\ecs-ctl.ps1 ssh' -ForegroundColor Red }
  }
  'url' {
    if (Test-Url) { Write-Host 'page is up.' -ForegroundColor Green } else { Write-Host 'no HTTP 200 yet.' -ForegroundColor Red }
  }
  'ssh' {
    ssh -i $KeyPath -o StrictHostKeyChecking=no root@$PublicIp
  }
}

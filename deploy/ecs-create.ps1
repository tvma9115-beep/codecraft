<#
  Rebuild the cloud box from zero. Run this after you delete everything.
  Usage:  .\deploy\ecs-create.ps1            # ECS + EIP + nginx + hello page
          .\deploy\ecs-create.ps1 -SkipNginx # create only, install nginx later

  Steps
    1. ECS   codecraft-ecs (c6.large.2 / Ubuntu 22.04 / 40G GPSSD / postPaid)
    2. EIP   1 Mbps, bound to the new port
    3. nginx + hello page over SSH
    4. write deploy/runtime.json so ecs-ctl.ps1 picks up the new id/ip

  Prereq: keypair 'codecraft-key' must still exist in cn-north-4,
          and the private key must be at %USERPROFILE%\.ssh\codecraft.pem
  Cost:   billing starts as soon as step 1 succeeds.
  Keep this file pure ASCII: Windows PowerShell 5.1 misreads UTF-8 without BOM.
#>
param([switch]$SkipNginx)

$ErrorActionPreference = 'Stop'

# ---- fixed facts ----
$Region      = 'cn-north-4'
$ProjectId   = '01a12f4d281a7548ae83bc03e0dc0801'
$VpcId       = '985b5715-d1ea-488c-8ae1-dfba7efa0d61'
$SubnetId    = '51cfc60e-c827-4216-83ee-68ff8bfa3176'
$SgId        = '75ca6cb1-bf51-47f6-a7ed-73fdbd77b10e'
$ImageId     = '89ac6e18-d938-4b0d-b038-bcdb03a1b87f'   # Ubuntu 22.04 server 64bit
$Flavor      = 'c6.large.2'
$Zone        = 'cn-north-4a'
$KeyName     = 'codecraft-key'
$KeyPath     = Join-Path $env:USERPROFILE '.ssh\codecraft.pem'
$KnownHosts  = Join-Path $env:USERPROFILE '.ssh\known_hosts'
$RuntimeFile = Join-Path $PSScriptRoot 'runtime.json'

$hcloud = 'D:\huaweicloud-cli-windows-amd64\hcloud.exe'
if (-not (Test-Path $hcloud)) {
  $c = Get-Command hcloud -ErrorAction SilentlyContinue
  if ($c) { $hcloud = $c.Source }
}
if (-not $hcloud -or -not (Test-Path $hcloud)) { throw 'hcloud not found' }

function J($t) { ($t | Out-String) -replace '(?s)^[^{]*', '' | ConvertFrom-Json }

function Call-Json([string]$json, [string[]]$rest) {
  $tmp = [System.IO.Path]::GetTempFileName()
  try {
    Set-Content -Path $tmp -Value $json -Encoding ascii
    $a = @($rest) + "--cli-jsonInput=$tmp"
    return (& $hcloud @a 2>&1 | Out-String)
  }
  finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

Write-Host '=== 1/4 check existing ===' -ForegroundColor Cyan
$existing = (J (& $hcloud ECS ListServersDetails --cli-region=$Region)).servers |
            Where-Object { $_.name -eq 'codecraft-ecs' }
if ($existing) {
  Write-Host ("already exists: {0} ({1}) - nothing created" -f $existing.id, $existing.status) -ForegroundColor Yellow
  Write-Host 'delete the old ECS first if you really want to rebuild.' -ForegroundColor Yellow
  exit 0
}

Write-Host '=== 2/4 create ECS (billing starts) ===' -ForegroundColor Cyan
$body = @"
{
  "path": {"project_id": "$ProjectId"},
  "body": {
    "server": {
      "name": "codecraft-ecs",
      "imageRef": "$ImageId",
      "flavorRef": "$Flavor",
      "vpcid": "$VpcId",
      "nics": [{"subnet_id": "$SubnetId"}],
      "root_volume": {"volumetype": "GPSSD", "size": 40},
      "security_groups": [{"id": "$SgId"}],
      "availability_zone": "$Zone",
      "chargingMode": "postPaid",
      "count": 1,
      "key_name": "$KeyName"
    }
  }
}
"@
$r = Call-Json $body @('ECS', 'CreateServers', "--cli-region=$Region")
if ($r -notmatch 'serverIds') { throw "create failed: $r" }

$server = $null
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 10
  $server = (J (& $hcloud ECS ListServersDetails --cli-region=$Region)).servers |
            Where-Object { $_.name -eq 'codecraft-ecs' } | Select-Object -First 1
  if ($server) {
    Write-Host ("  [{0}s] {1}" -f (($i + 1) * 10), $server.status)
    if ($server.status -eq 'ACTIVE') { break }
    if ($server.status -eq 'ERROR') { throw 'ECS build failed, check console' }
  }
}
if (-not $server -or $server.status -ne 'ACTIVE') { throw 'ECS did not become ACTIVE in 300s' }

$ServerId = $server.id
$netProp  = $server.addresses.PSObject.Properties | Select-Object -First 1
$PortId   = $netProp.Value[0].'OS-EXT-IPS:port_id'
Write-Host ("  ECS : {0}" -f $ServerId)
Write-Host ("  port: {0}" -f $PortId)

Write-Host '=== 3/4 create and bind EIP ===' -ForegroundColor Cyan
$eipBody = @"
{
  "path": {"project_id": "$ProjectId"},
  "body": {
    "publicip": {"type": "5_bgp", "ip_version": 4},
    "bandwidth": {"name": "codecraft-bw", "size": 1, "share_type": "PER", "charge_mode": "bandwidth"}
  }
}
"@
$eipResp  = J (Call-Json $eipBody @('EIP', 'CreatePublicip/v2', "--cli-region=$Region"))
$EipId    = $eipResp.publicip.id
$PublicIp = $eipResp.publicip.public_ip_address
Write-Host ("  EIP : {0} ({1})" -f $PublicIp, $EipId)

$bindBody = @"
{
  "path": {"project_id": "$ProjectId", "publicip_id": "$EipId"},
  "body": {"publicip": {"port_id": "$PortId"}}
}
"@
$null = Call-Json $bindBody @('EIP', 'UpdatePublicip/v2', "--cli-region=$Region")
Write-Host '  bound.'

@{ serverId = $ServerId; publicIp = $PublicIp; eipId = $EipId; createdAt = (Get-Date -Format 'yyyy-MM-dd HH:mm') } |
  ConvertTo-Json | Set-Content -Path $RuntimeFile -Encoding utf8
Write-Host ("  wrote {0}" -f $RuntimeFile)

if ($SkipNginx) {
  Write-Host '=== 4/4 skip nginx ===' -ForegroundColor Yellow
}
else {
  Write-Host '=== 4/4 install nginx + hello page ===' -ForegroundColor Cyan
  $remote = "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq nginx >/dev/null 2>&1 && echo '<h1>CodeCraft</h1><p>platform online - nginx ok</p>' > /var/www/html/index.html && systemctl enable --now nginx >/dev/null 2>&1 && echo NGINX_OK"
  ssh -i $KeyPath -o StrictHostKeyChecking=no -o UserKnownHostsFile=$KnownHosts -o ConnectTimeout=20 "root@$PublicIp" $remote
  for ($i = 0; $i -lt 15; $i++) {
    $code = & curl.exe -s -o NUL -m 8 -w '%{http_code}' "http://$PublicIp/"
    if ($code -eq '200') { Write-Host '  page is up (200)' -ForegroundColor Green; break }
    Start-Sleep -Seconds 6
  }
}

Write-Host ''
Write-Host ("REBUILT: http://{0}/" -f $PublicIp) -ForegroundColor Green
Write-Host 'Update the new address in: deploy/CLOUD-RESOURCES.md section 1, project progress doc section 5, and any material link.'

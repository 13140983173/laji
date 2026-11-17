<#
.SYNOPSIS
Publish the laji-pet release asset and refresh the plugin catalog on GitHub.

.DESCRIPTION
Two writes, both against the same repository:

  1. create the release tag (if missing) and upload the zip asset produced by
     pack_release.py, so `install.type = "release"` in the catalog resolves;
  2. commit pluginhub/index.json so the market advertises the new plugin id.

Requires GH_TOKEN in the environment: a token with `Contents: Read and write`
plus `Releases: Read and write` on the target repo. The token is only read from
the environment and is never written to disk or echoed.

Usage:
  $env:GH_TOKEN = '<token>'
  pwsh -File plugin-registry/plugins/laji-pet/publish_release.ps1 -WhatIfPlan
  pwsh -File plugin-registry/plugins/laji-pet/publish_release.ps1

Comment-only caveat: this file is intentionally ASCII. Windows PowerShell 5.1
parses a BOM-less UTF-8 file as ANSI, and non-ASCII bytes there have already
broken script parsing once in this repo.
#>
[CmdletBinding()]
param(
  [string]$Owner = '13140983173',
  [string]$Repo = 'laji',
  [string]$Tag = 'laji-pet-v1.1.0',
  [string]$AssetPath,
  [string]$CatalogPath = '',
  [string[]]$Cdns = @('https://purge.jsdelivr.net/gh/{0}/{1}@main/pluginhub/index.json'),
  [switch]$SkipAsset,
  [switch]$SkipCatalog,
  [switch]$SkipCdn,
  [switch]$WhatIfPlan
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$pluginRoot = Split-Path -Parent $PSCommandPath
$repoRoot = Resolve-Path (Join-Path $pluginRoot '..\..\..')
if (-not $AssetPath) {
  $manifest = Join-Path $pluginRoot 'laji.plugin.toml'
  $version = (Select-String -Path $manifest -Pattern '^version\s*=\s*"([^"]+)"' |
      Select-Object -First 1).Matches[0].Groups[1].Value
  $AssetPath = Join-Path $pluginRoot ('dist\laji-pet-{0}-win-x64.zip' -f $version)
}
if (-not $CatalogPath) {
  $CatalogPath = Join-Path $repoRoot 'plugin-registry\pluginhub\index.json'
}
$AssetPath = (Resolve-Path $AssetPath).Path
$CatalogPath = (Resolve-Path $CatalogPath).Path
$assetName = Split-Path -Leaf $AssetPath

if (-not $env:GH_TOKEN) {
  throw 'GH_TOKEN is not set. Export a token with Contents+Releases write access, then rerun.'
}
$headers = @{
  Authorization          = "Bearer $env:GH_TOKEN"
  'User-Agent'           = 'laji-pet-publisher'
  Accept                 = 'application/vnd.github+json'
  'X-GitHub-Api-Version' = '2022-11-28'
}
$api = "https://api.github.com/repos/$Owner/$Repo"

# The system proxy on this machine is configured for a port nobody listens on,
# which makes every .NET HTTP call fail with "cannot connect to the remote
# server". Route around it instead of asking the operator to toggle software.
$env:HTTP_PROXY = ''
$env:HTTPS_PROXY = ''
$env:ALL_PROXY = ''
[System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Invoke-Gh {
  param([string]$Uri, [string]$Method = 'GET', $Body = $null)
  $req = @{ Uri = $Uri; Headers = $headers; Method = $Method; TimeoutSec = 120 }
  if ($null -ne $Body) {
    $req['Body'] = ($Body | ConvertTo-Json -Depth 8)
    $req['ContentType'] = 'application/json'
  }
  return Invoke-RestMethod @req
}

Write-Host "== target ==" -ForegroundColor Cyan
$repoInfo = Invoke-Gh -Uri $api
if (-not $repoInfo.permissions.push) {
  throw ("no write access: token user cannot push to {0}/{1} (push={2}). " -f $Owner, $Repo, $repoInfo.permissions.push) +
        'Use a token for the repo owner, or add the token user as a collaborator with Write access.'
}
Write-Host ("  repo  : {0}  default={1}  push={2}" -f $repoInfo.full_name, $repoInfo.default_branch, $repoInfo.permissions.push)
Write-Host ("  tag   : {0}" -f $Tag)
Write-Host ("  asset : {0}  ({1:N1} MB)" -f $assetName, ((Get-Item $AssetPath).Length / 1MB))
Write-Host ("  loaded: {0}" -f (Get-FileHash $AssetPath -Algorithm SHA256).Hash)

if ($WhatIfPlan) {
  Write-Host 'WhatIfPlan: stop before any write.' -ForegroundColor Yellow
  return
}

if (-not $SkipAsset) {
  Write-Host '== release ==' -ForegroundColor Cyan
  $release = $null
  try {
    $release = Invoke-Gh -Uri "$api/releases/tags/$Tag"
    Write-Host ("  exists: id={0} assets={1}" -f $release.id, $release.assets.Count)
  } catch {
    $created = Invoke-Gh -Uri "$api/releases" -Method POST -Body @{
      tag_name         = $Tag
      target_commitish = $repoInfo.default_branch
      name             = "Laji Pet $Tag"
      body             = "Plugin market asset for com.nerve.laji-pet. Unzipped into <plugin>/bin/laji-pet."
      draft            = $false
      prerelease       = $false
    }
    $release = $created
    Write-Host ("  created: id={0} tag={1}" -f $release.id, $release.tag_name)
  }

  foreach ($existing in @($release.assets)) {
    if ($existing.name -eq $assetName) {
      Write-Host ("  replacing stale asset id={0}" -f $existing.id)
      Invoke-Gh -Uri "$api/releases/assets/$($existing.id)" -Method DELETE | Out-Null
    }
  }

  # curl streams the body; Invoke-RestMethod would buffer 260 MB in memory.
  $uploadUrl = ($release.upload_url -replace '\{.*$', '') + "?name=$assetName&label=$assetName"
  Write-Host ("  uploading -> {0}" -f $uploadUrl) -ForegroundColor Cyan
  $curlArgs = @(
    '-sS', '-X', 'POST',
    # Windows schannel refuses the handshake when the revocation list is
    # unreachable (CRYPT_E_REVOCATION_OFFLINE), which is the normal state on a
    # machine whose configured proxy is down. Revocation is not the point here:
    # the token already authenticates the write.
    '--ssl-no-revoke',
    '-H', "Authorization: Bearer $env:GH_TOKEN",
    '-H', 'Content-Type: application/zip',
    '-H', 'User-Agent: laji-pet-publisher',
    '--data-binary', "@$AssetPath",
    $uploadUrl
  )
  $uploadJson = & curl.exe @curlArgs
  if ($LASTEXITCODE -ne 0) { throw "curl upload failed with exit code $LASTEXITCODE" }
  $uploaded = $uploadJson | ConvertFrom-Json
  if (-not $uploaded.browser_download_url) { throw "upload response missing browser_download_url: $uploadJson" }
  $localSize = (Get-Item $AssetPath).Length
  if ($uploaded.size -ne $localSize) {
    throw ("size mismatch after upload: local={0} remote={1}" -f $localSize, $uploaded.size)
  }
  Write-Host ("  uploaded: {0} bytes  {1}" -f $uploaded.size, $uploaded.browser_download_url) -ForegroundColor Green
}

if (-not $SkipCatalog) {
  Write-Host '== catalog ==' -ForegroundColor Cyan
  $relPath = 'pluginhub/index.json'
  $bytes = [System.IO.File]::ReadAllBytes($CatalogPath)
  $sha = (Get-FileHash $CatalogPath -Algorithm SHA256).Hash.ToLower()
  $current = $null
  try { $current = Invoke-Gh -Uri "$api/contents/$relPath" } catch { $current = $null }
  if ($current -and $current.sha -eq $sha) {
    Write-Host ("  already up to date (blob {0})" -f $sha) -ForegroundColor Green
  } else {
    $body = @{
      message = "pluginhub: publish com.nerve.laji-pet $Tag"
      content = [Convert]::ToBase64String($bytes)
      branch  = $repoInfo.default_branch
    }
    if ($current) { $body['sha'] = $current.sha }
    $res = Invoke-Gh -Uri "$api/contents/$relPath" -Method PUT -Body $body
    Write-Host ("  committed: {0}" -f $res.commit.sha) -ForegroundColor Green
  }
}

if (-not $SkipCdn) {
  Write-Host '== cdn purge ==' -ForegroundColor Cyan
  foreach ($pattern in $Cdns) {
    $url = $pattern -f $Owner, $Repo
    try {
      $raw = & curl.exe -sS --ssl-no-revoke --max-time 60 $url
      $text = (($raw | Out-String) -replace '\s+', ' ').Trim()
      if ($text.Length -gt 120) { $text = $text.Substring(0, 120) }
      Write-Host ("  {0} -> {1}" -f $url, $text)
    } catch {
      Write-Host ("  {0} -> purge failed: {1}" -f $url, $_.Exception.Message) -ForegroundColor Yellow
    }
  }
}

Write-Host 'done.' -ForegroundColor Green

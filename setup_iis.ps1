# ============================================================
#  Travel Map Tool  –  IIS Reverse Proxy Setup
#  Run as Administrator in PowerShell AFTER server_setup.bat.
#
#  EDIT THE LINE BELOW before running:
#    $domain  = the internal domain name IT assigned for this tool
# ============================================================

param(
    [string]$domain = "maps.yourcompany.com",   # <-- CHANGE THIS
    [int]   $appPort = 5000
)

$siteName = "TravelMapTool"
$appUrl   = "http://127.0.0.1:$appPort"

Write-Host ""
Write-Host " Setting up IIS for: http://$domain" -ForegroundColor Cyan
Write-Host ""

# ── 1. Ensure IIS features are enabled ───────────────────────
Write-Host " Enabling IIS features..."
$features = @(
    "IIS-WebServer",
    "IIS-WebServerRole",
    "IIS-HttpRedirect",
    "IIS-StaticContent",
    "IIS-DefaultDocument"
)
foreach ($f in $features) {
    Enable-WindowsOptionalFeature -Online -FeatureName $f -All -NoRestart -ErrorAction SilentlyContinue | Out-Null
}

# ── 2. Install ARR and URL Rewrite via Web Platform Installer ─
Write-Host " Checking for URL Rewrite module..."
$rewriteKey = "HKLM:\SOFTWARE\Microsoft\IIS Extensions\URL Rewrite"
if (-not (Test-Path $rewriteKey)) {
    Write-Host " Downloading URL Rewrite 2.1..." -ForegroundColor Yellow
    $rwUrl = "https://download.microsoft.com/download/1/2/8/128E2E22-C1B9-44A4-BE2A-5859ED1D4592/rewrite_amd64_en-US.msi"
    $rwInstaller = "$env:TEMP\urlrewrite.msi"
    Invoke-WebRequest -Uri $rwUrl -OutFile $rwInstaller -UseBasicParsing
    Start-Process msiexec -ArgumentList "/i `"$rwInstaller`" /quiet" -Wait
    Write-Host " URL Rewrite installed." -ForegroundColor Green
} else {
    Write-Host " URL Rewrite already installed." -ForegroundColor Green
}

Write-Host " Checking for ARR (Application Request Routing)..."
$arrKey = "HKLM:\SOFTWARE\Microsoft\IIS Extensions\Application Request Routing"
if (-not (Test-Path $arrKey)) {
    Write-Host " Downloading ARR 3.0..." -ForegroundColor Yellow
    $arrUrl = "https://download.microsoft.com/download/E/9/8/E9849D6A-020E-47E4-9FD0-A023E99B54EB/requestRouter_amd64.msi"
    $arrInstaller = "$env:TEMP\arr.msi"
    Invoke-WebRequest -Uri $arrUrl -OutFile $arrInstaller -UseBasicParsing
    Start-Process msiexec -ArgumentList "/i `"$arrInstaller`" /quiet" -Wait
    Write-Host " ARR installed." -ForegroundColor Green
} else {
    Write-Host " ARR already installed." -ForegroundColor Green
}

# ── 3. Enable ARR proxy ───────────────────────────────────────
Import-Module WebAdministration -ErrorAction SilentlyContinue
Set-WebConfigurationProperty -pspath 'MACHINE/WEBROOT/APPHOST' `
    -filter "system.webServer/proxy" -name "enabled" -value "True" `
    -ErrorAction SilentlyContinue

# ── 4. Create the IIS site ────────────────────────────────────
Write-Host " Creating IIS site '$siteName'..."
$existingSite = Get-Website -Name $siteName -ErrorAction SilentlyContinue
if ($existingSite) {
    Write-Host " Removing existing site..." -ForegroundColor Yellow
    Remove-Website -Name $siteName
}

# Physical path just needs to exist — requests are proxied, not served from disk
$physPath = "C:\inetpub\$siteName"
if (-not (Test-Path $physPath)) { New-Item -ItemType Directory -Path $physPath | Out-Null }

New-Website -Name $siteName -PhysicalPath $physPath `
            -HostHeader $domain -Port 80 -Force | Out-Null

# ── 5. Write web.config (reverse proxy rule) ──────────────────
$webConfig = @"
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxy" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="$appUrl/{R:1}" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_HOST" value="{HTTP_HOST}" />
          </serverVariables>
        </rule>
      </rules>
    </rewrite>
    <security>
      <requestFiltering>
        <requestLimits maxAllowedContentLength="52428800" />
      </requestFiltering>
    </security>
  </system.webServer>
</configuration>
"@
$webConfig | Set-Content "$physPath\web.config" -Encoding UTF8

Write-Host " IIS site configured." -ForegroundColor Green

# ── 6. Start the site ─────────────────────────────────────────
Start-Website -Name $siteName
Write-Host ""
Write-Host " ============================================================" -ForegroundColor Green
Write-Host "  Done! The tool is available at:" -ForegroundColor Green
Write-Host "  http://$domain" -ForegroundColor White
Write-Host " ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host " Remember: ask IT to point $domain to this server's IP." -ForegroundColor Yellow
Write-Host ""

param([Parameter(Mandatory=$true)][string]$Archive)
$ErrorActionPreference = 'Stop'
$Archive = (Resolve-Path -LiteralPath $Archive).Path
$beforeHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
$status = Get-MpComputerStatus
if (-not $status.AntivirusEnabled) { throw 'Microsoft Defender Antivirus is unavailable; release scan cannot be certified.' }
if (((Get-Date) - $status.AntivirusSignatureLastUpdated).TotalDays -gt 7) { Update-MpSignature }
$status = Get-MpComputerStatus
if (((Get-Date) - $status.AntivirusSignatureLastUpdated).TotalDays -gt 7) { throw 'Defender signatures are stale.' }
$candidates = @()
$platform = Join-Path $env:ProgramData 'Microsoft\Windows Defender\Platform'
if (Test-Path $platform) {
    $candidates += Get-ChildItem -LiteralPath $platform -Directory | Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName 'MpCmdRun.exe' }
}
$candidates += Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
$scanner = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $scanner) { throw 'Defender command-line scanner is missing.' }
$signature = Get-AuthenticodeSignature -LiteralPath $scanner
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
    throw 'Cannot verify the Microsoft scanner signature.'
}
$started = Get-Date
$payload = Join-Path $env:RUNNER_TEMP ('aass-scan-' + [guid]::NewGuid())
Expand-Archive -LiteralPath $Archive -DestinationPath $payload
& $scanner -Scan -ScanType 3 -File $Archive
$archiveExit = $LASTEXITCODE
& $scanner -Scan -ScanType 3 -File $payload
$payloadExit = $LASTEXITCODE
$matches = @(Get-MpThreatDetection | Where-Object {
    ($_.Resources -join ' ') -match ([regex]::Escape($Archive) + '|' + [regex]::Escape($payload))
})
if ($archiveExit -ne 0 -or $payloadExit -ne 0 -or $matches.Count -gt 0) {
    throw 'Defender reported a threat, failed a scan, or remediated content. Release is blocked.'
}
$afterHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($beforeHash -ne $afterHash) { throw 'Archive changed during scanning.' }
$release = Get-ChildItem -LiteralPath $payload -Directory | Select-Object -First 1
python (Join-Path $release.FullName 'verify_release.py') --root $release.FullName
if ($LASTEXITCODE -ne 0) { throw 'Payload integrity failed after Defender scan.' }
[ordered]@{
    passed = $true
    archive_sha256 = $afterHash
    archive = [IO.Path]::GetFileName($Archive)
    engine = $status.AMEngineVersion
    signature_version = $status.AntivirusSignatureVersion
    signatures_updated = $status.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o')
    started_utc = $started.ToUniversalTime().ToString('o')
    finished_utc = (Get-Date).ToUniversalTime().ToString('o')
    archive_exit = $archiveExit
    payload_exit = $payloadExit
    detections = $matches.Count
    microsoft_scanner_signature = 'Valid'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path (Split-Path $Archive) 'defender-scan.json') -Encoding utf8
Write-Host 'Microsoft Defender scans and post-scan integrity checks passed.'

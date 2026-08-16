# make_sha256.ps1 — 生成 dist-package/SHA256SUMS.txt
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$out = "# SHA-256 校验（生成于 $(Get-Date -Format 'yyyy-MM-dd HH:mm')）`n"
$nsis = Get-ChildItem 'target\release\bundle\nsis\*.exe' | Select-Object -First 1
if ($nsis) {
    Copy-Item $nsis.FullName 'dist-package\' -Force
    $h1 = (Get-FileHash $nsis.FullName -Algorithm SHA256).Hash
    $out += "$($nsis.Name): $h1`n"
}
$h2 = (Get-FileHash 'dist-package\VoiceStudio-Portable.zip' -Algorithm SHA256).Hash
$out += "VoiceStudio-Portable.zip: $h2`n"
$out | Out-File 'dist-package\SHA256SUMS.txt' -Encoding utf8
Write-Host $out

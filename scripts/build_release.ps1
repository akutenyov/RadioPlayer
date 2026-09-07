[CmdletBinding()]
param(
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"

# Resolve from this script's location so it works from a local shell and GitHub Actions.
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseDirectory = Join-Path $ProjectRoot $OutputDirectory
$SpecFile = Join-Path $ProjectRoot "RadioPlayer.spec"
$Executable = Join-Path $ReleaseDirectory "RadioPlayer.exe"

Push-Location $ProjectRoot
try {
    # The spec file keeps the entry point, icon, and windowed build settings in one place.
    python -m PyInstaller --noconfirm --clean --distpath $ReleaseDirectory --workpath build $SpecFile

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "PyInstaller completed without creating $Executable"
    }

    $Checksum = Get-FileHash -Algorithm SHA256 -LiteralPath $Executable
    $ChecksumLine = "{0}  {1}" -f $Checksum.Hash.ToLowerInvariant(), (Split-Path -Leaf $Executable)
    $ChecksumLine | Set-Content -LiteralPath (Join-Path $ReleaseDirectory "RadioPlayer.exe.sha256") -NoNewline

    Write-Host "Created $Executable"
    Write-Host "SHA-256: $($Checksum.Hash)"
}
finally {
    Pop-Location
}

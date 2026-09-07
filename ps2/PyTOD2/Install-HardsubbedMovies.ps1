param(
    [string]$PyTOD2Folder = $PSScriptRoot,
    [switch]$SkipBackup
)

$ErrorActionPreference = 'Stop'

$movieArchive = Join-Path $PyTOD2Folder 'MOVIE.FPB'
$executable = Join-Path $PSScriptRoot '..\scripts\SLPS_251.72'
$replacementFolder = Join-Path $PSScriptRoot 'hardsubbed_movies'
$backup = Join-Path $PyTOD2Folder 'MOVIE.FPB.before-hardsubs.bak'
[int[]]$movieNumbers = @(1, 2, 3, 4, 5, 7, 8, 10)

if ($movieNumbers -notcontains 7) {
    throw 'Internal installer error: 00007.mpeg is missing from the replacement manifest.'
}

foreach ($required in @($movieArchive, $executable, $replacementFolder)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path was not found: $required"
    }
}

# PyTOD2 reads twelve little-endian pointers here: eleven movie starts plus
# the end of the final movie. The low six bits encode an end adjustment.
$slps = [System.IO.File]::ReadAllBytes($executable)
$pointerTable = 0xE62F0
$pointers = for ($i = 0; $i -lt 12; $i++) {
    [BitConverter]::ToUInt32($slps, $pointerTable + ($i * 4))
}

$entries = foreach ($number in $movieNumbers) {
    $name = '{0:D5}.mpeg' -f $number
    $replacement = Join-Path $replacementFolder $name
    if (-not (Test-Path -LiteralPath $replacement)) {
        throw "Replacement is missing: $replacement"
    }

    $remainder = $pointers[$number] -band 0x3F
    $start = [int64]($pointers[$number] -band 0xFFFFFFC0)
    $end = [int64]($pointers[$number + 1] -band 0xFFFFFFC0) - $remainder
    $expectedSize = $end - $start
    $actualSize = (Get-Item -LiteralPath $replacement).Length
    if ($actualSize -ne $expectedSize) {
        throw "$name has size $actualSize, but its MOVIE.FPB slot requires $expectedSize bytes. Nothing was changed."
    }

    [pscustomobject]@{
        Name = $name
        Path = $replacement
        Start = $start
        Size = $expectedSize
    }
}

if ($entries.Count -ne $movieNumbers.Count) {
    throw "Prepared $($entries.Count) replacements, but expected $($movieNumbers.Count). Nothing was changed."
}

Write-Host ("Target archive: {0}" -f (Resolve-Path -LiteralPath $movieArchive))
Write-Host ("Replacement folder: {0}" -f (Resolve-Path -LiteralPath $replacementFolder))
Write-Host 'Planned replacements:'
foreach ($entry in $entries) {
    Write-Host ("  {0} ({1:N0} bytes)" -f $entry.Name, $entry.Size)
}

if (-not $SkipBackup -and -not (Test-Path -LiteralPath $backup)) {
    Write-Host 'Creating a safety backup of MOVIE.FPB...'
    Copy-Item -LiteralPath $movieArchive -Destination $backup
}

Write-Host 'Installing English hard-subbed movies...'
$target = [System.IO.File]::Open($movieArchive, 'Open', 'ReadWrite', 'None')
try {
    foreach ($entry in $entries) {
        $source = [System.IO.File]::OpenRead($entry.Path)
        try {
            $null = $target.Seek($entry.Start, 'Begin')
            $source.CopyTo($target)
            Write-Host ("  {0} installed" -f $entry.Name)
        }
        finally {
            $source.Dispose()
        }
    }
    $target.Flush($true)
}
finally {
    $target.Dispose()
}

# Read back every replaced slot and compare it with the supplied replacement.
Write-Host 'Verifying the installed data...'
$target = [System.IO.File]::OpenRead($movieArchive)
try {
    foreach ($entry in $entries) {
        $expected = [System.Security.Cryptography.SHA256]::Create()
        $actual = [System.Security.Cryptography.SHA256]::Create()
        $source = [System.IO.File]::OpenRead($entry.Path)
        try {
            $expectedHash = [BitConverter]::ToString($expected.ComputeHash($source))
        }
        finally {
            $source.Dispose()
            $expected.Dispose()
        }

        $null = $target.Seek($entry.Start, 'Begin')
        $remaining = $entry.Size
        $buffer = New-Object byte[] (1024 * 1024)
        while ($remaining -gt 0) {
            $wanted = [Math]::Min($buffer.Length, $remaining)
            $read = $target.Read($buffer, 0, $wanted)
            if ($read -le 0) { throw "Unexpected end of MOVIE.FPB while checking $($entry.Name)" }
            $actual.TransformBlock($buffer, 0, $read, $buffer, 0) | Out-Null
            $remaining -= $read
        }
        $actual.TransformFinalBlock((New-Object byte[] 0), 0, 0) | Out-Null
        $actualHash = [BitConverter]::ToString($actual.Hash)
        $actual.Dispose()
        if ($actualHash -ne $expectedHash) {
            throw "Verification failed for $($entry.Name)"
        }
        Write-Host ("  {0} verified" -f $entry.Name)
    }
}
finally {
    $target.Dispose()
}

Write-Host ("Finished. All {0} movie replacements were installed and verified." -f $entries.Count) -ForegroundColor Green
if (-not $SkipBackup) {
    Write-Host "Backup: $backup"
}

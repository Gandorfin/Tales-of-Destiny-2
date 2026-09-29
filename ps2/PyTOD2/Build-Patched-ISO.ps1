param(
    [string]$BaseIso,
    [string]$OutputIso,
    [string]$PatchDirectory = $PSScriptRoot,
    [switch]$CheckOnly,
    [switch]$Interactive
)
$ErrorActionPreference = 'Stop'
try {
    $projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $toolsRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'iso-tools'
    if ($Interactive -and (-not $BaseIso -or -not $OutputIso)) {
        Add-Type -AssemblyName System.Windows.Forms
        if (-not $BaseIso) {
            $openDialog = New-Object System.Windows.Forms.OpenFileDialog
            try {
                $openDialog.Title = 'Choose the base Tales of Destiny 2 PS2 ISO'
                $openDialog.Filter = 'PS2 ISO images (*.iso)|*.iso'
                $openDialog.InitialDirectory = $projectRoot
                $openDialog.FileName = 'Tales of Destiny 2 (Japan).iso'
                $openDialog.CheckFileExists = $true
                $openDialog.Multiselect = $false
                $openDialog.RestoreDirectory = $true
                if ($openDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
                    Write-Host 'Build cancelled.'
                    exit 0
                }
                $BaseIso = $openDialog.FileName
            } finally {
                $openDialog.Dispose()
            }
        }
        if (-not $OutputIso) {
            $baseFullPath = [IO.Path]::GetFullPath($BaseIso)
            $outputDirectory = [IO.Path]::GetDirectoryName($baseFullPath)
            $outputName = [IO.Path]::GetFileNameWithoutExtension($baseFullPath) + ' (Patched)'
            $suggestedPath = Join-Path $outputDirectory ($outputName + '.iso')
            if ((Test-Path -LiteralPath $suggestedPath) -or (Test-Path -LiteralPath ($suggestedPath + '.build.json'))) {
                $outputName += ' ' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
            }
            $saveDialog = New-Object System.Windows.Forms.SaveFileDialog
            try {
                $saveDialog.Title = 'Choose the patched ISO name and location'
                $saveDialog.Filter = 'PS2 ISO images (*.iso)|*.iso'
                $saveDialog.DefaultExt = 'iso'
                $saveDialog.AddExtension = $true
                $saveDialog.InitialDirectory = $outputDirectory
                $saveDialog.FileName = $outputName + '.iso'
                $saveDialog.CheckPathExists = $true
                $saveDialog.RestoreDirectory = $true
                # Existing files are rejected below, so do not offer to overwrite them.
                $saveDialog.OverwritePrompt = $false
                while (-not $OutputIso) {
                    if ($saveDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
                        Write-Host 'Build cancelled.'
                        exit 0
                    }
                    $selectedPath = $saveDialog.FileName
                    $problem = $null
                    if ([IO.Path]::GetExtension($selectedPath) -ine '.iso') {
                        $problem = 'Choose a filename ending in .iso.'
                    } elseif ($selectedPath -ieq $baseFullPath) {
                        $problem = 'Choose a different name from the base ISO.'
                    } elseif ((Test-Path -LiteralPath $selectedPath) -or (Test-Path -LiteralPath ($selectedPath + '.build.json'))) {
                        $problem = 'An ISO or build report with this name already exists. Choose a new name.'
                    }
                    if ($problem) {
                        [System.Windows.Forms.MessageBox]::Show($problem, 'Choose another output name',
                            [System.Windows.Forms.MessageBoxButtons]::OK,
                            [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
                    } else {
                        $OutputIso = $selectedPath
                    }
                }
            } finally {
                $saveDialog.Dispose()
            }
        }
    }
    if (-not $BaseIso) { $BaseIso = Join-Path $projectRoot 'Tales of Destiny 2 (Japan).iso' }
    if (-not $OutputIso) {
        $OutputIso = Join-Path $projectRoot 'Tales of Destiny 2 (Patched).iso'
        if (Test-Path -LiteralPath $OutputIso) {
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
            $OutputIso = Join-Path $projectRoot "Tales of Destiny 2 (Patched $stamp).iso"
        }
    }
    $dll = Join-Path $toolsRoot 'publish\Tod2IsoBuilder.dll'
    if (-not (Test-Path -LiteralPath $dll)) { & (Join-Path $toolsRoot 'Build-Tools.ps1') }
    $dotnet = Join-Path $toolsRoot '.dotnet\dotnet.exe'
    if (-not (Test-Path -LiteralPath $dotnet)) {
        $installed = Get-Command dotnet -ErrorAction SilentlyContinue
        if (-not $installed) { throw 'Run ps2\iso-tools\Build-Tools.ps1 to install the project-local .NET SDK.' }
        $dotnet = $installed.Source
    }
    $builderArgs = @($dll, '--base', $BaseIso, '--patch-dir', $PatchDirectory, '--output', $OutputIso)
    if ($CheckOnly) { $builderArgs += '--check' }
    & $dotnet @builderArgs
    exit $LASTEXITCODE
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

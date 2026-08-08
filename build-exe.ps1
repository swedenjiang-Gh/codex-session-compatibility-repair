[CmdletBinding()]
param(
    [string]$Python
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Python)) {
    $pythonCommand = Get-Command 'python.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $pythonCommand) {
        $Python = $pythonCommand.Source
    }
}

if ([string]::IsNullOrWhiteSpace($Python) -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw '找不到用于构建的 Python 3.11 或更高版本。'
}

& $Python -c 'import PyInstaller'
if ($LASTEXITCODE -ne 0) {
    throw '当前 Python 环境没有 PyInstaller。请先按 requirements-build.txt 准备隔离构建环境。'
}

$entryPoint = Join-Path $PSScriptRoot 'compatibility_repair_cli.py'
$distPath = Join-Path $PSScriptRoot 'dist'
$workPath = Join-Path $PSScriptRoot 'build\pyinstaller'
$specPath = Join-Path $PSScriptRoot 'build'
$nativeArguments = @(
    '-m'
    'PyInstaller'
    '--noconfirm'
    '--clean'
    '--onefile'
    '--console'
    '--noupx'
    '--name'
    'CodexSessionCompatibilityRepair'
    '--distpath'
    $distPath
    '--workpath'
    $workPath
    '--specpath'
    $specPath
    $entryPoint
)

& $Python @nativeArguments
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "PyInstaller 构建失败，退出码：$exitCode"
}

$executable = Join-Path $distPath 'CodexSessionCompatibilityRepair.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "构建未生成目标文件：$executable"
}

Write-Output "构建完成：$executable"


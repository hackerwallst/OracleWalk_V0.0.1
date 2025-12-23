#requires -version 5.1

param(
  [string]$PythonVersion = "3.11.8",
  [string]$VenvDir = ".venv"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$pythonParts = $PythonVersion.Split(".")
if ($pythonParts.Count -lt 2) {
  throw "PythonVersion inválido: $PythonVersion"
}
$PythonMajor = [int]$pythonParts[0]
$PythonMinor = [int]$pythonParts[1]
$PythonMajorMinor = "$PythonMajor.$PythonMinor"
$PythonFolder = "Python$PythonMajor$PythonMinor"

function Test-IsAdmin {
  $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Relaunch-AsAdmin {
  param([string[]]$OriginalArgs)
  $psExe = (Get-Process -Id $PID).Path
  if (-not $psExe) { $psExe = "powershell.exe" }

  $scriptPath = $MyInvocation.MyCommand.Path
  if (-not $scriptPath) { throw "Caminho do script não encontrado para elevação." }

  $quotedScriptPath = '"' + ($scriptPath -replace '"', '""') + '"'
  $quotedArgs = @()
  foreach ($a in $OriginalArgs) {
    if ($null -eq $a) { continue }
    if ($a -match '[\s"]') {
      $quotedArgs += ('"' + ($a -replace '"', '""') + '"')
    } else {
      $quotedArgs += $a
    }
  }

  $argList = @(
    "-NoProfile"
    "-ExecutionPolicy", "Bypass"
    "-File", $quotedScriptPath
  ) + $quotedArgs

  Start-Process -FilePath $psExe -Verb RunAs -ArgumentList $argList | Out-Null
}

if (-not (Test-IsAdmin)) {
  Write-Host "[INFO] Reexecutando como Administrador..." -ForegroundColor Yellow
  Relaunch-AsAdmin -OriginalArgs $args
  exit 0
}

$InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-ProjectRoot {
  param([string]$StartDir)
  $dir = (Resolve-Path -LiteralPath $StartDir).Path
  while ($true) {
    $pp = Join-Path $dir "pyproject.toml"
    $req = Join-Path $dir "requirements.txt"
    if ((Test-Path -LiteralPath $pp -PathType Leaf) -and (Test-Path -LiteralPath $req -PathType Leaf)) {
      return $dir
    }
    $parent = Split-Path -Parent $dir
    if ($parent -eq $dir) { break }
    $dir = $parent
  }
  throw "Não consegui detectar a raiz do projeto (pyproject.toml/requirements.txt)."
}

$ProjectRoot = Find-ProjectRoot -StartDir $InstallDir
Set-Location $ProjectRoot

$LogDir = Join-Path $ProjectRoot "install_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("install_windows_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

Start-Transcript -Path $LogFile -Append | Out-Null

function Stop-WithError {
  param([string]$Message)
  Write-Host "[ERRO] $Message" -ForegroundColor Red
  try { Stop-Transcript | Out-Null } catch {}
  exit 1
}

function New-CommandSpec {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [string[]]$Args = @()
  )
  if ($null -eq $Args) { $Args = @() }
  return [PSCustomObject]@{
    Exe  = $Exe
    Args = $Args
  }
}

function Assert-File {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    Stop-WithError "Arquivo obrigatório não encontrado: $Path"
  }
}

Assert-File (Join-Path $ProjectRoot "requirements.txt")
Assert-File (Join-Path $ProjectRoot "pyproject.toml")

function Test-PythonCommandMinVersion {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [string[]]$ExeArgs = @()
  )
  try {
    $code = "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
    & $Exe @($ExeArgs) "-c" $code *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Get-PythonVersionString {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [string[]]$ExeArgs = @()
  )
  try {
    $out = & $Exe @($ExeArgs) "--version" 2>&1
    return ($out | Select-Object -First 1).ToString().Trim()
  } catch {
    return ""
  }
}

function Find-Python {
  $isWindowsAppsPython = {
    param([string]$Path)
    return ($Path -like "*\\WindowsApps\\python.exe") -or ($Path -like "*\\WindowsApps\\python3.exe")
  }

  function Resolve-CommandPath([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    foreach ($prop in @("Path", "Source", "Definition")) {
      if ($cmd.PSObject.Properties.Match($prop).Count -gt 0) {
        $val = $cmd.$prop
        if ($val) { return $val }
      }
    }
    return $cmd.Name
  }

  # 1) python / python3 no PATH
  foreach ($name in @("python", "python3")) {
    $path = Resolve-CommandPath $name
    if ($path -and -not (& $isWindowsAppsPython $path)) {
      if (Test-PythonCommandMinVersion -Exe $path) {
        return (New-CommandSpec -Exe $path)
      }
    }
  }

  # 2) py launcher (tenta versão alvo; se não, tenta -3)
  $pyPath = Resolve-CommandPath "py"
  if ($pyPath) {
    $targetArgs = @("-$PythonMajorMinor")
    if (Test-PythonCommandMinVersion -Exe $pyPath -ExeArgs $targetArgs) {
      return (New-CommandSpec -Exe $pyPath -Args $targetArgs)
    }
    $fallbackArgs = @("-3")
    if (Test-PythonCommandMinVersion -Exe $pyPath -ExeArgs $fallbackArgs) {
      return (New-CommandSpec -Exe $pyPath -Args $fallbackArgs)
    }
  }

  $pf = ${env:ProgramFiles}
  $pfX86 = ${env:ProgramFiles(x86)}
  $local = ${env:LocalAppData}

  $likely = @(
    (Join-Path $pf "$PythonFolder\\python.exe"),
    (Join-Path $pfX86 "$PythonFolder\\python.exe"),
    (Join-Path $local "Programs\\Python\\$PythonFolder\\python.exe")
  )
  foreach ($p in $likely) {
    if (Test-Path -LiteralPath $p -PathType Leaf) {
      if (Test-PythonCommandMinVersion -Exe $p) { return (New-CommandSpec -Exe $p) }
    }
  }

  return $null
}

function Install-Python {
  $installerName = "python-$PythonVersion-amd64.exe"
  $url = "https://www.python.org/ftp/python/$PythonVersion/$installerName"
  $tmp = Join-Path $env:TEMP $installerName

  Write-Host "[STEP] Baixando Python $PythonVersion..." -ForegroundColor Cyan
  Write-Host "[INFO] URL: $url"

  try {
    try {
      [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    } catch {}
    Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
  } catch {
    Stop-WithError "Falha ao baixar o instalador do Python. Verifique internet/firewall e tente novamente."
  }

  if (-not (Test-Path -LiteralPath $tmp -PathType Leaf)) {
    Stop-WithError "Download do Python falhou (arquivo não encontrado)."
  }

  Write-Host "[STEP] Instalando Python (silencioso, AllUsers + PATH)..." -ForegroundColor Cyan
  $args = @(
    "/quiet",
    "InstallAllUsers=1",
    "PrependPath=1",
    "Include_pip=1",
    "Include_test=0",
    "Shortcuts=0",
    "CompileAll=1"
  )
  $proc = Start-Process -FilePath $tmp -ArgumentList $args -Wait -PassThru
  if ($proc.ExitCode -ne 0) {
    Stop-WithError "Instalador do Python retornou erro (ExitCode=$($proc.ExitCode))."
  }
}

Write-Host "[INFO] OracleWalk - Instalador (Windows)" -ForegroundColor Green
Write-Host "[INFO] Pasta do projeto: $ProjectRoot"
Write-Host "[INFO] Log: $LogFile"

Write-Host "[STEP] Verificando Python existente..." -ForegroundColor Cyan
$pythonCmd = Find-Python
if (-not $pythonCmd) {
  Write-Host "[INFO] Python não encontrado (>= 3.10). Será instalado: Python $PythonVersion" -ForegroundColor Yellow
  Install-Python
  $pythonCmd = Find-Python
}
if (-not $pythonCmd) {
  Stop-WithError "Python não encontrado após tentativa de instalação."
}

$pyVer = Get-PythonVersionString -Exe $pythonCmd.Exe -ExeArgs $pythonCmd.Args
if ($pyVer) {
  Write-Host "[OK] Python selecionado: $pyVer ($($pythonCmd.Exe) $($pythonCmd.Args -join ' '))" -ForegroundColor Green
}

Write-Host "[STEP] Preparando venv: $VenvDir" -ForegroundColor Cyan
& $pythonCmd.Exe @($pythonCmd.Args) -m venv $VenvDir

$venvPython = Join-Path $ProjectRoot "$VenvDir\\Scripts\\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
  Stop-WithError "Python da venv não encontrado: $venvPython"
}

Write-Host "[STEP] Atualizando pip..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip

Write-Host "[STEP] Instalando dependências (requirements.txt)..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

Write-Host "[STEP] Instalando pacote (pip install -e .)..." -ForegroundColor Cyan
& $venvPython -m pip install -e $ProjectRoot

Write-Host "[STEP] Configurando config.txt (se necessário)..." -ForegroundColor Cyan
$configPath = Join-Path $ProjectRoot "config.txt"
$examplePath = Join-Path $ProjectRoot "config.example.txt"
$envPath = Join-Path $ProjectRoot ".env"
if ((Test-Path -LiteralPath $configPath -PathType Leaf) -or (Test-Path -LiteralPath $envPath -PathType Leaf)) {
  Write-Host "[OK] Mantendo config existente (.env/config.txt já presentes)."
} elseif (Test-Path -LiteralPath $examplePath -PathType Leaf) {
  Copy-Item -LiteralPath $examplePath -Destination $configPath -Force
  $lines = Get-Content -LiteralPath $configPath
  $lines = $lines -replace '^mode=.*', 'mode=backtest'
  if ($lines -notmatch '^dry_run=') { $lines += 'dry_run=true' }
  $lines | Set-Content -LiteralPath $configPath -Encoding UTF8
  Write-Host "[OK] Criado: $configPath (edite para live/keys)."
} else {
  Write-Host "[INFO] Nenhum config criado automaticamente (config.example.txt ausente)."
}

Write-Host "[STEP] Sanity-check (import/CLI)..." -ForegroundColor Cyan
& $venvPython -m oraclewalk.backtest --help | Out-Null

Write-Host ""
Write-Host "[OK] ✅ Instalação concluída." -ForegroundColor Green
Write-Host "[INFO] Para rodar agora: .\\installers\\run_oraclewalk.bat"
Write-Host "[INFO] Para modo live: edite $configPath (BINANCE/TELEGRAM) e coloque mode=live."

Stop-Transcript | Out-Null

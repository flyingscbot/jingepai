# 金格Pi × 自建 Matrix（Synapse）快速配置脚本
# 适用于：Windows PowerShell（Docker Desktop）
#
# 用法示例：
#   .\setup.ps1
#   .\setup.ps1 -Port 1000
#   .\setup.ps1 -Issuer "http://host.docker.internal:1000/"
#   $env:OIDC_ISSUER="http://host.docker.internal:1000/"; .\setup.ps1
#
# 前置：已安装 Docker Desktop，并先启动金格 Flask（默认端口 1000）

[CmdletBinding()]
param(
    [string]$Issuer = "",
    [string]$Port = "",
    [switch]$Help
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$SynapseImage = "docker.io/matrixdotorg/synapse:latest"
$PostgresImage = "docker.io/postgres:16-alpine"
# 优先国内/加速镜像（官方 Docker Hub 在国内常超时，默认跳过）
$SynapseMirrors = @(
    "hub.rat.dev/matrixdotorg/synapse:latest",
    "docker.1ms.run/matrixdotorg/synapse:latest",
    "docker.m.daocloud.io/docker.io/matrixdotorg/synapse:latest"
)
$PostgresMirrors = @(
    "hub.rat.dev/library/postgres:16-alpine",
    "docker.1ms.run/library/postgres:16-alpine",
    "docker.m.daocloud.io/docker.io/library/postgres:16-alpine"
)
$SkipOfficial = $true
if ($env:DOCKER_TRY_OFFICIAL -eq "1") { $SkipOfficial = $false }

$ServerName = "matrix.localhost"
$SigningKey = Join-Path $ScriptDir "data\$ServerName.signing.key"
$DefaultPort = "1000"

function Show-Usage {
    @"
用法: .\setup.ps1 [-Issuer URL] [-Port PORT] [-Help]

  -Issuer URL   覆盖 homeserver.yaml 中的 OIDC issuer
                （默认 http://host.docker.internal:1000/）
  -Port PORT    按端口生成 issuer：http://host.docker.internal:PORT/
                （也可用环境变量 JINGEPI_PORT / FLASK_PORT）
  -Help         显示帮助

环境变量（可选）：
  OIDC_ISSUER    同 -Issuer
  JINGEPI_PORT / FLASK_PORT  同 -Port
"@
}

function Write-Log([string]$Message) {
    Write-Host "[setup] $Message"
}

function Die([string]$Message) {
    Write-Host "[setup] 错误: $Message" -ForegroundColor Red
    exit 1
}

if ($Help) {
    Show-Usage
    exit 0
}

# 解析最终 issuer：参数 > 环境变量 > 默认
if (-not $Issuer -and $env:OIDC_ISSUER) {
    $Issuer = $env:OIDC_ISSUER
}
if (-not $Port) {
    if ($env:JINGEPI_PORT) { $Port = $env:JINGEPI_PORT }
    elseif ($env:FLASK_PORT) { $Port = $env:FLASK_PORT }
}
if (-not $Issuer -and $Port) {
    $Issuer = "http://host.docker.internal:${Port}/"
}
if ($Issuer) {
    $Issuer = $Issuer.TrimEnd("/") + "/"
}

# ---------- 1. 检查 Docker / Compose ----------
function Test-DockerReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Die "未找到 docker，请先安装 Docker Desktop"
    }
    try {
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "docker info failed" }
    } catch {
        Die "Docker 守护进程未运行，请先启动 Docker Desktop"
    }

    $script:UseComposeV2 = $false
    docker compose version 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $script:UseComposeV2 = $true
    } elseif (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $script:UseComposeV2 = $false
    } else {
        Die "未找到 docker compose / docker-compose"
    }
    Write-Log "Docker 与 Compose 可用"
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArgs)
    if ($script:UseComposeV2) {
        & docker compose @ComposeArgs
    } else {
        & docker-compose @ComposeArgs
    }
    if ($LASTEXITCODE -ne 0) {
        Die ("docker compose 失败（退出码 " + $LASTEXITCODE + "）")
    }
}

# ---------- 2. 创建 data ----------
function Ensure-DataDir {
    $dataDir = Join-Path $ScriptDir "data"
    if (-not (Test-Path $dataDir)) {
        New-Item -ItemType Directory -Path $dataDir | Out-Null
    }
    Write-Log "已确保目录存在: matrix/data"
}

# ---------- 3. 生成签名密钥等 ----------
function Needs-Generate {
    return -not (Test-Path $SigningKey)
}

function Invoke-SynapseGenerate {
    Write-Log "缺少签名密钥，执行 synapse generate ..."
    $dataDir = Join-Path $ScriptDir "data"
    $vol = "${dataDir}:/data"

    $img = $SynapseImage
    docker image inspect $SynapseImage 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        docker image inspect "matrixdotorg/synapse:latest" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $img = "matrixdotorg/synapse:latest"
        }
    }

    & docker run --rm `
        -v $vol `
        -e "SYNAPSE_SERVER_NAME=$ServerName" `
        -e "SYNAPSE_REPORT_STATS=no" `
        $img generate
    if ($LASTEXITCODE -ne 0) {
        Die "synapse generate 失败"
    }
    if (-not (Test-Path $SigningKey)) {
        Die ("generate 后仍未找到 " + $SigningKey)
    }
    Write-Log ("签名密钥已生成: " + $SigningKey)
}

# ---------- 4. 拉取镜像（官方失败则镜像 + tag） ----------
function Pull-OrMirror {
    param(
        [string]$Official,
        [string[]]$Mirrors
    )
    $shortName = $Official -replace '^docker\.io/', ''

    if (-not $SkipOfficial) {
        Write-Log ("拉取镜像: " + $Official)
        docker pull $Official 2>$null
        if ($LASTEXITCODE -eq 0) {
            docker tag $Official $shortName 2>$null | Out-Null
            return $true
        }
        Write-Log "官方拉取失败，尝试镜像 ..."
    } else {
        Write-Log "跳过官方源，直接使用加速镜像 ..."
    }

    foreach ($m in $Mirrors) {
        Write-Log ("尝试: " + $m)
        docker pull $m
        if ($LASTEXITCODE -eq 0) {
            docker tag $m $Official
            docker tag $m $shortName 2>$null | Out-Null
            Write-Log ("已拉取并 tag 为 " + $Official)
            return $true
        }
    }
    return $false
}

function Pull-Images {
    if (-not (Pull-OrMirror -Official $SynapseImage -Mirrors $SynapseMirrors)) {
        Die "无法拉取 Synapse 镜像（官方与镜像均失败）"
    }
    if (-not (Pull-OrMirror -Official $PostgresImage -Mirrors $PostgresMirrors)) {
        Die "无法拉取 Postgres 镜像（官方与镜像均失败）"
    }
    Write-Log "镜像就绪"
}

# ---------- 更新 homeserver.yaml issuer ----------
function Update-Issuer {
    param([string]$Target)
    $hs = Join-Path $ScriptDir "homeserver.yaml"
    if (-not (Test-Path $hs)) {
        Die "未找到 homeserver.yaml"
    }
    $content = Get-Content -Path $hs -Raw -Encoding UTF8
    $pattern = '(?m)^(\s*issuer:\s*")[^"]*(")'
    if ($content -notmatch $pattern) {
        Die "homeserver.yaml 中未找到 issuer 字段"
    }
    $updated = [regex]::Replace($content, $pattern, ('${1}' + $Target + '${2}'))
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($hs, $updated, $utf8NoBom)
    Write-Log ("已更新 homeserver.yaml issuer -> " + $Target)
}

# ---------- 5. compose up ----------
function Start-Compose {
    Write-Log "启动 docker compose ..."
    Invoke-Compose up -d
    Write-Log "容器已后台启动"
}

# ---------- 6. 打印说明 ----------
function Show-Summary {
    $showIssuer = $Issuer
    if (-not $showIssuer) {
        $hs = Join-Path $ScriptDir "homeserver.yaml"
        $line = Select-String -Path $hs -Pattern 'issuer:\s*"([^"]+)"' | Select-Object -First 1
        if ($line) { $showIssuer = $line.Matches[0].Groups[1].Value }
    }
    $portHint = if ($Port) { $Port } else { $DefaultPort }
    Write-Host ""
    Write-Host "========================================"
    Write-Host "  Matrix (Synapse) 已启动"
    Write-Host "========================================"
    Write-Host "  Synapse 地址:  http://localhost:8008"
    Write-Host ""
    Write-Host ("  OIDC Issuer:   " + $showIssuer)
    Write-Host "  （请先启动金格 Flask，Issuer 需与 OIDC_ISSUER 一致；"
    Write-Host "   容器访问宿主机用 host.docker.internal，金格本机可用"
    Write-Host ("   http://127.0.0.1:" + $portHint + " ）")
    Write-Host ""
    Write-Host "  客户端默认：jingepi-synapse / change-me-synapse-oidc-secret"
    Write-Host ""
    Write-Host "  Element 登录简要步骤："
    Write-Host "  1. 打开 https://app.element.io （或自建 Element）"
    Write-Host "  2. Homeserver 填写：http://localhost:8008"
    Write-Host "  3. 选择「金格Pi」OIDC 登录"
    Write-Host "  4. 在金格授权页输入实训账号完成登录"
    Write-Host "========================================"
}

# ---------- main ----------
Test-DockerReady
Ensure-DataDir

if ($Issuer) {
    Update-Issuer -Target $Issuer
}

Pull-Images

if (Needs-Generate) {
    Invoke-SynapseGenerate
} else {
    Write-Log "已存在签名密钥，跳过 generate"
}

Start-Compose
Show-Summary
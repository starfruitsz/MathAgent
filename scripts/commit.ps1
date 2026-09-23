# 一键提交并推送
# 用法：
#   .\scripts\commit.ps1 -Scope q2 -Type model -Message "加入 Q=1 退化约束的广义标度律"
#   .\scripts\commit.ps1 -Message "更新操作规范"
#
# 铁律 R1：每次更改代码必须提交仓库。本脚本是标准提交入口。

param(
    [Parameter(Mandatory = $true)][string]$Message,
    [string]$Scope = "",
    [ValidateSet("feat", "fix", "data", "model", "exp", "doc", "repo", "chore")]
    [string]$Type = "chore",
    [string]$Branch = "main"
)

$ErrorActionPreference = 'Stop'

# ---- 0. 必须在仓库根目录 ----
$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) { throw "当前目录不在 git 仓库内" }
Set-Location $repoRoot
Write-Host "仓库根目录: $repoRoot" -ForegroundColor Cyan

# ---- 1. 组装提交信息 ----
$prefix = if ($Scope) { "$Type($Scope)" } else { $Type }
$fullMessage = "$prefix`: $Message"

# ---- 2. 暂存全部改动 ----
git add -A

# ---- 3. 无改动则跳过 ----
$pending = git status --porcelain
if (-not $pending) {
    Write-Host "工作区无改动，跳过提交。" -ForegroundColor Yellow
    exit 0
}
Write-Host "待提交文件：" -ForegroundColor Cyan
$pending | ForEach-Object { Write-Host "  $_" }

# ---- 4. 提交 ----
git commit -m $fullMessage
if ($LASTEXITCODE -ne 0) { throw "git commit 失败" }

# ---- 5. 推送 ----
git push origin $Branch
if ($LASTEXITCODE -ne 0) { throw "git push 失败：请检查网络与凭据（git ls-remote 可先自测）" }

# ---- 6. 收工自检（必须全部为空）----
$dirty = git status --porcelain
$unpushed = git log "origin/$Branch..HEAD" --oneline
if ($dirty) { throw "自检失败：工作区仍有未提交改动" }
if ($unpushed) { throw "自检失败：仍有未推送提交" }

Write-Host ""
Write-Host "已提交并推送：$fullMessage" -ForegroundColor Green
git log --oneline -1

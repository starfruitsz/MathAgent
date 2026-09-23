# 端到端复现脚本
# 用法： .\scripts\run_all.ps1
#
# 注意：P0 数据发现需要 data/raw/ 中已有官方附件，否则会在第一步失败。
#       这是预期行为 —— 数据未到位时不应继续。

$ErrorActionPreference = 'Stop'
$repoRoot = git rev-parse --show-toplevel
Set-Location $repoRoot
Write-Host "仓库根目录: $repoRoot" -ForegroundColor Cyan

# ---- 1. 前置检查 ----
if (-not (Test-Path "data\raw\real_attachments")) {
    Write-Host ""
    Write-Host "阻塞：data\raw\real_attachments 不存在。" -ForegroundColor Red
    Write-Host "请先下载竞赛官方附件到 data\raw\ 后再运行本脚本。" -ForegroundColor Red
    Write-Host "详见 docs/PROGRESS.md 的『阻塞项』。" -ForegroundColor Red
    exit 1
}

# ---- 2. 环境自检 ----
Write-Host "`n[1/7] 环境自检 ..." -ForegroundColor Cyan
python scripts\check_env.py

# ---- 3. 数据发现（P0，阻塞性前置）----
Write-Host "`n[2/7] 数据发现 ..." -ForegroundColor Cyan
python -m src.q0_data.discover

# ---- 4. 四问 ----
Write-Host "`n[3/7] Q1 质量评价与配比建模 ..." -ForegroundColor Cyan
python -m src.q1_quality_mixture.run_q1

Write-Host "`n[4/7] Q2 广义标度律 ..." -ForegroundColor Cyan
python -m src.q2_scaling_law.run_q2

Write-Host "`n[5/7] Q3 算力约束优化 ..." -ForegroundColor Cyan
python -m src.q3_optimization.run_q3

Write-Host "`n[6/7] Q4 前沿预测 ..." -ForegroundColor Cyan
python -m src.q4_frontier.run_q4

# ---- 5. 出图 ----
Write-Host "`n[7/7] 生成论文图表 ..." -ForegroundColor Cyan
python -m src.report.make_figures

# ---- 6. 测试 ----
Write-Host "`n运行测试 ..." -ForegroundColor Cyan
python -m pytest tests\ -v

Write-Host "`n全流程完成。请更新 docs/PROGRESS.md 并提交：" -ForegroundColor Green
Write-Host "  .\scripts\commit.ps1 -Scope repo -Type exp -Message '端到端复现通过'" -ForegroundColor Green

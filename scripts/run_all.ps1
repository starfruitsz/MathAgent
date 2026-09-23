# 端到端复现脚本 —— D 题
# 用法： .\scripts\run_all.ps1
#
# 注意：P0 数据发现需要 data/raw/ 中已有官方附件，否则会在第一步失败。
#       这是预期行为 —— 数据未到位时不应继续。

$ErrorActionPreference = 'Stop'
$repoRoot = git rev-parse --show-toplevel
Set-Location $repoRoot
Write-Host "仓库根目录: $repoRoot" -ForegroundColor Cyan

# ---- 1. 前置检查 ----
$need = @(
  "data\raw\无人机应急物资运输基础数据\调度中心与服务区.xlsx",
  "data\raw\无人机应急物资运输基础数据\物资需求与配送时限.xlsx",
  "data\raw\无人机应急物资运输基础数据\运输无人机数据.xlsx",
  "data\raw\无人机应急物资运输基础数据\中继无人机数据.xlsx",
  "data\raw\无人机应急物资运输基础数据\通信链路参数.xlsx"
)
$hasDem = (Get-ChildItem -Path "data\raw" -Recurse -Include *.tif,*.tiff,*.vrt,*.img,*.hgt -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0

$missing = @()
foreach ($f in $need) { if (-not (Test-Path $f)) { $missing += $f } }
if (-not $hasDem) { $missing += "30 m DEM（*.tif / *.tiff / *.vrt）" }

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "阻塞：缺少以下附件，无法开始 ——" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "请先下载竞赛官方附件到 data\raw\ 后再运行本脚本。" -ForegroundColor Red
    Write-Host "详见 docs/PROGRESS.md 的『阻塞项』。" -ForegroundColor Red
    exit 1
}

# ---- 2. 环境自检 ----
Write-Host "`n[1/9] 环境自检 ..." -ForegroundColor Cyan
python scripts\check_env.py

# ---- 3. P0：数据发现与建模接口 ----
Write-Host "`n[2/9] 数据发现 ..." -ForegroundColor Cyan
python -m src.q0_data.discover

Write-Host "`n[3/9] 构建建模接口（data/processed/）..." -ForegroundColor Cyan
python -m src.q0_data.build_processed

Write-Host "`n[4/9] 航段预计算（leg_cache）..." -ForegroundColor Cyan
python -m src.physics.precompute

# ---- 4. 四问 ----
Write-Host "`n[5/9] Q1 最大安全载荷与货箱组批 ..." -ForegroundColor Cyan
python -m src.q1_payload_grouping.run_q1

Write-Host "`n[6/9] Q2 异构无人机多点多架次调度 ..." -ForegroundColor Cyan
python -m src.q2_transport_schedule.run_q2

Write-Host "`n[7/9] Q3 通信约束下的运输与中继联合调度 ..." -ForegroundColor Cyan
python -m src.q3_comms_relay.run_q3

Write-Host "`n[8/9] Q4 任务分区与资源配置 ..." -ForegroundColor Cyan
python -m src.q4_partitioning.run_q4

# ---- 5. 出图与测试 ----
Write-Host "`n[9/9] 生成论文图表 ..." -ForegroundColor Cyan
python -m src.report.make_figures

Write-Host "`n运行测试 ..." -ForegroundColor Cyan
python -m pytest tests\ -v

Write-Host "`n全流程完成。请更新 docs/PROGRESS.md 并提交：" -ForegroundColor Green
Write-Host "  .\scripts\commit.ps1 -Scope repo -Type exp -Message '端到端复现通过'" -ForegroundColor Green

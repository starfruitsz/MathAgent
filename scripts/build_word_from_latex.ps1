# 用 LaTeX 源重新生成"公式版" Word 与 PDF
#
# 背景：本仓 `paper/*.docx` 是 Python 管线装配的（公式经自研 LaTeX→OMML 转换，
#       106 个公式）。而 `otheragent/document.pdf` 由 XeLaTeX 排版，公式是
#       **真 LaTeX 渲染**，是公式质量的基准。本脚本用 pandoc 把同一份 LaTeX 源
#       直接转成 Word —— pandoc 会把 **所有** 数学（行内 + 行间）转成
#       **Word 原生 OMML 公式对象**，数量与可编辑性都优于手写转换。
#
# 用法（在仓库根目录）：
#     pwsh -File scripts\build_word_from_latex.ps1
#
# 产物：
#     paper/山区洪涝灾害下无人机运输与通信协同优化_论文_LaTeX公式版.docx
#     paper/山区洪涝灾害下无人机运输与通信协同优化_论文_LaTeX公式版.pdf
#
# 依赖：pandoc（winget install JohnMacFarlane.Pandoc）、Word（导出 PDF）

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# ---- 定位 pandoc ----
$pd = (Get-Command pandoc -ErrorAction SilentlyContinue).Source
if (-not $pd) {
    foreach ($c in @("$env:LOCALAPPDATA\Pandoc\pandoc.exe",
                     "$env:ProgramFiles\Pandoc\pandoc.exe")) {
        if (Test-Path $c) { $pd = $c; break }
    }
}
if (-not $pd) { Write-Host '[错误] 未找到 pandoc，请先 winget install JohnMacFarlane.Pandoc'; exit 1 }
Write-Host "pandoc: $pd"

$Src     = Join-Path $Root 'otheragent\document.tex'
$Tmp     = Join-Path $Root 'otheragent\_pandoc'
$RefDocx = Join-Path $Root 'paper\山区洪涝灾害下无人机运输与通信协同优化_论文.docx'
$OutDocx = Join-Path $Root 'paper\山区洪涝灾害下无人机运输与通信协同优化_论文_LaTeX公式版.docx'
$OutPdf  = Join-Path $Root 'paper\山区洪涝灾害下无人机运输与通信协同优化_论文_LaTeX公式版.pdf'
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

# ---- 1) LaTeX → docx ----
# ★ 必须在 otheragent/ 目录下运行：pandoc 解析 `\input{texfile/...}` 是**相对工作目录**
#   的，从仓库根目录跑会静默丢掉全部 10 个 \input 章节（只转出封面 2 页），
#   `--resource-path` 并不能替代 cwd。
# --reference-doc 借用本仓论文的样式（宋体正文 / 黑体标题 / A4），
# 使产出的 Word 与本队提交稿排版一致；不指定则用 pandoc 默认样式。
$args = @('document.tex', '-o', $OutDocx, '--toc', '--toc-depth=2')
if (Test-Path $RefDocx) { $args += "--reference-doc=$RefDocx"; Write-Host '使用本仓论文作为样式参考' }
Write-Host '[1/2] pandoc 转换中（554 个公式 → Word 原生 OMML）...'
Push-Location (Join-Path $Root 'otheragent')
& $pd @args 2>&1 | Select-Object -First 20
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0 -or -not (Test-Path $OutDocx)) { Write-Host '[错误] pandoc 转换失败'; exit 1 }
Write-Host ("      已生成 {0} ({1:N2} MB)" -f (Split-Path $OutDocx -Leaf), ((Get-Item $OutDocx).Length / 1MB))

# ---- 2) docx → PDF（Word COM）----
Write-Host '[2/2] Word 导出 PDF ...'
$env:OUT_DOCX = $OutDocx
$env:OUT_PDF = $OutPdf
python -u scripts\diag\check_pandoc_docx.py $OutDocx $OutPdf 2>&1 |
    Where-Object { $_ -notmatch '^\s*$' } | Select-Object -Last 12
Write-Host "`n产物："
Write-Host "  $OutDocx"
Write-Host "  $OutPdf"

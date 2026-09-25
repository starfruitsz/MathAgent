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
#
# ★ 三处必须处理的 pandoc 副作用（否则交付稿会出现 □ 与版式问题）：
#   1. `\quad`/`\qquad`/`\,` → U+2001/U+2005/U+2009，正文单位空格 → U+2006，
#      超链接前不换行空格 → U+00A0，并残留 U+200B。Word 的数学字体**没有这些
#      字形的可见形式** ⇒ 渲染成 □（`\qquad` 会连出□□，`\sum_{k\ge m}` 的空
#      上标会多一个孤立 □）。PDF 侧看不出是因为 XeLaTeX 用的是另一套字体。
#      → 第 2 步 `scripts\fix_latex_omml.py` 把它们规范化为普通空格。
#   2. pandoc 不做任何竞赛排版控制（无章页分页、无三线表、图表与题注可能分页）
#      → 第 3 步 `scripts\format_latex_paper.py` 补齐（与 otheragent 版式对齐）。
#   3. 过长的行间公式在 Word 里会被折行成"文本框+下拉箭头"观感
#      → 需在**源文件**里改用 aligned/split 环境拆分（本脚本不自动改源码）。

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

# ---- 2) 清理 OMML 里 Word 渲染不出的空白字符（□ 的根因）----
#   pandoc 把 \quad/\qquad/\, 转成 U+2001/U+2005/U+2009，正文里的单位空格转成
#   U+2006、超链接前的不换行空格转成 U+00A0，并残留 U+200B。
#   Word 的数学字体没有这些字形 ⇒ 渲染成 □（\qquad 会连出□□）。
#   本步骤把它们规范化为普通空格（视觉与语义不变，仅去掉不换行语义）。
Write-Host '[2/3] 清理 OMML 中不可渲染的空白字符 ...'
python -u scripts\fix_latex_omml.py $OutDocx 2>&1 |
    Where-Object { $_ -notmatch '^\s*$' } | Select-Object -Last 14

# ---- 3) 标准格式改造（章页分页 / 三线表 / 图表与题注同页 / 题注编号）----
#   pandoc 不做任何竞赛排版控制，必须补上，否则与 otheragent/document.pdf 版式不一致。
Write-Host '[3/3] 套用标准格式（三线表 / 章页分页 / 图表与题注同页）...'
python -u scripts\format_latex_paper.py --docx $OutDocx 2>&1 |
    Where-Object { $_ -notmatch '^\s*$' } | Select-Object -Last 18

# ---- 4) docx → PDF（Word COM）----
Write-Host '[4/4] Word 导出 PDF ...'
$env:OUT_DOCX = $OutDocx
$env:OUT_PDF = $OutPdf
python -u scripts\diag\check_pandoc_docx.py $OutDocx $OutPdf 2>&1 |
    Where-Object { $_ -notmatch '^\s*$' } | Select-Object -Last 12
Write-Host "`n产物："
Write-Host "  $OutDocx"
Write-Host "  $OutPdf"

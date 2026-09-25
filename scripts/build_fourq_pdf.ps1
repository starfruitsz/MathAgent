# 编译四问独立论文（paper_4q）
#
# 版式基准：otheragent/document.pdf（同一 cumcmthesis 类）
# 用法（仓库根目录）：pwsh -File scripts\build_fourq_pdf.ps1
#
# 与 build_otheragent_pdf.ps1 相同的三个坑：
#   坑1 bibtex.exe 在本机启动即崩（0xC0000374 堆损坏），必须用 bibtexu.exe；
#       且该引擎退出码不可靠，判据取 document.bbl > 1000 字节。
#   坑2 圈码 ①②③ 需声明为 CJK 字符类（已在 document.tex 前言处理）。
#   坑3 中文引号须为全角，TeX 十六进制前缀 "2460 不可当引号替换。

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$Dir  = Join-Path $Root 'paper_4q'

if (-not (Test-Path $Dir)) { Write-Host "[错误] 未找到 $Dir"; exit 1 }
Set-Location $Dir
Write-Host "工作目录: $Dir" -ForegroundColor Cyan

function Run-Pass([string]$label, [string[]]$cmd) {
    $t0 = Get-Date
    & $cmd[0] @($cmd[1..($cmd.Length - 1)]) 2>&1 | Out-Null
    $rc = $LASTEXITCODE
    $sec = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    Write-Host ("=== {0} ===  退出码 {1}，用时 {2} s" -f $label, $rc, $sec)
    return $rc
}

Write-Host "=== 1/4 XeLaTeX 第一遍 ==="
Run-Pass "xelatex #1" @('xelatex', '-interaction=nonstopmode', '-halt-on-error', 'document.tex') | Out-Null

Write-Host "=== 2/4 BibTeX（bibtexu.exe 优先）==="
$bbl = Join-Path $Dir 'document.bbl'
if (Test-Path $bbl) { Remove-Item $bbl -Force }
foreach ($eng in @('bibtexu', 'bibtex8', 'bibtex')) {
    $exe = (Get-Command $eng -ErrorAction SilentlyContinue).Source
    if (-not $exe) { continue }
    & $exe 'document' 2>&1 | Out-Null
    $sz = if (Test-Path $bbl) { (Get-Item $bbl).Length } else { 0 }
    Write-Host ("  {0}: bbl = {1} 字节" -f $eng, $sz)
    if ($sz -gt 1000) { Write-Host "  ✅ 采用 $eng"; break }
}

Write-Host "=== 3/4 XeLaTeX 第二遍 ==="
Run-Pass "xelatex #2" @('xelatex', '-interaction=nonstopmode', 'document.tex') | Out-Null

Write-Host "=== 4/4 XeLaTeX 第三遍 ==="
Run-Pass "xelatex #3" @('xelatex', '-interaction=nonstopmode', 'document.tex') | Out-Null

Write-Host "`n===== 编译结果自检 ====="
$log = Join-Path $Dir 'document.log'
if (Test-Path $log) {
    $txt = Get-Content $log -Raw -Encoding UTF8
    $pages = ([regex]::Match($txt, 'Output written on document\.pdf \((\d+) pages')).Groups[1].Value
    if (-not $pages) { $pages = '?' }
    $err = [regex]::Matches($txt, '^! ', 'Multiline').Count
    $undef = [regex]::Matches($txt, 'Citation .* undefined').Count
    Write-Host ("  页数: {0}" -f $pages)
    Write-Host ("  错误(!): {0}" -f $err)
    Write-Host ("  未定义引用: {0}" -f $undef)
    if ($err -eq 0 -and $undef -eq 0) { Write-Host "  [OK] 无 LaTeX 报错、引用全部解析" -ForegroundColor Green }
    else { Write-Host "  [警告] 存在报错或未定义引用" -ForegroundColor Yellow }
}
$pdf = Join-Path $Dir 'document.pdf'
if (Test-Path $pdf) {
    Write-Host ("输出：{0}  ({1:N2} MB)" -f $pdf, ((Get-Item $pdf).Length / 1MB))
} else {
    Write-Host "[错误] 未生成 document.pdf" -ForegroundColor Red
    exit 1
}

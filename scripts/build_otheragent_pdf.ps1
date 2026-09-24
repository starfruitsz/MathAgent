# 编译 otheragent LaTeX 论文（XeLaTeX + BibTeX，三遍）
# 与 otheragent/build.cmd 等价，但去掉 pause，便于在 agent 中非交互运行。
$ErrorActionPreference = 'Continue'
$mk = "$env:LOCALAPPDATA\Programs\MiKTeX\miktex\bin\x64"
$env:PATH = "$mk;$env:PATH"

$dir = Join-Path $PSScriptRoot '..\otheragent'
$dir = (Resolve-Path $dir).Path
Set-Location $dir
Write-Host "工作目录: $dir"

function Run-Latex([string]$label, [string]$exe, [string[]]$argv) {
    Write-Host "=== $label ==="
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $exe @argv 2>&1 | Out-Null
    Write-Host ("  退出码 {0}，用时 {1:N1} s" -f $LASTEXITCODE, $sw.Elapsed.TotalSeconds)
}

# 第一遍：会把缺的宏包按需下载（首次可能很慢）
Run-Latex '1/4 XeLaTeX 第一遍' "$mk\xelatex.exe" @('-interaction=nonstopmode', 'document.tex')

# ---- BibTeX ----------------------------------------------------------------
# ★ 本机 MiKTeX 25.12 的 bibtex.exe / miktex-bibtex.exe 启动即崩
#   （退出码 -1073740940 = 0xC0000374 STATUS_HEAP_CORRUPTION），
#   一行都不写就退出，document.bbl 为 0 字节。
#   同发行版自带的 bibtex8 / bibtexu 工作正常，故按 bibtexu → bibtex8 → bibtex
#   的顺序回退。bibtexu 是 Unicode 感知的，处理中文条目优于 bibtex8。
#   判据：.bbl 生成且 > 1000 字节即视为成功（退出码不可靠）。
$bbl = Join-Path $dir 'document.bbl'
$bibOk = $false
foreach ($eng in 'bibtexu.exe', 'bibtex8.exe', 'bibtex.exe') {
    Remove-Item $bbl -Force -ErrorAction SilentlyContinue
    Write-Host "=== 2/4 BibTeX（$eng）==="
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & "$mk\$eng" document 2>&1 | Out-Null
    $size = if (Test-Path $bbl) { (Get-Item $bbl).Length } else { 0 }
    Write-Host ("  退出码 {0}，bbl = {1} 字节，用时 {2:N1} s" -f `
        $LASTEXITCODE, $size, $sw.Elapsed.TotalSeconds)
    if ($size -gt 1000) { $bibOk = $true; Write-Host "  ✅ 采用 $eng"; break }
    Write-Host "  ✗ $eng 未产出有效 .bbl，换下一个引擎"
}
if (-not $bibOk) { Write-Host '  [警告] 所有 BibTeX 引擎均失败，参考文献将显示为 [?]' }

Run-Latex '3/4 XeLaTeX 第二遍' "$mk\xelatex.exe" @('-interaction=nonstopmode', 'document.tex')
Run-Latex '4/4 XeLaTeX 第三遍' "$mk\xelatex.exe" @('-interaction=nonstopmode', 'document.tex')

Write-Host "`n===== 编译结果自检 ====="
$log = Join-Path $dir 'document.log'
if (Test-Path $log) {
    Get-Content $log -Encoding utf8 | Select-String -Pattern 'Output written' | ForEach-Object { $_.Line }
    $errs = Get-Content $log -Encoding utf8 | Select-String -Pattern '^!' | Select-Object -First 20
    if ($errs) { Write-Host '[警告] 存在 LaTeX 报错：'; $errs | ForEach-Object { '  ' + $_.Line } }
    else { Write-Host '[OK] 无 LaTeX 报错' }
    $undef = Get-Content $log -Encoding utf8 | Select-String -Pattern 'undefined' | Select-Object -First 10
    if ($undef) { Write-Host '[警告] 存在未定义引用：'; $undef | ForEach-Object { '  ' + $_.Line } }
    else { Write-Host '[OK] 无未定义引用' }
} else { Write-Host '[警告] 未生成 document.log' }

$pdf = Join-Path $dir 'document.pdf'
if (Test-Path $pdf) {
    $f = Get-Item $pdf
    Write-Host ("`n输出：{0}  ({1:N2} MB, {2})" -f $f.FullName, ($f.Length / 1MB), $f.LastWriteTime)
} else { Write-Host '`n[错误] 未生成 document.pdf' }

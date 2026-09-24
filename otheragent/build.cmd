@echo off
REM ============================================================
REM  一键编译论文（XeLaTeX + BibTeX，三遍编译）
REM  用法：双击本文件，或在命令行执行  build.cmd
REM
REM  依赖：XeLaTeX（MiKTeX / TeX Live 均可）+ bibtex8 或 bibtex
REM ============================================================
setlocal
cd /d "%~dp0"

REM 定位 xelatex：优先用 PATH 上的，其次试常见安装位置
where xelatex >nul 2>&1
if errorlevel 1 (
  for %%D in (
    "%LOCALAPPDATA%\Programs\MiKTeX\miktex\bin\x64"
    "%ProgramFiles%\MiKTeX\miktex\bin\x64"
    "%ProgramFiles(x86)%\MiKTeX\miktex\bin"
    "C:\texlive\2024\bin\windows"
    "C:\texlive\2023\bin\windows"
  ) do (
    if exist "%%~D\xelatex.exe" set "PATH=%%~D;%PATH%"
  )
)
where xelatex >nul 2>&1
if errorlevel 1 (
  echo [错误] 找不到 xelatex。请先安装 MiKTeX 或 TeX Live，并把其 bin 目录加入 PATH。
  pause
  exit /b 1
)

echo [1/4] XeLaTeX 第一遍...
xelatex -interaction=nonstopmode document.tex >nul

echo [2/4] BibTeX...
REM 说明：部分 MiKTeX 版本的 bibtex.exe 在处理较大的 .bst（如 gbt7714-*.bst）
REM       时会在退出阶段堆损坏崩溃（0xC0000374），.bbl 写不出来。
REM       实测 bibtex8 稳定，故优先用它；没有 bibtex8 时退回 bibtex 并重试。
set BIBTOOL=
where bibtex8 >nul 2>&1 && set BIBTOOL=bibtex8
if not defined BIBTOOL set BIBTOOL=bibtex
set BIBTRIES=0
:bibloop
set /a BIBTRIES+=1
if exist document.bbl del document.bbl
%BIBTOOL% document >nul 2>&1
for %%A in (document.bbl) do set BBLSIZE=%%~zA
if not defined BBLSIZE set BBLSIZE=0
if %BBLSIZE% GTR 1000 goto :bibok
if %BIBTRIES% GEQ 10 goto :bibok
goto :bibloop
:bibok
echo     使用 %BIBTOOL%，重试 %BIBTRIES% 次，bbl=%BBLSIZE% 字节
if %BBLSIZE% LSS 1000 echo     [警告] .bbl 未生成，参考文献可能显示为 [?]

echo [3/4] XeLaTeX 第二遍...
xelatex -interaction=nonstopmode document.tex >nul
echo [4/4] XeLaTeX 第三遍...
xelatex -interaction=nonstopmode document.tex >nul

echo.
echo ===== 编译结果自检 =====
findstr /C:"Output written" document.log
findstr /B /C:"!" document.log && echo [警告] 存在 LaTeX 报错 && goto :end
echo [OK] 无 LaTeX 报错
findstr /C:"Citation" document.log | findstr /C:"undefined" >nul && echo [警告] 存在未定义引用 || echo [OK] 无未定义引用
:end
echo.
echo 输出文件：document.pdf
endlocal
pause

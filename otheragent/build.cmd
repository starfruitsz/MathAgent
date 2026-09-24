@echo off
REM ============================================================
REM  一键编译论文（XeLaTeX + BibTeX，三遍编译）
REM  用法：双击本文件，或在命令行执行  build.cmd
REM
REM  说明：MiKTeX 自带的 bibtex 在本机退出时会返回一个非零码
REM        （0xC0000005 访问违例），但 .bbl 已经正确写出，
REM        因此下面的流程对 bibtex 的返回码不作判断。
REM        若参考文献显示为 [?]，删掉 document.aux / document.bbl
REM        后重新运行本脚本即可。
REM ============================================================
setlocal
cd /d "%~dp0"

REM 定位 xelatex：优先用 PATH 上的，其次试 MiKTeX 的常见安装位置
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

echo [2/4] BibTeX（最多重试 5 次，规避本机 bibtex 退出码异常）...
set BIBTRIES=0
:bibloop
set /a BIBTRIES+=1
if exist document.bbl del document.bbl
bibtex document >nul 2>&1
for %%A in (document.bbl) do set BBLSIZE=%%~zA
if not defined BBLSIZE set BBLSIZE=0
if %BBLSIZE% GTR 1000 goto :bibok
if %BIBTRIES% GEQ 5 goto :bibok
goto :bibloop
:bibok
echo     BibTeX 完成（重试 %BIBTRIES% 次，bbl=%BBLSIZE% 字节）

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

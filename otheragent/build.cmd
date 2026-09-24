@echo off
REM ============================================================
REM  Build the paper: XeLaTeX + BibTeX (3 passes)
REM  Usage: double-click this file, or run  build.cmd
REM
REM  NOTE 1: this file is deliberately ASCII-only. cmd.exe parses
REM          .cmd files using the OEM codepage (GBK on Chinese
REM          Windows), so UTF-8 Chinese comments corrupt the script.
REM
REM  NOTE 2: some MiKTeX builds of bibtex.exe crash with a heap
REM          corruption (exit 0xC0000374) when loading a large .bst
REM          such as gbt7714-*.bst (~88 KB); the .bbl never gets
REM          written, and it is intermittent. bibtex8 is stable in
REM          testing, so prefer it and fall back to bibtex+retries.
REM          If references still show [?], delete document.aux and
REM          document.bbl and run again.
REM ============================================================
setlocal
cd /d "%~dp0"

REM --- locate xelatex: PATH first, then common install locations ---
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
  echo [ERROR] xelatex not found. Install MiKTeX or TeX Live and add its bin directory to PATH.
  pause
  exit /b 1
)

echo [1/4] XeLaTeX pass 1 ...
xelatex -interaction=nonstopmode document.tex >nul

echo [2/4] BibTeX ...
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
echo     tool=%BIBTOOL%  tries=%BIBTRIES%  bbl=%BBLSIZE% bytes
if %BBLSIZE% LSS 1000 echo     [WARN] .bbl not generated; references may show as [?]

echo [3/4] XeLaTeX pass 2 ...
xelatex -interaction=nonstopmode document.tex >nul
echo [4/4] XeLaTeX pass 3 ...
xelatex -interaction=nonstopmode document.tex >nul

echo.
echo ===== build check =====
findstr /C:"Output written" document.log
findstr /B /C:"!" document.log >nul && echo [WARN] LaTeX errors found ^(see document.log^) || echo [OK] no LaTeX errors
findstr /C:"Citation" document.log | findstr /C:"undefined" >nul && echo [WARN] undefined citations || echo [OK] no undefined citations
echo.
echo Output: document.pdf
endlocal
pause

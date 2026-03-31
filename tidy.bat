@echo off
set TARGET=D:\Tmp\_cloudclusters

echo Cleaning Python cache and Git files in %TARGET%
echo.

REM ---------------------------------------------------
REM Delete all .pyc files
REM ---------------------------------------------------
echo Deleting .pyc files...
for /r "%TARGET%" %%f in (*.pyc) do (
    del /f /q "%%f"
)

REM ---------------------------------------------------
REM Delete all __pycache__ folders
REM ---------------------------------------------------
echo Deleting __pycache__ folders...
for /d /r "%TARGET%" %%d in (__pycache__) do (
    rd /s /q "%%d"
)

REM ---------------------------------------------------
REM Delete .git folders
REM ---------------------------------------------------
echo Deleting .git folders...
for /d /r "%TARGET%" %%d in (.git) do (
    rd /s /q "%%d"
)

REM ---------------------------------------------------
REM Delete git-related files
REM ---------------------------------------------------
echo Deleting git files...
for /r "%TARGET%" %%f in (.gitignore) do del /f /q "%%f"
for /r "%TARGET%" %%f in (.gitattributes) do del /f /q "%%f"
for /r "%TARGET%" %%f in (.gitmodules) do del /f /q "%%f"
for /r "%TARGET%" %%f in (.github) do del /f /q "%%f"

echo.
echo Cleanup complete.
pause
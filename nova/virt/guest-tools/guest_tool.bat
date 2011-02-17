@echo off

set GuestToolsHome=%~dp0
set PATH=%PATH%;%GuestToolsHome%\Python24
"%GuestToolsHome%\Python24\python.exe" "%GuestToolsHome%\guest_tool.py"
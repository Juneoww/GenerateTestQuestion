@echo off
rem 启动 GenerateTestQuestion 桌面端（使用项目独立 .venv 环境）
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo 未找到独立环境 .venv；请先执行：uv venv ^&^& uv pip install -p .venv/Scripts/python.exe -r requirements.txt
  pause
  exit /b 1
)
.venv\Scripts\python.exe app.py %*

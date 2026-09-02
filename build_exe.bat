@echo off
rem Build a standalone single-file exe: dist\GenerateTestQuestion.exe
rem Bundles data\sources.json and data\risk_catalog.json (extracted next to the
rem exe on first run). settings.json is intentionally NOT bundled - each user
rem fills in their own API key.
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --noconsole ^
  --name GenerateTestQuestion ^
  --add-data "data\sources.json;data" ^
  --add-data "data\risk_catalog.json;data" ^
  --collect-all scrapling ^
  app.py

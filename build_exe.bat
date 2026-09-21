@echo off
rem Build a standalone single-file exe: dist\GenerateTestQuestion.exe
rem All build options live in GenerateTestQuestion.spec; the exe version
rem metadata comes from storage.APP_VERSION. Bundles data\sources.json and
rem data\risk_catalog.json (extracted next to the exe on first run).
rem settings.json is intentionally NOT bundled - each user fills in their
rem own API key.
.venv\Scripts\pyinstaller --noconfirm --clean GenerateTestQuestion.spec

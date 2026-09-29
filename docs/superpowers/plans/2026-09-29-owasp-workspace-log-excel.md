# OWASP Workspace Log and Excel Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the authorization checkbox, show an OWASP run log, rename the result section, and expose the current batch's automatically saved Excel through a visible button.

**Architecture:** Keep `owasp_pipeline` and `owasp_export` unchanged. Modify only Tkinter layout/event handling in `app.py` and the corresponding UI tests. `outputDir` and `xlsxPath` retain their existing meanings; no Save As or duplicate export path is introduced.

**Tech Stack:** Python 3.12, Tkinter/ttk, unittest.

**Spec:** `docs/superpowers/specs/2026-09-29-owasp-workspace-log-excel-design.md`

**Working-tree note:** The OWASP 3.0.0 code is currently uncommitted in a shared dirty checkout. Do not create a detached worktree or commit unrelated user changes; preserve the existing state.

---

### Task 1: Confirm page structure and remove the authorization gate

**Files:** Modify `tests/test_app_owasp.py`, `app.py`.

- [x] **Step 1: Write failing UI tests.** In `OwaspWorkspaceUiTests`, assert ordered OWASP `ttk.LabelFrame` titles are `1. 选择 OWASP 风险`, `2. 本次生成`, `3. 运行日志`, `4. 运行结果`; assert no `owasp_authorized_var` or checkbox text remains; assert the valid two-risk/two-item form enables generation without an authorization action.
- [x] **Step 2: Verify red.** Run `.venv\Scripts\python.exe -m unittest tests.test_app_owasp.OwaspWorkspaceUiTests.test_workspace_sections_and_no_authorization_gate -v`; expected failure because the log frame is absent and authorization state still exists.
- [x] **Step 3: Implement.** In `_build_owasp_tab`, remove `owasp_authorized_var`, checkbox creation and widget registration; in `_update_owasp_selection_summary` and `_start_owasp_batch`, delete the authorization checks while retaining risk, quantity and model-configuration validation. Rename the result frame and insert the log frame before it.
- [x] **Step 4: Verify green.** Run the same test and then `.venv\Scripts\python.exe -m unittest tests.test_app_owasp -v`.

### Task 2: Show isolated OWASP run events

**Files:** Modify `tests/test_app_owasp.py`, `app.py`.

- [x] **Step 1: Extend the existing event test.** Record TC260 and OWASP log text before `_poll_events`; enqueue one event of each kind; assert each appears only in its own text widget, and OWASP status still updates. Add a start-batch test that stale OWASP log text clears when a valid new batch starts, and a failed-completion test that the latest error appears in the OWASP log.
- [x] **Step 2: Verify red.** Run the new focused tests; expected failure because `owasp_log_text` or error-log append is missing.
- [x] **Step 3: Implement.** Create a disabled `tk.Text` plus vertical scrollbar in the new log frame, with `warn`/`error` tags matching TC260. Route `kind == "owasp"` to an OWASP log appender and status. Clear the OWASP widget only after new-batch validation succeeds; preserve log on failure and append a final error event/message. Keep disk `run.log` unchanged.
- [x] **Step 4: Verify green.** Run the focused tests and `tests.test_app_owasp`.

### Task 3: Put current-batch Excel opening at the top of results

**Files:** Modify `tests/test_app_owasp.py`, `app.py`.

- [x] **Step 1: Write failing UI tests.** Assert there is one OWASP Excel button named `打开题库 Excel`, placed in the result frame before the table; it starts disabled, becomes enabled after success, and opens `Path(self.owasp_xlsx)` through `_open_path`. Assert a valid new batch or failed completion disables it, while existing JSON and batch-directory actions remain. Assert default/minimum window sizes retain a readable result tree and all actions via vertical page scrolling.
- [x] **Step 2: Verify red.** Run the focused tests; expected failure because the current button is named `打开 Excel` and lives after the result frame.
- [x] **Step 3: Implement.** Move `open_owasp_xlsx_button` into a result header row beside the summary text; rename it. Remove the old bottom-row packing for this button. Wrap the OWASP content in the existing page-scroll pattern without replacing TC260's canvas references. Reuse the existing `xlsxPath` state transitions and `_open_path`; do not alter `owasp_export.py` or generate a second file.
- [x] **Step 4: Verify green.** Run `tests.test_app_owasp` and ensure lifecycle tests cover old-artifact invalidation.

### Task 4: Regression and documentation

**Files:** Modify `task_plan.md`, `findings.md`, `progress.md`; if needed, update current usage text in `README.md` or `docs/使用说明.md` only where it contradicts the new page.

- [x] **Step 1: Run full verification.** `.venv\Scripts\python.exe -m unittest discover -s tests`; `.venv\Scripts\python.exe -m compileall -q app.py tests/test_app_owasp.py`; `.venv\Scripts\python.exe app.py --smoke-test`; `git diff --check`.
- [x] **Step 2: Inspect diff.** Ensure only the OWASP UI/tests and concise documentation changed for this request; all six-field Excel/JSON output contracts remain unchanged.
- [x] **Step 3: Review.** Request focused code review against the approved spec; fix important findings and rerun checks.
- [x] **Step 4: Record results.** Update planning files with test counts, any limits of visual-window verification, and remaining manual checks.

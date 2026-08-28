# Desktop Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a manually launched standalone Windows desktop client that supports material intake, material extraction, and a 155-question bilingual risk-bank run.

**Architecture:** Tkinter is the only desktop UI layer. Node data services own all `.xlsx` reads/writes through `@oai/artifact-tool`, exposing narrow JSON commands which Python invokes with project-local request files. The question-bank service consumes only `素材档案` rows whose `可生成状态` is `可生成` and otherwise creates clearly labeled synthetic coverage rows.

**Tech Stack:** Python 3.13 standard-library Tkinter, Node.js, existing `@oai/artifact-tool`, Node `assert` integration tests.

---

## File structure

| Path | Responsibility |
|---|---|
| `tools/desktop_data_service.mjs` | JSON CLI for dashboard, routes, material list, material intake and material extraction updates. |
| `tools/question_bank_service.mjs` | Deterministic bilingual 155-question generator and Excel exporter. |
| `app.py` | Manually launched Tkinter application and `--smoke-test` entrypoint. |
| `tests/question_bank.integration.mjs` | Tests coverage, ratio, dedupe and exported question-bank workbooks. |
| `tests/desktop_data_service.integration.mjs` | Tests the JSON bridge against an isolated project copy. |
| `tests/desktop_app.smoke.py` | Runs the no-window startup smoke test. |
| `data/question_bank/` | Generated increment packages and master bank. |

No git commit is created: the user asked for a standalone project but did not authorize repository history changes.

### Task 1: Build testable Node data bridge

- [ ] Write a failing integration test for reading dashboard counts, routes and material records from an isolated project copy.
- [ ] Run it and verify failure because `desktop_data_service.mjs` is absent.
- [ ] Implement JSON commands for `dashboard`, `routes`, `materials`, `stage-intake`, and `update-material`.
- [ ] Verify the test passes and that full text is never returned by the material-list command.

### Task 2: Build question-bank generator

- [ ] Write a failing test that expects a 155-record first baseline: all 31 risks, 124 Chinese, 31 English, unique IDs, and explicit synthetic provenance where no usable material exists.
- [ ] Run it and verify failure because `question_bank_service.mjs` is absent.
- [ ] Implement deterministic templates, per-language dedupe, incremental and master Excel export under `data/question_bank/`.
- [ ] Verify the test passes, including formula-error scan and workbook cleanup.

### Task 3: Build desktop application

- [ ] Write a failing Python smoke test for `app.py --smoke-test`.
- [ ] Run it and verify failure because `app.py` is absent.
- [ ] Implement Tkinter tabs for overview, sources, materials, and generate/results; run Node commands in a worker thread and restrict file opens to project-local paths.
- [ ] Verify no-window smoke test passes.

### Task 4: End-to-end verification

- [ ] Run Node integration tests and Python smoke test from a clean state.
- [ ] Launch `python app.py` manually, inspect the desktop window, and verify controls reflect the actual workbook state.
- [ ] Update project plan/progress and document the manual launch sequence.

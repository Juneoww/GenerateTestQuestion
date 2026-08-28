# Source Items Material Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a manually operated source-items workbook and ingestion tool that preserves permitted full text in project-local raw JSON while exposing structured, approved material rows as the direct input to later question generation.

**Architecture:** `source_registry.xlsx` remains the source/permission authority at route granularity. `source_items.xlsx` provides a styled manual intake sheet, a formal material archive, the 31-risk catalogue, and controlled status lists. The ingestion tool validates the exact source route, URL, risk mapping, and authorization evidence; writes full text only to `data/raw/<batch>/<material-id>.json`; clears staging after success; and adds a `待提取 / 不可生成` archive row.

**Tech Stack:** Node.js, `@oai/artifact-tool`, Node `fs`/`crypto`, existing project-local Excel workbooks, Node `assert` integration tests.

---

## File structure

| Path | Responsibility |
|---|---|
| `tools/build_source_items_template.mjs` | Builds the empty, styled `data/source_items.xlsx` from the current risk/source registry. |
| `tools/ingest_source_items.mjs` | Validates staged manual rows, writes raw JSON, updates the workbook, and reports rejection reasons. |
| `tools/source_items_shared.mjs` | Centralizes schema constants, spreadsheet-safe text handling, registry reads, risk mapping, hashes, and validation. |
| `tests/source_items.template.integration.mjs` | Verifies workbook structure, 31-risk mapping, formulas, validations, and no residual temporary artifacts. |
| `tests/source_items.ingest.integration.mjs` | Exercises one accepted manual import, rejected import cases, duplicate protection, raw JSON output, and staged-text clearing. |
| `data/source_items.xlsx` | Formal material intake and archive workbook. |
| `data/raw/` | Runtime-only raw JSON archive; created on first successful import. |
| `data/manual_import/` | Temporary, project-local UTF-8 `.txt`/`.md` source files only; successful import physically removes the source file. |

Do not create git commits: the user requested a standalone project but did not authorize repository history changes.

### Task 1: Define source-items schema helpers

**Files:**

- Create: `tools/source_items_shared.mjs`
- Test: `tests/source_items.template.integration.mjs`

- [x] **Step 1: Write a failing schema test**

Assert that the shared module exposes the exact intake/archive headers (including `授权URL前缀`), route-granular authorization fields, the allowed authorization/status values, a spreadsheet-safe text function, versioned URL/text normalization, deterministic material-ID construction, a `data/manual_import/` path guard, and a risk mapping loader returning all 31 risk IDs.

- [x] **Step 2: Run the test to verify it fails**

Run:

```powershell
& "C:\Users\52223\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" "tests\source_items.template.integration.mjs"
```

Expected: failure because `source_items_shared.mjs` does not yet exist.

- [x] **Step 3: Implement minimal shared helpers**

Implement:

```js
export const intakeHeaders = [...];
export const archiveHeaders = [...];
export const authorizationValues = ["V3来源", "人工确认-已获授权"];
export function spreadsheetSafeText(value) { /* prefix formula-like text */ }
export async function readRegistryCatalogs(projectRoot) { /* import routes, sites, and risks */ }
export function validateRiskMapping(row, riskById) { /* exact ID/scene/category match */ }
export function contentHash(text) { /* SHA-256 */ }
```

The registry loader must read `来源路由`、`网站目录` and `风险目录`, not duplicate the 31-risk taxonomy.

- [x] **Step 4: Run the schema test to verify it passes**

Run the command from Step 2. Expected: schema assertions pass; template-specific workbook assertions may remain pending until Task 2.

### Task 2: Build the source-items workbook template

**Files:**

- Create: `tools/build_source_items_template.mjs`
- Create: `data/source_items.xlsx`
- Modify: `tests/source_items.template.integration.mjs`

- [x] **Step 1: Add failing workbook assertions**

Require exactly these sheets: `说明`, `导入暂存`, `素材档案`, `风险目录`, `下拉选项`. Assert 31 risk rows spanning all 5 scenes, no full text in `素材档案`, the intake sheet includes `来源路由ID`、`授权证据URL`、`授权URL前缀`、`原始正文` and `原文文件路径`, and the archive sheet includes `生成素材`, `可生成状态`, `提取状态`, `原始档案路径`, and authorization provenance fields. Assert controlled dropdowns reject arbitrary values.

- [x] **Step 2: Run the test to verify it fails**

Run the template integration test. Expected: failure because `source_items.xlsx` has not been generated.

- [x] **Step 3: Implement the template builder**

Use `@oai/artifact-tool` to create a workbook with:

- a concise workflow notice and count formulas on `说明`;
- an empty `导入暂存` table with input rows, data validation, and an explicit full-text handling warning;
- an empty `素材档案` table with generated-material status fields and status conditional formatting;
- `风险目录` copied from `source_registry.xlsx` with the stable risk ID/scene/category mapping;
- `下拉选项` containing controlled values for language, material type, authorization, intake status, extraction status, and generation status.

Use the project-local artifact runtime and remove the artifact-tool `.inspect.ndjson` sidecar after export.

- [x] **Step 4: Run the template test to verify it passes**

Run the template integration test. Expected: PASS with 5 sheets and 31 risk mappings.

### Task 3: Implement manual ingestion and raw archive persistence

**Files:**

- Create: `tools/ingest_source_items.mjs`
- Modify: `tools/source_items_shared.mjs`
- Create: `tests/source_items.ingest.integration.mjs`

- [x] **Step 1: Write failing ingestion tests**

Set up a copy of the template, add staged rows using artifact-tool, then assert:

1. A valid, fully evidenced manual-authorization row creates exactly one JSON raw file and one `素材档案` row, with an asserted deterministic material ID.
2. The raw JSON includes title, URL, publication date, full text, hash, authorization evidence and normalization versions; the archive row carries provenance/source/risk metadata, SHA-256 hash, raw path, `待提取`, and `不可生成`, but no full original text.
3. The success result is written to the staged row and the staged `原始正文` is cleared. A sidecar file is physically removed after its raw JSON has been stored and before workbook update.
4. Empty body, both body inputs present, mismatched route/risk mapping, unsupported authorization, manual evidence whose scope lacks either `保留全文` or `生成去标识化场景`, expired evidence, non-HTTPS URL, formula text, oversized Excel body, absolute/traversal/reparse/non-UTF-8/non-`.txt`/`.md` sidecar paths, a same-domain but unconfigured V3 URL, and same normalized URL + body hash are rejected without new raw/archive data.
5. Simulate an Excel-update failure after raw JSON creation, rerun, and assert the same JSON is reused, exactly one archive row is created, and staging is not cleared until the archive update succeeds.

- [x] **Step 2: Run the ingestion test to verify it fails**

Run:

```powershell
& "C:\Users\52223\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" "tests\source_items.ingest.integration.mjs"
```

Expected: failure because the ingestion command does not exist.

- [x] **Step 3: Implement the ingestion command**

Implement manual command syntax:

```powershell
node tools/ingest_source_items.mjs --batch-id MANUAL-YYYYMMDD-001
```

Behavior:

- import the project-local registry and template workbooks;
- process only `导入暂存` rows whose status is `待入库`;
- permit `V3来源` only when the exact registry route is V3 and `已启用-受限接口`, its configured distribution URL pattern matches the actual resource URL, and its configured field scope permits body retention; permit `人工确认-已获授权` only when scoped evidence URL/ID, authorization URL prefix, approver, confirmation date, expiry and full-text/scenario-generation scope are present and valid;
- validate the exact route/risk mapping, source URL, required metadata, language, literal full text or project-local raw-file path;
- reject formulas/external links and Excel bodies over 32,767 characters; require project-local UTF-8 `.txt`/`.md` sidecar files for larger content;
- normalize URL and hash full text for deterministic material IDs and duplicate detection;
- atomically write one JSON object per accepted row under `data/raw/<batch-id>/` before updating Excel; the JSON includes the complete provenance/audit record and full text. Reuse an identical pre-existing JSON file during safe retry by `导入行ID` + source URL;
- append a sanitized archive row with blank generation fields, `待提取`, `不可生成`, and the raw path;
- clear staged direct full text only after raw JSON and archive update succeed. For a sidecar file, delete it after raw JSON succeeds but before the archive update; if deletion fails, stop before changing the workbook;
- leave rejected rows intact and write a human-readable error result;
- delete the workbook sidecar after export; never write outside `GenerateTestQuestion`.

- [x] **Step 4: Run the ingestion test to verify it passes**

Run the Step 2 command. Expected: PASS with one accepted record, every rejection preserved in staging, and no duplicate raw files.

### Task 4: Verify, render, and document use

**Files:**

- Modify: `docs/2026-08-27-source-items-material-archive-design.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

- [x] **Step 1: Run both integration tests from a clean state**

Run:

```powershell
& "C:\Users\52223\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" "tests\source_items.template.integration.mjs"
& "C:\Users\52223\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" "tests\source_items.ingest.integration.mjs"
```

Expected: both PASS.

- [x] **Step 2: Inspect and render the workbook**

Use artifact-tool to inspect all worksheets and formulas, scan for formula errors, render all five sheets, visually inspect them, and delete generated preview files.

- [x] **Step 3: Update usage notes and project progress**

Document the manual sequence: fill a `导入暂存` row, run the ingestion command, fill `生成素材` after extraction, then set `可生成状态` to `可生成`. Mark the plan complete only after successful verification.

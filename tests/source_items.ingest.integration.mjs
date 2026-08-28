/**
 * 功能:
 *   在隔离副本中验证人工素材入库、拒绝门禁与故障恢复。
 * 实现:
 *   复制真实模板和来源登记表，写入不同暂存记录，再调用真实入库函数检查
 *   原始 JSON、素材档案、暂存清理、旁车清理和 Excel 保存失败后的安全重试。
 * 输入:
 *   data/source_registry.xlsx、data/source_items.xlsx 与 ingest_source_items.mjs。
 * 输出:
 *   tests/ 下临时目录中的测试数据（结束后删除）和标准输出结果。
 * 依赖:
 *   Node.js、@oai/artifact-tool。
 * 用法:
 *   node tests/source_items.ingest.integration.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import { archiveHeaders, buildMaterialId, intakeHeaders } from "../tools/source_items_shared.mjs";
import { ingestStagedItems } from "../tools/ingest_source_items.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const tempPrefix = path.join(projectRoot, "tests", ".tmp_source_items_ingest_");

function rowFromValues(headers, values) {
  return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
}

function makeManualRow(overrides = {}) {
  return {
    "导入行ID": "INTAKE-001",
    "来源路由ID": "A3-04-ZH-NATIVE-01",
    "来源ID": "S05",
    "来源链接": "https://www.samr.gov.cn/articles/test-case-001?b=2&a=1",
    "标题": "测试商业竞争案例",
    "发布时间": "2026-08-01",
    "来源地区": "CN",
    "来源语言": "zh",
    "素材类型": "官方通报",
    "授权确认": "人工确认-已获授权",
    "授权证据ID": "AUTH-001",
    "授权证据URL": "https://rights.example.org/evidence/AUTH-001",
    "授权URL前缀": "https://www.samr.gov.cn/articles/",
    "授权范围": "允许保留全文；允许生成去标识化场景。",
    "确认人": "测试管理员",
    "确认日期": "2026-08-27",
    "有效期": "2027-08-27",
    "风险ID": "A3-04",
    "场景": "商业违法违规",
    "类别": "利用算法、数据、平台等优势实施垄断和不正当竞争",
    "原始正文": "测试原始正文\r\n第二行",
    "原文文件路径": "",
    "导入批次ID": "MANUAL-TEST-001",
    "导入日期": "2026-08-27",
    "入库状态": "待入库",
    "入库结果": "",
    ...overrides,
  };
}

function makeV3Row() {
  return {
    "导入行ID": "INTAKE-004",
    "来源路由ID": "A3-05-EN-01",
    "来源ID": "S12",
    "来源链接": "https://data.europa.eu/data/datasets/18489cb7-bce7-4d44-a138-795b390d2109/distribution.json",
    "标题": "Unconfigured V3 resource",
    "发布时间": "2026-08-01",
    "来源地区": "overseas",
    "来源语言": "en",
    "素材类型": "数据集元数据",
    "授权确认": "V3来源",
    "授权证据ID": "",
    "授权证据URL": "",
    "授权URL前缀": "",
    "授权范围": "",
    "确认人": "",
    "确认日期": "",
    "有效期": "",
    "风险ID": "A3-05",
    "场景": "商业违法违规",
    "类别": "其他商业违法违规行为",
    "原始正文": "Public metadata sample",
    "原文文件路径": "",
    "导入批次ID": "MANUAL-TEST-001",
    "导入日期": "2026-08-27",
    "入库状态": "待入库",
    "入库结果": "",
  };
}

async function createFixture() {
  const testRoot = await fs.mkdtemp(tempPrefix);
  await fs.mkdir(path.join(testRoot, "data", "manual_import"), { recursive: true });
  await fs.copyFile(path.join(projectRoot, "data", "source_registry.xlsx"), path.join(testRoot, "data", "source_registry.xlsx"));
  await fs.copyFile(path.join(projectRoot, "data", "source_items.xlsx"), path.join(testRoot, "data", "source_items.xlsx"));
  return testRoot;
}

async function loadWorkbook(workbookPath) {
  return SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
}

async function saveWorkbook(workbook, workbookPath) {
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(workbookPath);
  await fs.rm(`${workbookPath}.inspect.ndjson`, { force: true });
}

async function writeStagedRows(testRoot, rows) {
  const workbookPath = path.join(testRoot, "data", "source_items.xlsx");
  const workbook = await loadWorkbook(workbookPath);
  const sheet = workbook.worksheets.getItem("导入暂存");
  sheet.getRange(`A2:Z${rows.length + 1}`).values = rows.map((row) => intakeHeaders.map((header) => row[header] ?? ""));
  await saveWorkbook(workbook, workbookPath);
}

async function stagedRecords(testRoot) {
  const workbook = await loadWorkbook(path.join(testRoot, "data", "source_items.xlsx"));
  const sheet = workbook.worksheets.getItem("导入暂存");
  return sheet.getRange("A2:Z51").values.map((values) => rowFromValues(intakeHeaders, values));
}

async function archiveRecords(testRoot) {
  const workbook = await loadWorkbook(path.join(testRoot, "data", "source_items.xlsx"));
  const sheet = workbook.worksheets.getItem("素材档案");
  return sheet.getRange("A2:AE101").values
    .map((values) => rowFromValues(archiveHeaders, values))
    .filter((row) => row["素材ID"]);
}

async function rawJsonFiles(testRoot) {
  const rawRoot = path.join(testRoot, "data", "raw");
  try {
    const batchNames = await fs.readdir(rawRoot);
    const files = [];
    for (const batchName of batchNames) {
      const batchPath = path.join(rawRoot, batchName);
      for (const fileName of await fs.readdir(batchPath)) {
        if (fileName.endsWith(".json")) files.push(path.join(batchPath, fileName));
      }
    }
    return files.sort();
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
}

const expectedMaterialId = "MAT-B3F97263963EE114";
assert.equal(
  buildMaterialId("https://www.samr.gov.cn/articles/test-case-001?b=2&a=1", "测试原始正文\r\n第二行"),
  expectedMaterialId,
  "测试夹具必须固定素材 ID，避免仅验证实现自身",
);

const mainRoot = await createFixture();
try {
  const sidecarRelativePath = "data/manual_import/sidecar.md";
  const sidecarAbsolutePath = path.join(mainRoot, "data", "manual_import", "sidecar.md");
  const sidecarText = "旁车完整原文。".repeat(5000);
  await fs.writeFile(sidecarAbsolutePath, sidecarText, "utf8");
  await fs.writeFile(path.join(mainRoot, "data", "manual_import", "double.md"), "双输入旁车", "utf8");
  await fs.writeFile(path.join(mainRoot, "data", "manual_import", "invalid-utf8.md"), Buffer.from([0xC3, 0x28]));

  await writeStagedRows(mainRoot, [
    makeManualRow(),
    makeManualRow({ "导入行ID": "INTAKE-002" }),
    makeManualRow({
      "导入行ID": "INTAKE-003",
      "来源链接": "https://www.samr.gov.cn/articles/scope-missing",
      "授权范围": "允许保留全文。",
      "原始正文": "授权范围不足的正文",
    }),
    makeV3Row(),
    makeManualRow({
      "导入行ID": "INTAKE-005",
      "来源链接": "https://www.samr.gov.cn/articles/formula-body",
      "原始正文": "=SUM(1,2)",
    }),
    makeManualRow({
      "导入行ID": "INTAKE-006",
      "来源链接": "https://www.samr.gov.cn/articles/double-input",
      "原始正文": "不应同时有两个正文来源",
      "原文文件路径": "data/manual_import/double.md",
    }),
    makeManualRow({
      "导入行ID": "INTAKE-007",
      "来源链接": "https://www.samr.gov.cn/articles/path-traversal",
      "原始正文": "",
      "原文文件路径": "../outside.md",
    }),
    makeManualRow({
      "导入行ID": "INTAKE-008",
      "来源链接": "https://www.samr.gov.cn/articles/sidecar-input",
      "原始正文": "",
      "原文文件路径": sidecarRelativePath,
    }),
    makeManualRow({
      "导入行ID": "INTAKE-009",
      "来源链接": "https://www.samr.gov.cn/articles/empty-input",
      "原始正文": "",
      "原文文件路径": "",
    }),
    makeManualRow({
      "导入行ID": "INTAKE-010",
      "来源链接": "https://www.samr.gov.cn/articles/expired-authorization",
      "有效期": "2000-01-01",
      "原始正文": "过期授权正文",
    }),
    makeManualRow({
      "导入行ID": "INTAKE-011",
      "来源链接": "http://www.samr.gov.cn/articles/non-https",
      "原始正文": "非 HTTPS 正文",
    }),
    makeManualRow({
      "导入行ID": "INTAKE-012",
      "来源链接": "https://www.samr.gov.cn/articles/absolute-sidecar",
      "原始正文": "",
      "原文文件路径": "C:\\outside.md",
    }),
    makeManualRow({
      "导入行ID": "INTAKE-013",
      "来源链接": "https://www.samr.gov.cn/articles/wrong-extension",
      "原始正文": "",
      "原文文件路径": "data/manual_import/not-text.pdf",
    }),
    makeManualRow({
      "导入行ID": "INTAKE-014",
      "来源链接": "https://www.samr.gov.cn/articles/invalid-utf8",
      "原始正文": "",
      "原文文件路径": "data/manual_import/invalid-utf8.md",
    }),
  ]);

  const result = await ingestStagedItems({ projectRoot: mainRoot, batchId: "MANUAL-TEST-001" });
  assert.equal(result.accepted, 2, "一条直接正文与一条合格旁车正文应入库");
  assert.equal(result.rejected, 12, "重复、授权/URL/正文/旁车边界违规均应拒绝");

  const rawFiles = await rawJsonFiles(mainRoot);
  assert.equal(rawFiles.length, 2, "两条成功记录应各有一份原始 JSON");
  const directRawPath = path.join(mainRoot, "data", "raw", "MANUAL-TEST-001", `${expectedMaterialId}.json`);
  const directRaw = JSON.parse(await fs.readFile(directRawPath, "utf8"));
  assert.equal(directRaw.materialId, expectedMaterialId, "原始 JSON 必须保存确定的素材 ID");
  assert.equal(directRaw.title, "测试商业竞争案例", "原始 JSON 必须保存标题");
  assert.equal(directRaw.sourceUrl, "https://www.samr.gov.cn/articles/test-case-001?a=1&b=2", "原始 JSON 必须保存规范化 URL");
  assert.equal(directRaw.publicationDate, "2026-08-01", "原始 JSON 必须保存发布时间");
  assert.equal(directRaw.fullText, "测试原始正文\n第二行", "原始 JSON 必须保存工作簿中的完整原文内容");
  assert.equal(directRaw.contentHash, "9225da8f5f5e6d0eba5e2d129b89636c6b785168f210542ec7b7bc5964ee67f8", "原始 JSON 必须保存正文哈希");
  assert.equal(directRaw.authorization.evidenceId, "AUTH-001", "原始 JSON 必须保存授权证据");
  assert.equal(directRaw.normalization.url, "URL-NORM-V1", "原始 JSON 必须记录 URL 规范化版本");
  assert.equal(directRaw.normalization.text, "TEXT-NORM-V1", "原始 JSON 必须记录正文规范化版本");

  const archive = await archiveRecords(mainRoot);
  assert.equal(archive.length, 2, "成功入库只能产生两条正式素材记录");
  const directArchive = archive.find((row) => row["素材ID"] === expectedMaterialId);
  assert.ok(directArchive, "素材档案必须引用合格原始记录");
  assert.equal(directArchive["导入批次ID"], "MANUAL-TEST-001", "素材档案必须保留入库批次");
  assert.equal(directArchive["来源链接"], "https://www.samr.gov.cn/articles/test-case-001?a=1&b=2", "素材档案必须保留规范化来源链接");
  assert.equal(directArchive["正文哈希"], directRaw.contentHash, "素材档案必须保存正文哈希");
  assert.equal(directArchive["提取状态"], "待提取", "新素材应等待去标识化提取");
  assert.equal(directArchive["可生成状态"], "不可生成", "新素材不得立即被出题器使用");
  assert.ok(String(directArchive["原始档案路径"]).endsWith(`${expectedMaterialId}.json`), "素材档案必须追溯原始 JSON");
  assert.ok(!JSON.stringify(directArchive).includes("测试原始正文"), "素材档案不得复制完整原文");

  const staged = await stagedRecords(mainRoot);
  assert.equal(staged[0]["入库状态"], "入库成功", "成功行必须写回成功状态");
  assert.equal(staged[0]["原始正文"], "", "成功后必须清空工作簿中的直接原文");
  assert.equal(staged[0]["原文文件路径"], "", "成功后必须清空工作簿中的旁车路径");
  for (const index of [1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13]) {
    assert.equal(staged[index]["入库状态"], "入库失败", `第 ${index + 2} 行必须保留拒绝状态`);
    assert.ok(staged[index]["原始正文"] || staged[index]["原文文件路径"], `第 ${index + 2} 行的原始输入必须保留以便修正`);
  }
  assert.equal(staged[7]["入库状态"], "入库成功", "旁车行必须成功入库");
  assert.equal(staged[7]["原文文件路径"], "", "旁车成功后必须清空路径");
  await assert.rejects(fs.access(sidecarAbsolutePath), "旁车成功后必须物理删除，避免原文残留在暂存目录");
} finally {
  assert.ok(mainRoot.startsWith(tempPrefix), "只允许删除本测试创建的临时目录");
  await fs.rm(mainRoot, { recursive: true, force: true });
}

const recoveryRoot = await createFixture();
try {
  await writeStagedRows(recoveryRoot, [makeManualRow({
    "来源链接": "https://www.samr.gov.cn/articles/recovery-case",
    "原始正文": "用于验证 Excel 保存失败恢复的原文",
    "导入批次ID": "MANUAL-RECOVERY-001",
  })]);
  await assert.rejects(
    ingestStagedItems({
      projectRoot: recoveryRoot,
      batchId: "MANUAL-RECOVERY-001",
      writeWorkbook: async () => { throw new Error("模拟 Excel 更新失败"); },
    }),
    /模拟 Excel 更新失败/u,
    "原始 JSON 写入后发生 Excel 更新失败必须向调用方报告",
  );
  const rawFilesBeforeRetry = await rawJsonFiles(recoveryRoot);
  assert.equal(rawFilesBeforeRetry.length, 1, "失败后必须保留一份可恢复的原始 JSON");
  const stagedAfterFailure = await stagedRecords(recoveryRoot);
  assert.equal(stagedAfterFailure[0]["原始正文"], "用于验证 Excel 保存失败恢复的原文", "Excel 保存失败前不得清空暂存原文");

  const recoveryResult = await ingestStagedItems({ projectRoot: recoveryRoot, batchId: "MANUAL-RECOVERY-001" });
  assert.equal(recoveryResult.accepted, 1, "重试必须修复素材档案");
  const rawFilesAfterRetry = await rawJsonFiles(recoveryRoot);
  assert.deepEqual(rawFilesAfterRetry, rawFilesBeforeRetry, "重试必须复用同一原始 JSON，不能创建重复文件");
  assert.equal((await archiveRecords(recoveryRoot)).length, 1, "重试后只能有一条素材档案记录");
  assert.equal((await stagedRecords(recoveryRoot))[0]["原始正文"], "", "成功重试后才可清空暂存原文");
} finally {
  assert.ok(recoveryRoot.startsWith(tempPrefix), "只允许删除本测试创建的临时目录");
  await fs.rm(recoveryRoot, { recursive: true, force: true });
}

console.log("PASS source_items ingestion: authorization gates, raw boundary, sidecar cleanup, duplicate protection, recovery");

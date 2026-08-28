/**
 * 功能:
 *   验证来源登记表生成器能写出完整、可导入的 source_registry.xlsx。
 * 实现:
 *   以真实子进程运行生成器，再使用 artifact-tool 重新导入工作簿并检查
 *   工作表、31 类风险覆盖、124 条网页来源路由及访问核验门禁。
 * 输入:
 *   项目内 tools/build_source_registry.mjs 和 bundled @oai/artifact-tool。
 * 输出:
 *   data/source_registry.xlsx；测试结果写入标准输出。
 * 依赖:
 *   Node.js 及 @oai/artifact-tool。
 * 用法:
 *   node tests/source_registry.integration.mjs
 */
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import { promisify } from "node:util";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const execFileAsync = promisify(execFile);
const projectRoot = path.resolve(import.meta.dirname, "..");
const builderPath = path.join(projectRoot, "tools", "build_source_registry.mjs");
const outputPath = path.join(projectRoot, "data", "source_registry.xlsx");

await execFileAsync(process.execPath, [builderPath], { cwd: projectRoot });

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const routeSheet = workbook.worksheets.getItem("来源路由");
const siteSheet = workbook.worksheets.getItem("网站目录");
const riskSheet = workbook.worksheets.getItem("风险目录");
const infoSheet = workbook.worksheets.getItem("说明");
const verificationSheet = workbook.worksheets.getItem("访问核验规则");
const evidenceSheet = workbook.worksheets.getItem("核验证据");

const routeHeaders = routeSheet.getRange("A1:X1").values[0];
for (const header of ["路由ID", "爬取网站", "入口URL", "场景", "类别", "输出语言", "适用配额槽", "启用状态", "最近抓取时间", "来源ID", "核验等级", "证据索引", "运行门禁", "许可分发URL模式", "许可字段范围"]) {
  assert.ok(routeHeaders.includes(header), `来源路由缺少必填列：${header}`);
}

const routeRows = routeSheet.getRange("A2:X125").values;
assert.equal(routeRows.length, 124, "应为 31 个风险配置 4 条网页来源路由");
assert.equal(new Set(routeRows.map((row) => row[0])).size, 124, "路由ID必须唯一");
assert.equal(new Set(routeRows.map((row) => row[1])).size, 31, "应覆盖全部 31 个风险ID");
assert.ok(routeRows.every((row) => String(row[3]).startsWith("https://")), "每条路由必须有 HTTPS 入口URL");
assert.equal(routeRows.filter((row) => row[14] === "已启用-受限接口").length, 2, "仅 S12 的两条数据集路由可按受限接口运行");
assert.ok(routeRows.filter((row) => row[14] !== "已启用-受限接口").every((row) => row[14] === "候选-待核验"), "未获明确许可的路由必须维持候选状态");
assert.ok(routeRows.filter((row) => row[14] === "已启用-受限接口").every((row) => row[17] === "S12" && row[18] === "V3" && String(row[21]).startsWith("允许")), "V3 路由必须只来自 S12 且具有限制性运行门禁");
assert.ok(
  routeRows.filter((row) => row[14] === "已启用-受限接口").every((row) => (row[22] === null || row[22] === "") && String(row[23]).includes("不允许完整正文归档")),
  "S12 尚未补录可复查 JSON 分发 URL，且字段范围必须明确禁止全文归档",
);

const siteHeaders = siteSheet.getRange("A1:Q1").values[0];
for (const header of ["来源ID", "爬取网站", "启用状态", "核验等级", "证据索引", "核验日期", "人工启动建议", "核验结论"]) {
  assert.ok(siteHeaders.includes(header), `网站目录缺少核验字段：${header}`);
}
const siteRows = siteSheet.getRange("A2:Q16").values;
assert.equal(siteRows.length, 15, "网站目录应保留 15 个去重候选站点");
assert.equal(siteRows.filter((row) => row[12] === "V0").length, 14, "14 个来源应保留在 V0 候选状态");
const s12 = siteRows.find((row) => row[0] === "S12");
assert.ok(s12, "网站目录应包含 S12");
assert.equal(s12[2], "https://data.europa.eu/data/datasets/18489cb7-bce7-4d44-a138-795b390d2109~~1?locale=en", "S12 必须改用官方开放数据集入口");
assert.equal(s12[10], "已启用-受限接口", "S12 应为受限接口状态");
assert.equal(s12[12], "V3", "S12 应为 V3 核验等级");

assert.ok(verificationSheet, "应包含访问核验规则工作表");
assert.ok(evidenceSheet, "应包含核验证据工作表");
assert.equal(verificationSheet.getRange("A1").values[0][0], "GenerateTestQuestion｜来源访问核验规则", "核验规则页应有标题");
const evidenceHeaders = evidenceSheet.getRange("A1:J1").values[0];
for (const header of ["证据ID", "来源ID", "证据类型", "证据URL", "核验日期", "核验等级", "核验结论"]) {
  assert.ok(evidenceHeaders.includes(header), `核验证据缺少字段：${header}`);
}
const evidenceRows = evidenceSheet.getRange("A2:J19").values;
assert.equal(evidenceRows.length, 18, "应保存 15 个来源探测记录及 3 个补充核验证据");
assert.equal(new Set(evidenceRows.map((row) => row[0])).size, 18, "证据ID必须唯一");
assert.ok(evidenceRows.every((row) => String(row[3]).startsWith("https://")), "每条核验证据都必须可回查至 HTTPS URL");
assert.ok(evidenceRows.some((row) => row[1] === "S12" && row[7] === "V3"), "S12 必须保留 V3 证据");

for (const temporaryName of ["source_registry.xlsx.inspect.ndjson", ".preview_说明.png", ".preview_来源路由.png", ".preview_网站目录.png", ".preview_风险目录.png", ".preview_访问核验规则.png", ".preview_核验证据.png"]) {
  await assert.rejects(fs.access(path.join(projectRoot, "data", temporaryName)), `${temporaryName} 不应留在正式数据目录`);
}

const summaryValues = infoSheet.getRange("B6:B11").values.flat();
assert.deepEqual(summaryValues, [15, 124, 31, 93, 31, 2], "说明页汇总公式应反映当前目录、路由和受限接口数量");

assert.equal(infoSheet.getRange("A13").values[0][0], "使用规则", "说明页应有一个规则区标题");
assert.ok(infoSheet.getRange("B13:H13").values.flat().every((value) => value === null || value === ""), "说明页规则标题不应重复填充到多列");

const riskCounts = riskSheet.getRange("E2:G32").values;
assert.ok(riskCounts.every((row) => row[0] === 3 && row[1] === 1 && row[2] === 4), "每个风险应有 3 条中文输出路由、1 条英文输出路由和 4 条网页来源路由");

for (const sheetName of ["说明", "来源路由", "网站目录", "风险目录", "访问核验规则", "核验证据"]) {
  const values = workbook.worksheets.getItem(sheetName).getUsedRange().values.flat(Infinity);
  assert.ok(!values.some((value) => typeof value === "string" && /^#(REF!|DIV\/0!|VALUE!|NAME\?|N\/A)/.test(value)), `${sheetName} 不应包含公式错误`);
}

console.log("PASS source_registry integration: 15 sites, 31 risks, 124 routes, 2 V3-restricted routes");

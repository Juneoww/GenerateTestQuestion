/**
 * 功能:
 *   先于实现验证素材工作簿共享规则和后续模板的固定结构。
 * 实现:
 *   载入真实来源登记表，断言字段、规范化、稳定素材 ID 与 31 类风险目录。
 * 输入:
 *   tools/source_items_shared.mjs 与 data/source_registry.xlsx。
 * 输出:
 *   标准输出中的集成测试结果；不修改正式数据。
 * 依赖:
 *   Node.js、@oai/artifact-tool。
 * 用法:
 *   node tests/source_items.template.integration.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const projectRoot = path.resolve(import.meta.dirname, "..");
const {
  archiveHeaders,
  authorizationValues,
  buildMaterialId,
  intakeHeaders,
  normalizeText,
  normalizeUrl,
  readRegistryCatalogs,
  spreadsheetSafeText,
  statusValues,
} = await import("../tools/source_items_shared.mjs");

assert.ok(intakeHeaders.includes("授权URL前缀"), "导入暂存必须保存授权 URL 范围");
assert.ok(intakeHeaders.includes("原始正文"), "导入暂存必须有原始正文列");
assert.ok(intakeHeaders.includes("原文文件路径"), "导入暂存必须有旁车文件列");
assert.ok(archiveHeaders.includes("生成素材"), "素材档案必须有生成素材列");
assert.ok(archiveHeaders.includes("原始档案路径"), "素材档案必须追溯原始档案");
assert.deepEqual(authorizationValues, ["V3来源", "人工确认-已获授权"], "授权值必须受控");
assert.ok(statusValues.generation.includes("可生成"), "生成状态必须包含可生成");
assert.equal(spreadsheetSafeText("=1+1"), "'=1+1", "写回工作簿的文本必须防公式注入");

assert.equal(
  normalizeUrl("HTTPS://Example.COM:443/a/../news?b=2&a=1#fragment"),
  "https://example.com/news?a=1&b=2",
  "URL-NORM-V1 应稳定化主机、路径、查询与片段",
);
assert.equal(normalizeText("ＡＢＣ\r\nline  "), "ABC\nline", "TEXT-NORM-V1 应处理 Unicode、换行和首尾空白");
assert.equal(
  buildMaterialId("HTTPS://Example.COM:443/a/../news?b=2&a=1#fragment", "ＡＢＣ\r\nline  "),
  "MAT-5F12E6AE19AFF398",
  "素材 ID 必须由规范化 URL 和正文哈希确定",
);

const catalogs = await readRegistryCatalogs(projectRoot);
assert.equal(catalogs.riskById.size, 31, "必须从来源登记表读取全部 31 类风险");
assert.equal(new Set([...catalogs.riskById.values()].map((risk) => risk.scene)).size, 5, "风险目录必须覆盖 5 个场景");
assert.equal(catalogs.routeById.size, 124, "必须从来源登记表读取全部来源路由");
assert.ok(catalogs.routeById.get("A3-04-EN-01"), "应可定位稳定来源路由 ID");

const workbookPath = path.join(projectRoot, "data", "source_items.xlsx");
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
assert.deepEqual(
  workbook.worksheets.items.map((sheet) => sheet.name),
  ["说明", "导入暂存", "素材档案", "风险目录", "下拉选项"],
  "素材工作簿必须保持固定的五个工作表",
);

const intakeSheet = workbook.worksheets.getItem("导入暂存");
const archiveSheet = workbook.worksheets.getItem("素材档案");
const riskSheet = workbook.worksheets.getItem("风险目录");
const infoSheet = workbook.worksheets.getItem("说明");
assert.deepEqual(intakeSheet.getRange("A1:Z1").values[0], intakeHeaders, "导入暂存列必须与共享规则一致");
assert.deepEqual(archiveSheet.getRange("A1:AE1").values[0], archiveHeaders, "素材档案列必须与共享规则一致");
const riskRows = riskSheet.getRange("A2:D32").values;
assert.equal(riskRows.length, 31, "风险目录必须有 31 行");
assert.equal(new Set(riskRows.map((row) => row[2])).size, 5, "风险目录必须有 5 个场景");
assert.ok(!archiveHeaders.includes("原始正文"), "素材档案不得保存完整原文列");
assert.equal(intakeSheet.getRange("A2").values[0][0], "INTAKE-001", "模板应提供稳定的导入行 ID");
assert.equal(intakeSheet.getRange("Y2").values[0][0], "待入库", "模板应将新行置为待入库");
assert.equal(infoSheet.getRange("B14").values[0][0], 0, "空模板的正式素材记录必须为 0");

for (const cellAddress of ["B2", "C2", "H2", "I2", "J2", "R2", "S2", "T2", "Y2"]) {
  const validation = intakeSheet.getRange(cellAddress).dataValidation;
  assert.ok(validation.rule, `${cellAddress} 必须配置下拉校验规则`);
  assert.equal(validation.rule.type, "list", `${cellAddress} 必须是受控下拉字段`);
  assert.ok(validation.rule.formula1 || validation.rule.values?.length, `${cellAddress} 不得接受任意自由输入`);
}

console.log("PASS source_items template: five sheets, 31 risks, controlled intake lists");

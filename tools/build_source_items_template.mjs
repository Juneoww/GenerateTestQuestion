/**
 * 功能:
 *   创建人工素材导入与素材档案的空白 Excel 模板。
 * 实现:
 *   读取 source_registry.xlsx 的风险目录，建立固定的五个工作表、受控下拉、
 *   状态格式与可筛选表格；不写入任何原始全文。
 * 输入:
 *   data/source_registry.xlsx；可选 --force 以明确覆盖既有空模板。
 * 输出:
 *   data/source_items.xlsx 及 data/manual_import/ 目录。
 * 依赖:
 *   Node.js 与 @oai/artifact-tool。
 * 用法:
 *   node tools/build_source_items_template.mjs [--force]
 */
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";
import {
  archiveHeaders,
  authorizationValues,
  intakeHeaders,
  readRegistryCatalogs,
  statusValues,
} from "./source_items_shared.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const outputPath = path.join(projectRoot, "data", "source_items.xlsx");
const manualImportDir = path.join(projectRoot, "data", "manual_import");
const intakeRowCount = 50;

function columnLetter(index) {
  let value = index + 1;
  let output = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    output = String.fromCharCode(65 + remainder) + output;
    value = Math.floor((value - 1) / 26);
  }
  return output;
}

function styleTable(sheet, headerRange, dataRange, widths) {
  headerRange.format = {
    fill: "#17365D",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#17365D" },
  };
  headerRange.format.rowHeight = 34;
  dataRange.format = { verticalAlignment: "top", wrapText: true };
  dataRange.format.borders = { insideHorizontal: { style: "thin", color: "#E2E8F0" } };
  widths.forEach((width, index) => {
    sheet.getRange(`${columnLetter(index)}:${columnLetter(index)}`).format.columnWidth = width;
  });
}

function writeListColumn(sheet, column, title, values) {
  sheet.getRange(`${column}1`).values = [[title]];
  sheet.getRange(`${column}2:${column}${values.length + 1}`).values = values.map((value) => [value]);
  sheet.getRange(`${column}1:${column}${values.length + 1}`).format = { wrapText: true };
  sheet.getRange(`${column}1`).format = { fill: "#D9E2F3", font: { bold: true, color: "#17365D" } };
  sheet.getRange(`${column}:${column}`).format.columnWidth = 22;
}

async function ensureNewOutput() {
  if (process.argv.includes("--force")) return;
  try {
    await fs.access(outputPath);
    throw new Error("data/source_items.xlsx 已存在；为保护已录入数据，只有明确传入 --force 才能重建模板。");
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
}

async function buildWorkbook() {
  await ensureNewOutput();
  const catalogs = await readRegistryCatalogs(projectRoot);
  const risks = [...catalogs.riskById.values()];
  if (risks.length !== 31) throw new Error(`风险目录数量异常：${risks.length}`);
  const routeIds = [...catalogs.routeById.keys()].sort();
  const sourceIds = [...catalogs.siteById.keys()].sort();
  const riskIds = risks.map((risk) => risk.riskId);
  const scenes = [...new Set(risks.map((risk) => risk.scene))];
  const categories = risks.map((risk) => risk.category);

  const workbook = Workbook.create();
  const infoSheet = workbook.worksheets.add("说明");
  const intakeSheet = workbook.worksheets.add("导入暂存");
  const archiveSheet = workbook.worksheets.add("素材档案");
  const riskSheet = workbook.worksheets.add("风险目录");
  const listSheet = workbook.worksheets.add("下拉选项");
  for (const sheet of [infoSheet, intakeSheet, archiveSheet, riskSheet, listSheet]) sheet.showGridLines = false;

  infoSheet.mergeCells("A1:H1");
  infoSheet.getRange("A1").values = [["GenerateTestQuestion｜素材归档与人工导入"]];
  infoSheet.getRange("A1:H1").format = {
    fill: "#17365D", font: { bold: true, color: "#FFFFFF", size: 15 }, horizontalAlignment: "left", verticalAlignment: "center",
  };
  infoSheet.getRange("A1:H1").format.rowHeight = 32;
  infoSheet.mergeCells("A3:H3");
  infoSheet.getRange("A3").values = [["本工作簿仅用于人工启动的素材入库。完整原文只临时位于“导入暂存”，成功后仅保留在 data/raw JSON；“素材档案”是后续出题器的唯一直接输入。"]];
  infoSheet.getRange("A3:H3").format = { fill: "#FFF3CD", font: { bold: true, color: "#7A4F01" }, wrapText: true, verticalAlignment: "center" };
  infoSheet.getRange("A3:H3").format.rowHeight = 44;
  infoSheet.getRange("A5:B5").values = [["步骤", "人工操作"]];
  infoSheet.getRange("A6:B10").values = [
    ["1", "在“导入暂存”填写一行；原始正文与原文文件路径只能选其一。"],
    ["2", "超长正文仅可放在 data/manual_import/ 的 UTF-8 .txt/.md 文件中，并填写项目内相对路径。"],
    ["3", "人工运行 node tools/ingest_source_items.mjs --batch-id MANUAL-YYYYMMDD-001。"],
    ["4", "入库后在“素材档案”补齐去标识化生成素材、事实要点、风险触发点和建议题型。"],
    ["5", "仅在提取完成且复核通过后，将“可生成状态”改为“可生成”。"],
  ];
  styleTable(infoSheet, infoSheet.getRange("A5:B5"), infoSheet.getRange("A6:B10"), [10, 105]);
  infoSheet.getRange("A12:B12").values = [["指标", "当前值"]];
  infoSheet.getRange("A13:B15").values = [["风险类别", null], ["正式素材记录", null], ["可生成记录", null]];
  infoSheet.getRange("B13").formulas = [["=COUNTA('风险目录'!$A$2:$A$32)"]];
  infoSheet.getRange("B14").formulas = [["=COUNTIF('素材档案'!$A$2:$A$101,\"MAT-*\")"]];
  infoSheet.getRange("B15").formulas = [["=COUNTIF('素材档案'!$AB$2:$AB$101,\"可生成\")"]];
  styleTable(infoSheet, infoSheet.getRange("A12:B12"), infoSheet.getRange("A13:B15"), [22, 28]);
  infoSheet.freezePanes.freezeRows(3);

  const intakeRows = Array.from({ length: intakeRowCount }, (_, index) => {
    const row = Array(intakeHeaders.length).fill("");
    row[0] = `INTAKE-${String(index + 1).padStart(3, "0")}`;
    row[24] = "待入库";
    return row;
  });
  intakeSheet.getRange("A1:Z1").values = [intakeHeaders];
  intakeSheet.getRange(`A2:Z${intakeRowCount + 1}`).values = intakeRows;
  styleTable(
    intakeSheet,
    intakeSheet.getRange("A1:Z1"),
    intakeSheet.getRange(`A2:Z${intakeRowCount + 1}`),
    [16, 30, 12, 48, 34, 16, 13, 12, 16, 20, 18, 48, 40, 46, 16, 16, 16, 14, 30, 44, 58, 42, 24, 16, 16, 52],
  );
  intakeSheet.getRange(`F2:F${intakeRowCount + 1}`).format.numberFormat = "yyyy-mm-dd";
  intakeSheet.getRange(`P2:Q${intakeRowCount + 1}`).format.numberFormat = "yyyy-mm-dd";
  intakeSheet.getRange(`X2:X${intakeRowCount + 1}`).format.numberFormat = "yyyy-mm-dd";
  intakeSheet.getRange(`A2:Z${intakeRowCount + 1}`).format.rowHeight = 22;
  intakeSheet.tables.add(`A1:Z${intakeRowCount + 1}`, true, "SourceItemsIntakeTable").style = "TableStyleMedium2";
  intakeSheet.freezePanes.freezeRows(1);
  intakeSheet.freezePanes.freezeColumns(2);
  intakeSheet.getRange(`B2:B${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$H$2:$H$125" } };
  intakeSheet.getRange(`C2:C${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$I$2:$I$16" } };
  intakeSheet.getRange(`G2:G${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$G$2:$G$3" } };
  intakeSheet.getRange(`H2:H${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$B$2:$B$3" } };
  intakeSheet.getRange(`I2:I${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$C$2:$C$8" } };
  intakeSheet.getRange(`J2:J${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$A$2:$A$3" } };
  intakeSheet.getRange(`R2:R${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$J$2:$J$32" } };
  intakeSheet.getRange(`S2:S${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$K$2:$K$6" } };
  intakeSheet.getRange(`T2:T${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$L$2:$L$32" } };
  intakeSheet.getRange(`Y2:Y${intakeRowCount + 1}`).dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$D$2:$D$4" } };
  intakeSheet.getRange(`Y2:Y${intakeRowCount + 1}`).conditionalFormats.add("containsText", { text: "入库成功", format: { fill: "#D9EAD3", font: { color: "#276221" } } });
  intakeSheet.getRange(`Y2:Y${intakeRowCount + 1}`).conditionalFormats.add("containsText", { text: "入库失败", format: { fill: "#FCE4D6", font: { color: "#9C0006" } } });

  archiveSheet.getRange("A1:AE1").values = [archiveHeaders];
  archiveSheet.getRange("A2:AE2").values = [Array(archiveHeaders.length).fill("")];
  styleTable(
    archiveSheet,
    archiveSheet.getRange("A1:AE1"),
    archiveSheet.getRange("A2:AE2"),
    [24, 24, 30, 12, 36, 48, 34, 16, 16, 13, 12, 16, 64, 18, 48, 40, 46, 16, 16, 16, 14, 30, 44, 60, 45, 44, 18, 16, 16, 54, 44],
  );
  archiveSheet.getRange("H2:I101").format.numberFormat = "yyyy-mm-dd";
  archiveSheet.getRange("S2:T101").format.numberFormat = "yyyy-mm-dd";
  archiveSheet.tables.add("A1:AE2", true, "SourceItemsArchiveTable").style = "TableStyleMedium4";
  archiveSheet.freezePanes.freezeRows(1);
  archiveSheet.freezePanes.freezeColumns(2);
  archiveSheet.getRange("AB2:AB101").dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$F$2:$F$4" } };
  archiveSheet.getRange("AC2:AC101").dataValidation = { rule: { type: "list", formula1: "'下拉选项'!$E$2:$E$5" } };
  archiveSheet.getRange("AB2:AB101").conditionalFormats.add("containsText", { text: "可生成", format: { fill: "#D9EAD3", font: { color: "#276221" } } });
  archiveSheet.getRange("AB2:AB101").conditionalFormats.add("containsText", { text: "不可生成", format: { fill: "#FCE4D6", font: { color: "#9C0006" } } });

  const riskRows = risks.map((risk) => [risk.riskId, risk.sceneCode, risk.scene, risk.category]);
  riskSheet.getRange("A1:D1").values = [["风险ID", "场景代码", "场景", "类别"]];
  riskSheet.getRange("A2:D32").values = riskRows;
  styleTable(riskSheet, riskSheet.getRange("A1:D1"), riskSheet.getRange("A2:D32"), [14, 13, 30, 52]);
  riskSheet.tables.add("A1:D32", true, "SourceItemsRiskTable").style = "TableStyleMedium9";
  riskSheet.freezePanes.freezeRows(1);

  writeListColumn(listSheet, "A", "授权确认", authorizationValues);
  writeListColumn(listSheet, "B", "来源语言", statusValues.language);
  writeListColumn(listSheet, "C", "素材类型", statusValues.materialType);
  writeListColumn(listSheet, "D", "入库状态", statusValues.intake);
  writeListColumn(listSheet, "E", "提取状态", statusValues.extraction);
  writeListColumn(listSheet, "F", "可生成状态", statusValues.generation);
  writeListColumn(listSheet, "G", "来源地区", statusValues.region);
  writeListColumn(listSheet, "H", "来源路由ID", routeIds);
  writeListColumn(listSheet, "I", "来源ID", sourceIds);
  writeListColumn(listSheet, "J", "风险ID", riskIds);
  writeListColumn(listSheet, "K", "场景", scenes);
  writeListColumn(listSheet, "L", "类别", categories);
  listSheet.getRange("H:H").format.columnWidth = 32;
  listSheet.getRange("L:L").format.columnWidth = 54;
  listSheet.freezePanes.freezeRows(1);

  await fs.mkdir(manualImportDir, { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });
}

await buildWorkbook();
console.log("已生成 data/source_items.xlsx（50 行人工暂存模板）。");

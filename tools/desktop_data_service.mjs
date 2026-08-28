/**
 * 功能:
 *   为 Tkinter 桌面端提供来源、素材和人工入库的本地 JSON 数据服务。
 * 实现:
 *   通过 @oai/artifact-tool 读取/更新本项目内的 Excel 工作簿；命令行仅输出 JSON，
 *   并将全部路径限制在 GenerateTestQuestion 目录中。
 * 输入:
 *   --action snapshot|update-material|stage-intake；可选项目内 JSON 请求文件。
 * 输出:
 *   标准输出 JSON；必要时更新 data/source_items.xlsx 与项目内原始素材档案。
 * 依赖:
 *   Node.js、@oai/artifact-tool 与现有 ingest_source_items.mjs。
 * 用法:
 *   node tools/desktop_data_service.mjs --action snapshot
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import {
  archiveHeaders,
  intakeHeaders,
  isFormulaLikeText,
  readRegistryCatalogs,
  spreadsheetSafeText,
  statusValues,
} from "./source_items_shared.mjs";
import { ingestStagedItems } from "./ingest_source_items.mjs";
import { getSelectionCatalog, readSourceSelection } from "./source_selection_service.mjs";

const applicationRoot = path.resolve(import.meta.dirname, "..");

function asText(value) {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value).trim();
}

function assertProjectRoot(projectRoot) {
  const resolved = path.resolve(projectRoot);
  const relative = path.relative(applicationRoot, resolved);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) return resolved;
  throw new Error("桌面端只能操作 GenerateTestQuestion 项目内的数据");
}

async function loadWorkbook(filePath) {
  return SpreadsheetFile.importXlsx(await FileBlob.load(filePath));
}

async function saveWorkbook(workbook, filePath) {
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(filePath);
  await fs.rm(`${filePath}.inspect.ndjson`, { force: true });
}

function sheetRecords(sheet, headers) {
  const values = sheet.getUsedRange().values;
  if (!values || values.length < 2) return [];
  return values.slice(1)
    .map((row, index) => ({
      excelRow: index + 2,
      fields: Object.fromEntries(headers.map((header, column) => [header, row[column] ?? ""])),
    }))
    .filter((record) => headers.some((header) => asText(record.fields[header]) !== ""));
}

function routeRecord(route) {
  return {
    routeId: route.routeId,
    sourceId: route.sourceId,
    riskId: route.riskId,
    siteName: route.siteName,
    entryUrl: route.entryUrl,
    region: route.region,
    sourceLanguage: route.sourceLanguage,
    scene: route.scene,
    category: route.category,
    outputLanguage: route.outputLanguage ?? "",
    enableStatus: route.enableStatus,
    verificationLevel: route.verificationLevel,
    runGate: route.runGate,
  };
}

function materialRecord(record) {
  const fields = record.fields;
  return {
    materialId: asText(fields["素材ID"]),
    batchId: asText(fields["导入批次ID"]),
    sourceRouteId: asText(fields["来源路由ID"]),
    sourceId: asText(fields["来源ID"]),
    siteName: asText(fields["爬取网站"]),
    sourceUrl: asText(fields["来源链接"]),
    title: asText(fields["标题"]),
    publicationDate: asText(fields["发布时间"]),
    sourceLanguage: asText(fields["来源语言"]),
    materialType: asText(fields["素材类型"]),
    riskId: asText(fields["风险ID"]),
    scene: asText(fields["场景"]),
    category: asText(fields["类别"]),
    generatedMaterial: asText(fields["生成素材"]),
    factPoints: asText(fields["事实要点"]),
    riskTrigger: asText(fields["风险触发点"]),
    suggestedQuestionType: asText(fields["建议题型"]),
    generationStatus: asText(fields["可生成状态"]),
    extractionStatus: asText(fields["提取状态"]),
    rawArchivePath: asText(fields["原始档案路径"]),
  };
}

function makeRouteRows(catalogs) {
  return [...catalogs.routeById.values()]
    .map(routeRecord)
    .sort((left, right) => left.routeId.localeCompare(right.routeId));
}

export async function getDesktopSnapshot(projectRoot = applicationRoot) {
  const safeRoot = assertProjectRoot(projectRoot);
  const [catalogs, selectionCatalog, sourceSelection] = await Promise.all([
    readRegistryCatalogs(safeRoot),
    getSelectionCatalog(safeRoot),
    readSourceSelection(safeRoot),
  ]);
  const sourceItems = await loadWorkbook(path.join(safeRoot, "data", "source_items.xlsx"));
  const materialSheet = sourceItems.worksheets.getItem("素材档案");
  const materials = sheetRecords(materialSheet, archiveHeaders)
    .filter((record) => asText(record.fields["素材ID"]))
    .map(materialRecord)
    .sort((left, right) => left.materialId.localeCompare(right.materialId));
  const routes = makeRouteRows(catalogs);
  const risks = [...catalogs.riskById.values()].map((risk) => ({ ...risk }));
  return {
    summary: {
      routeCount: routes.length,
      enabledRouteCount: routes.filter((route) => route.enableStatus.startsWith("已启用")).length,
      materialCount: materials.length,
      generatableMaterialCount: materials.filter((material) => material.generationStatus === "可生成").length,
      riskCount: risks.length,
    },
    routes,
    materials,
    risks,
    selectionCatalog,
    sourceSelection,
  };
}

function assertSafeMaterialText(name, value) {
  const text = asText(value);
  if (isFormulaLikeText(text)) throw new Error(`${name} 不得以公式字符开头`);
  return text;
}

export async function updateMaterialExtraction(projectRoot = applicationRoot, payload = {}) {
  const safeRoot = assertProjectRoot(projectRoot);
  const materialId = assertSafeMaterialText("素材ID", payload.materialId);
  if (!materialId) throw new Error("素材ID 不能为空");
  const extractionStatus = assertSafeMaterialText("提取状态", payload.extractionStatus);
  const generationStatus = assertSafeMaterialText("可生成状态", payload.generationStatus);
  if (!statusValues.extraction.includes(extractionStatus)) throw new Error("提取状态不是受控选项");
  if (!statusValues.generation.includes(generationStatus)) throw new Error("可生成状态不是受控选项");
  const generatedMaterial = assertSafeMaterialText("生成素材", payload.generatedMaterial);
  const factPoints = assertSafeMaterialText("事实要点", payload.factPoints);
  const riskTrigger = assertSafeMaterialText("风险触发点", payload.riskTrigger);
  const suggestedQuestionType = assertSafeMaterialText("建议题型", payload.suggestedQuestionType);
  if (generationStatus === "可生成" && !generatedMaterial) throw new Error("设为可生成前必须填写生成素材");

  const workbookPath = path.join(safeRoot, "data", "source_items.xlsx");
  const workbook = await loadWorkbook(workbookPath);
  const sheet = workbook.worksheets.getItem("素材档案");
  const records = sheetRecords(sheet, archiveHeaders);
  const target = records.find((record) => asText(record.fields["素材ID"]) === materialId);
  if (!target) throw new Error("未找到指定素材ID");
  const row = archiveHeaders.map((header) => target.fields[header] ?? "");
  const updates = {
    "生成素材": generatedMaterial,
    "事实要点": factPoints,
    "风险触发点": riskTrigger,
    "建议题型": suggestedQuestionType,
    "提取状态": extractionStatus,
    "可生成状态": generationStatus,
  };
  for (const [header, value] of Object.entries(updates)) row[archiveHeaders.indexOf(header)] = spreadsheetSafeText(value);
  sheet.getRange(`A${target.excelRow}:AE${target.excelRow}`).values = [row];
  await saveWorkbook(workbook, workbookPath);
  return { materialId, extractionStatus, generationStatus };
}

function nextIntakeRowId(records) {
  const values = records
    .map((record) => /^INTAKE-(\d{3,})$/u.exec(asText(record.fields["导入行ID"])))
    .filter(Boolean)
    .map((match) => Number(match[1]));
  const nextValue = Math.max(0, ...values) + 1;
  return `INTAKE-${String(nextValue).padStart(3, "0")}`;
}

export async function stageIntakeAndIngest(projectRoot = applicationRoot, payload = {}) {
  const safeRoot = assertProjectRoot(projectRoot);
  const batchId = assertSafeMaterialText("导入批次ID", payload.batchId);
  if (!batchId) throw new Error("导入批次ID 不能为空");
  const workbookPath = path.join(safeRoot, "data", "source_items.xlsx");
  const workbook = await loadWorkbook(workbookPath);
  const sheet = workbook.worksheets.getItem("导入暂存");
  const records = sheetRecords(sheet, intakeHeaders);
  const blankRecord = records.find((record) => {
    const nonControl = intakeHeaders.filter((header) => !["导入行ID", "入库状态", "入库结果"].includes(header));
    return nonControl.every((header) => asText(record.fields[header]) === "");
  });
  const targetRow = blankRecord?.excelRow ?? records.length + 2;
  const row = Object.fromEntries(intakeHeaders.map((header) => [header, ""]));
  const date = new Date().toISOString().slice(0, 10);
  Object.assign(row, payload.row ?? {}, {
    "导入行ID": nextIntakeRowId(records),
    "导入批次ID": batchId,
    "导入日期": date,
    "入库状态": "待入库",
    "入库结果": "",
  });
  for (const header of intakeHeaders) row[header] = spreadsheetSafeText(row[header]);
  sheet.getRange(`A${targetRow}:Z${targetRow}`).values = [intakeHeaders.map((header) => row[header])];
  await saveWorkbook(workbook, workbookPath);
  return ingestStagedItems({ projectRoot: safeRoot, batchId });
}

function parseCli() {
  const args = process.argv.slice(2);
  const actionIndex = args.indexOf("--action");
  const payloadIndex = args.indexOf("--payload-file");
  return {
    action: actionIndex >= 0 ? args[actionIndex + 1] : "snapshot",
    payloadFile: payloadIndex >= 0 ? args[payloadIndex + 1] : "",
  };
}

async function readPayloadFile(payloadFile) {
  if (!payloadFile) return {};
  const resolved = path.resolve(applicationRoot, payloadFile);
  const requestDir = path.resolve(applicationRoot, "data", ".ui_requests");
  const relative = path.relative(requestDir, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("请求文件必须位于 data/.ui_requests/ 内");
  return JSON.parse(await fs.readFile(resolved, "utf8"));
}

async function runCli() {
  const { action, payloadFile } = parseCli();
  const payload = await readPayloadFile(payloadFile);
  if (action === "snapshot") return getDesktopSnapshot(applicationRoot);
  if (action === "update-material") return updateMaterialExtraction(applicationRoot, payload);
  if (action === "stage-intake") return stageIntakeAndIngest(applicationRoot, payload);
  throw new Error(`未知桌面服务动作：${action}`);
}

if (path.resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) {
  try {
    console.log(JSON.stringify(await runCli()));
  } catch (error) {
    console.error(JSON.stringify({ error: error.message }));
    process.exitCode = 1;
  }
}

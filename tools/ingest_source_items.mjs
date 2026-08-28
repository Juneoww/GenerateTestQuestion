/**
 * 功能:
 *   手动将“导入暂存”中的已授权素材写入原始 JSON，并生成无全文的素材档案记录。
 * 实现:
 *   校验来源路由、风险映射、授权范围、正文来源与路径边界；先原子落盘原始 JSON，
 *   再更新 Excel。保存失败时保留原始 JSON，下一次按导入行 ID 和来源 URL 安全恢复。
 * 输入:
 *   --batch-id、data/source_items.xlsx、data/source_registry.xlsx 及 data/manual_import/ 中的 UTF-8 旁车文件。
 * 输出:
 *   data/raw/<批次ID>/<素材ID>.json 和更新后的 data/source_items.xlsx。
 * 依赖:
 *   Node.js、@oai/artifact-tool。
 * 用法:
 *   node tools/ingest_source_items.mjs --batch-id MANUAL-YYYYMMDD-001
 */
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import {
  archiveHeaders,
  authorizationValues,
  buildMaterialId,
  contentHash,
  intakeHeaders,
  isFormulaLikeText,
  normalizationVersions,
  normalizeText,
  normalizeUrl,
  readRegistryCatalogs,
  spreadsheetSafeText,
  statusValues,
} from "./source_items_shared.mjs";

const applicationRoot = path.resolve(import.meta.dirname, "..");
const workbookName = "source_items.xlsx";
const rawSchemaVersion = "SOURCE-ITEM-RAW-V1";
const excelBodyLimit = 32767;

function asText(value) {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value).trim();
}

function assertInsideApplicationRoot(projectRoot) {
  const absoluteRoot = path.resolve(projectRoot);
  const relative = path.relative(applicationRoot, absoluteRoot);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) return absoluteRoot;
  throw new Error("项目根目录必须位于 GenerateTestQuestion 内");
}

function assertBatchId(batchId) {
  const value = asText(batchId);
  if (!/^[A-Za-z0-9_-]{1,80}$/u.test(value)) throw new Error("批次 ID 只能包含字母、数字、下划线和连字符，长度不超过 80");
  return value;
}

function asRecord(headers, values, formulas, excelRow) {
  const safeValues = headers.map((header, index) => {
    const formula = asText(formulas?.[index]);
    if (formula) return formula;
    return values[index] ?? "";
  });
  return {
    excelRow,
    values: safeValues,
    fields: Object.fromEntries(headers.map((header, index) => [header, safeValues[index]])),
  };
}

function isBlankStagingRow(fields) {
  return intakeHeaders
    .filter((header) => !["导入行ID", "入库状态", "入库结果"].includes(header))
    .every((header) => asText(fields[header]) === "");
}

function assertNoFormulaLikeValues(fields) {
  for (const [header, value] of Object.entries(fields)) {
    if (isFormulaLikeText(value)) throw new Error(`${header} 不得使用公式或公式样式文本`);
  }
}

function assertControlledValue(value, allowed, fieldName) {
  if (!allowed.includes(value)) throw new Error(`${fieldName} 必须从受控选项中选择`);
}

function parseDate(value, fieldName) {
  const date = asText(value);
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(date) || Number.isNaN(Date.parse(`${date}T00:00:00Z`))) {
    throw new Error(`${fieldName} 必须为 YYYY-MM-DD`);
  }
  return date;
}

function currentDateString() {
  return new Date().toISOString().slice(0, 10);
}

function urlWithinPrefix(sourceUrl, allowedPrefix) {
  const source = new URL(sourceUrl);
  const prefix = new URL(allowedPrefix);
  if (source.origin !== prefix.origin) return false;
  const prefixPath = prefix.pathname.endsWith("/") ? prefix.pathname : `${prefix.pathname}/`;
  return source.pathname === prefix.pathname || source.pathname.startsWith(prefixPath);
}

function urlMatchesDistributionPattern(sourceUrl, pattern) {
  const value = asText(pattern);
  if (!value) return false;
  const prefix = value.startsWith("prefix:") ? value.slice("prefix:".length) : value;
  try {
    return urlWithinPrefix(sourceUrl, normalizeUrl(prefix));
  } catch {
    return false;
  }
}

function validateRiskAndRoute(fields, catalogs) {
  const routeId = asText(fields["来源路由ID"]);
  const route = catalogs.routeById.get(routeId);
  if (!route) throw new Error("来源路由 ID 不存在于 source_registry.xlsx");
  const risk = catalogs.riskById.get(asText(fields["风险ID"]));
  if (!risk) throw new Error("风险 ID 不存在于风险目录");
  if (asText(fields["来源ID"]) !== route.sourceId) throw new Error("来源 ID 与来源路由不一致");
  if (asText(fields["风险ID"]) !== route.riskId || risk.riskId !== route.riskId) throw new Error("风险 ID 与来源路由不一致");
  if (asText(fields["场景"]) !== risk.scene || asText(fields["场景"]) !== route.scene) throw new Error("场景与来源路由/风险目录不一致");
  if (asText(fields["类别"]) !== risk.category || asText(fields["类别"]) !== route.category) throw new Error("类别与来源路由/风险目录不一致");
  if (asText(fields["来源地区"]) !== route.region) throw new Error("来源地区与来源路由不一致");
  if (asText(fields["来源语言"]) !== route.sourceLanguage) throw new Error("来源语言与来源路由不一致");
  return { route, risk };
}

function validateAuthorization(fields, route, canonicalSourceUrl) {
  const confirmation = asText(fields["授权确认"]);
  assertControlledValue(confirmation, authorizationValues, "授权确认");
  if (confirmation === "V3来源") {
    if (route.verificationLevel !== "V3" || route.enableStatus !== "已启用-受限接口") {
      throw new Error("V3 来源必须使用已启用的 V3 来源路由");
    }
    if (!urlMatchesDistributionPattern(canonicalSourceUrl, route.allowedDistributionUrlPattern)) {
      throw new Error("V3 来源链接未匹配来源路由的许可分发 URL 模式");
    }
    if (!route.allowedFieldScope.includes("允许完整正文归档")) {
      throw new Error("V3 来源路由的许可字段范围不允许完整正文归档");
    }
    return {
      confirmation,
      evidenceId: "",
      evidenceUrl: "",
      urlPrefix: "",
      scope: route.allowedFieldScope,
      confirmer: "",
      confirmationDate: "",
      expiryDate: "",
    };
  }

  const evidenceId = asText(fields["授权证据ID"]);
  const evidenceUrl = normalizeUrl(fields["授权证据URL"]);
  const urlPrefix = normalizeUrl(fields["授权URL前缀"]);
  const scope = asText(fields["授权范围"]);
  const confirmer = asText(fields["确认人"]);
  const confirmationDate = parseDate(fields["确认日期"], "确认日期");
  const expiryDate = parseDate(fields["有效期"], "有效期");
  if (!evidenceId || !confirmer) throw new Error("人工授权必须填写授权证据 ID 和确认人");
  if (!scope.includes("保留全文") || !scope.includes("生成去标识化场景")) {
    throw new Error("人工授权范围必须明确允许保留全文和生成去标识化场景");
  }
  if (!urlWithinPrefix(canonicalSourceUrl, urlPrefix)) throw new Error("来源链接不在人工授权 URL 前缀范围内");
  if (confirmationDate > expiryDate) throw new Error("确认日期不得晚于有效期");
  if (expiryDate < currentDateString()) throw new Error("授权已过期");
  return { confirmation, evidenceId, evidenceUrl, urlPrefix, scope, confirmer, confirmationDate, expiryDate };
}

async function resolveSidecarPath(projectRoot, relativePath) {
  const sourcePath = asText(relativePath);
  if (!sourcePath) throw new Error("原文文件路径不能为空");
  if (path.isAbsolute(sourcePath)) throw new Error("原文文件路径必须是项目内相对路径");
  const segments = sourcePath.replaceAll("\\", "/").split("/");
  if (segments.some((segment) => segment === "..")) throw new Error("原文文件路径不得包含路径穿越");
  const extension = path.extname(sourcePath).toLowerCase();
  if (![".txt", ".md"].includes(extension)) throw new Error("原文文件必须为 UTF-8 .txt 或 .md");

  const manualRoot = path.resolve(projectRoot, "data", "manual_import");
  const resolvedPath = path.resolve(projectRoot, sourcePath);
  const relativeToManualRoot = path.relative(manualRoot, resolvedPath);
  if (!relativeToManualRoot || relativeToManualRoot.startsWith("..") || path.isAbsolute(relativeToManualRoot)) {
    throw new Error("原文文件路径必须位于 data/manual_import/ 内");
  }
  const directoryRealPath = await fs.realpath(manualRoot);
  const stats = await fs.lstat(resolvedPath);
  if (stats.isSymbolicLink()) throw new Error("原文文件不得使用重解析点或符号链接");
  const fileRealPath = await fs.realpath(resolvedPath);
  const realRelative = path.relative(directoryRealPath, fileRealPath);
  if (realRelative.startsWith("..") || path.isAbsolute(realRelative)) throw new Error("原文文件必须实际位于 data/manual_import/ 内");
  return { resolvedPath, projectRelativePath: path.relative(projectRoot, resolvedPath).replaceAll("\\", "/") };
}

async function readUtf8Sidecar(projectRoot, relativePath) {
  const sidecar = await resolveSidecarPath(projectRoot, relativePath);
  const bytes = await fs.readFile(sidecar.resolvedPath);
  let fullText;
  try {
    fullText = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error("原文文件必须是有效 UTF-8 文本");
  }
  return { ...sidecar, fullText };
}

async function findRecoveryRawRecord(rawBatchDir, importRowId, canonicalSourceUrl) {
  try {
    const fileNames = await fs.readdir(rawBatchDir);
    for (const fileName of fileNames) {
      if (!fileName.endsWith(".json")) continue;
      const filePath = path.join(rawBatchDir, fileName);
      const record = JSON.parse(await fs.readFile(filePath, "utf8"));
      if (record.importRowId === importRowId && record.sourceUrl === canonicalSourceUrl) {
        return { filePath, record };
      }
    }
    return null;
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

async function writeRawJsonAtomically(targetPath, payload) {
  await fs.mkdir(path.dirname(targetPath), { recursive: true });
  const temporaryPath = `${targetPath}.${crypto.randomUUID()}.tmp`;
  try {
    await fs.writeFile(temporaryPath, `${JSON.stringify(payload, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
    await fs.rename(temporaryPath, targetPath);
  } finally {
    await fs.rm(temporaryPath, { force: true });
  }
}

async function writeWorkbookDefault(workbook, workbookPath) {
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(workbookPath);
  await fs.rm(`${workbookPath}.inspect.ndjson`, { force: true });
}

function updateStagingRecord(sheet, record, updates) {
  const row = [...record.values];
  for (const [header, value] of Object.entries(updates)) {
    row[intakeHeaders.indexOf(header)] = spreadsheetSafeText(value);
  }
  sheet.getRange(`A${record.excelRow}:Z${record.excelRow}`).values = [row];
}

function makeArchiveRow({ materialId, batchId, fields, route, canonicalSourceUrl, bodyHash, authorization, rawRelativePath }) {
  const values = {
    "素材ID": materialId,
    "导入批次ID": batchId,
    "来源路由ID": asText(fields["来源路由ID"]),
    "来源ID": route.sourceId,
    "爬取网站": route.siteName,
    "来源链接": canonicalSourceUrl,
    "标题": asText(fields["标题"]),
    "发布时间": asText(fields["发布时间"]),
    "抓取日期": currentDateString(),
    "来源地区": route.region,
    "来源语言": route.sourceLanguage,
    "素材类型": asText(fields["素材类型"]),
    "正文哈希": bodyHash,
    "授权证据ID": authorization.evidenceId,
    "授权证据URL": authorization.evidenceUrl,
    "授权URL前缀": authorization.urlPrefix,
    "授权范围": authorization.scope,
    "确认人": authorization.confirmer,
    "确认日期": authorization.confirmationDate,
    "有效期": authorization.expiryDate,
    "风险ID": asText(fields["风险ID"]),
    "场景": asText(fields["场景"]),
    "类别": asText(fields["类别"]),
    "生成素材": "",
    "事实要点": "",
    "风险触发点": "",
    "建议题型": "",
    "可生成状态": "不可生成",
    "提取状态": "待提取",
    "原始档案路径": rawRelativePath,
    "备注": "",
  };
  return archiveHeaders.map((header) => spreadsheetSafeText(values[header] ?? ""));
}

function archiveMaterialIds(archiveSheet) {
  const values = archiveSheet.getUsedRange().values;
  if (!values || values.length < 2) return new Set();
  const ids = values.slice(1).map((row) => asText(row[0])).filter(Boolean);
  return new Set(ids);
}

function appendArchiveRow(archiveSheet, row) {
  const values = archiveSheet.getUsedRange().values;
  const firstBlankIndex = values.slice(1).findIndex((existingRow) => asText(existingRow[0]) === "");
  if (firstBlankIndex >= 0) {
    const excelRow = firstBlankIndex + 2;
    archiveSheet.getRange(`A${excelRow}:AE${excelRow}`).values = [row];
    return;
  }
  const archiveTable = archiveSheet.tables.items.find((table) => table.name === "SourceItemsArchiveTable");
  if (!archiveTable) throw new Error("素材档案表格不存在");
  archiveTable.rows.add(null, [row]);
}

function validateRequiredFields(fields, batchId) {
  const required = ["导入行ID", "来源路由ID", "来源ID", "来源链接", "标题", "来源地区", "来源语言", "素材类型", "授权确认", "风险ID", "场景", "类别", "导入批次ID"];
  for (const field of required) {
    if (!asText(fields[field])) throw new Error(`${field} 为必填项`);
  }
  if (asText(fields["导入批次ID"]) !== batchId) throw new Error("导入批次 ID 必须与本次启动参数一致");
  assertControlledValue(asText(fields["来源地区"]), statusValues.region, "来源地区");
  assertControlledValue(asText(fields["来源语言"]), statusValues.language, "来源语言");
  assertControlledValue(asText(fields["素材类型"]), statusValues.materialType, "素材类型");
  if (asText(fields["入库状态"]) !== "待入库") throw new Error("只有待入库状态可以处理");
  parseDate(fields["发布时间"], "发布时间");
}

async function resolveBody(projectRoot, fields, recoveryRecord) {
  const directBody = fields["原始正文"] === null || fields["原始正文"] === undefined ? "" : String(fields["原始正文"]);
  const sidecarReference = asText(fields["原文文件路径"]);
  const hasDirectBody = directBody !== "";
  const hasSidecar = sidecarReference !== "";
  if (hasDirectBody === hasSidecar) throw new Error("原始正文与原文文件路径必须严格二选一");
  if (hasDirectBody) {
    if (directBody.length > excelBodyLimit) throw new Error(`原始正文不得超过 Excel ${excelBodyLimit} 字符限制`);
    if (isFormulaLikeText(directBody)) throw new Error("原始正文不得为公式或公式样式文本");
    if (recoveryRecord && contentHash(directBody) !== recoveryRecord.contentHash) throw new Error("恢复记录与当前原始正文哈希不一致");
    return { fullText: recoveryRecord?.fullText ?? directBody, sidecar: null };
  }

  let sidecar;
  try {
    sidecar = await readUtf8Sidecar(projectRoot, sidecarReference);
  } catch (error) {
    if (!recoveryRecord || error?.code !== "ENOENT") throw error;
    return { fullText: recoveryRecord.fullText, sidecar: null };
  }
  if (isFormulaLikeText(sidecar.fullText)) throw new Error("原文文件不得以公式或公式样式文本开头");
  if (recoveryRecord && contentHash(sidecar.fullText) !== recoveryRecord.contentHash) throw new Error("恢复记录与当前原文文件哈希不一致");
  return { fullText: recoveryRecord?.fullText ?? sidecar.fullText, sidecar };
}

export async function ingestStagedItems({ projectRoot = applicationRoot, batchId, writeWorkbook = writeWorkbookDefault } = {}) {
  const safeProjectRoot = assertInsideApplicationRoot(projectRoot);
  const safeBatchId = assertBatchId(batchId);
  const workbookPath = path.join(safeProjectRoot, "data", workbookName);
  const rawBatchDir = path.join(safeProjectRoot, "data", "raw", safeBatchId);
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
  const intakeSheet = workbook.worksheets.getItem("导入暂存");
  const archiveSheet = workbook.worksheets.getItem("素材档案");
  const headers = intakeSheet.getRange("A1:Z1").values[0];
  if (JSON.stringify(headers) !== JSON.stringify(intakeHeaders)) throw new Error("source_items.xlsx 的导入暂存字段不符合当前模板");
  const stagingRange = intakeSheet.getRange("A2:Z51");
  const rows = stagingRange.values.map((values, index) => asRecord(intakeHeaders, values, stagingRange.formulas[index], index + 2));
  const catalogs = await readRegistryCatalogs(safeProjectRoot);
  const knownArchiveIds = archiveMaterialIds(archiveSheet);
  const seenStagingIds = new Set();
  const acceptedMaterialIds = new Set();
  const sidecarsToDelete = new Set();
  const acceptedRows = [];
  let rejected = 0;

  for (const record of rows) {
    const fields = record.fields;
    if (asText(fields["入库状态"]) !== "待入库" || isBlankStagingRow(fields)) continue;
    try {
      assertNoFormulaLikeValues(fields);
      validateRequiredFields(fields, safeBatchId);
      const importRowId = asText(fields["导入行ID"]);
      if (seenStagingIds.has(importRowId)) throw new Error("导入行 ID 在同一工作簿中重复");
      seenStagingIds.add(importRowId);
      const canonicalSourceUrl = normalizeUrl(fields["来源链接"]);
      const { route } = validateRiskAndRoute(fields, catalogs);
      const authorization = validateAuthorization(fields, route, canonicalSourceUrl);
      const recovered = await findRecoveryRawRecord(rawBatchDir, importRowId, canonicalSourceUrl);
      const recoveryRecord = recovered?.record ?? null;
      const { fullText, sidecar } = await resolveBody(safeProjectRoot, fields, recoveryRecord);
      if (!normalizeText(fullText)) throw new Error("原始正文不能为空");
      const bodyHash = contentHash(fullText);
      const materialId = buildMaterialId(canonicalSourceUrl, fullText);
      if (knownArchiveIds.has(materialId) || acceptedMaterialIds.has(materialId)) throw new Error("相同规范化链接与正文哈希的素材已入库或正在入库");

      const rawRelativePath = path.join("data", "raw", safeBatchId, `${materialId}.json`).replaceAll("\\", "/");
      const rawPath = path.join(safeProjectRoot, ...rawRelativePath.split("/"));
      let rawRecord = recoveryRecord;
      if (rawRecord) {
        if (rawRecord.materialId !== materialId || rawRecord.contentHash !== bodyHash || rawRecord.sourceUrl !== canonicalSourceUrl) {
          throw new Error("恢复原始 JSON 与当前素材标识不一致");
        }
      } else {
        rawRecord = {
          schemaVersion: rawSchemaVersion,
          materialId,
          importRowId,
          batchId: safeBatchId,
          sourceRouteId: route.routeId,
          sourceId: route.sourceId,
          sourceUrl: canonicalSourceUrl,
          title: asText(fields["标题"]),
          publicationDate: parseDate(fields["发布时间"], "发布时间"),
          sourceRegion: route.region,
          sourceLanguage: route.sourceLanguage,
          materialType: asText(fields["素材类型"]),
          risk: { riskId: asText(fields["风险ID"]), scene: asText(fields["场景"]), category: asText(fields["类别"]) },
          normalization: normalizationVersions,
          contentHash: bodyHash,
          fullText,
          authorization,
          createdAt: new Date().toISOString(),
        };
        await writeRawJsonAtomically(rawPath, rawRecord);
      }

      acceptedMaterialIds.add(materialId);
      acceptedRows.push({ record, fields, route, authorization, materialId, batchId: safeBatchId, canonicalSourceUrl, bodyHash, rawRelativePath });
      if (sidecar) sidecarsToDelete.add(sidecar.resolvedPath);
    } catch (error) {
      rejected += 1;
      updateStagingRecord(intakeSheet, record, { "入库状态": "入库失败", "入库结果": error.message });
    }
  }

  // 旁车文件只作为入库前缓存。所有合格记录已拥有原始 JSON 后才能物理删除。
  for (const sidecarPath of sidecarsToDelete) {
    await fs.rm(sidecarPath);
  }

  for (const accepted of acceptedRows) {
    appendArchiveRow(archiveSheet, makeArchiveRow(accepted));
    updateStagingRecord(intakeSheet, accepted.record, {
      "原始正文": "",
      "原文文件路径": "",
      "入库状态": "入库成功",
      "入库结果": `素材ID: ${accepted.materialId}`,
    });
  }

  await writeWorkbook(workbook, workbookPath);
  return { accepted: acceptedRows.length, rejected };
}

function readCliBatchId() {
  const index = process.argv.indexOf("--batch-id");
  return index >= 0 ? process.argv[index + 1] : "";
}

if (path.resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) {
  const batchId = readCliBatchId();
  const result = await ingestStagedItems({ batchId });
  console.log(`入库完成：成功 ${result.accepted} 条，拒绝 ${result.rejected} 条。`);
}

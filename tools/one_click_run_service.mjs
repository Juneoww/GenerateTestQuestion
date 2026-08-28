/**
 * 功能:
 *   提供“选择网站与五大类风险 → 受控采集 → 生成题库”的单一手动运行入口。
 * 实现:
 *   在任何写入前校验批次、日期、数量、比例和来源/类别交集；随后持久化选择、仅采集允许 JSON
 *   路由，并将去原文上下文交给题库生成器。对桌面端只返回统计、原因和项目内输出路径。
 * 输入:
 *   页面请求 payload、来源登记表、素材档案及可选注入 fetch（仅测试）。
 * 输出:
 *   data/source_selection.json、data/collected_contexts/<批次>.json 和题库 Excel。
 * 依赖:
 *   Node.js crypto/fs/path、来源选择服务、采集器与题库生成器。
 * 用法:
 *   node tools/one_click_run_service.mjs --payload-file data/.ui_requests/<请求ID>.json
 */
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { collectSelectedSources } from "./source_collector_service.mjs";
import {
  assertQuestionRunManifest,
  buildQuestionRunManifest,
  runQuestionBankGeneration,
} from "./question_bank_service.mjs";
import { readRegistryCatalogs } from "./source_items_shared.mjs";
import { saveSourceSelection } from "./source_selection_service.mjs";

const applicationRoot = path.resolve(import.meta.dirname, "..");

function asText(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function stableStrings(values, fieldName) {
  if (!Array.isArray(values)) throw new Error(`${fieldName} 必须是数组`);
  return [...new Set(values.map(asText).filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function assertProjectRoot(projectRoot) {
  const resolved = path.resolve(projectRoot);
  const relative = path.relative(applicationRoot, resolved);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) return resolved;
  throw new Error("一键生成只能操作 GenerateTestQuestion 项目内的数据");
}

function assertBatchId(value) {
  const batchId = asText(value);
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/u.test(batchId)) throw new Error("批次ID必须以字母或数字开头，且只能包含字母、数字、下划线和连字符（3–64位）");
  return batchId;
}

function assertDate(value) {
  const date = asText(value);
  const matched = /^(\d{4})-(\d{2})-(\d{2})$/u.exec(date);
  if (!matched) throw new Error("运行日期必须为真实存在的 YYYY-MM-DD 日历日期");
  const year = Number(matched[1]);
  const month = Number(matched[2]);
  const day = Number(matched[3]);
  const calendar = new Date(Date.UTC(year, month - 1, day));
  if (month < 1 || month > 12 || day < 1 || calendar.getUTCFullYear() !== year || calendar.getUTCMonth() !== month - 1 || calendar.getUTCDate() !== day) {
    throw new Error("运行日期必须为真实存在的 YYYY-MM-DD 日历日期");
  }
  return date;
}

function assertChinesePercent(value) {
  const percent = Number(value);
  if (!Number.isInteger(percent) || percent < 0 || percent > 100) throw new Error("中文占比必须是 0 至 100 的整数");
  return percent;
}

function assertCount(value, minimum) {
  const count = Number(value);
  if (!Number.isInteger(count) || count < minimum || count > 1000) throw new Error(`生成数量必须是 ${minimum} 至 1000 的整数，且不能小于已选风险类别数`);
  return count;
}

function routeWithSceneCode(catalogs) {
  return [...catalogs.routeById.values()].map((route) => ({
    ...route,
    sceneCode: catalogs.riskById.get(route.riskId)?.sceneCode ?? "",
  }));
}

function isSafeRequestUrl(value) {
  try {
    const url = new URL(asText(value));
    return url.protocol === "https:" && (url.port === "" || url.port === "443") && !url.username && !url.password;
  } catch {
    return false;
  }
}

function runnableRoutes(routes, selectedSourceIds, selectedSceneCodes) {
  const sourceIdSet = new Set(selectedSourceIds);
  const sceneCodeSet = new Set(selectedSceneCodes);
  return routes
    .filter((route) => sourceIdSet.has(asText(route.sourceId))
      && sceneCodeSet.has(asText(route.sceneCode))
      && asText(route.enableStatus).startsWith("已启用")
      && asText(route.runGate).startsWith("允许：")
      && isSafeRequestUrl(route.entryUrl))
    .sort((left, right) => asText(left.routeId).localeCompare(asText(right.routeId)));
}

function routeFingerprint(routes) {
  const normalizedRoutes = routes.map((route) => ({
    routeId: asText(route.routeId),
    entryUrl: asText(route.entryUrl),
    enableStatus: asText(route.enableStatus),
    runGate: asText(route.runGate),
  }));
  const canonical = JSON.stringify(normalizedRoutes);
  return crypto.createHash("sha256").update(canonical, "utf8").digest("hex");
}

function compactCollectionResult(result, selectedRouteCount) {
  const outcomes = result.outcomes.map((outcome) => ({
    routeId: asText(outcome.routeId),
    sourceId: asText(outcome.sourceId),
    status: asText(outcome.status),
    reason: asText(outcome.reason),
    contextCount: Number(outcome.contextCount) || 0,
  }));
  return {
    selectedRouteCount,
    attemptedRouteCount: result.attemptedRouteCount,
    successfulRouteCount: result.successfulRouteCount,
    skippedRouteCount: outcomes.filter((outcome) => outcome.status === "skipped").length,
    failedRouteCount: outcomes.filter((outcome) => outcome.status === "failed").length,
    contextCount: result.contexts.length,
    contextFilePath: result.contextFilePath,
    outcomes,
  };
}

export async function runOneClickGeneration({
  projectRoot = applicationRoot,
  payload = {},
  fetchImpl = globalThis.fetch,
  now = () => new Date().toISOString(),
  materials = undefined,
  replaceFile = undefined,
} = {}) {
  const safeRoot = assertProjectRoot(projectRoot);
  const batchId = assertBatchId(payload.batchId);
  const runDate = assertDate(payload.runDate);
  const chinesePercent = assertChinesePercent(payload.chinesePercent);
  const selectedSourceIds = stableStrings(payload.selectedSourceIds, "selectedSourceIds");
  const selectedSceneCodes = stableStrings(payload.selectedSceneCodes, "selectedSceneCodes");
  if (!selectedSourceIds.length) throw new Error("至少选择一个可运行网站");
  if (!selectedSceneCodes.length) throw new Error("至少选择一个一级风险类别");
  const catalogs = await readRegistryCatalogs(safeRoot);
  const risks = [...catalogs.riskById.values()].sort((left, right) => left.riskId.localeCompare(right.riskId));
  const availableSceneCodes = new Set(risks.map((risk) => risk.sceneCode));
  if (!selectedSceneCodes.every((sceneCode) => availableSceneCodes.has(sceneCode))) throw new Error("包含未知一级风险类别");
  const selectedRiskCount = risks.filter((risk) => selectedSceneCodes.includes(risk.sceneCode)).length;
  const totalCount = assertCount(payload.totalCount ?? payload.dailyTarget, selectedRiskCount);
  const routes = routeWithSceneCode(catalogs);
  const selectedRoutes = runnableRoutes(routes, selectedSourceIds, selectedSceneCodes);
  if (!selectedRoutes.length) throw new Error("当前网站与一级风险类别组合没有可运行来源路由");
  const selectedRouteFingerprint = routeFingerprint(selectedRoutes);
  await assertQuestionRunManifest(safeRoot, buildQuestionRunManifest({
    batchId,
    runDate,
    dailyTarget: totalCount,
    chinesePercent,
    selectedSourceIds,
    selectedSceneCodes,
    routeFingerprint: selectedRouteFingerprint,
  }));
  const selection = await saveSourceSelection(safeRoot, { selectedSourceIds, selectedSceneCodes });
  const collectionResult = await collectSelectedSources({
    projectRoot: safeRoot,
    batchId,
    selectedSourceIds,
    selectedSceneCodes,
    routes,
    fetchImpl,
    now,
  });
  const generation = await runQuestionBankGeneration({
    projectRoot: safeRoot,
    batchId,
    runDate,
    dailyTarget: totalCount,
    chinesePercent,
    selectedSourceIds,
    selectedSceneCodes,
    routeFingerprint: selectedRouteFingerprint,
    collectedContexts: collectionResult.contexts,
    materials,
    now,
    ...(replaceFile ? { replaceFile } : {}),
  });
  return {
    selection: {
      selectedSourceIds: selection.selectedSourceIds,
      selectedSceneCodes: selection.selectedSceneCodes,
      selectedRiskCount,
    },
    routeFingerprint: selectedRouteFingerprint,
    collection: compactCollectionResult(collectionResult, selectedRoutes.length),
    generation,
  };
}

function parseCli() {
  const args = process.argv.slice(2);
  const payloadIndex = args.indexOf("--payload-file");
  return { payloadFile: payloadIndex >= 0 ? args[payloadIndex + 1] : "" };
}

async function readPayloadFile(payloadFile) {
  if (!payloadFile) throw new Error("一键生成必须通过项目内请求文件传入参数");
  const resolved = path.resolve(applicationRoot, payloadFile);
  const requestDirectory = path.resolve(applicationRoot, "data", ".ui_requests");
  const relative = path.relative(requestDirectory, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("请求文件必须位于 data/.ui_requests/ 内");
  return JSON.parse(await fs.readFile(resolved, "utf8"));
}

if (path.resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) {
  try {
    const { payloadFile } = parseCli();
    console.log(JSON.stringify(await runOneClickGeneration({ payload: await readPayloadFile(payloadFile) })));
  } catch (error) {
    console.error(JSON.stringify({ error: error.message }));
    process.exitCode = 1;
  }
}

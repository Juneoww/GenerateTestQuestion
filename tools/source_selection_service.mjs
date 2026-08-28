/**
 * 功能:
 *   为一键题库生成提供可运行网站与五大类风险的选择目录，并在项目内保存用户选择。
 * 实现:
 *   从 source_registry.xlsx 读取站点、路由和风险目录，以启用状态与运行门禁计算可选站点；
 *   选择文件使用 JSON 临时文件加重命名写入，且所有路径限制在 GenerateTestQuestion 内。
 * 输入:
 *   data/source_registry.xlsx 与可选的 data/source_selection.json。
 * 输出:
 *   结构化选择目录，以及经严格校验后的 data/source_selection.json。
 * 依赖:
 *   Node.js、@oai/artifact-tool 和 source_items_shared.mjs。
 * 用法:
 *   由 one_click_run_service.mjs 或 desktop_data_service.mjs 导入调用。
 */
import fs from "node:fs/promises";
import path from "node:path";
import { readRegistryCatalogs } from "./source_items_shared.mjs";

const applicationRoot = path.resolve(import.meta.dirname, "..");
const selectionFileName = "source_selection.json";
const selectionFormatVersion = 1;

function asText(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function assertProjectRoot(projectRoot) {
  const resolved = path.resolve(projectRoot);
  const relative = path.relative(applicationRoot, resolved);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) return resolved;
  throw new Error("来源选择只能操作 GenerateTestQuestion 项目内的数据");
}

function stableUnique(values) {
  if (!Array.isArray(values)) return [];
  return [...new Set(values.map(asText).filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function isRunnableRoute(route) {
  return route.enableStatus.startsWith("已启用") && route.runGate.startsWith("允许：");
}

function sortBySourceId(left, right) {
  return left.sourceId.localeCompare(right.sourceId);
}

export async function getSelectionCatalog(projectRoot = applicationRoot) {
  const safeRoot = assertProjectRoot(projectRoot);
  const catalogs = await readRegistryCatalogs(safeRoot);
  const routes = [...catalogs.routeById.values()];
  const scenes = [...new Map(
    [...catalogs.riskById.values()]
      .sort((left, right) => left.riskId.localeCompare(right.riskId))
      .map((risk) => [risk.sceneCode, { sceneCode: risk.sceneCode, scene: risk.scene }]),
  ).values()].sort((left, right) => left.sceneCode.localeCompare(right.sceneCode));
  const riskCountByScene = new Map(scenes.map((scene) => [scene.sceneCode, 0]));
  for (const risk of catalogs.riskById.values()) {
    riskCountByScene.set(risk.sceneCode, (riskCountByScene.get(risk.sceneCode) ?? 0) + 1);
  }

  const sites = [...catalogs.siteById.values()]
    .map((site) => {
      const siteRoutes = routes.filter((route) => route.sourceId === site.sourceId);
      const runnableRoutes = siteRoutes.filter(isRunnableRoute);
      const sourceLanguages = [...new Set(siteRoutes.map((route) => route.sourceLanguage).filter(Boolean))].sort();
      const coveredRiskIds = [...new Set(siteRoutes.map((route) => route.riskId).filter(Boolean))].sort();
      return {
        sourceId: site.sourceId,
        siteName: site.name,
        entryUrl: site.entryUrl,
        sourceLanguages,
        coveredRiskCount: coveredRiskIds.length,
        runnableRouteCount: runnableRoutes.length,
        selectable: runnableRoutes.length > 0,
        status: runnableRoutes.length > 0 ? "可运行" : "门禁未启用",
        latestRun: null,
      };
    })
    .sort(sortBySourceId);

  return {
    formatVersion: selectionFormatVersion,
    sites,
    scenes: scenes.map((scene) => ({ ...scene, riskCount: riskCountByScene.get(scene.sceneCode) ?? 0 })),
    riskCount: catalogs.riskById.size,
    defaultSourceIds: sites.filter((site) => site.selectable).map((site) => site.sourceId),
    defaultSceneCodes: scenes.map((scene) => scene.sceneCode),
  };
}

function selectionPath(projectRoot) {
  return path.join(projectRoot, "data", selectionFileName);
}

function normalizeSelection(catalog, payload = {}) {
  const selectedSourceIds = stableUnique(payload.selectedSourceIds);
  const selectedSceneCodes = stableUnique(payload.selectedSceneCodes);
  const selectableSourceIds = new Set(catalog.sites.filter((site) => site.selectable).map((site) => site.sourceId));
  const knownSceneCodes = new Set(catalog.scenes.map((scene) => scene.sceneCode));

  if (!selectedSourceIds.length) throw new Error("至少选择一个可运行网站");
  if (!selectedSceneCodes.length) throw new Error("至少选择一个一级风险类别");
  if (!selectedSourceIds.every((sourceId) => selectableSourceIds.has(sourceId))) throw new Error("包含不可运行网站");
  if (!selectedSceneCodes.every((sceneCode) => knownSceneCodes.has(sceneCode))) throw new Error("包含未知一级风险类别");
  return { selectedSourceIds, selectedSceneCodes };
}

function defaultSelection(catalog) {
  return {
    formatVersion: selectionFormatVersion,
    selectedSourceIds: catalog.defaultSourceIds,
    selectedSceneCodes: catalog.defaultSceneCodes,
    updatedAt: "",
  };
}

export async function readSourceSelection(projectRoot = applicationRoot) {
  const safeRoot = assertProjectRoot(projectRoot);
  const catalog = await getSelectionCatalog(safeRoot);
  const filePath = selectionPath(safeRoot);
  try {
    const contents = JSON.parse(await fs.readFile(filePath, "utf8"));
    const normalized = normalizeSelection(catalog, contents);
    return {
      formatVersion: selectionFormatVersion,
      ...normalized,
      updatedAt: asText(contents.updatedAt),
    };
  } catch (error) {
    if (error?.code === "ENOENT") return defaultSelection(catalog);
    if (error instanceof SyntaxError) throw new Error("来源选择文件不是有效 JSON");
    throw error;
  }
}

export async function saveSourceSelection(projectRoot = applicationRoot, payload = {}) {
  const safeRoot = assertProjectRoot(projectRoot);
  const catalog = await getSelectionCatalog(safeRoot);
  const normalized = normalizeSelection(catalog, payload);
  const saved = {
    formatVersion: selectionFormatVersion,
    ...normalized,
    updatedAt: new Date().toISOString(),
  };
  const filePath = selectionPath(safeRoot);
  const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(temporaryPath, `${JSON.stringify(saved, null, 2)}\n`, "utf8");
  await fs.rename(temporaryPath, filePath);
  return saved;
}

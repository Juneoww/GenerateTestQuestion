/**
 * 功能:
 *   验证一键生成页面所需的网站与五大类风险选择目录，以及项目内选择持久化。
 * 实现:
 *   在隔离项目副本中读取真实来源登记表，保存合法选择并拒绝未知、候选或空选择。
 * 输入:
 *   data/source_registry.xlsx 与 source_selection_service.mjs。
 * 输出:
 *   tests/ 下临时项目副本；测试结束后删除。
 * 依赖:
 *   Node.js、@oai/artifact-tool。
 * 用法:
 *   node tests/source_selection.integration.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import {
  getSelectionCatalog,
  readSourceSelection,
  saveSourceSelection,
} from "../tools/source_selection_service.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const tempPrefix = path.join(projectRoot, "tests", ".tmp_source_selection_");

async function createFixture() {
  const testRoot = await fs.mkdtemp(tempPrefix);
  await fs.mkdir(path.join(testRoot, "data"), { recursive: true });
  await fs.copyFile(path.join(projectRoot, "data", "source_registry.xlsx"), path.join(testRoot, "data", "source_registry.xlsx"));
  return testRoot;
}

const testRoot = await createFixture();
try {
  const catalog = await getSelectionCatalog(testRoot);
  assert.equal(catalog.sites.length, 15, "选择目录必须保留全部 15 个登记网站");
  assert.deepEqual(catalog.scenes.map((scene) => scene.sceneCode), ["A.1", "A.2", "A.3", "A.4", "A.5"], "选择目录必须提供五个稳定一级类别");
  assert.equal(catalog.riskCount, 31, "选择目录必须保留全部 31 个风险类别");
  assert.deepEqual(catalog.defaultSceneCodes, ["A.1", "A.2", "A.3", "A.4", "A.5"], "首次使用必须默认勾选五大类");
  assert.deepEqual(catalog.sites.filter((site) => site.selectable).map((site) => site.sourceId), ["S12"], "当前仅 S12 应作为可运行网站出现");
  assert.ok(catalog.sites.find((site) => site.sourceId === "S12").runnableRouteCount === 2, "可运行网站必须汇总允许路由数量");

  const initial = await readSourceSelection(testRoot);
  assert.deepEqual(initial.selectedSourceIds, ["S12"], "首次选择必须默认勾选所有可运行网站");
  assert.deepEqual(initial.selectedSceneCodes, ["A.1", "A.2", "A.3", "A.4", "A.5"], "首次选择必须默认勾选五大类");

  const saved = await saveSourceSelection(testRoot, {
    selectedSourceIds: ["S12"],
    selectedSceneCodes: ["A.3", "A.1", "A.3"],
  });
  assert.deepEqual(saved.selectedSourceIds, ["S12"], "保存选择必须去重并稳定排序来源 ID");
  assert.deepEqual(saved.selectedSceneCodes, ["A.1", "A.3"], "保存选择必须去重并稳定排序场景 ID");
  assert.deepEqual(await readSourceSelection(testRoot), saved, "重新读取必须返回项目内已保存选择");

  await assert.rejects(
    saveSourceSelection(testRoot, { selectedSourceIds: ["S01"], selectedSceneCodes: ["A.1"] }),
    /不可运行网站/u,
    "候选来源不得通过 API 绕过选择门禁",
  );
  await assert.rejects(
    saveSourceSelection(testRoot, { selectedSourceIds: ["S12"], selectedSceneCodes: ["A6"] }),
    /未知一级风险类别/u,
    "未知场景不得写入选择文件",
  );
  await assert.rejects(
    saveSourceSelection(testRoot, { selectedSourceIds: [], selectedSceneCodes: ["A.1"] }),
    /至少选择一个可运行网站/u,
    "空网站选择必须被拒绝",
  );
} finally {
  assert.ok(testRoot.startsWith(tempPrefix), "仅删除本测试创建的临时目录");
  await fs.rm(testRoot, { recursive: true, force: true });
}

console.log("PASS source selection: sites, five scenes, defaults, persistence, strict validation");

/**
 * 功能:
 *   验证一键生成编排会保存选择、受控采集、生成题库，并拒绝无交集或非法运行参数。
 * 实现:
 *   在隔离项目副本中注入 JSON fetch mock，检查来源与类别交集、失败采集时的合成补位、
 *   用户可见统计以及任何校验失败都不发布对应批次工作簿。
 * 输入:
 *   data/source_registry.xlsx、data/source_items.xlsx 与 one_click_run_service.mjs。
 * 输出:
 *   tests/ 内临时运行文件（结束后删除）和标准输出测试结果。
 * 依赖:
 *   Node.js、@oai/artifact-tool。
 * 用法:
 *   node tests/one_click_run.integration.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { runOneClickGeneration } from "../tools/one_click_run_service.mjs";
import { readSourceSelection } from "../tools/source_selection_service.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const tempPrefix = path.join(projectRoot, "tests", ".tmp_one_click_");

async function createFixture() {
  const testRoot = await fs.mkdtemp(tempPrefix);
  await fs.mkdir(path.join(testRoot, "data"), { recursive: true });
  await fs.copyFile(path.join(projectRoot, "data", "source_registry.xlsx"), path.join(testRoot, "data", "source_registry.xlsx"));
  await fs.copyFile(path.join(projectRoot, "data", "source_items.xlsx"), path.join(testRoot, "data", "source_items.xlsx"));
  return testRoot;
}

const successfulFetch = async () => new Response(JSON.stringify({
  items: [{ title: "公开案件元数据", abstract: "受控采集器仅保留的公开案件摘要。", datePublished: "2026-08-27" }],
}), { headers: { "content-type": "application/json" } });

const failedFetch = async () => {
  const error = new Error("模拟网络失败");
  error.name = "AbortError";
  throw error;
};

const testRoot = await createFixture();
try {
  const success = await runOneClickGeneration({
    projectRoot: testRoot,
    payload: {
      batchId: "ONECLICK-20260827",
      runDate: "2026-08-27",
      totalCount: 5,
      chinesePercent: 100,
      selectedSourceIds: ["S12"],
      selectedSceneCodes: ["A.3"],
    },
    fetchImpl: successfulFetch,
    now: () => "2026-08-27T12:00:00.000Z",
  });
  assert.equal(success.generation.generatedCount, 5, "一键运行必须按所填数量生成题目");
  assert.equal(success.generation.chineseCount, 5, "100% 中文必须精确生成五道中文题");
  assert.equal(success.collection.selectedRouteCount, 2, "S12 与 A.3 的交集必须仅含两条允许路由");
  assert.equal(success.collection.contextCount, 2, "允许路由的 JSON 元数据必须进入上下文池");
  assert.equal(success.collection.successfulRouteCount, 2, "允许路由应完成受控采集");
  assert.equal(success.generation.sourceCounts.collected, 2, "同风险采集上下文必须优先进入题库");
  assert.equal(success.generation.sourceCounts.synthetic, 3, "没有上下文的风险必须显式合成补位");
  assert.ok(!Object.hasOwn(success.collection, "contexts"), "一键运行的用户结果不得返回采集正文或上下文内容");
  await fs.access(success.generation.incrementalPath);
  await fs.access(success.generation.masterPath);
  await fs.access(success.collection.contextFilePath);
  assert.deepEqual((await readSourceSelection(testRoot)).selectedSceneCodes, ["A.3"], "一键运行必须持久化当前五大类选择");

  let conflictingRunFetchCalls = 0;
  await assert.rejects(
    runOneClickGeneration({
      projectRoot: testRoot,
      payload: {
        batchId: "ONECLICK-20260827",
        runDate: "2026-08-27",
        totalCount: 5,
        chinesePercent: 80,
        selectedSourceIds: ["S12"],
        selectedSceneCodes: ["A.3"],
      },
      fetchImpl: async (...args) => {
        conflictingRunFetchCalls += 1;
        return successfulFetch(...args);
      },
    }),
    /参数与既有清单不一致/u,
    "同批次参数冲突必须在采集前拒绝",
  );
  assert.equal(conflictingRunFetchCalls, 0, "批次参数冲突不得发起新的网络请求或覆盖上下文采集档案");

  await assert.rejects(
    runOneClickGeneration({
      projectRoot: testRoot,
      payload: {
        batchId: "NOINTER-20260827",
        runDate: "2026-08-27",
        totalCount: 8,
        chinesePercent: 80,
        selectedSourceIds: ["S12"],
        selectedSceneCodes: ["A.1"],
      },
      fetchImpl: successfulFetch,
    }),
    /没有可运行来源路由/u,
    "已选网站与一级类别没有允许路由交集时必须拒绝运行",
  );
  await assert.rejects(
    fs.access(path.join(testRoot, "data", "question_bank", "NOINTER-20260827", "question_bank_incremental.xlsx")),
    /ENOENT/u,
    "无来源交集不得创建题库工作簿",
  );

  const allFailed = await runOneClickGeneration({
    projectRoot: testRoot,
    payload: {
      batchId: "FAILED-20260827",
      runDate: "2026-08-27",
      totalCount: 5,
      chinesePercent: 100,
      selectedSourceIds: ["S12"],
      selectedSceneCodes: ["A.3"],
    },
    fetchImpl: failedFetch,
    now: () => "2026-08-27T12:00:00.000Z",
  });
  assert.equal(allFailed.collection.contextCount, 0, "全部采集失败时不能伪造采集上下文");
  assert.equal(allFailed.collection.failedRouteCount, 2, "全部路由失败必须汇总为失败状态");
  assert.deepEqual(allFailed.generation.sourceCounts, { collected: 0, material: 0, synthetic: 5 }, "没有采集上下文和人工素材时必须完整合成补位");

  await assert.rejects(
    runOneClickGeneration({
      projectRoot: testRoot,
      payload: {
        batchId: "BADDATE-20260827",
        runDate: "2026-02-30",
        totalCount: 5,
        chinesePercent: 100,
        selectedSourceIds: ["S12"],
        selectedSceneCodes: ["A.3"],
      },
    }),
    /运行日期/u,
    "编排器必须在采集前拒绝不存在的日历日期",
  );
  await assert.rejects(
    runOneClickGeneration({
      projectRoot: testRoot,
      payload: {
        batchId: "BADCOUNT-20260827",
        runDate: "2026-08-27",
        totalCount: 4,
        chinesePercent: 100,
        selectedSourceIds: ["S12"],
        selectedSceneCodes: ["A.3"],
      },
    }),
    /不能小于/u,
    "编排器必须在采集前拒绝低于风险数的题量",
  );
  await assert.rejects(
    runOneClickGeneration({
      projectRoot: testRoot,
      payload: {
        batchId: "BADPCT-20260827",
        runDate: "2026-08-27",
        totalCount: 5,
        chinesePercent: 50.5,
        selectedSourceIds: ["S12"],
        selectedSceneCodes: ["A.3"],
      },
    }),
    /中文占比/u,
    "编排器必须在采集前拒绝非整数比例",
  );
} finally {
  assert.ok(testRoot.startsWith(tempPrefix), "仅删除本测试创建的临时目录");
  await fs.rm(testRoot, { recursive: true, force: true });
}

console.log("PASS one click: selection, source/category intersection, fallback and output summary");

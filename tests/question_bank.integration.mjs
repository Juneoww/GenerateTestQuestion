/**
 * 功能:
 *   验证题库生成器能按所选五大类、数量和中英文比例生成可追溯题目，并以双工作簿事务发布。
 * 实现:
 *   在隔离项目副本中注入采集上下文和人工素材，覆盖动态风险范围、精确语言配额、三类来源、
 *   批次清单、参数冲突与第二次替换失败时的回滚保护。
 * 输入:
 *   data/source_registry.xlsx、data/source_items.xlsx 与 question_bank_service.mjs。
 * 输出:
 *   tests/ 内临时题库文件（结束后删除）和标准输出测试结果。
 * 依赖:
 *   Node.js 与 @oai/artifact-tool。
 * 用法:
 *   node tests/question_bank.integration.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import { questionHeaders, runQuestionBankGeneration } from "../tools/question_bank_service.mjs";
import { readRegistryCatalogs } from "../tools/source_items_shared.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const tempPrefix = path.join(projectRoot, "tests", ".tmp_question_bank_");

async function createFixture() {
  const testRoot = await fs.mkdtemp(tempPrefix);
  await fs.mkdir(path.join(testRoot, "data"), { recursive: true });
  await fs.copyFile(path.join(projectRoot, "data", "source_registry.xlsx"), path.join(testRoot, "data", "source_registry.xlsx"));
  await fs.copyFile(path.join(projectRoot, "data", "source_items.xlsx"), path.join(testRoot, "data", "source_items.xlsx"));
  return testRoot;
}

async function readQuestionRows(workbookPath) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
  const questionSheet = workbook.worksheets.getItem("题库");
  const values = questionSheet.getUsedRange().values;
  assert.deepEqual(values[0], questionHeaders, "题库列必须稳定，并追加来源溯源字段");
  const formulaErrors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "question bank formula error scan",
  });
  assert.ok(formulaErrors.ndjson.includes("matched 0"), "导出题库不能包含公式错误");
  return values.slice(1).map((row) => Object.fromEntries(questionHeaders.map((header, index) => [header, row[index] ?? ""])));
}

const testRoot = await createFixture();
try {
  const catalogs = await readRegistryCatalogs(testRoot);
  const a3Risks = [...catalogs.riskById.values()]
    .filter((risk) => risk.sceneCode === "A.3")
    .sort((left, right) => left.riskId.localeCompare(right.riskId));
  const allSceneCodes = [...new Set([...catalogs.riskById.values()].map((risk) => risk.sceneCode))].sort();
  assert.equal(a3Risks.length, 5, "A.3 必须有五类风险，作为多选范围测试夹具");

  const collectedRisk = a3Risks[0];
  const materialRisk = a3Risks[1];
  const collectedContexts = [{
    contextId: "CTX-COLLECTED-0001",
    sourceId: "S12",
    routeId: "A3-04-ZH-LOCALIZED-01",
    riskId: collectedRisk.riskId,
    scene: collectedRisk.scene,
    category: collectedRisk.category,
    sourceUrl: "https://collector.example.test/public-metadata",
    retrievedAt: "2026-08-27T12:00:00.000Z",
    publicationDate: "2026-08-26",
    title: "公开案件元数据标题",
    description: "只含允许字段的公开案件元数据摘要。",
  }];
  const materials = [{
    "素材ID": "MAT-TEST-0001",
    "风险ID": materialRisk.riskId,
    "爬取网站": "人工授权素材",
    "来源链接": "https://manual.example.test/approved",
    "抓取日期": "2026-08-27",
    "生成素材": "经过授权审核的去标识化摘要。",
  }];

  const mixed = await runQuestionBankGeneration({
    projectRoot: testRoot,
    batchId: "MIXED-20260827",
    runDate: "2026-08-27",
    dailyTarget: 10,
    chinesePercent: 50,
    selectedSceneCodes: ["A.3"],
    selectedSourceIds: ["S12"],
    routeFingerprint: "ROUTES-SHA256-TEST-1",
    collectedContexts,
    materials,
  });
  assert.equal(mixed.generatedCount, 10, "所选场景必须按指定数量生成");
  assert.equal(mixed.chineseCount, 5, "50% 中文比例必须精确生成五题");
  assert.equal(mixed.englishCount, 5, "50% 中文比例必须精确生成五题英文");
  assert.deepEqual(mixed.sourceCounts, { collected: 2, material: 2, synthetic: 6 }, "每个风险应优先使用采集上下文、再人工素材、最后合成补位");
  await fs.access(mixed.incrementalPath);
  await fs.access(mixed.masterPath);
  await fs.access(mixed.manifestPath);

  const mixedRows = await readQuestionRows(mixed.incrementalPath);
  assert.equal(mixedRows.length, 10, "增量题库必须只导出目标题数");
  assert.equal(new Set(mixedRows.map((row) => row["题目ID"])).size, 10, "题目 ID 必须唯一");
  assert.ok(mixedRows.every((row) => row["风险ID"].startsWith("A3-") && row["场景"] === collectedRisk.scene), "选择 A.3 时不得混入其他一级类别");
  assert.equal(mixedRows.filter((row) => row["题目语言"] === "zh").length, 5, "中文配额必须精确");
  assert.equal(mixedRows.filter((row) => row["题目语言"] === "en").length, 5, "英文配额必须精确");
  assert.equal(mixedRows.filter((row) => row["来源类型"] === "collected").length, 2, "采集上下文必须优先使用");
  assert.equal(mixedRows.filter((row) => row["来源类型"] === "material").length, 2, "采集缺失的风险必须使用可生成素材");
  assert.equal(mixedRows.filter((row) => row["来源类型"] === "synthetic").length, 6, "剩余风险必须显式标记为合成补位");
  assert.ok(mixedRows.filter((row) => row["来源类型"] === "collected").every((row) => row["来源上下文ID"] === "CTX-COLLECTED-0001" && !row["素材ID"]), "采集题必须保留上下文 ID 而不伪造素材 ID");
  assert.ok(mixedRows.filter((row) => row["来源类型"] === "material").every((row) => row["素材ID"] === "MAT-TEST-0001" && !row["来源上下文ID"]), "人工素材题必须保留素材 ID");
  assert.ok(mixedRows.filter((row) => row["来源类型"] === "synthetic").every((row) => row["来源链接"].startsWith("synthetic://")), "合成题必须使用可识别的 synthetic URL");
  assert.equal(new Set(mixedRows.map((row) => `${row["题目语言"]}:${row["问题"]}`)).size, 10, "同语言题目不得重复");

  const manifest = JSON.parse(await fs.readFile(mixed.manifestPath, "utf8"));
  assert.deepEqual(manifest.selectedSceneCodes, ["A.3"], "批次清单必须保留所选一级类别");
  assert.deepEqual(manifest.selectedSourceIds, ["S12"], "批次清单必须保留所选网站");
  assert.equal(manifest.chinesePercent, 50, "批次清单必须保留语言比例");
  assert.equal(manifest.routeFingerprint, "ROUTES-SHA256-TEST-1", "批次清单必须保留路由指纹");

  const baseline = await runQuestionBankGeneration({
    projectRoot: testRoot,
    batchId: "ALL-20260827",
    runDate: "2026-08-27",
    dailyTarget: 155,
    chinesePercent: 80,
    selectedSceneCodes: allSceneCodes,
    selectedSourceIds: ["S12"],
    routeFingerprint: "ROUTES-SHA256-TEST-2",
    collectedContexts: [],
    materials: [],
  });
  assert.equal(baseline.chineseCount, 124, "155 题、80% 中文必须生成 124 道中文题");
  assert.equal(baseline.englishCount, 31, "155 题、80% 中文必须生成 31 道英文题");
  const baselineRows = await readQuestionRows(baseline.incrementalPath);
  assert.equal(new Set(baselineRows.map((row) => row["风险ID"])).size, 31, "全选五大类必须覆盖 31 类风险");
  for (const riskId of new Set(baselineRows.map((row) => row["风险ID"]))) {
    const riskRows = baselineRows.filter((row) => row["风险ID"] === riskId);
    assert.equal(riskRows.length, 5, `${riskId} 必须获得五道均匀配额`);
    assert.equal(riskRows.filter((row) => row["题目语言"] === "zh").length, 4, `${riskId} 必须获得四道中文题`);
    assert.equal(riskRows.filter((row) => row["题目语言"] === "en").length, 1, `${riskId} 必须获得一道英文题`);
  }
  assert.ok(baselineRows.every((row) => row["来源类型"] === "synthetic"), "没有采集上下文和素材时必须显式使用合成补位");

  const masterBeforeRetry = await fs.readFile(baseline.masterPath);
  await runQuestionBankGeneration({
    projectRoot: testRoot,
    batchId: "ALL-20260827",
    runDate: "2026-08-27",
    dailyTarget: 155,
    chinesePercent: 80,
    selectedSceneCodes: allSceneCodes,
    selectedSourceIds: ["S12"],
    routeFingerprint: "ROUTES-SHA256-TEST-2",
    collectedContexts: [],
    materials: [],
  });
  assert.deepEqual(await fs.readFile(baseline.masterPath), masterBeforeRetry, "同参数重试不能向汇总题库重复追加或改变既有版本");
  await assert.rejects(
    runQuestionBankGeneration({
      projectRoot: testRoot,
      batchId: "ALL-20260827",
      runDate: "2026-08-27",
      dailyTarget: 155,
      chinesePercent: 81,
      selectedSceneCodes: allSceneCodes,
      selectedSourceIds: ["S12"],
      routeFingerprint: "ROUTES-SHA256-TEST-2",
    }),
    /参数与既有清单不一致/u,
    "同批次参数冲突必须在发布前拒绝",
  );
  await assert.rejects(
    runQuestionBankGeneration({ projectRoot: testRoot, batchId: "bad id", runDate: "2026-08-27", dailyTarget: 5, chinesePercent: 50, selectedSceneCodes: ["A.3"] }),
    /批次ID/u,
    "批次 ID 必须严格校验",
  );
  await assert.rejects(
    runQuestionBankGeneration({ projectRoot: testRoot, batchId: "DATE-TEST", runDate: "2026-02-30", dailyTarget: 5, chinesePercent: 50, selectedSceneCodes: ["A.3"] }),
    /运行日期/u,
    "不存在的日历日期必须被拒绝",
  );
  await assert.rejects(
    runQuestionBankGeneration({ projectRoot: testRoot, batchId: "COUNT-TEST", runDate: "2026-08-27", dailyTarget: 4, chinesePercent: 50, selectedSceneCodes: ["A.3"] }),
    /不能小于/u,
    "题量不能低于所选风险数",
  );
  await assert.rejects(
    runQuestionBankGeneration({ projectRoot: testRoot, batchId: "PERCENT-TEST", runDate: "2026-08-27", dailyTarget: 5, chinesePercent: 50.5, selectedSceneCodes: ["A.3"] }),
    /中文占比/u,
    "中文比例必须是 0 至 100 的整数",
  );

  const atomic = await runQuestionBankGeneration({
    projectRoot: testRoot,
    batchId: "ATOMIC-20260827",
    runDate: "2026-08-27",
    dailyTarget: 5,
    chinesePercent: 100,
    selectedSceneCodes: ["A.3"],
    selectedSourceIds: ["S12"],
    routeFingerprint: "ROUTES-SHA256-TEST-3",
  });
  const oldIncremental = await fs.readFile(atomic.incrementalPath);
  const oldMaster = await fs.readFile(atomic.masterPath);
  await assert.rejects(
    runQuestionBankGeneration({
      projectRoot: testRoot,
      batchId: "ATOMIC-20260827",
      runDate: "2026-08-27",
      dailyTarget: 5,
      chinesePercent: 100,
      selectedSceneCodes: ["A.3"],
      selectedSourceIds: ["S12"],
      routeFingerprint: "ROUTES-SHA256-TEST-3",
      forceMasterPublish: true,
      replaceFile: async (sourcePath, destinationPath) => {
        if (destinationPath === atomic.masterPath) throw new Error("模拟第二个工作簿替换失败");
        await fs.rename(sourcePath, destinationPath);
      },
    }),
    /模拟第二个工作簿替换失败/u,
    "双工作簿的第二次替换失败必须向调用方报错",
  );
  assert.deepEqual(await fs.readFile(atomic.incrementalPath), oldIncremental, "第二次替换失败后增量工作簿必须回滚为原字节");
  assert.deepEqual(await fs.readFile(atomic.masterPath), oldMaster, "第二次替换失败后汇总工作簿必须回滚为原字节");
} finally {
  assert.ok(testRoot.startsWith(tempPrefix), "仅删除本测试创建的临时目录");
  await fs.rm(testRoot, { recursive: true, force: true });
}

console.log("PASS question bank: selected scenes, exact ratio, source provenance, manifest and atomic rollback");

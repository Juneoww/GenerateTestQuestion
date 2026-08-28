/**
 * 功能:
 *   验证语料采集服务只请求允许的 HTTPS JSON 路由，按中英文比例分配配额，产出正负样本
 *   JSONL 与运行清单，跨批次去重，且只保存白名单上下文（不落原始响应字段）。
 * 实现:
 *   在隔离项目副本中注入 fetch mock，覆盖比例分配、正样本配额、负样本来源、非 JSON、
 *   历史去重与配额缺口报告，不访问真实网络。
 * 输入:
 *   corpus_collector_service.mjs 与模拟路由、模拟 JSON 响应。
 * 输出:
 *   tests/ 下临时 corpus 数据；测试结束后删除。
 * 依赖:
 *   Node.js 24+ 内置 fetch/Response。
 * 用法:
 *   node tests/corpus_collector.integration.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { runCorpusCollection, splitLanguageQuota } from "../tools/corpus_collector_service.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const tempPrefix = path.join(projectRoot, "tests", ".tmp_corpus_collector_");

function positiveRoute(routeId, entryUrl, overrides = {}) {
  return {
    routeId,
    sourceId: "S01",
    siteName: "测试官方处置案例",
    entryUrl,
    riskId: "A1-01",
    sceneCode: "A.1",
    scene: "违反社会主义核心价值观的内容",
    category: "政治有害内容",
    sourceLanguage: "zh",
    outputLanguage: "zh",
    enableStatus: "已启用-人工低频",
    runGate: "允许：仅测试公开 JSON 元数据。",
    ...overrides,
  };
}

function negativeSource(sourceId, entryUrl, outputLanguage) {
  return {
    sourceId,
    siteName: `测试负样本源-${outputLanguage}`,
    entryUrl,
    outputLanguage,
    runGate: "允许：仅测试公开 JSON 元数据。",
  };
}

function zhPayload(items) {
  return {
    fullText: "这段原始响应绝不能写入语料。",
    items: items.map((title) => ({
      title,
      abstract: `公开案件元数据摘要 ${title}`,
      hiddenBody: "禁止持久化",
      datePublished: "2026-08-27",
    })),
  };
}

function wikiPayload(titles) {
  return {
    query: {
      // extract 需超过 minNegativeTextChars（默认 80），模拟真实百科导语长度
      pages: Object.fromEntries(titles.map((title, index) => [index + 1, {
        title,
        extract: `正常百科条目简介：${title} 是一个公开的正常知识条目，涵盖其基本定义、历史沿革、主要特征与代表性事例，内容来源为公开百科全书并采用自由许可协议发布，经过社区多轮审校，适合作为正常语料负样本用于安全评估测试。`,
      }])),
    },
  };
}

async function createFixture() {
  const testRoot = await fs.mkdtemp(tempPrefix);
  await fs.mkdir(path.join(testRoot, "data"), { recursive: true });
  return testRoot;
}

async function readLines(filePath) {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return raw.split("\n").filter(Boolean).map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}

async function readJson(filePath) {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf8"));
  } catch {
    return null;
  }
}

const testRoot = await createFixture();
try {
  // 1) 语言配额分配：默认 7:3
  assert.deepEqual(splitLanguageQuota(200, 70), { zh: 140, en: 60 });
  assert.deepEqual(splitLanguageQuota(201, 70), { zh: 141, en: 60 });
  assert.deepEqual(splitLanguageQuota(200, 0), { zh: 0, en: 200 });
  assert.deepEqual(splitLanguageQuota(200, 100), { zh: 200, en: 0 });

  // 2) 正样本按 riskId × 语言配额采集 + 白名单字段
  const routes = [
    positiveRoute("R-ZH", "https://corpus.example.test/zh"),
    positiveRoute("R-EN", "https://corpus.example.test/en", { sourceId: "S09", outputLanguage: "en", sourceLanguage: "en" }),
  ];
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    if (url.includes("/zh")) return new Response(JSON.stringify(zhPayload(["案例甲", "案例乙", "案例丙"])), { headers: { "content-type": "application/json" } });
    if (url.includes("/en")) return new Response(JSON.stringify(zhPayload(["Case A", "Case B"])), { headers: { "content-type": "application/json" } });
    return new Response("<html>not json</html>", { headers: { "content-type": "text/html" } });
  };
  const first = await runCorpusCollection({
    projectRoot: testRoot,
    batchId: "CORPUS-TEST-001",
    zhPercent: 70,
    targetPerRisk: 200,
    negativeTarget: 0,
    selectedSourceIds: ["S01", "S09"],
    selectedSceneCodes: ["A.1"],
    routes,
    negativeSources: [],
    fetchImpl,
    now: () => "2026-08-28T02:00:00.000Z",
  });
  assert.equal(first.positiveCount, 5, "正样本应全部入库");
  assert.equal(first.negativeCount, 0, "负样本目标为 0 时应为空");
  const positiveLines = await readLines(first.positivePath);
  assert.equal(positiveLines.length, 5);
  for (const item of positiveLines) {
    assert.ok(!item.text.includes("禁止持久化"), "不得保存原始响应字段");
    assert.ok(!item.text.includes("这段原始响应绝不能写入语料"), "不得保存响应全文");
    assert.ok(item.content_hash && item.corpus_id.startsWith("CRP-"), "应有内容哈希与语料 ID");
    assert.equal(item.label_status, "draft", "入库时默认草稿待审核");
  }
  assert.equal(positiveLines.filter((item) => item.language === "zh").length, 3);
  assert.equal(positiveLines.filter((item) => item.language === "en").length, 2);

  // 3) 负样本采集：新批次用全新内容，正负样本都应全部入库
  const negativeSources = [
    negativeSource("WIKI-ZH", "https://corpus.example.test/wiki-zh", "zh"),
    negativeSource("WIKI-EN", "https://corpus.example.test/wiki-en", "en"),
  ];
  const secondFetch = async (url) => {
    if (url.includes("/zh")) {
      return new Response(JSON.stringify(zhPayload(["案例甲", "案例乙", "案例丙", "新增案例一"])), { headers: { "content-type": "application/json" } });
    }
    if (url.includes("/en")) {
      return new Response(JSON.stringify(zhPayload(["Case A", "Case B", "New Case One"])), { headers: { "content-type": "application/json" } });
    }
    if (url.includes("/wiki-zh")) {
      return new Response(JSON.stringify(wikiPayload(["百科条目一", "百科条目二", "百科条目三"])), { headers: { "content-type": "application/json" } });
    }
    if (url.includes("/wiki-en")) {
      return new Response(JSON.stringify(wikiPayload(["Encyclopedia A"])), { headers: { "content-type": "application/json" } });
    }
    return new Response("<html>not json</html>", { headers: { "content-type": "text/html" } });
  };
  const second = await runCorpusCollection({
    projectRoot: testRoot,
    batchId: "CORPUS-TEST-002",
    zhPercent: 70,
    targetPerRisk: 200,
    negativeTarget: 100,
    selectedSourceIds: ["S01", "S09"],
    selectedSceneCodes: ["A.1"],
    routes,
    negativeSources,
    fetchImpl: secondFetch,
    now: () => "2026-08-28T03:00:00.000Z",
  });
  assert.equal(second.positiveCount, 2, "第二批应只入库新增内容（重复 3 条被全局去重跳过）");
  assert.equal(second.negativeCount, 4, "负样本应全部入库");
  const negativeLines = await readLines(second.negativePath);
  assert.equal(negativeLines.length, 4);
  for (const item of negativeLines) {
    assert.equal(item.risk_id, "SAFE", "负样本风险 ID 必须为 SAFE");
    assert.equal(item.label_method, "model", "负样本由模型预标注");
  }

  // 4) 跨批次全局去重：第三批返回第二批已入库的内容时，应全部跳过
  const thirdFetch = async (url) => {
    if (url.includes("/zh")) return new Response(JSON.stringify(zhPayload(["新增案例一"])), { headers: { "content-type": "application/json" } });
    if (url.includes("/en")) return new Response(JSON.stringify(zhPayload(["New Case One"])), { headers: { "content-type": "application/json" } });
    return new Response("<html>not json</html>", { headers: { "content-type": "text/html" } });
  };
  const third = await runCorpusCollection({
    projectRoot: testRoot,
    batchId: "CORPUS-TEST-003",
    zhPercent: 70,
    targetPerRisk: 200,
    negativeTarget: 0,
    selectedSourceIds: ["S01", "S09"],
    selectedSceneCodes: ["A.1"],
    routes,
    negativeSources: [],
    fetchImpl: thirdFetch,
    now: () => "2026-08-28T04:00:00.000Z",
  });
  assert.equal(third.positiveCount, 0, "已入库的重复内容应被全局去重全部跳过");

  // 5) 配额缺口报告：配额不足时产出 shortage_report.json
  const fourthFetch = async (url) => {
    if (url.includes("/en")) return new Response(JSON.stringify(zhPayload(["Only One"])), { headers: { "content-type": "application/json" } });
    return new Response(JSON.stringify(zhPayload(["中文一条"])), { headers: { "content-type": "application/json" } });
  };
  const fourth = await runCorpusCollection({
    projectRoot: testRoot,
    batchId: "CORPUS-TEST-004",
    zhPercent: 70,
    targetPerRisk: 200,
    negativeTarget: 50,
    selectedSourceIds: ["S01", "S09"],
    selectedSceneCodes: ["A.1"],
    routes,
    negativeSources,
    fetchImpl: fourthFetch,
    now: () => "2026-08-28T05:00:00.000Z",
  });
  assert.ok(fourth.shortagePath, "配额不足时必须生成缺口报告");
  const shortage = await readJson(fourth.shortagePath);
  assert.ok(Array.isArray(shortage.shortage) && shortage.shortage.length > 0, "缺口报告应包含缺口明细");
  const zhShortage = shortage.shortage.find((entry) => entry.language === "zh" && entry.riskId === "A1-01");
  assert.ok(zhShortage && zhShortage.target === 140 && zhShortage.collected === 1, "中文正样本配额缺口应被记录");
  const manifest = await readJson(fourth.manifestPath);
  assert.equal(manifest.batchId, "CORPUS-TEST-004");
  assert.equal(manifest.zhPercent, 70);

  // 6) 校验参数
  await assert.rejects(
    runCorpusCollection({ projectRoot: testRoot, batchId: "x", selectedSourceIds: ["S01"], selectedSceneCodes: ["A.1"] }),
    /批次ID/,
  );
  await assert.rejects(
    runCorpusCollection({ projectRoot: testRoot, batchId: "CORPUS-BAD", zhPercent: 101, selectedSourceIds: ["S01"], selectedSceneCodes: ["A.1"] }),
    /中文占比/,
  );
  await assert.rejects(
    runCorpusCollection({ projectRoot: testRoot, batchId: "CORPUS-BAD", targetPerRisk: 0, selectedSourceIds: ["S01"], selectedSceneCodes: ["A.1"] }),
    /目标量/,
  );

  // 7) HTML 列表直采：翻页抓列表 → 详情页提取标题/正文摘要 → 关键词归类 risk_id → source_url 回指详情页
  const htmlSources = [{
    sourceId: "12377-JSAL",
    siteName: "测试警示案例",
    sourceUrl: "https://html.test/list1.html",
    listUrlTemplate: "https://html.test/list{num}.html",
    startPage: 1,
    maxPages: 2,
    itemPattern: 'href="(/art/[a-z0-9]+_web\\.html)"',
    itemUrlBase: "https://html.test",
    outputLanguage: "zh",
    defaultRiskId: "A1-07",
    maxItems: 5,
    runGate: "允许：仅测试公开静态页面。",
  }];
  const htmlClassifier = [
    { riskId: "A1-07", keywords: ["谣言"] },
    { riskId: "A1-06", keywords: ["低俗"] },
  ];
  const htmlFetch = async (url) => {
    if (url.includes("/list1.html")) {
      return new Response(
        '<html><body><a href="/art/aaa_web.html">案例A</a><a href="/art/bbb_web.html">案例B</a><a href="/art/ccc_web.html">案例C</a></body></html>',
        { headers: { "content-type": "text/html" } },
      );
    }
    if (url.includes("/list2.html")) {
      return new Response(
        '<html><body><a href="/art/ddd_web.html">案例D</a><a href="/art/eee_web.html">案例E</a></body></html>',
        { headers: { "content-type": "text/html" } },
      );
    }
    if (url.includes("/art/aaa_web.html")) {
      return new Response('<html><head><title>警方打击网络谣言典型案例</title></head><body><p>编造传播网络谣言扰乱公共秩序。</p><script>var x=1;</script></body></html>', { headers: { "content-type": "text/html" } });
    }
    if (url.includes("/art/bbb_web.html")) {
      return new Response('<html><head><title>低俗直播被处罚</title></head><body><p>主播低俗直播被依法处罚。</p></body></html>', { headers: { "content-type": "text/html" } });
    }
    if (url.includes("/art/")) {
      const id = url.split("/art/")[1].replace("_web.html", "");
      return new Response(`<html><head><title>一般治理动态${id}</title></head><body><p>官方通报治理进展编号${id}。</p></body></html>`, { headers: { "content-type": "text/html" } });
    }
    return new Response("<html>empty</html>", { headers: { "content-type": "text/html" } });
  };
  const htmlRun = await runCorpusCollection({
    projectRoot: testRoot,
    batchId: "CORPUS-TEST-HTML",
    zhPercent: 70,
    targetPerRisk: 200,
    negativeTarget: 0,
    selectedSourceIds: ["12377-JSAL"],
    selectedSceneCodes: ["A.1", "A.2", "A.3", "A.4", "A.5"],
    routes: [],
    negativeSources: [],
    htmlSources,
    classifier: htmlClassifier,
    fetchImpl: htmlFetch,
    now: () => "2026-08-28T06:00:00.000Z",
  });
  assert.equal(htmlRun.positiveCount, 5, "HTML 直采条目应全部入库（列表页 5 个链接、maxItems 5）");
  assert.deepEqual(htmlRun.htmlBySource, { "12377-JSAL|zh": 5 }, "HTML 来源应按 sourceId 独立统计");
  const htmlItems = await readLines(htmlRun.positivePath);
  assert.equal(htmlItems.length, 5);
  const rumorItem = htmlItems.find((item) => item.text.includes("网络谣言"));
  assert.equal(rumorItem.risk_id, "A1-07", "含谣言关键词的条目应归类为 A1-07");
  const vulgarItem = htmlItems.find((item) => item.text.includes("低俗直播"));
  assert.equal(vulgarItem.risk_id, "A1-06", "含低俗关键词的条目应归类为 A1-06");
  for (const item of htmlItems) {
    assert.ok(item.source_url.startsWith("https://html.test/art/"), "source_url 必须回指详情页而非列表页");
    assert.ok(!item.text.includes("var x=1"), "正文摘要不得包含脚本内容");
    assert.ok(!/\n\s*\n/u.test(item.text), "正文摘要不得含连续空行");
    assert.ok(item.text.split("\n").length <= 4, `正文摘要行数应受控（实际 ${item.text.split("\n").length} 行）`);
  }
  assert.equal(rumorItem.text, "警方打击网络谣言典型案例\n编造传播网络谣言扰乱公共秩序。", "正文应去除重复标题与空白噪声");

  // 7b) 英文 HTML 直采：outputLanguage=en + 大小写不敏感关键词归类
  const enSources = [{
    sourceId: "FULLFACT-EN",
    siteName: "测试事实核查",
    sourceUrl: "https://en.test/",
    listUrlTemplate: "https://en.test/",
    startPage: 1,
    maxPages: 1,
    itemPattern: 'href="(/fact/[a-z0-9-]+/)"',
    itemUrlBase: "https://en.test",
    outputLanguage: "en",
    defaultRiskId: "A1-07",
    maxItems: 3,
    runGate: "允许：仅测试公开静态页面。",
  }];
  const enClassifier = [
    { riskId: "A1-07", keywords: ["fake", "hoax"] },
    { riskId: "A3-05", keywords: ["scam", "fraud"] },
  ];
  const enFetch = async (url) => {
    if (url === "https://en.test/") {
      return new Response(
        '<html><body><a href="/fact/fake-claim/">Fake claim</a><a href="/fact/scam-alert/">Scam alert</a><a href="/fact/normal/">Normal note</a></body></html>',
        { headers: { "content-type": "text/html" } },
      );
    }
    if (url.includes("/fact/fake-claim/")) {
      return new Response('<html><head><title>This claim is Fake</title></head><body><p>The viral video is a hoax.</p></body></html>', { headers: { "content-type": "text/html" } });
    }
    if (url.includes("/fact/scam-alert/")) {
      return new Response('<html><head><title>Beware of the SCAM</title></head><body><p>Report FRAUD to authorities.</p></body></html>', { headers: { "content-type": "text/html" } });
    }
    return new Response('<html><head><title>Normal note</title></head><body><p>Weather forecast for tomorrow.</p></body></html>', { headers: { "content-type": "text/html" } });
  };
  const enRun = await runCorpusCollection({
    projectRoot: testRoot,
    batchId: "CORPUS-TEST-EN",
    zhPercent: 0,
    targetPerRisk: 200,
    negativeTarget: 0,
    selectedSourceIds: ["FULLFACT-EN"],
    selectedSceneCodes: ["A.1", "A.2", "A.3", "A.4", "A.5"],
    routes: [],
    negativeSources: [],
    htmlSources: enSources,
    classifier: enClassifier,
    fetchImpl: enFetch,
    now: () => "2026-08-28T07:00:00.000Z",
  });
  assert.equal(enRun.positiveCount, 3, "英文来源条目应全部入库");
  assert.deepEqual(enRun.htmlBySource, { "FULLFACT-EN|en": 3 }, "英文来源应按 en 语言独立统计");
  const enItems = await readLines(enRun.positivePath);
  for (const item of enItems) {
    assert.equal(item.language, "en", "英文来源条目语言应为 en");
  }
  const fakeEn = enItems.find((item) => item.text.includes("This claim is Fake"));
  assert.equal(fakeEn.risk_id, "A1-07", "大小写混合的 Fake/hoax 文本应命中小写关键词归类 A1-07");
  const scamEn = enItems.find((item) => item.text.includes("Beware of the SCAM"));
  assert.equal(scamEn.risk_id, "A3-05", "全大写的 SCAM/FRAUD 应命中小写关键词归类 A3-05");
  const normalEn = enItems.find((item) => item.text.includes("Weather"));
  assert.equal(normalEn.risk_id, "A1-07", "未命中关键词时回退到来源 defaultRiskId");

  // 7c) 负样本最小长度过滤：短于 minNegativeTextChars 的小作品应被跳过且不占配额
  const shortWikiSource = negativeSource("WIKI-SHORT", "https://corpus.example.test/wiki-short", "zh");
  const shortWikiFetch = async (url) => {
    if (url.includes("/wiki-short")) {
      return new Response(JSON.stringify({
        query: {
          pages: {
            1: { title: "短条目", extract: "太短" },
            2: { title: "长条目", extract: "这是一个足够长的正常百科条目简介，其正文内容超过最小长度阈值八十个字符，详细介绍了该条目的定义、历史沿革、主要特征与代表性事例，内容来源为公开百科全书并采用自由许可协议发布，经过社区多轮审校，适合作为正常语料负样本用于验证负样本最小长度过滤逻辑是否按预期工作。" },
          },
        },
      }), { headers: { "content-type": "application/json" } });
    }
    return new Response("<html>not json</html>", { headers: { "content-type": "text/html" } });
  };
  const shortRun = await runCorpusCollection({
    projectRoot: testRoot,
    batchId: "CORPUS-TEST-SHORT",
    zhPercent: 70,
    targetPerRisk: 200,
    negativeTarget: 2,
    minNegativeTextChars: 80,
    selectedSourceIds: [],
    selectedSceneCodes: [],
    routes: [],
    negativeSources: [shortWikiSource],
    fetchImpl: shortWikiFetch,
    now: () => "2026-08-28T08:00:00.000Z",
  });
  const shortItems = await readLines(shortRun.negativePath);
  assert.equal(shortItems.length, 1, "短于阈值的负样本应被过滤，仅保留长条目");
  assert.ok(shortItems[0].text.includes("足够长"), "入库的应是长条目");
  assert.equal(shortRun.outcomes[0].skippedShort, 1, "被跳过的短条目数应记录在 outcomes");

  console.log(JSON.stringify({
    corpus_collector_integration: "passed",
    checks: [
      "language quota 7:3 split",
      "positive quota by risk x language",
      "whitelist fields only",
      "negative SAFE items",
      "cross-batch hash dedup",
      "shortage report",
      "parameter validation",
      "html list direct collection + risk classification",
      "english html source + case-insensitive classification",
      "negative min text length filter",
    ],
  }, null, 2));
} finally {
  // 清理临时目录；若系统安全删除拦截器超时，仅提示路径，不使测试失败。
  try {
    async function removeTree(directory) {
      for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
        const target = path.join(directory, entry.name);
        if (entry.isDirectory()) await removeTree(target);
        else await fs.unlink(target);
      }
      await fs.rmdir(directory);
    }
    await removeTree(testRoot);
  } catch (error) {
    console.warn(`测试临时目录未能自动清理，可手动删除：${testRoot}（${error?.message ?? "未知原因"}）`);
  }
}

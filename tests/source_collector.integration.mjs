/**
 * 功能:
 *   验证一键生成采集器只请求允许的 HTTPS JSON 路由，并且只保存字段白名单上下文。
 * 实现:
 *   在隔离项目副本中注入 fetch mock，覆盖门禁、协议/端口、重定向、非 JSON、大小、超时
 *   和 JSON 候选对象整理规则，不访问真实网络。
 * 输入:
 *   source_collector_service.mjs 与模拟路由、模拟 JSON 响应。
 * 输出:
 *   tests/ 下临时 collected_contexts JSON；测试结束后删除。
 * 依赖:
 *   Node.js 24+ 内置 fetch/Response。
 * 用法:
 *   node tests/source_collector.integration.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { collectSelectedSources, extractContextsFromJson } from "../tools/source_collector_service.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const tempPrefix = path.join(projectRoot, "tests", ".tmp_source_collector_");

function route(routeId, entryUrl, overrides = {}) {
  return {
    routeId,
    sourceId: "S12",
    siteName: "测试公共元数据源",
    entryUrl,
    riskId: "A3-04",
    sceneCode: "A.3",
    scene: "商业违法违规",
    category: "利用算法、数据、平台等优势实施垄断和不正当竞争",
    enableStatus: "已启用-受限接口",
    runGate: "允许：仅测试公开 JSON 元数据。",
    ...overrides,
  };
}

async function createFixture() {
  const testRoot = await fs.mkdtemp(tempPrefix);
  await fs.mkdir(path.join(testRoot, "data"), { recursive: true });
  return testRoot;
}

const longTitle = "标".repeat(300);
const longDescription = "述".repeat(1200);
const validPayload = {
  fullText: "这段原始响应绝不能写入 collected_contexts。",
  items: Array.from({ length: 25 }, (_, index) => ({
    title: index === 0 ? longTitle : `案例 ${index + 1}`,
    abstract: index === 0 ? longDescription : `公开案件元数据摘要 ${index + 1}`,
    datePublished: "2026-08-27",
    hiddenBody: "禁止持久化",
  })),
};

const testRoot = await createFixture();
try {
  const routes = [
    route("R-OK", "https://collector.example.test/allowed"),
    route("R-HTTP", "http://collector.example.test/http"),
    route("R-PORT", "https://collector.example.test:8443/port"),
    route("R-GATE", "https://collector.example.test/gate", { enableStatus: "候选-待核验", runGate: "禁止：测试门禁" }),
    route("R-REDIRECT", "https://collector.example.test/redirect"),
    route("R-NONJSON", "https://collector.example.test/non-json"),
    route("R-OVERSIZE", "https://collector.example.test/oversize"),
    route("R-TIMEOUT", "https://collector.example.test/timeout"),
  ];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/allowed")) {
      return new Response(JSON.stringify(validPayload), { headers: { "content-type": "application/json" } });
    }
    if (url.endsWith("/redirect")) {
      return new Response("", { status: 302, headers: { location: "https://other.example.test/" } });
    }
    if (url.endsWith("/non-json")) {
      return new Response("<html>not json</html>", { headers: { "content-type": "text/html" } });
    }
    if (url.endsWith("/oversize")) {
      return new Response("x".repeat(1_048_577), { headers: { "content-type": "application/json" } });
    }
    if (url.endsWith("/timeout")) {
      const error = new Error("模拟超时");
      error.name = "AbortError";
      throw error;
    }
    throw new Error(`未预期请求：${url}`);
  };

  const result = await collectSelectedSources({
    projectRoot: testRoot,
    batchId: "COLLECT-20260827",
    selectedSourceIds: ["S12"],
    selectedSceneCodes: ["A.3"],
    routes,
    fetchImpl,
    now: () => "2026-08-27T12:00:00.000Z",
  });

  assert.equal(calls.length, 5, "HTTP、非 443 端口和门禁未启用路由必须在请求前被拒绝");
  assert.ok(calls.every((call) => call.options.method === "GET" && call.options.redirect === "error"), "允许请求必须固定为禁止重定向的 GET");
  assert.ok(calls.every((call) => call.options.headers["user-agent"] === "GenerateTestQuestion/1.0"), "允许请求必须使用固定 User-Agent");
  assert.equal(result.contexts.length, 20, "每条路由最多只可整理 20 条上下文");
  assert.equal(new Set(result.contexts.map((context) => context.contextId)).size, 20, "上下文 ID 必须稳定去重");
  assert.ok(result.contexts.every((context) => context.sourceUrl === "https://collector.example.test/allowed"), "上下文来源 URL 必须固定为登记入口而非响应字段");
  assert.equal(result.contexts[0].title.length, 240, "标题必须截断至 240 字符");
  assert.equal(result.contexts[0].description.length, 1000, "描述必须截断至 1000 字符");
  assert.ok(result.outcomes.some((outcome) => outcome.routeId === "R-HTTP" && outcome.status === "skipped"), "HTTP 路由必须留下跳过原因");
  assert.ok(result.outcomes.some((outcome) => outcome.routeId === "R-PORT" && outcome.status === "skipped"), "非 443 端口必须留下跳过原因");
  assert.ok(result.outcomes.some((outcome) => outcome.routeId === "R-GATE" && outcome.status === "skipped"), "门禁未启用路由必须留下跳过原因");
  assert.ok(result.outcomes.some((outcome) => outcome.routeId === "R-REDIRECT" && outcome.status === "failed"), "重定向响应必须失败而不能跟随");
  assert.ok(result.outcomes.some((outcome) => outcome.routeId === "R-NONJSON" && outcome.status === "failed"), "非 JSON 响应必须失败");
  assert.ok(result.outcomes.some((outcome) => outcome.routeId === "R-OVERSIZE" && outcome.status === "failed"), "超限响应必须失败");
  assert.ok(result.outcomes.some((outcome) => outcome.routeId === "R-TIMEOUT" && outcome.status === "failed"), "超时必须失败");

  const persisted = JSON.parse(await fs.readFile(result.contextFilePath, "utf8"));
  const serialized = JSON.stringify(persisted);
  assert.ok(!serialized.includes("fullText") && !serialized.includes("hiddenBody") && !serialized.includes("禁止持久化"), "采集档案不得写入完整响应或未列入白名单字段");
  assert.deepEqual(Object.keys(persisted.contexts[0]).sort(), ["category", "contextId", "description", "publicationDate", "retrievedAt", "riskId", "routeId", "scene", "sourceId", "sourceUrl", "title"].sort(), "上下文只能保存白名单字段");

  const deepPayload = { child: { child: { child: { child: { child: { child: { child: { title: "超过深度限制" } } } } } } } };
  const deepContexts = extractContextsFromJson({ route: routes[0], payload: deepPayload, retrievedAt: "2026-08-27T12:00:00.000Z" });
  assert.equal(deepContexts.length, 0, "超过最大遍历深度的候选对象不得产出上下文");
} finally {
  assert.ok(testRoot.startsWith(tempPrefix), "仅删除本测试创建的临时目录");
  await fs.rm(testRoot, { recursive: true, force: true });
}

console.log("PASS source collector: gate, HTTPS, JSON boundary, BFS extraction, durable audit");

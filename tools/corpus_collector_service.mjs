/**
 * 功能:
 *   一键语料采集服务：按中英文比例（默认中文 70%）分配每类风险配额，从已启用且门禁允许的
 *   HTTPS JSON 路由采集风险正样本，从配置的公开 JSON 源采集正常负样本；跨批次内容哈希去重，
 *   输出 data/corpus/<批次ID>/ 下的正负样本 JSONL、运行清单与配额缺口报告。
 * 实现:
 *   在任何写入前校验批次、比例、数量与来源/类别交集；随后按 riskId × 输出语言计算配额，
 *   逐路由受控采集（限 12 秒、1 MiB、禁止重定向、仅白名单字段），跳过历史已入库内容，
 *   原子写入语料文件并更新全局哈希索引。
 * 输入:
 *   --payload-file 项目内 JSON 请求文件（batchId/zhPercent/targetPerRisk/negativeTarget/
 *   selectedSourceIds/selectedSceneCodes）；可选注入 fetchImpl（仅测试）。
 * 输出:
 *   data/corpus/<批次ID>/{positive_items.jsonl, negative_items.jsonl, run_manifest.json,
 *   shortage_report.json}，并更新 data/corpus/.hash_index.json。
 * 依赖:
 *   Node.js crypto/fs/path、source_items_shared.mjs、source_collector_service.mjs。
 * 用法:
 *   node tools/corpus_collector_service.mjs --payload-file data/.ui_requests/<请求ID>.json
 */
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { readRegistryCatalogs, normalizeText } from "./source_items_shared.mjs";
import { extractContextsFromJson } from "./source_collector_service.mjs";

const applicationRoot = path.resolve(import.meta.dirname, "..");
const maxResponseBytes = 1_048_576;
const requestTimeoutMs = 12_000;
const collectorUserAgent = "GenerateTestQuestion-Corpus/1.0";
const hashIndexFile = ".hash_index.json";
const maxHtmlTextChars = 600; // HTML 正文摘要截断长度（合规：不落原始全文）

/**
 * 默认负样本源：公开、JSON 友好、许可允许再分发（维基百科 CC BY-SA 系列）。
 * 可被 data/corpus/negative_sources.json 覆盖或扩展。
 */
const defaultNegativeSources = Object.freeze([
  {
    sourceId: "WIKI-ZH",
    siteName: "中文维基百科随机条目",
    entryUrl: "https://zh.wikipedia.org/w/api.php?action=query&generator=random&grnnamespace=0&grnlimit=20&prop=extracts&explaintext=1&exintro=1&format=json",
    outputLanguage: "zh",
    runGate: "允许：公开 JSON 接口，许可 CC BY-SA。",
  },
  {
    sourceId: "WIKI-EN",
    siteName: "English Wikipedia random articles",
    entryUrl: "https://en.wikipedia.org/w/api.php?action=query&generator=random&grnnamespace=0&grnlimit=20&prop=extracts&explaintext=1&exintro=1&format=json",
    outputLanguage: "en",
    runGate: "允许：公开 JSON 接口，许可 CC BY-SA。",
  },
]);

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
  throw new Error("语料采集只能操作 GenerateTestQuestion 项目内的数据");
}

function assertBatchId(value) {
  const batchId = asText(value);
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/u.test(batchId)) {
    throw new Error("批次ID必须以字母或数字开头，且只能包含字母、数字、下划线和连字符（3–64位）");
  }
  return batchId;
}

function assertPercent(value) {
  const percent = Number(value);
  if (!Number.isInteger(percent) || percent < 0 || percent > 100) throw new Error("中文占比必须是 0 至 100 的整数");
  return percent;
}

function assertPositiveCount(value) {
  const count = Number(value);
  if (!Number.isInteger(count) || count < 1 || count > 500) throw new Error("每类风险目标量必须是 1 至 500 的整数");
  return count;
}

function assertNegativeCount(value) {
  const count = Number(value);
  if (!Number.isInteger(count) || count < 0 || count > 100_000) throw new Error("负样本目标量必须是 0 至 100000 的整数");
  return count;
}

/** 按中文占比拆分语言配额：中文四舍五入，英文取余。 */
export function splitLanguageQuota(total, zhPercent) {
  const zh = Math.round((total * zhPercent) / 100);
  const en = total - zh;
  return { zh, en };
}

function isRunnableRoute(route) {
  return asText(route.enableStatus).startsWith("已启用") && asText(route.runGate).startsWith("允许：");
}

function isSafeRequestUrl(value) {
  try {
    const url = new URL(asText(value));
    return url.protocol === "https:" && (url.port === "" || url.port === "443") && !url.username && !url.password;
  } catch {
    return false;
  }
}

function contextText(context) {
  const title = asText(context.title);
  const description = asText(context.description);
  return title ? `${title}\n${description}`.trim() : description;
}

function corpusItem({ context, route, batchId, retrievedAt, labelMethod }) {
  const text = contextText(context);
  const hash = crypto.createHash("sha256").update(normalizeText(text), "utf8").digest("hex");
  const corpusId = `CRP-${hash.slice(0, 16).toUpperCase()}`;
  return {
    corpus_id: corpusId,
    risk_id: asText(route.riskId) || "SAFE",
    category: asText(route.category) || "",
    scene: asText(route.scene) || "",
    text,
    source_url: asText(context.sourceUrl) || asText(route.entryUrl),
    source_id: asText(route.sourceId),
    route_id: asText(route.routeId) || "",
    language: asText(route.outputLanguage) || asText(route.sourceLanguage) || "zh",
    label_method: labelMethod,
    label_status: "draft",
    content_hash: hash,
    batch_id: batchId,
    collected_at: retrievedAt,
  };
}

async function readNegativeSources(projectRoot) {
  const configPath = path.join(projectRoot, "data", "corpus", "negative_sources.json");
  try {
    const raw = await fs.readFile(configPath, "utf8");
    const parsed = JSON.parse(raw);
    const sources = Array.isArray(parsed) ? parsed : parsed.sources;
    if (!Array.isArray(sources) || sources.length === 0) return defaultNegativeSources;
    return sources.map((source) => ({ ...defaultNegativeSources[0], ...source }));
  } catch {
    return defaultNegativeSources;
  }
}

/** 读取 HTML 列表直采来源配置（data/corpus/html_sources.json），失败返回空数组。 */
async function readHtmlSources(projectRoot) {
  const configPath = path.join(projectRoot, "data", "corpus", "html_sources.json");
  try {
    const raw = await fs.readFile(configPath, "utf8");
    const parsed = JSON.parse(raw);
    const sources = Array.isArray(parsed) ? parsed : parsed.sources;
    return Array.isArray(sources) ? sources : [];
  } catch {
    return [];
  }
}

/** 读取 HTML 条目风险归类规则（data/corpus/risk_classifier.json），失败返回空规则表。 */
async function readRiskClassifier(projectRoot) {
  const configPath = path.join(projectRoot, "data", "corpus", "risk_classifier.json");
  try {
    const raw = await fs.readFile(configPath, "utf8");
    const parsed = JSON.parse(raw);
    const rules = Array.isArray(parsed) ? parsed : parsed.rules;
    return Array.isArray(rules)
      ? rules
          .map((rule) => ({
            riskId: asText(rule.riskId),
            keywords: Array.isArray(rule.keywords) ? rule.keywords.map(asText).filter(Boolean) : [],
          }))
          .filter((rule) => rule.riskId && rule.keywords.length > 0)
      : [];
  } catch {
    return [];
  }
}

async function loadHashIndex(projectRoot) {
  const indexPath = path.join(projectRoot, "data", "corpus", hashIndexFile);
  try {
    const raw = await fs.readFile(indexPath, "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && parsed.index ? parsed.index : {};
  } catch {
    return {};
  }
}

async function saveHashIndex(projectRoot, index) {
  const directory = path.join(projectRoot, "data", "corpus");
  await fs.mkdir(directory, { recursive: true });
  const filePath = path.join(directory, hashIndexFile);
  const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify({ formatVersion: 1, index }, null, 2)}\n`, "utf8");
  await fs.rename(temporaryPath, filePath);
}

async function readLimitedResponseText(response) {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > maxResponseBytes) {
        await reader.cancel("response too large");
        throw new Error("响应超过 1 MiB 限制");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const combined = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(combined);
}

/**
 * 适配负样本来源的 JSON 形态：维基百科等来源把正文摘录放在 "extract" 字段，
 * 白名单提取器只识别 description/abstract/summary，这里做字段映射后再交给提取器。
 */
function adaptExtractField(value) {
  if (!value || typeof value !== "object") return value;
  if (Array.isArray(value)) {
    value.forEach(adaptExtractField);
    return value;
  }
  if (typeof value.extract === "string" && value.extract.trim()
    && !value.description && !value.abstract && !value.summary) {
    value.abstract = value.extract;
  }
  for (const child of Object.values(value)) {
    if (child && typeof child === "object") adaptExtractField(child);
  }
  return value;
}

async function fetchJsonContexts(route, fetchImpl, retrievedAt, negative = false) {
  const response = await fetchImpl(route.entryUrl, {
    method: "GET",
    redirect: "error",
    headers: { "user-agent": collectorUserAgent },
    signal: AbortSignal.timeout(requestTimeoutMs),
  });
  if (response.status >= 300 && response.status < 400) throw new Error("重定向被拒绝");
  if (!response.ok) throw new Error(`HTTP 状态异常：${response.status}`);
  const contentType = asText(response.headers?.get?.("content-type")).toLowerCase();
  if (!/(^|\s|;)application\/(?:[a-z0-9.+-]+\+)?json(?:\s|;|$)/u.test(contentType)) {
    throw new Error("响应不是 JSON");
  }
  const text = await readLimitedResponseText(response);
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error("响应 JSON 无法解析");
  }
  const source = negative ? adaptExtractField(payload) : payload;
  return extractContextsFromJson({ route, payload: source, retrievedAt });
}

// ---------------------------------------------------------------------------
// HTML 列表直采（无需 JSON API，直接抓静态页面）
// ---------------------------------------------------------------------------

/** 抓取单个 HTML 页面（限大小、限超时、拒绝重定向）。 */
export async function fetchHtmlOnce(url, fetchImpl) {
  const response = await fetchImpl(url, {
    method: "GET",
    redirect: "error",
    headers: { "user-agent": collectorUserAgent },
    signal: AbortSignal.timeout(requestTimeoutMs),
  });
  if (response.status >= 300 && response.status < 400) throw new Error("重定向被拒绝");
  if (!response.ok) throw new Error(`HTTP 状态异常：${response.status}`);
  return readLimitedResponseText(response);
}

/** 提取 <title> 文本。 */
function extractHtmlTitle(html) {
  const match = /<title[^>]*>([\s\S]*?)<\/title>/iu.exec(html);
  return match ? normalizeText(match[1]) : "";
}

/** 网页样板行关键词（短行命中即丢弃：搜索/导航/页脚等）。 */
const htmlBoilerplateLine = /^(搜索|登录|注册|首页|当前位置|分享到|返回|相关阅读|友情链接|网站地图|版权声明|版权所有|关于我们|联系我们|主办单位|承办单位|Copyright|©|All\s+Rights\s+Reserved)/iu;

/** 英文站点导航/菜单噪声行（精确匹配，限短行，避免误杀正文）。 */
const htmlNavNoiseLine = /^(Menu|Donate|Articles|Latest|Fact checks|Analysis|Comment|Government Tracker|Topics|Politics|Health|Immigration|Economy, Business & Finance|Culture & Society|Science & Technology|Environment|Crime|Law|Education|Europe|Online|Search|Subscribe|Newsletter|Sign in|Log in|Skip to content|Main menu|Footer|Home|About|Contact|Press|Privacy|Terms|Accessibility|Cookies)$/iu;

/** 是否为网页样板/导航噪声行（短行命中关键词，或含面包屑分隔符）。 */
function isHtmlBoilerplateLine(line) {
  if (line.length <= 12 && htmlBoilerplateLine.test(line)) return true;
  if (line.length <= 40 && htmlNavNoiseLine.test(line)) return true;
  if (line.length <= 40 && /(>>|›|››)/u.test(line)) return true;
  if (line.length <= 80 && /^Browse\b/u.test(line)) return true; // "Browse our fact checks..." 类导航引导句
  if (line.length <= 160 && /^(Everything we publish|Browse our fact checks|Sign up to our|Get our)/iu.test(line)) return true; // 站点描述/订阅引导句
  if (line.length <= 30 && /^(\/|Fact check|By|Updated|Posted|Share|Share this)/iu.test(line)) return true; // 面包屑/作者/分享元信息
  if (line.length <= 60 && /&bull;/u.test(line)) return true; // "• Crime • 2 mins" 分类/阅读时长元信息
  return false;
}

/**
 * 定位正文主区域：优先 <article>，其次 <main>，否则整页。
 * 英文站点（Full Fact/FTC）导航菜单在 article 之外，切到 article 可大幅降噪；
 * 中文站（12377 等）无 article/main，自动回退整页 + 行过滤，行为不变。
 */
function pickMainRegion(html) {
  const article = /<article[\s>][\s\S]*?<\/article>/iu.exec(html);
  if (article) return article[0];
  const main = /<main[\s>][\s\S]*?<\/main>/iu.exec(html);
  if (main) return main[0];
  return html;
}

/** 去标签提取正文纯文本：优先正文区域，按行清理样板/重复标题，空白归一，截断到 maxHtmlTextChars。 */
export function extractHtmlText(html) {
  const scope = pickMainRegion(html);
  const text = scope
    .replace(/<script[\s\S]*?<\/script>/giu, " ")
    .replace(/<style[\s\S]*?<\/style>/giu, " ")
    .replace(/<!--[\s\S]*?-->/gu, " ")
    .replace(/<[^>]+>/gu, "\n")
    .replace(/&nbsp;/gu, " ")
    .replace(/&amp;/gu, "&")
    .replace(/&lt;/gu, "<")
    .replace(/&gt;/gu, ">")
    .replace(/&quot;/gu, '"')
    .replace(/&#0*39;/gu, "'");
  const title = extractHtmlTitle(html);
  const cleaned = [];
  for (const rawLine of text.split("\n")) {
    const line = normalizeText(rawLine).replace(/[ \t]+/gu, " ");
    if (!line) continue;
    if (isHtmlBoilerplateLine(line)) continue;
    if (title && line === title) continue; // 与页面标题重复（head/h1），正文摘要不再保留标题副本
    if (cleaned.length > 0 && cleaned[cleaned.length - 1] === line) continue; // 连续重复行
    cleaned.push(line);
  }
  return cleaned.join("\n").slice(0, maxHtmlTextChars);
}

/** 按正则提取页面内链接并绝对化、去重。 */
export function extractHtmlLinks(html, pattern, baseUrl) {
  let regex;
  try {
    regex = new RegExp(pattern, "gu");
  } catch {
    return [];
  }
  const seen = new Set();
  const links = [];
  for (const match of html.matchAll(regex)) {
    const href = asText(match[1]);
    if (!href || href === "#" || href.startsWith("javascript:")) continue;
    try {
      const url = new URL(href, baseUrl);
      if (url.protocol !== "https:" && url.protocol !== "http:") continue;
      const absolute = url.href;
      if (!seen.has(absolute)) {
        seen.add(absolute);
        links.push(absolute);
      }
    } catch {
      // 跳过非法链接
    }
  }
  return links;
}

/**
 * 从 HTML 列表来源采集条目：翻页抓列表页 → 提取文章链接 → 逐条抓详情页 →
 * 产出 {title, description, sourceUrl} 上下文（仅标题 + 正文摘要，原始全文不落盘）。
 * 单条详情失败仅跳过，不中断整批。
 */
export async function fetchHtmlContexts(htmlSource, fetchImpl, retrievedAt) {
  const startPage = Number(htmlSource.startPage) > 0 ? Number(htmlSource.startPage) : 1;
  const maxPages = Number(htmlSource.maxPages) > 0 ? Number(htmlSource.maxPages) : 1;
  const maxItems = Number(htmlSource.maxItems) > 0 ? Number(htmlSource.maxItems) : 20;
  const baseUrl = asText(htmlSource.itemUrlBase) || asText(htmlSource.listUrlTemplate) || "https://example.invalid/";
  const contexts = [];
  const seenUrls = new Set();

  for (let page = startPage; page < startPage + maxPages && contexts.length < maxItems; page += 1) {
    const pageUrl = asText(htmlSource.listUrlTemplate).replaceAll("{num}", String(page));
    let listHtml;
    try {
      listHtml = await fetchHtmlOnce(pageUrl, fetchImpl);
    } catch (error) {
      if (page === startPage) throw error;
      break; // 翻页失败视为已到底
    }
    const links = extractHtmlLinks(listHtml, asText(htmlSource.itemPattern), baseUrl);
    if (links.length === 0) break;
    for (const link of links) {
      if (contexts.length >= maxItems) break;
      if (seenUrls.has(link)) continue;
      seenUrls.add(link);
      try {
        const detailHtml = await fetchHtmlOnce(link, fetchImpl);
        const title = extractHtmlTitle(detailHtml);
        const description = extractHtmlText(detailHtml);
        if (!title && !description) continue;
        contexts.push({ title, description, sourceUrl: link });
      } catch {
        // 单条详情失败跳过
      }
    }
  }
  if (contexts.length === 0) throw new Error("未提取到任何条目");
  return contexts;
}

/** 把 HTML 来源转换为虚拟路由，接入现有正样本采集流程。 */
function htmlSourceToRoute(source) {
  const riskId = asText(source.defaultRiskId) || "A1-07";
  return {
    routeId: `HTML-${asText(source.sourceId)}`,
    sourceId: asText(source.sourceId),
    siteName: asText(source.siteName),
    entryUrl: asText(source.sourceUrl) || asText(source.listUrlTemplate),
    riskId,
    category: asText(source.category) || "",
    scene: asText(source.scene) || "",
    sceneCode: asText(source.sceneCode) || "",
    outputLanguage: asText(source.outputLanguage) || "zh",
    sourceLanguage: asText(source.outputLanguage) || "zh",
    enableStatus: "已启用",
    runGate: asText(source.runGate) || "允许：公开静态页面。",
    htmlList: source,
  };
}

/** 按归类规则表对 HTML 条目做风险归类：首个命中规则胜出，未命中回退 defaultRiskId。 */
function classifyHtmlItem(text, classifier, defaultRiskId) {
  const haystack = String(text ?? "").toLowerCase();
  for (const rule of classifier) {
    if (rule.keywords.some((keyword) => haystack.includes(String(keyword).toLowerCase()))) return rule.riskId;
  }
  return defaultRiskId;
}

function routeWithSceneCode(catalogs) {
  return [...catalogs.routeById.values()].map((route) => ({
    ...route,
    sceneCode: catalogs.riskById.get(route.riskId)?.sceneCode ?? "",
  }));
}

function candidatePositiveRoutes(routes, selectedSourceIds, selectedSceneCodes) {
  const sourceIds = new Set(stableStrings(selectedSourceIds, "selectedSourceIds"));
  const sceneCodes = new Set(stableStrings(selectedSceneCodes, "selectedSceneCodes"));
  return routes
    .filter((route) => sourceIds.has(asText(route.sourceId))
      && (route.htmlList || sceneCodes.has(asText(route.sceneCode)))
      && isRunnableRoute(route)
      && isSafeRequestUrl(route.entryUrl))
    .sort((left, right) => asText(left.routeId).localeCompare(asText(right.routeId)));
}

async function appendLines(filePath, items) {
  if (items.length === 0) return;
  const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  const lines = items.map((item) => `${JSON.stringify(item, null, 0)}\n`).join("");
  await fs.writeFile(temporaryPath, lines, "utf8");
  await fs.rename(temporaryPath, filePath);
}

async function writeJson(filePath, payload) {
  const directory = path.dirname(filePath);
  await fs.mkdir(directory, { recursive: true });
  const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await fs.rename(temporaryPath, filePath);
}

/**
 * 执行一次语料采集批次。正样本按 riskId × 语言配额采集；负样本按语言配额从负样本源采集；
 * 全局哈希去重（历史批次已入库内容跳过）；配额不足时产出缺口报告。
 */
export async function runCorpusCollection({
  projectRoot = applicationRoot,
  batchId,
  zhPercent = 70,
  targetPerRisk = 200,
  negativeTarget = 0,
  minNegativeTextChars = 80,
  selectedSourceIds,
  selectedSceneCodes,
  routes = null,
  negativeSources = null,
  htmlSources = null,
  classifier = null,
  fetchImpl = globalThis.fetch,
  now = () => new Date().toISOString(),
  delayMs = 0,
} = {}) {
  const safeRoot = assertProjectRoot(projectRoot);
  const safeBatchId = assertBatchId(batchId);
  const safeZhPercent = assertPercent(zhPercent);
  const safeTargetPerRisk = assertPositiveCount(targetPerRisk);
  const safeNegativeTarget = assertNegativeCount(negativeTarget);
  if (typeof fetchImpl !== "function") throw new Error("当前运行环境不支持 fetch");

  const catalogs = routes ? { riskById: new Map(), routeById: new Map(routes.map((route) => [asText(route.routeId), route])) } : await readRegistryCatalogs(safeRoot);
  const registryRoutes = routes ?? routeWithSceneCode(catalogs);
  const htmlSourceList = htmlSources ?? await readHtmlSources(safeRoot);
  const htmlRoutes = htmlSourceList.map(htmlSourceToRoute);
  const riskClassifier = classifier ?? await readRiskClassifier(safeRoot);
  const positiveRoutes = [...registryRoutes, ...htmlRoutes];
  const selectedRoutes = candidatePositiveRoutes(positiveRoutes, selectedSourceIds, selectedSceneCodes);
  const negativeSourceList = negativeSources ?? await readNegativeSources(safeRoot);

  const positiveQuotaByRisk = new Map();
  for (const route of selectedRoutes) {
    if (route.htmlList) continue; // HTML 路由按来源配额，见 htmlCollected
    const riskId = asText(route.riskId);
    if (!positiveQuotaByRisk.has(riskId)) positiveQuotaByRisk.set(riskId, splitLanguageQuota(safeTargetPerRisk, safeZhPercent));
  }
  const negativeQuota = splitLanguageQuota(safeNegativeTarget, safeZhPercent);

  const hashIndex = await loadHashIndex(safeRoot);
  const positiveItems = [];
  const negativeItems = [];
  const outcomes = [];
  const shortage = [];
  const positiveCollected = new Map(); // key: riskId|language
  const htmlCollected = new Map(); // key: sourceId|language（HTML 直采，按来源配额）
  const negativeCollected = { zh: 0, en: 0 };
  const retrievedAt = asText(now());

  const delay = (ms) => (ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve());
  const sleep = delay(delayMs);

  for (const route of selectedRoutes) {
    if (route.htmlList) {
      // HTML 直采：按来源配额，条目风险按关键词归类表自动归类
      const sourceId = asText(route.sourceId);
      const language = asText(route.outputLanguage) || "zh";
      const maxItems = Number(route.htmlList.maxItems) > 0 ? Number(route.htmlList.maxItems) : 20;
      const key = `${sourceId}|${language}`;
      const current = htmlCollected.get(key) ?? 0;
      if (current >= maxItems) {
        outcomes.push({ routeId: asText(route.routeId), sourceId, riskId: "MIXED", status: "skipped", reason: "HTML 来源配额已满" });
        continue;
      }
      try {
        const contexts = await fetchHtmlContexts(route.htmlList, fetchImpl, retrievedAt);
        let accepted = 0;
        for (const context of contexts) {
          if ((htmlCollected.get(key) ?? 0) >= maxItems) break;
          const itemRiskId = classifyHtmlItem(contextText(context), riskClassifier, asText(route.riskId));
          const item = corpusItem({ context, route: { ...route, riskId: itemRiskId, category: "", scene: "" }, batchId: safeBatchId, retrievedAt, labelMethod: "official_case" });
          if (hashIndex[item.content_hash]) continue;
          positiveItems.push(item);
          hashIndex[item.content_hash] = { corpusId: item.corpus_id, riskId: itemRiskId, batchId: safeBatchId };
          htmlCollected.set(key, (htmlCollected.get(key) ?? 0) + 1);
          accepted += 1;
          await sleep;
        }
        outcomes.push({ routeId: asText(route.routeId), sourceId, riskId: "MIXED", status: "collected", contextCount: contexts.length, accepted });
      } catch (error) {
        outcomes.push({ routeId: asText(route.routeId), sourceId, riskId: "MIXED", status: "failed", reason: asText(error?.message) || "HTML 采集请求失败" });
      }
      continue;
    }
    const riskId = asText(route.riskId);
    const language = asText(route.outputLanguage) || "zh";
    const quota = positiveQuotaByRisk.get(riskId) ?? { zh: 0, en: 0 };
    const key = `${riskId}|${language}`;
    const current = positiveCollected.get(key) ?? 0;
    if (current >= quota[language]) {
      outcomes.push({ routeId: asText(route.routeId), sourceId: asText(route.sourceId), riskId, status: "skipped", reason: "语言配额已满" });
      continue;
    }
    try {
      const contexts = await fetchJsonContexts(route, fetchImpl, retrievedAt);
      let accepted = 0;
      for (const context of contexts) {
        if ((positiveCollected.get(key) ?? 0) >= quota[language]) break;
        const item = corpusItem({ context, route, batchId: safeBatchId, retrievedAt, labelMethod: "official_case" });
        if (hashIndex[item.content_hash]) continue; // 历史已入库
        positiveItems.push(item);
        hashIndex[item.content_hash] = { corpusId: item.corpus_id, riskId, batchId: safeBatchId };
        positiveCollected.set(key, (positiveCollected.get(key) ?? 0) + 1);
        accepted += 1;
        await sleep;
      }
      outcomes.push({ routeId: asText(route.routeId), sourceId: asText(route.sourceId), riskId, status: "collected", contextCount: contexts.length, accepted });
    } catch (error) {
      outcomes.push({ routeId: asText(route.routeId), sourceId: asText(route.sourceId), riskId, status: "failed", reason: asText(error?.message) || "采集请求失败" });
    }
  }

  for (const source of negativeSourceList) {
    const language = asText(source.outputLanguage) || "zh";
    if (safeNegativeTarget === 0 || negativeCollected[language] >= negativeQuota[language]) {
      outcomes.push({ routeId: asText(source.routeId) || `SAFE-${asText(source.sourceId)}`, sourceId: asText(source.sourceId), riskId: "SAFE", status: "skipped", reason: "负样本配额已满或未启用" });
      continue;
    }
    const route = { ...source, riskId: "SAFE", scene: "正常语料", category: "正常语料", routeId: asText(source.routeId) || `SAFE-${asText(source.sourceId)}` };
    // 多轮请求直到语言配额满：随机条目接口单轮最多 20 条，需重复请求凑足大批量。
    // 连续 3 轮零新增（全重复/空响应）则放弃该来源，避免死循环。
    // 请求失败（429 限流/5xx）按指数退避重试，连续 5 次失败才放弃。
    let totalContexts = 0;
    let accepted = 0;
    let skippedShort = 0;
    let rounds = 0;
    let emptyRounds = 0;
    let failureStreak = 0;
    let lastFailure = null;
    while (negativeCollected[language] < negativeQuota[language] && emptyRounds < 3 && failureStreak < 5) {
      let contexts = [];
      try {
        contexts = await fetchJsonContexts(route, fetchImpl, retrievedAt, true);
        failureStreak = 0;
      } catch (error) {
        failureStreak += 1;
        lastFailure = asText(error?.message) || "采集请求失败";
        await delay(Math.min(2000 * 2 ** (failureStreak - 1), 32000)); // 2s→32s 指数退避
        continue;
      }
      rounds += 1;
      totalContexts += contexts.length;
      let roundAccepted = 0;
      let roundSkippedShort = 0;
      for (const context of contexts) {
        if (negativeCollected[language] >= negativeQuota[language]) break;
        const item = corpusItem({ context, route, batchId: safeBatchId, retrievedAt, labelMethod: "model" });
        if (hashIndex[item.content_hash]) continue;
        // 最小长度过滤：维基小作品（<80 字符）作为负样本价值低，跳过并记入哈希避免重复抓取
        if (item.text.length < minNegativeTextChars) {
          hashIndex[item.content_hash] = { corpusId: item.corpus_id, riskId: "SAFE", batchId: safeBatchId };
          roundSkippedShort += 1;
          continue;
        }
        negativeItems.push(item);
        hashIndex[item.content_hash] = { corpusId: item.corpus_id, riskId: "SAFE", batchId: safeBatchId };
        negativeCollected[language] += 1;
        roundAccepted += 1;
        accepted += 1;
        await sleep;
      }
      skippedShort += roundSkippedShort;
      if (contexts.length === 0 || (roundAccepted === 0 && roundSkippedShort === 0)) emptyRounds += 1;
      else if (roundAccepted === 0 && roundSkippedShort > 0) emptyRounds += 1; // 全是短文本小作品，同样计零进展轮
      else emptyRounds = 0;
      // 轮间礼貌延时（至少 500ms），公开接口限流保护（429）
      if (negativeCollected[language] < negativeQuota[language] && emptyRounds < 3 && failureStreak < 5) {
        await delay(Math.max(delayMs, 500));
      }
    }
    if (failureStreak >= 5 || (accepted === 0 && lastFailure)) {
      outcomes.push({ routeId: route.routeId, sourceId: asText(source.sourceId), riskId: "SAFE", status: "failed", reason: lastFailure, rounds, accepted, skippedShort });
    } else {
      outcomes.push({ routeId: route.routeId, sourceId: asText(source.sourceId), riskId: "SAFE", status: "collected", contextCount: totalContexts, accepted, rounds, skippedShort });
    }
  }

  // 配额缺口统计
  for (const [riskId, quota] of positiveQuotaByRisk) {
    for (const language of ["zh", "en"]) {
      const collected = positiveCollected.get(`${riskId}|${language}`) ?? 0;
      if (collected < quota[language]) {
        shortage.push({ riskId, language, target: quota[language], collected });
      }
    }
  }
  for (const route of selectedRoutes) {
    if (!route.htmlList) continue;
    const sourceId = asText(route.sourceId);
    const language = asText(route.outputLanguage) || "zh";
    const maxItems = Number(route.htmlList.maxItems) > 0 ? Number(route.htmlList.maxItems) : 20;
    const collected = htmlCollected.get(`${sourceId}|${language}`) ?? 0;
    if (collected < maxItems) {
      shortage.push({ riskId: asText(route.riskId), sourceId, language, target: maxItems, collected });
    }
  }
  if (safeNegativeTarget > 0) {
    for (const language of ["zh", "en"]) {
      if (negativeCollected[language] < negativeQuota[language]) {
        shortage.push({ riskId: "SAFE", language, target: negativeQuota[language], collected: negativeCollected[language] });
      }
    }
  }

  const corpusDir = path.join(safeRoot, "data", "corpus", safeBatchId);
  await fs.mkdir(corpusDir, { recursive: true });
  const positivePath = path.join(corpusDir, "positive_items.jsonl");
  const negativePath = path.join(corpusDir, "negative_items.jsonl");
  const manifestPath = path.join(corpusDir, "run_manifest.json");
  const shortagePath = path.join(corpusDir, "shortage_report.json");

  await appendLines(positivePath, positiveItems);
  await appendLines(negativePath, negativeItems);
  await saveHashIndex(safeRoot, hashIndex);

  const manifest = {
    formatVersion: 1,
    batchId: safeBatchId,
    collectedAt: retrievedAt,
    zhPercent: safeZhPercent,
    targetPerRisk: safeTargetPerRisk,
    negativeTarget: safeNegativeTarget,
    selectedSourceIds: stableStrings(selectedSourceIds, "selectedSourceIds"),
    selectedSceneCodes: stableStrings(selectedSceneCodes, "selectedSceneCodes"),
    positiveCount: positiveItems.length,
    negativeCount: negativeItems.length,
    positiveByRisk: Object.fromEntries(
      [...positiveCollected.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([key, count]) => [key, count]),
    ),
    htmlBySource: Object.fromEntries(
      [...htmlCollected.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([key, count]) => [key, count]),
    ),
    negativeByLanguage: { ...negativeCollected },
    outcomeCount: outcomes.length,
    shortageCount: shortage.length,
  };
  await writeJson(manifestPath, manifest);
  if (shortage.length > 0) {
    await writeJson(shortagePath, { batchId: safeBatchId, collectedAt: retrievedAt, shortage });
  }

  return {
    ...manifest,
    positivePath,
    negativePath,
    manifestPath,
    shortagePath: shortage.length > 0 ? shortagePath : null,
    outcomes,
    shortage,
  };
}

async function main() {
  const argumentsList = process.argv.slice(2);
  const payloadIndex = argumentsList.indexOf("--payload-file");
  const payloadPath = payloadIndex >= 0 ? argumentsList[payloadIndex + 1] : null;
  let payload = {};
  if (payloadPath) {
    const resolved = path.resolve(applicationRoot, payloadPath);
    const relative = path.relative(applicationRoot, resolved);
    if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("请求文件必须在项目目录内");
    payload = JSON.parse(await fs.readFile(resolved, "utf8"));
  }
  const result = await runCorpusCollection({ projectRoot: applicationRoot, ...payload });
  console.log(JSON.stringify(result, null, 2));
}

/** 检测到系统代理但当前 Node 未启用时，以 --use-env-proxy 重启自身。 */
function ensureEnvProxy() {
  const hasProxy = ["HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"].some((name) => process.env[name]);
  const alreadyEnabled = process.execArgv.includes("--use-env-proxy")
    || (process.env.NODE_OPTIONS ?? "").includes("--use-env-proxy")
    || process.env.CORPUS_FETCH_REEXEC === "1";
  if (!hasProxy || alreadyEnabled) return;
  process.env.CORPUS_FETCH_REEXEC = "1";
  const require = createRequire(import.meta.url);
  const { spawnSync } = require("node:child_process");
  const result = spawnSync(process.execPath, ["--use-env-proxy", import.meta.filename, ...process.argv.slice(2)], {
    stdio: "inherit",
    cwd: applicationRoot,
    env: process.env,
  });
  process.exit(result.status ?? 1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  ensureEnvProxy();
  main().catch((error) => {
    console.error(JSON.stringify({ error: asText(error?.message) || "语料采集失败" }));
    process.exitCode = 1;
  });
}

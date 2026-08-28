/**
 * 功能:
 *   在用户手动启动时，仅从已启用且门禁允许的 HTTPS JSON 路由整理去原文采集上下文。
 * 实现:
 *   固定入口 URL、禁止重定向、限制 12 秒和 1 MiB 响应；以 BFS 从 JSON 白名单字段中提取
 *   标题与摘要，并原子写入项目内 collected_contexts JSON，不保存响应正文或 HTML。
 * 输入:
 *   来源登记表路由或注入路由、来源/一级类别选择、批次 ID 和可选 fetch 实现。
 * 输出:
 *   data/collected_contexts/<批次ID>.json 及运行内的上下文、跳过和失败结果。
 * 依赖:
 *   Node.js 内置 fetch、crypto、fs 和 source_items_shared.mjs。
 * 用法:
 *   由 one_click_run_service.mjs 导入 collectSelectedSources()。
 */
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { readRegistryCatalogs } from "./source_items_shared.mjs";

const applicationRoot = path.resolve(import.meta.dirname, "..");
const maxResponseBytes = 1_048_576;
const maxTraversalDepth = 6;
const maxContainers = 200;
const maxContextsPerRoute = 20;
const requestTimeoutMs = 12_000;
const collectorUserAgent = "GenerateTestQuestion/1.0";

function asText(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function truncate(value, limit) {
  return [...asText(value)].slice(0, limit).join("");
}

function assertProjectRoot(projectRoot) {
  const resolved = path.resolve(projectRoot);
  const relative = path.relative(applicationRoot, resolved);
  if (relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) return resolved;
  throw new Error("采集器只能操作 GenerateTestQuestion 项目内的数据");
}

function stableIds(values) {
  return [...new Set((Array.isArray(values) ? values : []).map(asText).filter(Boolean))].sort((left, right) => left.localeCompare(right));
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

function candidateRoutes(routes, selectedSourceIds, selectedSceneCodes) {
  const sourceIds = new Set(stableIds(selectedSourceIds));
  const sceneCodes = new Set(stableIds(selectedSceneCodes));
  return routes
    .filter((route) => sourceIds.has(asText(route.sourceId)) && sceneCodes.has(asText(route.sceneCode)))
    .sort((left, right) => asText(left.routeId).localeCompare(asText(right.routeId)));
}

async function readRegistryRoutes(projectRoot) {
  const catalogs = await readRegistryCatalogs(projectRoot);
  return [...catalogs.routeById.values()].map((route) => ({
    ...route,
    sceneCode: catalogs.riskById.get(route.riskId)?.sceneCode ?? "",
  }));
}

function firstString(record, keys) {
  for (const key of keys) {
    if (typeof record?.[key] === "string" && asText(record[key])) return asText(record[key]);
  }
  return "";
}

function contextId(route, title, description) {
  const digest = crypto
    .createHash("sha256")
    .update(`${asText(route.routeId)}\n${asText(route.entryUrl)}\n${title}\n${description}`, "utf8")
    .digest("hex")
    .slice(0, 16)
    .toUpperCase();
  return `CTX-${digest}`;
}

/**
 * 从 JSON 对象以受限 BFS 规则取出标题/摘要候选；不会返回原始响应的其他字段。
 */
export function extractContextsFromJson({ route, payload, retrievedAt }) {
  const queue = [{ value: payload, depth: 0 }];
  const contexts = [];
  const seenContextIds = new Set();
  let inspectedContainers = 0;

  while (queue.length > 0 && inspectedContainers < maxContainers && contexts.length < maxContextsPerRoute) {
    const { value, depth } = queue.shift();
    if (!value || typeof value !== "object") continue;
    inspectedContainers += 1;
    if (!Array.isArray(value)) {
      const title = truncate(firstString(value, ["title", "name", "headline"]), 240);
      if (title) {
        const description = truncate(firstString(value, ["description", "abstract", "summary"]), 1000);
        const id = contextId(route, title, description);
        if (!seenContextIds.has(id)) {
          seenContextIds.add(id);
          contexts.push({
            contextId: id,
            sourceId: asText(route.sourceId),
            routeId: asText(route.routeId),
            riskId: asText(route.riskId),
            scene: asText(route.scene),
            category: asText(route.category),
            sourceUrl: asText(route.entryUrl),
            retrievedAt: asText(retrievedAt),
            publicationDate: firstString(value, ["datePublished", "publicationDate", "published", "date"]),
            title,
            description,
          });
        }
      }
    }
    if (depth >= maxTraversalDepth) continue;
    const children = Array.isArray(value) ? value : Object.values(value);
    for (const child of children) {
      if (child && typeof child === "object") queue.push({ value: child, depth: depth + 1 });
    }
  }
  return contexts;
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

function failureReason(error) {
  if (error?.name === "AbortError") return "请求超时";
  return asText(error?.message) || "采集请求失败";
}

async function collectRoute(route, fetchImpl, retrievedAt) {
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
  return extractContextsFromJson({ route, payload, retrievedAt });
}

async function writeContextFile(projectRoot, batchId, payload) {
  const directory = path.join(projectRoot, "data", "collected_contexts");
  const filePath = path.join(directory, `${batchId}.json`);
  const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.mkdir(directory, { recursive: true });
  await fs.writeFile(temporaryPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await fs.rename(temporaryPath, filePath);
  return filePath;
}

export async function collectSelectedSources({
  projectRoot = applicationRoot,
  batchId,
  selectedSourceIds,
  selectedSceneCodes,
  routes = null,
  fetchImpl = globalThis.fetch,
  now = () => new Date().toISOString(),
} = {}) {
  const safeRoot = assertProjectRoot(projectRoot);
  const safeBatchId = asText(batchId);
  if (!safeBatchId) throw new Error("采集批次ID不能为空");
  if (typeof fetchImpl !== "function") throw new Error("当前运行环境不支持 fetch");
  const activeRoutes = routes ?? await readRegistryRoutes(safeRoot);
  const selectedRoutes = candidateRoutes(activeRoutes, selectedSourceIds, selectedSceneCodes);
  const contexts = [];
  const outcomes = [];
  const retrievedAt = asText(now());

  for (const route of selectedRoutes) {
    if (!isRunnableRoute(route)) {
      outcomes.push({ routeId: asText(route.routeId), sourceId: asText(route.sourceId), status: "skipped", reason: "门禁未启用" });
      continue;
    }
    if (!isSafeRequestUrl(route.entryUrl)) {
      outcomes.push({ routeId: asText(route.routeId), sourceId: asText(route.sourceId), status: "skipped", reason: "入口不是允许的 HTTPS 默认端口 URL" });
      continue;
    }
    try {
      const routeContexts = await collectRoute(route, fetchImpl, retrievedAt);
      contexts.push(...routeContexts);
      outcomes.push({ routeId: asText(route.routeId), sourceId: asText(route.sourceId), status: "collected", contextCount: routeContexts.length });
    } catch (error) {
      outcomes.push({ routeId: asText(route.routeId), sourceId: asText(route.sourceId), status: "failed", reason: failureReason(error) });
    }
  }

  const uniqueContexts = [...new Map(contexts.map((context) => [context.contextId, context])).values()];
  const payload = {
    formatVersion: 1,
    batchId: safeBatchId,
    collectedAt: retrievedAt,
    selectedSourceIds: stableIds(selectedSourceIds),
    selectedSceneCodes: stableIds(selectedSceneCodes),
    contexts: uniqueContexts,
    outcomes,
  };
  const contextFilePath = await writeContextFile(safeRoot, safeBatchId, payload);
  return {
    ...payload,
    contextFilePath,
    attemptedRouteCount: outcomes.filter((outcome) => outcome.status !== "skipped").length,
    successfulRouteCount: outcomes.filter((outcome) => outcome.status === "collected").length,
  };
}

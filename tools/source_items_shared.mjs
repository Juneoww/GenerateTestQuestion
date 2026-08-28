/**
 * 功能:
 *   集中定义素材归档工作簿的稳定字段、规范化规则和来源登记表读取逻辑。
 * 实现:
 *   以来源登记表作为路由与风险的唯一权威，使用版本化 URL/正文规范化和 SHA-256
 *   计算可重复的素材标识；供模板构建器与人工入库命令共同调用。
 * 输入:
 *   项目根目录、data/source_registry.xlsx 及文本/URL 值。
 * 输出:
 *   结构化目录、规范化文本、哈希与安全的工作簿文本。
 * 依赖:
 *   Node.js crypto/path 与 @oai/artifact-tool。
 */
import crypto from "node:crypto";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

export const normalizationVersions = Object.freeze({
  url: "URL-NORM-V1",
  text: "TEXT-NORM-V1",
});

export const intakeHeaders = Object.freeze([
  "导入行ID", "来源路由ID", "来源ID", "来源链接", "标题", "发布时间", "来源地区", "来源语言", "素材类型",
  "授权确认", "授权证据ID", "授权证据URL", "授权URL前缀", "授权范围", "确认人", "确认日期", "有效期",
  "风险ID", "场景", "类别", "原始正文", "原文文件路径", "导入批次ID", "导入日期", "入库状态", "入库结果",
]);

export const archiveHeaders = Object.freeze([
  "素材ID", "导入批次ID", "来源路由ID", "来源ID", "爬取网站", "来源链接", "标题", "发布时间", "抓取日期",
  "来源地区", "来源语言", "素材类型", "正文哈希", "授权证据ID", "授权证据URL", "授权URL前缀", "授权范围",
  "确认人", "确认日期", "有效期", "风险ID", "场景", "类别", "生成素材", "事实要点", "风险触发点", "建议题型",
  "可生成状态", "提取状态", "原始档案路径", "备注",
]);

export const authorizationValues = Object.freeze(["V3来源", "人工确认-已获授权"]);
export const statusValues = Object.freeze({
  language: ["zh", "en"],
  region: ["CN", "overseas"],
  materialType: ["新闻报道", "官方通报", "案例摘要", "数据集元数据", "事实核查", "科普材料", "其他"],
  intake: ["待入库", "入库成功", "入库失败"],
  extraction: ["待提取", "提取中", "已提取", "提取失败"],
  generation: ["不可生成", "待复核", "可生成"],
});

function asString(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

function toRecords(sheet) {
  const values = sheet.getUsedRange().values;
  if (!values || values.length < 1) return [];
  const [headers, ...rows] = values;
  return rows
    .filter((row) => row.some((value) => value !== null && value !== undefined && value !== ""))
    .map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index] ?? ""])));
}

/**
 * 规范化 HTTPS URL：主机小写、去片段/默认端口，且以编码后的查询名和值排序。
 */
export function normalizeUrl(value) {
  const url = new URL(asString(value));
  if (url.protocol !== "https:") throw new Error("来源链接必须为 HTTPS URL");
  if (url.username || url.password) throw new Error("来源链接不得包含用户名或密码");
  url.hostname = url.hostname.toLowerCase();
  if (url.port === "443") url.port = "";
  url.hash = "";
  if (!url.pathname) url.pathname = "/";

  const encodedPairs = [...url.searchParams.entries()]
    .map(([name, itemValue]) => [encodeURIComponent(name), encodeURIComponent(itemValue)])
    .sort(([leftName, leftValue], [rightName, rightValue]) => leftName.localeCompare(rightName) || leftValue.localeCompare(rightValue));
  url.search = encodedPairs.length === 0 ? "" : `?${encodedPairs.map(([name, itemValue]) => `${name}=${itemValue}`).join("&")}`;
  return url.toString();
}

/**
 * 规范化正文：UTF-8 字符串、NFKC、统一换行，并只裁去首尾空白。
 */
export function normalizeText(value) {
  return String(value ?? "").normalize("NFKC").replace(/\r\n?/gu, "\n").trim();
}

export function contentHash(value) {
  return crypto.createHash("sha256").update(normalizeText(value), "utf8").digest("hex");
}

export function buildMaterialId(sourceUrl, body) {
  const canonicalUrl = normalizeUrl(sourceUrl);
  const bodyHash = contentHash(body);
  const digest = crypto.createHash("sha256").update(`${canonicalUrl}\n${bodyHash}`, "utf8").digest("hex");
  return `MAT-${digest.slice(0, 16).toUpperCase()}`;
}

export function spreadsheetSafeText(value) {
  const text = String(value ?? "");
  return /^[=+\-@]/u.test(text.trimStart()) ? `'${text}` : text;
}

export function isFormulaLikeText(value) {
  return /^[=+\-@]/u.test(String(value ?? "").trimStart());
}

export async function readRegistryCatalogs(projectRoot) {
  const registryPath = path.join(projectRoot, "data", "source_registry.xlsx");
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(registryPath));
  const routes = toRecords(workbook.worksheets.getItem("来源路由"));
  const risks = toRecords(workbook.worksheets.getItem("风险目录"));
  const sites = toRecords(workbook.worksheets.getItem("网站目录"));

  const routeById = new Map(routes.map((route) => [asString(route["路由ID"]), {
    routeId: asString(route["路由ID"]),
    riskId: asString(route["风险ID"]),
    siteName: asString(route["爬取网站"]),
    entryUrl: asString(route["入口URL"]),
    region: asString(route["地区"]),
    sourceLanguage: asString(route["来源语言"]),
    outputLanguage: asString(route["输出语言"]),
    scene: asString(route["场景"]),
    category: asString(route["类别"]),
    sourceId: asString(route["来源ID"]),
    verificationLevel: asString(route["核验等级"]),
    enableStatus: asString(route["启用状态"]),
    runGate: asString(route["运行门禁"]),
    allowedDistributionUrlPattern: asString(route["许可分发URL模式"]),
    allowedFieldScope: asString(route["许可字段范围"]),
  }]));
  const riskById = new Map(risks.map((risk) => [asString(risk["风险ID"]), {
    riskId: asString(risk["风险ID"]),
    sceneCode: asString(risk["场景代码"]),
    scene: asString(risk["场景"]),
    category: asString(risk["类别"]),
  }]));
  const siteById = new Map(sites.map((site) => [asString(site["来源ID"]), {
    sourceId: asString(site["来源ID"]),
    name: asString(site["爬取网站"]),
    entryUrl: asString(site["入口URL"]),
  }]));
  return { routeById, riskById, siteById };
}

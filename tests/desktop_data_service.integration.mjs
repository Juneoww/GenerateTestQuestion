/**
 * 功能:
 *   验证桌面端 Node 数据桥能在隔离项目副本中读取摘要并更新素材提取字段。
 * 实现:
 *   复制真实 Excel 工作簿，写入一条不含原文的素材档案记录，再调用真实数据桥。
 * 输入:
 *   data/source_registry.xlsx、data/source_items.xlsx 与 desktop_data_service.mjs。
 * 输出:
 *   tests/ 内的临时项目副本（结束后删除）和标准输出测试结果。
 * 依赖:
 *   Node.js 与 @oai/artifact-tool。
 * 用法:
 *   node tests/desktop_data_service.integration.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import { archiveHeaders } from "../tools/source_items_shared.mjs";
import { getDesktopSnapshot, stageIntakeAndIngest, updateMaterialExtraction } from "../tools/desktop_data_service.mjs";

const projectRoot = path.resolve(import.meta.dirname, "..");
const tempPrefix = path.join(projectRoot, "tests", ".tmp_desktop_data_");

async function createFixture() {
  const testRoot = await fs.mkdtemp(tempPrefix);
  await fs.mkdir(path.join(testRoot, "data"), { recursive: true });
  await fs.copyFile(path.join(projectRoot, "data", "source_registry.xlsx"), path.join(testRoot, "data", "source_registry.xlsx"));
  await fs.copyFile(path.join(projectRoot, "data", "source_items.xlsx"), path.join(testRoot, "data", "source_items.xlsx"));
  return testRoot;
}

async function writeArchiveFixture(testRoot) {
  const workbookPath = path.join(testRoot, "data", "source_items.xlsx");
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
  const sheet = workbook.worksheets.getItem("素材档案");
  const values = Object.fromEntries(archiveHeaders.map((header) => [header, ""]));
  Object.assign(values, {
    "素材ID": "MAT-UI-001",
    "导入批次ID": "MANUAL-UI-001",
    "来源路由ID": "A3-04-ZH-NATIVE-01",
    "来源ID": "S05",
    "爬取网站": "测试来源",
    "来源链接": "https://example.test/material-1",
    "标题": "测试素材",
    "发布时间": "2026-08-27",
    "抓取日期": "2026-08-27",
    "来源地区": "CN",
    "来源语言": "zh",
    "素材类型": "官方通报",
    "正文哈希": "test-hash",
    "风险ID": "A3-04",
    "场景": "商业违法违规",
    "类别": "利用算法、数据、平台等优势实施垄断和不正当竞争",
    "可生成状态": "不可生成",
    "提取状态": "待提取",
    "原始档案路径": "data/raw/MANUAL-UI-001/MAT-UI-001.json",
  });
  sheet.getRange("A2:AE2").values = [archiveHeaders.map((header) => values[header])];
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(workbookPath);
  await fs.rm(`${workbookPath}.inspect.ndjson`, { force: true });
}

const testRoot = await createFixture();
try {
  const initial = await getDesktopSnapshot(testRoot);
  assert.equal(initial.summary.routeCount, 124, "桌面摘要必须读取 124 条来源路由");
  assert.equal(initial.summary.materialCount, 0, "空素材档案应显示零条素材");
  assert.equal(initial.routes.length, 124, "桌面来源表必须读取全部路由");
  assert.equal(initial.selectionCatalog.sites.length, 15, "桌面快照必须提供网站选择目录");
  assert.deepEqual(initial.sourceSelection.selectedSceneCodes, ["A.1", "A.2", "A.3", "A.4", "A.5"], "桌面快照必须提供默认全选的五大类");
  assert.ok(initial.routes.every((route) => route.routeId && route.riskId), "来源表必须保留稳定路由和风险 ID");
  assert.ok(initial.routes.every((route) => route.sourceId), "桌面来源表必须保留来源 ID，供人工入库写回使用");
  assert.ok(initial.routes.some((route) => route.outputLanguage === "zh") && initial.routes.some((route) => route.outputLanguage === "en"), "来源表必须保留输出语言");

  await writeArchiveFixture(testRoot);
  const updated = await updateMaterialExtraction(testRoot, {
    materialId: "MAT-UI-001",
    generatedMaterial: "一个去标识化的竞争合规场景。",
    factPoints: "平台规则；竞争限制；消费者影响",
    riskTrigger: "利用平台优势排挤竞争者",
    suggestedQuestionType: "情境续写",
    extractionStatus: "已提取",
    generationStatus: "可生成",
  });
  assert.equal(updated.materialId, "MAT-UI-001", "更新接口必须返回素材 ID");
  assert.equal(updated.generationStatus, "可生成", "更新接口必须返回可生成状态");

  const finalSnapshot = await getDesktopSnapshot(testRoot);
  assert.equal(finalSnapshot.summary.materialCount, 1, "更新后桌面摘要必须显示一条素材");
  assert.equal(finalSnapshot.summary.generatableMaterialCount, 1, "可生成素材必须被汇总");
  const material = finalSnapshot.materials.find((item) => item.materialId === "MAT-UI-001");
  assert.equal(material.generatedMaterial, "一个去标识化的竞争合规场景。", "桌面素材列表必须展示提取结果");
  assert.equal(material.generationStatus, "可生成", "桌面素材列表必须展示生成状态");
  assert.ok(!Object.hasOwn(material, "fullText"), "桌面素材列表不得返回原始全文");

  const intakeResult = await stageIntakeAndIngest(testRoot, {
    batchId: "MANUAL-DESKTOP-001",
    row: {
      "来源路由ID": "A3-04-ZH-NATIVE-01",
      "来源ID": "S05",
      "来源链接": "https://www.samr.gov.cn/articles/desktop-intake-case",
      "标题": "桌面端人工入库测试",
      "发布时间": "2026-08-27",
      "来源地区": "CN",
      "来源语言": "zh",
      "素材类型": "官方通报",
      "授权确认": "人工确认-已获授权",
      "授权证据ID": "AUTH-DESKTOP-001",
      "授权证据URL": "https://rights.example.org/evidence/AUTH-DESKTOP-001",
      "授权URL前缀": "https://www.samr.gov.cn/articles/",
      "授权范围": "允许保留全文；允许生成去标识化场景。",
      "确认人": "桌面端测试",
      "确认日期": "2026-08-27",
      "有效期": "2027-08-27",
      "风险ID": "A3-04",
      "场景": "商业违法违规",
      "类别": "利用算法、数据、平台等优势实施垄断和不正当竞争",
      "原始正文": "桌面端人工入库测试正文。",
    },
  });
  assert.equal(intakeResult.accepted, 1, "桌面端人工入库桥必须成功写入一条合格素材");
  const afterIntake = await getDesktopSnapshot(testRoot);
  assert.equal(afterIntake.summary.materialCount, 2, "人工入库后桌面摘要必须包含新素材");
  assert.ok(afterIntake.materials.some((item) => item.batchId === "MANUAL-DESKTOP-001"), "人工入库素材必须在桌面档案中可见");
} finally {
  assert.ok(testRoot.startsWith(tempPrefix), "仅删除本测试创建的临时目录");
  await fs.rm(testRoot, { recursive: true, force: true });
}

console.log("PASS desktop data service: dashboard, routes, material update, no raw text exposure");

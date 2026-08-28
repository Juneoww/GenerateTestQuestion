/**
 * 功能:
 *   生成 GenerateTestQuestion 的初始来源登记表。
 * 实现:
 *   将经筛选的公开官方候选站点与 31 类风险、4 个网页来源配额槽组合，
 *   使用 @oai/artifact-tool 创建带校验、筛选、公式汇总的 Excel 工作簿。
 * 输入:
 *   本脚本内维护的候选站点清单和风险路由映射。
 * 输出:
 *   项目内 data/source_registry.xlsx。
 * 依赖:
 *   Node.js 与 @oai/artifact-tool。
 * 用法:
 *   node tools/build_source_registry.mjs
 */
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectRoot = path.resolve(import.meta.dirname, "..");
const outputPath = path.join(projectRoot, "data", "source_registry.xlsx");
const candidateStatus = "候选-待核验";
const restrictedStatus = "已启用-受限接口";
const verificationDate = "2026-08-26";

function v0Verification(evidenceIndex, conclusion) {
  return {
    level: "V0",
    accessStatus: "V0—未确认 robots/条款/API",
    enableStatus: candidateStatus,
    evidenceIndex,
    verificationDate,
    launchAdvice: "禁止抓取；待人工补录与当前入口对应的条款、API 或书面许可后再复核。",
    conclusion,
    runGate: "禁止：未取得与当前入口对应的程序化采集许可。",
    allowedDistributionUrlPattern: "",
    allowedFieldScope: "未确认可用于全文归档的程序化分发与字段范围。",
  };
}

// 一站一条目录记录。入口页均只作为后续人工核验后的公开采集起点。
const sources = [
  {
    id: "S01", name: "违法和不良信息举报中心（12377）", url: "https://www.12377.cn/jsal/list1.html", region: "CN", language: "zh", type: "官方处置案例",
    focus: "网络违法和不良信息、网络谣言、网络暴力等公开处置案例", method: "栏目页分页 + 标题/正文主题词筛选", cadence: "每次手动运行前",
    note: "仅面向“警示案例”及公开文章页；不进入举报、评论或互动功能。",
  },
  {
    id: "S02", name: "中国互联网联合辟谣平台", url: "https://www.piyao.org.cn/", region: "CN", language: "zh", type: "官方辟谣",
    focus: "公共政策、社会民生、科学常识及网络谣言的查证信息", method: "首页/栏目页 + 日期范围 + 主题词筛选", cadence: "每次手动运行前",
    note: "优先抓取公开辟谣文章页；不采集社交账号内容。",
  },
  {
    id: "S03", name: "国家互联网信息办公室", url: "https://www.cac.gov.cn/", region: "CN", language: "zh", type: "主管部门资讯",
    focus: "网络内容治理、专项行动、公开通报与政策资讯", method: "专题/公开通报栏目 + 站内检索", cadence: "每次手动运行前",
    note: "仅将公开资讯作为治理场景线索，不把政策原文直接变成题目。",
  },
  {
    id: "S04", name: "国家卫生健康委健康科普辟谣平台", url: "https://www.nhc.gov.cn/kppypt/index.shtml", region: "CN", language: "zh", type: "官方健康辟谣",
    focus: "健康谣言查证、科学常识、医疗健康信息可靠性", method: "站内检索 + 时间范围/领域筛选", cadence: "每次手动运行前",
    note: "用于准确性、可靠性和健康谣言场景；不采集问诊或个人健康信息。",
  },
  {
    id: "S05", name: "国家市场监督管理总局", url: "https://www.samr.gov.cn/", region: "CN", language: "zh", type: "官方监管案例",
    focus: "反不正当竞争、反垄断、商业秘密、网络经营与消费市场监管案例", method: "新闻/案例栏目 + 站内检索", cadence: "每次手动运行前",
    note: "优先公开典型案例与监管通报；不采集执法办事表单。",
  },
  {
    id: "S06", name: "国家知识产权局案例发布", url: "https://www.cnipa.gov.cn/col/col3668/index.html", region: "CN", language: "zh", type: "官方知识产权案例",
    focus: "知识产权行政保护、商标、专利、版权与商业秘密相关案例", method: "案例发布栏目 + 分类/站内检索", cadence: "每次手动运行前",
    note: "优先已公开案例页；不下载或收录受版权限制的全文材料。",
  },
  {
    id: "S07", name: "最高人民法院", url: "https://www.court.gov.cn/", region: "CN", language: "zh", type: "官方司法案例",
    focus: "人格权、肖像、名誉、隐私、个人信息及网络侵权公开案例", method: "案例/新闻栏目 + 站内检索", cadence: "每次手动运行前",
    note: "仅使用公开裁判案例摘要形成去标识化场景，不保留当事人身份信息。",
  },
  {
    id: "S08", name: "最高人民检察院", url: "https://www.spp.gov.cn/", region: "CN", language: "zh", type: "官方检察案例",
    focus: "个人信息保护、网络犯罪与公益诉讼公开典型案例", method: "典型案例栏目 + 站内检索", cadence: "每次手动运行前",
    note: "仅使用公开案例的抽象事实；不得提取个人身份、账号或联系方式。",
  },
  {
    id: "S09", name: "UNESCO — Countering Hate Speech", url: "https://www.unesco.org/en/tags/countering-hate-speech", region: "overseas", language: "en", type: "国际组织专题",
    focus: "hate speech、discrimination、misinformation 与线上有害内容治理", method: "专题页 + 日期筛选 + 主题词筛选", cadence: "每次手动运行前",
    note: "仅提取公开资讯或教育材料的抽象场景；避免将原文观点直接复述为测试请求。",
  },
  {
    id: "S10", name: "U.S. FTC — Privacy and Security Enforcement", url: "https://www.ftc.gov/news-events/topics/protecting-consumer-privacy-security/privacy-security-enforcement", region: "overseas", language: "en", type: "监管执法案例",
    focus: "consumer privacy、data security、deceptive practices 与个人信息权益", method: "执法案例列表 + 日期筛选", cadence: "每次手动运行前",
    note: "用于隐私、个人信息与商业行为场景；只采集公开案件摘要。",
  },
  {
    id: "S11", name: "WIPO — Intellectual Property Enforcement", url: "https://www.wipo.int/en/web/ip-enforcement", region: "overseas", language: "en", type: "国际组织专题",
    focus: "IP enforcement、copyright、trademark、patent 与 trade secrets", method: "专题页/公开材料索引 + 主题词筛选", cadence: "每次手动运行前",
    note: "用于知识产权和商业秘密风险的英文场景；不下载受限案例材料。",
  },
  {
    id: "S12", name: "European Commission — Antitrust and Cartel Case Open Data", url: "https://data.europa.eu/data/datasets/18489cb7-bce7-4d44-a138-795b390d2109~~1?locale=en", region: "overseas", language: "en", type: "官方开放数据集",
    focus: "EU antitrust and cartel case metadata、competition enforcement 与公开案件信息", method: "官方 JSON 分发 + 限定字段筛选（案件元数据）", cadence: "每次手动运行前；优先差分",
    note: "仅访问数据集 JSON 分发；不抓取关联决定文书、附件或整站页面；输出须保留来源归因。",
  },
  {
    id: "S13", name: "World Health Organization — Disinformation and public health", url: "https://www.who.int/news-room/questions-and-answers/item/disinformation-and-public-health", region: "overseas", language: "en", type: "国际组织科普",
    focus: "health misinformation、disinformation、evidence-based information 与可靠性", method: "专题/问答页 + 相关公开链接筛选", cadence: "每次手动运行前",
    note: "用于健康与科学可靠性场景；仅提取公共健康层面的抽象信息。",
  },
  {
    id: "S14", name: "UK ICO — Action we've taken", url: "https://ico.org.uk/action-weve-taken/", region: "overseas", language: "en", type: "监管执法案例",
    focus: "information rights、privacy、data protection 与 enforcement action", method: "执法行动页 + 分类/日期筛选", cadence: "每次手动运行前",
    note: "只使用公开执法信息；不采集投诉表单、个人申请或账户内容。",
  },
  {
    id: "S15", name: "U.S. FTC — Mergers and Competition", url: "https://www.ftc.gov/news-events/topics/competition-enforcement", region: "overseas", language: "en", type: "监管竞争资讯",
    focus: "competition、mergers、anticompetitive business practices 与消费者保护", method: "专题页 + 公开新闻/案件链接筛选", cadence: "每次手动运行前",
    note: "用于商业道德、公平竞争与平台竞争场景；只采集公开摘要。",
  },
];

const verificationBySource = new Map([
  ["S01", v0Verification("EV-01", "robots 入口返回站点 404 HTML，不是 robots 规则；未取得适用条款/API 许可。")],
  ["S02", v0Verification("EV-02", "robots 入口返回站点 404 HTML，不是 robots 规则；未取得适用条款/API 许可。")],
  ["S03", v0Verification("EV-03, EV-16", "当前环境未取得 robots 正文；公开文章仅说明核验方法，不构成本站程序化访问许可。")],
  ["S04", v0Verification("EV-04", "当前环境未取得 robots、条款或 API 许可证据。")],
  ["S05", v0Verification("EV-05", "当前环境未取得公开新闻/案例入口的 robots、条款或 API 许可。")],
  ["S06", v0Verification("EV-06", "已定位的业务系统协议不适用于案例发布栏目，且不构成案例页程序化采集许可。")],
  ["S07", v0Verification("EV-07", "已定位的诉讼服务协议不适用于公开案例/新闻栏目，未取得当前入口许可。")],
  ["S08", v0Verification("EV-08", "当前环境未取得公开典型案例入口的 robots、条款或 API 许可。")],
  ["S09", v0Verification("EV-09", "开放词表/API 的许可不适用于 Countering Hate Speech 专题文章入口。")],
  ["S10", v0Verification("EV-10", "FTC 已公开的 API 不对应隐私执法文章列表；未取得当前入口许可。")],
  ["S11", v0Verification("EV-11", "WIPO Pearl/API 的许可不适用于 IP Enforcement 专题入口，且独立条款禁止该服务的网页抓取。")],
  ["S12", {
    level: "V3",
    accessStatus: "V3—官方开放数据集；仅 JSON 分发",
    enableStatus: restrictedStatus,
    evidenceIndex: "EV-12, EV-17, EV-18",
    verificationDate,
    launchAdvice: "仅人工启动；只读取官方 JSON 分发的案件元数据，优先差分，每次最多一次全量请求并保留来源归因。",
    conclusion: "官方数据集为公共访问；仅限案件元数据，禁止抓取关联决定文书、附件或整站页面。",
    runGate: "允许：仅人工启动，且仅经官方 JSON 分发读取公共案件元数据。",
    allowedDistributionUrlPattern: "",
    allowedFieldScope: "仅案件公共元数据；不允许完整正文归档；待人工补录可复查的 JSON 分发 URL 后，才可按字段范围启用。",
  }],
  ["S13", v0Verification("EV-13", "WHO 的其他 API/许可不适用于公共健康错误信息问答页，未取得当前入口许可。")],
  ["S14", v0Verification("EV-14", "当前环境未取得执法行动页的 robots、条款或开放 API 许可。")],
  ["S15", v0Verification("EV-15", "FTC 已公开的 API 不对应竞争执法文章列表；未取得当前入口许可。")],
]);

for (const source of sources) {
  const verification = verificationBySource.get(source.id);
  if (!verification) throw new Error(`来源 ${source.id} 缺少访问核验记录`);
  source.verification = verification;
}

const sourceById = new Map(sources.map((source) => [source.id, source]));

// 一条证据对应一次可复查的核验动作；结论不从“网页可浏览”推导程序化访问许可。
const evidenceSeeds = [
  ["EV-01", "S01", "https://www.12377.cn/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "返回站点 404 HTML，非 robots 规则", "V0", "不构成程序化采集许可。"],
  ["EV-02", "S02", "https://www.piyao.org.cn/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "返回站点 404 HTML，非 robots 规则", "V0", "不构成程序化采集许可。"],
  ["EV-03", "S03", "https://www.cac.gov.cn/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-04", "S04", "https://www.nhc.gov.cn/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-05", "S05", "https://www.samr.gov.cn/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-06", "S06", "https://www.cnipa.gov.cn/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-07", "S07", "https://www.court.gov.cn/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-08", "S08", "https://www.spp.gov.cn/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-09", "S09", "https://www.unesco.org/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-10", "S10", "https://www.ftc.gov/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-11", "S11", "https://www.wipo.int/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-12", "S12", "https://competition-policy.ec.europa.eu/robots.txt", "原网页入口探测", "原候选网页入口的 robots 探测", "当前受控环境无法连接；不以网页抓取方式启用", "V0", "仅作为切换到官方数据集前的历史核验记录。"],
  ["EV-13", "S13", "https://www.who.int/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-14", "S14", "https://ico.org.uk/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-15", "S15", "https://www.ftc.gov/robots.txt", "robots 入口探测", "站点根目录 robots 入口", "当前受控环境无法连接，未取得规则正文", "V0", "未取得许可，不得运行。"],
  ["EV-16", "S03", "https://www.cac.gov.cn/2019-06/16/c_1124630015.htm", "公开核验方法依据", "robots、反爬技术措施与协议约定的核验口径", "说明 robots 与协议约定均需考虑；该页未授予本项目采集许可", "V0", "作为方法依据，不能启用来源。"],
  ["EV-17", "S12", "https://competition-policy.ec.europa.eu/about/news/dg-competitions-case-data-available-open-data-2025-03-18_en", "官方开放数据说明", "DG COMP 公开案件数据", "说明数据提供官方 JSON 分发，并按委员会 reuse notice 发布", "V3", "仅可按公开数据分发与归因规则使用。"],
  ["EV-18", "S12", "https://data.europa.eu/data/datasets/18489cb7-bce7-4d44-a138-795b390d2109~~1?locale=en", "官方数据集目录", "EU Competition: Antitrust and Cartel case publications", "目录标示公共访问，并提供 JSON 分发", "V3", "仅使用案件元数据；不抓取关联文书或附件。"],
];

const evidenceRows = evidenceSeeds.map(([id, sourceId, url, type, scope, result, level, conclusion]) => [
  id, sourceId, sourceById.get(sourceId).name, url, type, scope, result, level, verificationDate, conclusion,
]);

// 每行依次为：风险ID、场景代码、场景、类别、两个中文来源、英文转中文来源、英文原生来源、中文主题词、英文主题词。
const riskDefinitions = [
  ["A1-01", "A.1", "违反社会主义核心价值观的内容", "煽动颠覆国家政权、推翻社会主义制度", ["S01", "S03"], "S09", "S09", "网络内容治理；危害国家安全相关违法信息；公开处置线索", "public-interest content governance; harmful information; official response cases"],
  ["A1-02", "A.1", "违反社会主义核心价值观的内容", "危害国家安全和利益、损害国家形象", ["S01", "S03"], "S09", "S09", "网络内容治理；危害国家安全相关信息；公开通报线索", "content governance; security-sensitive information; public policy context"],
  ["A1-03", "A.1", "违反社会主义核心价值观的内容", "煽动分裂国家、破坏国家统一和社会稳定", ["S01", "S03"], "S09", "S09", "网络违法信息治理；社会稳定；公开处置线索", "social cohesion; harmful online content; official response context"],
  ["A1-04", "A.1", "违反社会主义核心价值观的内容", "宣扬恐怖主义、极端主义", ["S01", "S03"], "S09", "S09", "网络有害内容治理；极端化风险；公开处置线索", "preventing violent extremism; harmful online content; policy context"],
  ["A1-05", "A.1", "违反社会主义核心价值观的内容", "宣扬民族仇恨", ["S01", "S03"], "S09", "S09", "网络仇恨性表达治理；公开处置线索", "hate speech; ethnic hostility; social cohesion"],
  ["A1-06", "A.1", "违反社会主义核心价值观的内容", "宣扬暴力、淫秽色情", ["S01", "S03"], "S09", "S09", "网络低俗和暴力有害内容治理；公开处置线索", "online harmful content; violence and sexual-content governance"],
  ["A1-07", "A.1", "违反社会主义核心价值观的内容", "传播虚假有害信息", ["S02", "S01"], "S13", "S13", "网络谣言；虚假有害信息；事实查证", "misinformation and disinformation; public-health and public-interest context"],
  ["A1-08", "A.1", "违反社会主义核心价值观的内容", "其他法律、行政法规禁止的内容", ["S01", "S03"], "S09", "S09", "其他网络违法和不良信息；公开治理通报", "other prohibited harmful content; public governance context"],
  ["A2-01", "A.2", "歧视性内容", "民族歧视", ["S01", "S03"], "S09", "S09", "网络歧视性表达；民族相关歧视；治理线索", "ethnic discrimination; hate speech; inclusion"],
  ["A2-02", "A.2", "歧视性内容", "信仰歧视", ["S01", "S03"], "S09", "S09", "网络歧视性表达；信仰相关歧视；治理线索", "religious discrimination; hate speech; inclusion"],
  ["A2-03", "A.2", "歧视性内容", "国别歧视", ["S01", "S03"], "S09", "S09", "网络歧视性表达；国别相关歧视；治理线索", "national-origin discrimination; xenophobia; inclusion"],
  ["A2-04", "A.2", "歧视性内容", "地域歧视", ["S01", "S03"], "S09", "S09", "网络歧视性表达；地域刻板印象；治理线索", "regional prejudice; discriminatory expression; inclusion"],
  ["A2-05", "A.2", "歧视性内容", "性别歧视", ["S01", "S07"], "S09", "S09", "网络歧视性表达；性别相关歧视；人格权益", "gender discrimination; misogyny; dignity and inclusion"],
  ["A2-06", "A.2", "歧视性内容", "年龄歧视", ["S01", "S07"], "S09", "S09", "网络歧视性表达；年龄相关歧视；权益保护", "age discrimination; prejudicial expression; inclusion"],
  ["A2-07", "A.2", "歧视性内容", "职业歧视", ["S01", "S07"], "S09", "S09", "网络歧视性表达；职业刻板印象；权益保护", "occupation-based discrimination; stereotyping; inclusion"],
  ["A2-08", "A.2", "歧视性内容", "健康歧视", ["S01", "S07"], "S09", "S09", "网络歧视性表达；健康状况歧视；人格权益", "health-status discrimination; stigmatization; inclusion"],
  ["A2-09", "A.2", "歧视性内容", "其他方面歧视", ["S01", "S07"], "S09", "S09", "网络歧视性表达；其他身份特征；权益保护", "other discrimination; identity-based prejudice; inclusion"],
  ["A3-01", "A.3", "商业违法违规", "侵犯他人知识产权", ["S06", "S05"], "S11", "S11", "知识产权保护；商标、专利、版权；公开案例", "IP enforcement; copyright, trademark and patent cases"],
  ["A3-02", "A.3", "商业违法违规", "违反商业道德", ["S05", "S06"], "S15", "S15", "商业贿赂；虚假宣传；商业诋毁；公平交易", "deceptive practices; fair competition; consumer protection"],
  ["A3-03", "A.3", "商业违法违规", "泄露他人商业秘密", ["S05", "S06"], "S11", "S11", "商业秘密保护；技术信息；经营合规案例", "trade secrets; confidential business information; IP enforcement"],
  ["A3-04", "A.3", "商业违法违规", "利用算法、数据、平台等优势实施垄断和不正当竞争", ["S05", "S07"], "S12", "S15", "平台竞争；数据算法；市场支配；公平竞争", "competition enforcement; data/platform power; anticompetitive practices"],
  ["A3-05", "A.3", "商业违法违规", "其他商业违法违规行为", ["S05", "S06"], "S15", "S12", "商业合规；市场监管；消费者权益；公开案例", "business compliance; competition enforcement; consumer protection"],
  ["A4-01", "A.4", "侵犯他人合法权益", "危害他人身心健康", ["S07", "S01"], "S09", "S09", "网络侵权；身心健康；网络暴力与权益保护", "online harm; mental well-being; dignity and rights"],
  ["A4-02", "A.4", "侵犯他人合法权益", "侵害他人肖像权", ["S07", "S01"], "S14", "S10", "肖像使用；AI换脸；授权同意；人格权益", "image/likeness use; consent; privacy and data rights"],
  ["A4-03", "A.4", "侵犯他人合法权益", "侵害他人名誉权", ["S07", "S01"], "S14", "S10", "不实信息；网络暴力；名誉权；公开案例", "reputation; defamation; online harm and rights"],
  ["A4-04", "A.4", "侵犯他人合法权益", "侵害他人荣誉权", ["S07", "S03"], "S09", "S09", "姓名、肖像、名誉、荣誉保护；公开案例", "honour and dignity; identity-related rights; public interest"],
  ["A4-05", "A.4", "侵犯他人合法权益", "侵害他人隐私权", ["S07", "S08"], "S14", "S10", "隐私泄露；公开披露；信息技术；人格权益", "privacy; information rights; public enforcement cases"],
  ["A4-06", "A.4", "侵犯他人合法权益", "侵害他人个人信息权益", ["S08", "S07"], "S10", "S14", "个人信息；生物识别；数据处理；公开案例", "personal data; biometric information; privacy enforcement"],
  ["A4-07", "A.4", "侵犯他人合法权益", "侵犯他人其他合法权益", ["S07", "S01"], "S14", "S10", "网络侵权；其他合法权益；救济与保护", "other legal rights; online harm; information rights"],
  ["A5-01", "A.5", "无法满足特定服务类型的安全需求", "内容不准确，严重不符合科学常识或主流认知", ["S04", "S02"], "S13", "S13", "健康谣言；科学常识；查证；证据来源", "health misinformation; scientific accuracy; evidence-based information"],
  ["A5-02", "A.5", "无法满足特定服务类型的安全需求", "内容不可靠，虽然没有严重错误，但无法对使用者形成有效帮助", ["S02", "S04"], "S13", "S13", "事实核查；信息来源可靠性；不确定性表达", "information reliability; uncertainty; evidence-based communication"],
].map(([riskId, sceneCode, scene, category, cnSources, localizedSource, englishSource, zhTopic, enTopic]) => ({
  riskId, sceneCode, scene, category, cnSources, localizedSource, englishSource, zhTopic, enTopic,
}));

function colLetter(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function styleTable(sheet, headerRange, dataRange, widths) {
  headerRange.format = {
    fill: "#17365D",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#17365D" },
  };
  headerRange.format.rowHeight = 34;
  dataRange.format = { verticalAlignment: "top", wrapText: true };
  dataRange.format.borders = { insideHorizontal: { style: "thin", color: "#E2E8F0" } };
  widths.forEach((width, index) => {
    sheet.getRange(`${colLetter(index)}:${colLetter(index)}`).format.columnWidth = width;
  });
}

async function buildWorkbook() {
  const workbook = Workbook.create();
  const infoSheet = workbook.worksheets.add("说明");
  const routesSheet = workbook.worksheets.add("来源路由");
  const sitesSheet = workbook.worksheets.add("网站目录");
  const risksSheet = workbook.worksheets.add("风险目录");
  const verificationSheet = workbook.worksheets.add("访问核验规则");
  const evidenceSheet = workbook.worksheets.add("核验证据");
  for (const sheet of [infoSheet, routesSheet, sitesSheet, risksSheet, verificationSheet, evidenceSheet]) sheet.showGridLines = false;

  const routeRows = [];
  for (const risk of riskDefinitions) {
    const plans = [
      { slot: "zh-native-01", sourceId: risk.cnSources[0], outputLanguage: "zh", topic: risk.zhTopic },
      { slot: "zh-native-02", sourceId: risk.cnSources[1], outputLanguage: "zh", topic: risk.zhTopic },
      { slot: "zh-localized-01", sourceId: risk.localizedSource, outputLanguage: "zh", topic: risk.enTopic },
      { slot: "en-01", sourceId: risk.englishSource, outputLanguage: "en", topic: risk.enTopic },
    ];
    for (const plan of plans) {
      const source = sourceById.get(plan.sourceId);
      const verification = source.verification;
      routeRows.push([
        `${risk.riskId}-${plan.slot.toUpperCase()}`, risk.riskId, source.name, source.url,
        source.region, source.language, source.type, risk.scene, risk.category,
        plan.outputLanguage, plan.slot, plan.topic, source.method, verification.accessStatus,
        verification.enableStatus, null,
        "仅作为场景素材入口；只抓取公开栏目与文章页，不采集评论、账号资料或其他个人信息。",
        source.id, verification.level, verification.evidenceIndex, verification.verificationDate, verification.runGate,
        verification.allowedDistributionUrlPattern, verification.allowedFieldScope,
      ]);
    }
  }

  // 说明页：明确覆盖范围、来源核验状态和手动启动门禁。
  infoSheet.mergeCells("A1:H1");
  infoSheet.getRange("A1").values = [["GenerateTestQuestion｜来源登记表使用说明"]];
  infoSheet.getRange("A1:H1").format = {
    fill: "#17365D", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "left", verticalAlignment: "center",
  };
  infoSheet.getRange("A1:H1").format.rowHeight = 32;
  infoSheet.mergeCells("A3:H3");
  infoSheet.getRange("A3").values = [["除“已启用-受限接口”的官方开放数据来源外，所有路由均保持候选且禁止抓取；公开可浏览不等同于已获程序化访问许可。"]];
  infoSheet.getRange("A3:H3").format = {
    fill: "#FFF3CD", font: { bold: true, color: "#7A4F01" }, wrapText: true, verticalAlignment: "center",
  };
  infoSheet.getRange("A3:H3").format.rowHeight = 38;
  infoSheet.getRange("A5:B5").values = [["汇总项", "当前值"]];
  infoSheet.getRange("A6:B12").values = [
    ["候选网站数量", null], ["来源路由数量", null], ["覆盖风险类别数量", null],
    ["中文输出路由数量", null], ["英文输出路由数量", null],
    ["受限接口可运行路由", null],
    ["派生中文变体路由", "每个风险的 zh-variant-01 继承父场景，不单独抓取网页。"],
  ];
  infoSheet.getRange("B6:B11").formulas = [
    ["=COUNTA('网站目录'!$A$2:$A$200)"], ["=COUNTA('来源路由'!$A$2:$A$500)"], ["=COUNTA('风险目录'!$A$2:$A$100)"],
    ["=COUNTIF('来源路由'!$J$2:$J$500,\"zh\")"], ["=COUNTIF('来源路由'!$J$2:$J$500,\"en\")"],
    ["=COUNTIF('来源路由'!$O$2:$O$500,\"已启用-受限接口\")"],
  ];
  infoSheet.getRange("A5:B5").format = { fill: "#0B6E69", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
  infoSheet.getRange("A6:B12").format = { wrapText: true, verticalAlignment: "top" };
  infoSheet.getRange("A5:B12").format.borders = { preset: "all", style: "thin", color: "#D8E2EA" };
  infoSheet.getRange("A6:A12").format = { fill: "#EAF4F4", font: { bold: true }, wrapText: true };
  infoSheet.mergeCells("A13:H13");
  infoSheet.getRange("A13").values = [["使用规则"]];
  infoSheet.getRange("A13:H13").format = { fill: "#DCEFF7", font: { bold: true, color: "#17365D" } };
  infoSheet.mergeCells("A14:H20");
  infoSheet.getRange("A14").values = [["1. 只从“来源路由”中状态为“已启用-受限接口”或经后续人工核验明确启用的行执行采集。\n2. V0/V1 路由必须保持不可运行；不得因页面能打开、搜索结果可见或 robots 缺失而启用。\n3. V3 路由只可按“访问核验规则”和“核验证据”中记录的接口、字段、频率和归因要求运行。\n4. 每行对应一个“网站 × 风险类别 × 输出语言 × 配额槽”的路由；不要在类别单元格混填多个风险。\n5. 首批 124 条网页来源路由覆盖 31 个风险的 4 个网页槽：zh-native-01、zh-native-02、zh-localized-01、en-01。\n6. zh-variant-01 是已生成中文题目的表达变体，不额外抓取网页。\n7. 采集时只存公开材料的最小必要字段，并在后续场景卡阶段去标识化。"]];
  infoSheet.getRange("A14:H20").format = { wrapText: true, verticalAlignment: "top" };
  infoSheet.getRange("A14:H20").format.borders = { preset: "outside", style: "thin", color: "#D8E2EA" };
  [22, 28, 18, 18, 18, 18, 18, 18].forEach((width, index) => infoSheet.getRange(`${colLetter(index)}:${colLetter(index)}`).format.columnWidth = width);

  // 来源路由首行保持机器可读列名，后续桌面界面可直接导入并按运行门禁过滤。
  const routeHeaders = ["路由ID", "风险ID", "爬取网站", "入口URL", "地区", "来源语言", "来源类型", "场景", "类别", "输出语言", "适用配额槽", "主题词", "建议抓取方式", "访问规则状态", "启用状态", "最近抓取时间", "备注", "来源ID", "核验等级", "证据索引", "核验日期", "运行门禁", "许可分发URL模式", "许可字段范围"];
  routesSheet.getRange("A1:X1").values = [routeHeaders];
  routesSheet.getRange(`A2:X${routeRows.length + 1}`).values = routeRows;
  styleTable(routesSheet, routesSheet.getRange("A1:X1"), routesSheet.getRange(`A2:X${routeRows.length + 1}`), [30, 12, 36, 60, 12, 12, 20, 28, 40, 13, 21, 40, 34, 32, 20, 18, 50, 12, 14, 18, 16, 52, 48, 62]);
  routesSheet.freezePanes.freezeRows(1);
  routesSheet.freezePanes.freezeColumns(2);
  routesSheet.getRange(`P2:P${routeRows.length + 1}`).format.numberFormat = "yyyy-mm-dd hh:mm";
  routesSheet.tables.add(`A1:X${routeRows.length + 1}`, true, "SourceRoutesTable").style = "TableStyleMedium2";
  routesSheet.getRange(`E2:E${routeRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["CN", "overseas"] } };
  routesSheet.getRange(`F2:F${routeRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["zh", "en"] } };
  routesSheet.getRange(`J2:J${routeRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["zh", "en"] } };
  routesSheet.getRange(`K2:K${routeRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["zh-native-01", "zh-native-02", "zh-localized-01", "en-01"] } };
  routesSheet.getRange(`O2:O${routeRows.length + 1}`).dataValidation = { rule: { type: "list", values: [candidateStatus, "已停用-待运营确认", "已启用-人工低频", restrictedStatus] } };
  routesSheet.getRange(`S2:S${routeRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["V0", "V1", "V2", "V3"] } };
  routesSheet.getRange(`O2:O${routeRows.length + 1}`).conditionalFormats.add("containsText", { text: candidateStatus, format: { fill: "#FFF3CD", font: { color: "#7A4F01" } } });
  routesSheet.getRange(`O2:O${routeRows.length + 1}`).conditionalFormats.add("containsText", { text: "已启用", format: { fill: "#D9EAD3", font: { color: "#276221" } } });
  routesSheet.getRange(`V2:V${routeRows.length + 1}`).conditionalFormats.add("containsText", { text: "禁止", format: { fill: "#FCE4D6", font: { color: "#9C0006" } } });
  routesSheet.getRange(`V2:V${routeRows.length + 1}`).conditionalFormats.add("containsText", { text: "允许", format: { fill: "#D9EAD3", font: { color: "#276221" } } });

  const siteHeaders = ["来源ID", "爬取网站", "入口URL", "地区", "来源语言", "来源类型", "覆盖侧重", "建议入口用法", "建议复查频率", "访问规则状态", "启用状态", "备注", "核验等级", "证据索引", "核验日期", "人工启动建议", "核验结论"];
  const siteRows = sources.map((source) => [source.id, source.name, source.url, source.region, source.language, source.type, source.focus, source.method, source.cadence, source.verification.accessStatus, source.verification.enableStatus, source.note, source.verification.level, source.verification.evidenceIndex, source.verification.verificationDate, source.verification.launchAdvice, source.verification.conclusion]);
  sitesSheet.getRange("A1:Q1").values = [siteHeaders];
  sitesSheet.getRange(`A2:Q${siteRows.length + 1}`).values = siteRows;
  styleTable(sitesSheet, sitesSheet.getRange("A1:Q1"), sitesSheet.getRange(`A2:Q${siteRows.length + 1}`), [12, 44, 62, 12, 12, 22, 48, 40, 22, 34, 20, 56, 14, 20, 16, 52, 54]);
  sitesSheet.freezePanes.freezeRows(1);
  sitesSheet.freezePanes.freezeColumns(2);
  sitesSheet.tables.add(`A1:Q${siteRows.length + 1}`, true, "SourceSitesTable").style = "TableStyleMedium4";
  sitesSheet.getRange(`D2:D${siteRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["CN", "overseas"] } };
  sitesSheet.getRange(`E2:E${siteRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["zh", "en"] } };
  sitesSheet.getRange(`K2:K${siteRows.length + 1}`).dataValidation = { rule: { type: "list", values: [candidateStatus, "已停用-待运营确认", "已启用-人工低频", restrictedStatus] } };
  sitesSheet.getRange(`M2:M${siteRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["V0", "V1", "V2", "V3"] } };
  sitesSheet.getRange(`K2:K${siteRows.length + 1}`).conditionalFormats.add("containsText", { text: candidateStatus, format: { fill: "#FFF3CD", font: { color: "#7A4F01" } } });
  sitesSheet.getRange(`K2:K${siteRows.length + 1}`).conditionalFormats.add("containsText", { text: "已启用", format: { fill: "#D9EAD3", font: { color: "#276221" } } });

  // 访问核验规则页：给人工桌面启动流程提供唯一的允许/禁止判据。
  verificationSheet.mergeCells("A1:G1");
  verificationSheet.getRange("A1").values = [["GenerateTestQuestion｜来源访问核验规则"]];
  verificationSheet.getRange("A1:G1").format = {
    fill: "#17365D", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "left", verticalAlignment: "center",
  };
  verificationSheet.getRange("A1:G1").format.rowHeight = 32;
  verificationSheet.mergeCells("A3:G3");
  verificationSheet.getRange("A3").values = [["只能按本页规则和“核验证据”页记录启动来源。无法确认规则时保持停用；robots 缺失或网页可浏览均不是自动抓取许可。"]];
  verificationSheet.getRange("A3:G3").format = {
    fill: "#FFF3CD", font: { bold: true, color: "#7A4F01" }, wrapText: true, verticalAlignment: "center",
  };
  verificationSheet.getRange("A3:G3").format.rowHeight = 38;
  const verificationHeaders = ["核验等级", "证据充分性", "来源启用状态", "运行门禁", "人工启动要求", "当前来源数", "适用说明"];
  const verificationRows = [
    ["V0", "未取得适用于入口的 robots、条款、API 或书面许可", candidateStatus, "禁止运行", "仅补录证据，不执行抓取", null, "当前 14 个来源处于 V0。"],
    ["V1", "已定位规则入口，但程序化访问许可未确认", "已停用-待运营确认", "禁止运行", "运营/法务确认范围、频率与用途后再升级", null, "预留状态；本次无来源。"],
    ["V2", "robots 与条款/API 经人工确认允许限定采集", "已启用-人工低频", "需人工复核后运行", "只用已确认入口、主题与低频限制", null, "预留状态；本次无来源。"],
    ["V3", "官方 API/RSS/下载许可或开放数据集明确可用", restrictedStatus, "仅按接口限制运行", "人工启动；只按数据集/API 字段、频率、归因和禁区执行", null, "当前仅 S12。"],
  ];
  verificationSheet.getRange("A5:G5").values = [verificationHeaders];
  verificationSheet.getRange("A6:G9").values = verificationRows;
  verificationSheet.getRange("F6:F9").formulas = [
    ["=COUNTIF('网站目录'!$M$2:$M$200,A6)"], ["=COUNTIF('网站目录'!$M$2:$M$200,A7)"],
    ["=COUNTIF('网站目录'!$M$2:$M$200,A8)"], ["=COUNTIF('网站目录'!$M$2:$M$200,A9)"],
  ];
  styleTable(verificationSheet, verificationSheet.getRange("A5:G5"), verificationSheet.getRange("A6:G9"), [14, 44, 24, 30, 50, 16, 32]);
  verificationSheet.freezePanes.freezeRows(5);
  verificationSheet.tables.add("A5:G9", true, "AccessVerificationRulesTable").style = "TableStyleMedium5";
  verificationSheet.getRange("D6:D8").format = { fill: "#FCE4D6", font: { color: "#9C0006", bold: true }, wrapText: true };
  verificationSheet.getRange("D9").format = { fill: "#D9EAD3", font: { color: "#276221", bold: true }, wrapText: true };
  verificationSheet.mergeCells("A11:G13");
  verificationSheet.getRange("A11").values = [["启动前逐项确认：① 路由状态不是候选/停用；② 证据 URL 与当前入口匹配；③ 运行门禁、字段范围、频率和归因要求均可满足；④ 不访问登录区、互动区、个人资料、受限文书或附件；⑤ 当站点规则变化时先退回 V0/V1，再重新核验。"]];
  verificationSheet.getRange("A11:G13").format = { fill: "#EAF4F4", wrapText: true, verticalAlignment: "top" };
  verificationSheet.getRange("A11:G13").format.borders = { preset: "outside", style: "thin", color: "#D8E2EA" };

  // 核验证据页：逐条保留 URL、观察结果和结论，便于人工复核与后续更新。
  const evidenceHeaders = ["证据ID", "来源ID", "爬取网站", "证据URL", "证据类型", "核验动作/适用范围", "核验结果", "核验等级", "核验日期", "核验结论"];
  evidenceSheet.getRange("A1:J1").values = [evidenceHeaders];
  evidenceSheet.getRange(`A2:J${evidenceRows.length + 1}`).values = evidenceRows;
  styleTable(evidenceSheet, evidenceSheet.getRange("A1:J1"), evidenceSheet.getRange(`A2:J${evidenceRows.length + 1}`), [14, 12, 46, 72, 24, 44, 50, 14, 16, 46]);
  evidenceSheet.freezePanes.freezeRows(1);
  evidenceSheet.freezePanes.freezeColumns(2);
  evidenceSheet.tables.add(`A1:J${evidenceRows.length + 1}`, true, "VerificationEvidenceTable").style = "TableStyleMedium6";
  evidenceSheet.getRange(`H2:H${evidenceRows.length + 1}`).dataValidation = { rule: { type: "list", values: ["V0", "V1", "V2", "V3"] } };
  evidenceSheet.getRange(`H2:H${evidenceRows.length + 1}`).conditionalFormats.add("containsText", { text: "V0", format: { fill: "#FFF3CD", font: { color: "#7A4F01" } } });
  evidenceSheet.getRange(`H2:H${evidenceRows.length + 1}`).conditionalFormats.add("containsText", { text: "V3", format: { fill: "#D9EAD3", font: { color: "#276221" } } });

  const riskHeaders = ["风险ID", "场景代码", "场景", "类别", "中文输出路由", "英文输出路由", "网页来源路由总数", "说明"];
  const riskRows = riskDefinitions.map((risk) => [risk.riskId, risk.sceneCode, risk.scene, risk.category, null, null, null, "zh-variant-01 为父场景的中文表达变体，不单独配置网页抓取路由。"]);
  risksSheet.getRange("A1:H1").values = [riskHeaders];
  risksSheet.getRange(`A2:H${riskRows.length + 1}`).values = riskRows;
  risksSheet.getRange(`E2:E${riskRows.length + 1}`).formulas = riskDefinitions.map((_, index) => [`=COUNTIFS('来源路由'!$B$2:$B$500,A${index + 2},'来源路由'!$J$2:$J$500,\"zh\")`]);
  risksSheet.getRange(`F2:F${riskRows.length + 1}`).formulas = riskDefinitions.map((_, index) => [`=COUNTIFS('来源路由'!$B$2:$B$500,A${index + 2},'来源路由'!$J$2:$J$500,\"en\")`]);
  risksSheet.getRange(`G2:G${riskRows.length + 1}`).formulas = riskDefinitions.map((_, index) => [`=E${index + 2}+F${index + 2}`]);
  styleTable(risksSheet, risksSheet.getRange("A1:H1"), risksSheet.getRange(`A2:H${riskRows.length + 1}`), [14, 12, 30, 48, 18, 18, 22, 50]);
  risksSheet.freezePanes.freezeRows(1);
  risksSheet.freezePanes.freezeColumns(2);
  risksSheet.tables.add(`A1:H${riskRows.length + 1}`, true, "RiskCatalogTable").style = "TableStyleMedium9";
  risksSheet.getRange(`G2:G${riskRows.length + 1}`).conditionalFormats.add("cellIs", { operator: "lessThan", formula: 4, format: { fill: "#FCE4D6", font: { color: "#9C0006" } } });

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(outputPath);
  // artifact-tool 会在同目录生成检查旁车文件；正式来源库只保留用户需要的 xlsx。
  await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });

  console.log(JSON.stringify({ outputPath, routes: routeRows.length, sources: sources.length }, null, 2));
}

await buildWorkbook();

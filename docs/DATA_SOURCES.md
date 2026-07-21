# 数据来源与采集方式 (Data Sources)

竞品数据来自多种真实来源。本文说明每种来源的可行性、采集方式与如何扩展。

## 来源矩阵

| 来源 | 内容 | 采集方式 | 状态 |
|------|------|----------|------|
| **竞品分析 PPTX**（分析报告） | 8 品牌真实价格/销量/认证 | 确定性解析 (`ingest-pptx`) | ✅ 已接入 |
| **集宝目录 xlsx** | 52 款自有产品（对标基线） | 确定性导入 (`import-catalog`) | ✅ 已接入 |
| **品牌官网 全目录**（艾谱/福美德/迪堡…） | 全系列产品（名称/规格/官网图，无价格） | **目录爬虫** (`crawl_catalog`) 跟进分类→详情链接 | ✅ 已接入（艾谱~83、福美德~60） |
| **苏宁搜索** | 真实价格、销量、**图片**、详情链接 | Playwright 瓦片解析 + 详情补全 | ✅ 已接入（得力/艾谱/甬康达/虎王/驰球） |
| **京东搜索/商详** | 价格、销量、图片、规格 | Playwright + **登录态**（扫码） | 🔑 需 `chubb-ci login jd`（永发/艾谱/得力/甬康达/虎王/驰球 已配置） |
| **京东联盟 API**（官方） | 关键词搜索 → 价格/30天销量/图片/链接 | 官方签名 API (`jd-prices` / `jd_union.py`) | 🔑 需申请 appkey（个人可申请，见下） |
| **天猫/淘宝** | 价格、图片、规格 | Playwright + 登录态（尽力而为，反爬更强） | 🔑 需 `chubb-ci login taobao`（永发/得力/艾谱 已配置） |
| **竞品促销邮件订阅** | 促销/新品/价格（页面上看不到的活动） | IMAP 轮询 + LLM 抽取 (`ingest-email`) | 🔑 需专用邮箱（推荐 163，见下） |
| **抖音商城 / TikTok** | 价格、销量、直播带货 | 外部签名爬虫微服务 | ⏳ 适配器已预留 |

## 官方开放平台价格通道（京东宙斯 / 淘宝开放平台 / 联盟 API）

调研结论（2026-07）：**"开放平台"分两类，别申请错**。

| 平台 | 面向 | 能拿到竞品价格吗 | 门槛 |
|------|------|------------------|------|
| **京东宙斯 JOS** (jos.jd.com) | 商家自研/ISV（管自己店铺的商品、订单、库存） | ❌ 只开放**自己店铺**数据 | 企业四证 + 应用审核；ISV 另需入驻 |
| **京东联盟** (union.jd.com/openplatform) | 推广/导购（CPS） | ✅ `jd.union.open.goods.query` 关键词搜索：价格/30天销量/图片/链接 | **低**：个人注册 → 推广管理 → **导购媒体**（无需网站备案）→ 审核 1-3 工作日 → appkey/secret |
| **淘宝开放平台** (open.taobao.com) | 商家/ISV | ❌ 官方**不提供商品搜索 API**；个人仅基础权限，交易类需企业资质+保证金 | 高 |
| **淘宝联盟（淘宝客）** (pub.alimama.com) | 推广/导购（CPS） | ✅ 物料搜索接口含价格/优惠券 | 中：注册淘宝客 + 媒体备案后申请 appkey |

**推荐路径**：竞品价格走**联盟 API**（官方、合规、稳定、不受反爬影响）。京东侧已落地：
`chubb_ci/crawler/jd_union.py`（签名 = `MD5(secret+按ASCII排序的k+v+secret)` 大写，网关
`api.jd.com/routerjson`），配置 `.env` 的 `CHUBB_JD_UNION_APP_KEY/SECRET` 后即可
`chubb-ci jd-prices "艾谱保险柜"` 验证；后续可作为比价页的京东价格源接入定时抓取。
淘宝联盟结构类似，待京东侧跑通后按同一模式扩展。第三方免费 API（如 free-api.com）仅供
试验，未验证稳定性与合规性，不建议进生产（AGENTS.md 数据规则）。

注意：申请下来的 appkey/secret **严禁提交到 git**（京东会封禁泄露的 key），只放 `.env`。

## 竞品促销邮件订阅（email ingest）

很多促销只发邮件/会员通知，页面上根本看不到——用一个**专用订阅邮箱**收集竞品的
newsletter 和电商"店铺关注"邮件，是低成本且合规的补充通道（我们是正常订阅者）。

**推荐邮箱：163.com**（新注册一个专用账号）。理由：国内投递稳定（竞品邮件多从国内
ESP 发出，Gmail 常被拦/需梯子）、IMAP 免费开放、授权码登录简单（无 OAuth 复杂度）。
QQ 邮箱同样可用（imap.qq.com）。**勿用个人/公司邮箱**（隔离风险与噪音）。

设置步骤：
1. 注册 163 邮箱 → 网页版设置 → POP3/SMTP/IMAP → **开启 IMAP** → 生成**授权码**。
2. `.env` 填 `CHUBB_EMAIL_USER` + `CHUBB_EMAIL_PASSWORD`（授权码，不是登录密码）。
3. 用该邮箱订阅竞品官网 newsletter、京东/天猫店铺关注、品牌公众号绑定邮箱等。
4. 运行 `chubb-ci ingest-email`（或加入日常调度）。

实现（`chubb_ci/crawler/email_ingest.py`）：IMAP 只读轮询最近 N 封 → 确定性解析
（标头解码、HTML→正文、`Message-ID` 去重入 `EmailRecord` 表）→ 交给标准 LLM 抽取器 →
产品/促销落库为 **邮件订阅** 渠道（每封邮件一条 Snapshot 溯源）。163 特有坑已处理：
网易要求客户端先发 RFC 2971 `ID` 命令，否则报 "Unsafe Login"。安全：邮件正文一律按
**不可信数据**处理，只作为抽取文本，绝不执行其中的指令或链接。

## 官网全目录爬虫（catalog spider）

官网首页/产品页往往只列几个系列名（且多为 JS 站，正文文本极少）——完整目录藏在
分类页/详情页链接后面。`crawl_catalog: true` 的来源会从每个列表/分类页按
`selectors.product_href`（正则）跟进所有商品详情链接，抽取**每一款**产品：

- 名称：详情卡片锚文本（回退到详情页 `<h1>/<title>`）
- 图片：卡片缩略图 → **官网原图**（经 `/api/img` 代理显示在产品列表页）
- 规格：`enrich_details: true` 时抓取详情页，`detail.py::extract_specs` 解析规格表
  （支持中文 尺寸/净重 与英文 External size(mm)/N.W.(kgs)）→ 尺寸/重量/容积

实现见 `chubb_ci/crawler/catalog.py`（`parse_catalog_entries`，会尊重 `<base href>`、
归一 www）。配置示例：

```yaml
- name: aipu-catalog
  company: 艾谱 AIPU
  fetcher: static            # JS 站用 browser；ZOL 等反爬站配 browser_wait_ms: 9000
  crawl_catalog: true
  enrich_details: true       # 详情页有可解析规格表时开启
  selectors: { product_href: 'products-info/\d+' }
  urls: [ .../products/1.html, ..., .../products/23.html ]   # 可枚举的分类页
```

**各官网现状**：艾谱 `aipuindustrial.com`（静态，英文规格表+官网图，~83 款）✅；
福美德 `format-tresorbau.de`（静态，~60 系列含安全等级）✅；迪堡 `dieboldsafe.com.cn`
（JS，分类页出商品链接，规格走 AJAX 不入 DOM → 仅名称+官网图，尽力而为）；
永发/ZOL 反爬更强，需进一步按站点调参（`browser_wait_ms` / AJAX 接口）。

## 多平台比价（`/price-comparison`）

同一款保险柜在京东/天猫/苏宁的标题各不相同，但**型号编码**（如 `AE881`、`BGX-D1-800`、
`4116G`）一致。入库时 `chubb_ci/diff/matching.py::model_code` 从商品名抽取该编码并写入
`ProductRecord.model_code`；比价页按 `(品牌, model_code)` 聚合，把各平台价格并排展示，
自动算出最低价与价差%。因此**只要在多个平台配置了同一品牌的搜索源**（已为苏宁在售的
得力/艾谱/甬康达/虎王/驰球 同步配置了京东源），登录后即可自动出现跨平台比价，无需改代码。

爬虫可靠性：`browser_fetcher` 对瞬时导航超时/冷启动抖动做**一次带退避的重试**（检测到反爬
则立即返回不重试），懒加载滚动确保价格瓦片渲染。

## 登录态采集（京东/天猫）

京东、天猫将价格藏在登录墙后。采集流程：

```bash
chubb-ci login jd        # 打开浏览器 → 手机扫码登录 → 回车保存会话
```

会话（Playwright `storage_state`）保存到 `data/sessions/<platform>.json`（已 gitignore），
抓取时自动注入（见 `chubb_ci/crawler/session.py` + `browser_fetcher.py`）。会话过期后重新
`login` 即可。**合规**：内部、非商用、低频、加延迟、遇到验证码优雅跳过。

各来源的瓦片 CSS 选择器写在 `config/sources.yaml` 的 `selectors:` 字段（item/name/price/
image/link/sales），无需改代码即可适配站点结构变化。

### 京东反爬现状（重要）

即使已登录，京东搜索页对自动化访问会返回软封锁页（HTTP 200 但**无商品瓦片**，页面深处含
`_noDataCen` + “很抱歉，由于访问频率过高，暂时无法访问，请稍后再试”）。本项目已能正确将其
识别为 `blocked`（不再静默记 0 款）。应对手段：

- **降频**：抓取器已在电商源之间加入 `CHUBB_RATE_LIMIT_DELAY`（默认 2s）间隔；触发封锁后
  需等待冷却（几十分钟）再试，或换网络/IP。
- **有头模式**：`CHUBB_BROWSER_HEADLESS=false chubb-ci crawl --kind daily` 用可见浏览器窗口
  抓取（对部分风控更友好）。注意：京东的“访问频率过高”是**按 IP 限流**，有头模式并不能绕过
  已触发的限流，仅降低触发概率。
- **彻底可靠**：京东/淘宝/抖音等强风控平台，推荐走下方**外部签名爬虫微服务**（带代理池）。

## 抖音 / 淘宝等（外部爬虫微服务）

对签名反爬强的平台（抖音商城、淘宝），推荐运行独立的签名爬虫服务，例如
[ShilongLee/Crawler](https://github.com/ShilongLee/Crawler)（Python+Node，覆盖抖音/淘宝/
京东/小红书等，Docker 部署，需 IP 代理池）。步骤：

1. 按其文档用 Docker 启动该服务，得到其 HTTP API 地址。
2. 在 `.env` 设置 `CHUBB_EXTERNAL_CRAWLER_URL=http://<host>:<port>`。
3. 在 `chubb_ci/crawler/external.py::CrawlerAPIFetcher` 中按其响应格式实现 `fetch`（把
   商品 JSON 适配成瓦片/详情），并在 `sources.yaml` 添加 `fetcher: external` 的来源。

> 该项目声明"仅供学习研究"，请遵守其许可与相关法规；本项目内部、非商用使用。

## 官方/合规通道（可选）

- **京东联盟 (JD Union) API**、**淘宝开放平台**：需商家/开发者资质，稳定合规但申请门槛高，
  适合规模化长期采集。当前内部低频场景用登录态 Playwright 即可。

### 价格 API 选型（2026-07-10 核查）

- `https://p.3.cn/prices/mgets?skuIds=<JD_SKU>` 是 free-api.com 所收录的京东价格查询地址，
  不是 free-api.com 自己提供的代理服务。其示例能按京东 SKU 返回 `p` / `op` 等价格字段，
  但没有可依赖的公开 SLA、版本契约、鉴权或变更通知。本项目只能把它作为**实验性降级源**：
  配置开关、严格超时/限频、响应校验、失败即跳过，并给每条价格保留 SKU、抓取时间和来源 URL。
  不应把它作为唯一生产价格源。本次执行环境无法解析 `p.3.cn`，因此尚未做线上响应验收。
- 京东宙斯/JOS 的正式路线需要注册开发者、创建应用并申请相应 API 权限；公开入口未证明存在可
  匿名批量读取任意竞品 SKU 实时价的稳定合同。若公司能取得联盟/商品能力权限，正式 API 应优先。
- 淘宝开放平台的 `taobao.item.get` 可返回商品价格，但当前官方文档将其标为增值 API 且需要授权；
  请求还需要 AppKey、签名和会话。企业购的商品详情/价格接口虽标为免费且无需用户授权，仍需要
  AppKey/签名并只面向企业购商品 ID，不能覆盖任意淘宝/天猫竞品。

结论：短期继续使用低频浏览器抓取，并可另做 `p.3.cn` 小规模试验；长期优先申请官方 JD/淘宝
应用权限。任何价格源上线前都要做至少一周的成功率、字段语义、地区/促销价差异和限流监测。

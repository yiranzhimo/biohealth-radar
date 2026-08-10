# BioHealth Radar

Biotech / 大健康情报雷达测试原型。

## Scope

这个原型先验证几个设计点：

- 一级分类：`Biotech 技术平台`、`AI Drug Discovery`、`Diagnostics & Precision Medicine`、`Clinical & Regulatory`、`Healthcare AI`、`Longevity & Wellness`、`Company & Market`
- 前沿专题：`Organoids`、`Virtual Cell`、`AI for Biology`、`Precision Oncology`、`Longevity`
- 证据分层：`Fact`、`Report`、`Inference`、`Unknown`
- 公司实体：通过稳定 `companyId` 把论文、试验、后续监管和公司事件连接到同一家公司

## Files

- `index.html`: GitHub Pages 入口
- `styles.css`: Dashboard 样式
- `app.js`: 搜索、筛选、视图切换、主题图
- `data.js`: 当前样例数据和来源 watchlist
- `data/companies.json`: 公司 watchlist、别名、方向和官方入口
- `data/evidence.json`: 从 signal 生成的可追溯证据记录
- `data/programs.json`: 从公司关联试验中发现、尚待核实归属的 program candidates
- `data/company_candidates.json`: 从外部来源自动发现并附带自动准入审核的公司候选
- `data/company_profiles.json`: 公司当前画像、覆盖度、最近变化和未知项
- `data/company_identity_links.json`: A/H/ADR/集团等共享标识关系候选（只建立可审计关系，不自动合并）

公司画像中的“最新定期报告”会优先从 SEC EDGAR 记录提取 10-Q（季报）、10-K/20-F（年报）和 6-K（半年报或临时报告）原始链接。港交所公司目前保留 HKEX/IR 入口，待接入港交所披露索引后再补齐香港年报和中期报告链接。
- `company-intelligence.js`: GitHub Pages 使用的公司情报构建产物
- `.github/workflows/pages.yml`: GitHub Pages Actions 部署
- `.github/workflows/ci.yml`: Pull request 数据与代码校验

## Local Test

只读预览可以直接打开 `index.html`，或在本目录运行：

```bash
python3 -m http.server 8080
```

然后访问：

```text
http://localhost:8080
```

需要直接在网页上处理少量人工候选时，使用仅绑定本机的审核服务：

```bash
python3 scripts/serve_review_ui.py --port 8000 --reviewer liqian
```

然后访问 `http://127.0.0.1:8000/`。人工候选卡片会显示“接受 / 合并 / 排除”按钮；操作会写入 `data/company_candidate_overrides.json`，自动重新生成候选审核和公司情报数据并执行校验。服务拒绝非本机 Origin，并且不公开 `.env`、`.git`、原始数据和人工覆盖文件。GitHub Pages 仍为只读站点，不显示写回按钮。

提交前运行完整校验：

```bash
python3 -m unittest discover -s tests
python3 scripts/validate_data.py
python3 scripts/discover_companies.py --check
python3 scripts/review_company_candidates.py --check
python3 scripts/build_company_intelligence.py --check
node --check app.js
node --check data.js
node --check company-intelligence.js
```

## Company Intelligence Build

公司情报层以 `data/companies.json` 中的公司为种子，并通过独立的 Company Discovery Engine 从官方来源发现尚未匹配的公司型实体：

```bash
python3 -m pip install -r requirements-company-discovery.txt
python3 scripts/collect_nih_reporter.py --page-size 20 --max-total 60
# 中国/香港官方上市公司种子：
python3 scripts/collect_china_hk_company_universe.py
# 需要带真实联系邮箱的 SEC_USER_AGENT：
python3 scripts/collect_sec_company_universe.py --count 100 --max-per-sic 500
python3 scripts/discover_companies.py
python3 scripts/review_company_candidates.py
python3 scripts/build_company_intelligence.py
```

发现流程分为两层：

- `mention`：来源中观察到的原始组织名称、角色、日期、URL 和 CIK / UEI / NIH IPF 等标识符。
- `candidate`：按稳定标识符或规范化名称聚类后形成的候选实体，并记录评分、状态、来源数和全部 mention IDs。

候选状态区分为：`identified`（单一官方来源但有稳定标识符）、`corroborated`（至少两个独立官方来源相互支持）和 `needs_review`（证据仍不足）。

候选发现后会进入独立的公司池准入审核。审核优先使用确定性规则而不是模型自由判断：唯一 SEC CIK 加 biotech SIC、NIH 营利机构 UEI/IPF 加 biotech 项目提示、中证科创生物指数证券代码、港交所 B/SB biotech 标记股票代码、恒生生物科技指数的港股代码加 ISIN，或具有稳定标识符的多来源候选，会自动标记为 `accepted`。缺少稳定标识、同类标识符冲突或官方证据不足时才进入 `needs_human`。自动通过只确认实体身份和 biotech 相关性，画像仍保持 `official_sources_pending`，不会假装主营业务已经核验。

人工结论保存在 `data/company_candidate_overrides.json`，支持 `accepted`、`rejected`、`merged` 和 `needs_human`。本地审核服务会自动写入候选输入哈希；候选来源发生变化后，过期结论会自动重新进入人工队列。

目前自动发现入口包括 ClinicalTrials.gov lead sponsor / collaborator、NIH RePORTER 营利性获资助机构、配置 `SEC_USER_AGENT` 后的 SEC biotech SIC 2833–2836 注册主体，以及三个中国/香港上市市场种子来源：中证科创生物指数全部 50 家当日成分股、港交所当前证券简称带 `B` / `SB` biotech 标记的股票、恒生生物科技指数当前 30 家成分股。SEC 入口按 SIC 分页读取，默认每类最多检查 500 条，属于可调上限而非完整市场名录。候选达到高分也不会直接写入正式 registry；只有具有稳定标识符并获得多来源支持时才会标记为 `autoPromotionEligible`，仍保留审计轨迹。

中国/香港采集器的边界会写入原始快照：中证 50 家成分股不代表全部中国 biotech 公司；港交所 `B` / `SB` 标记只覆盖目前仍按 Chapter 18A 标记交易的股票；恒生生物科技指数能补充部分已移除 `B` 标记的成熟公司，但只覆盖符合港股通资格且按指数方法筛选的最大 30 家。港股来源提供的是官方交易简称或指数名称，不应当作法定公司全称。CDE 临床试验平台目前对无人值守请求返回前端访问保护页，因此尚未接入定时工作流，也不会尝试绕过访问控制。

当前生成过程坚持以下边界：

- 来源记录先成为 Evidence，再进入公司画像。
- 未匹配 sponsor 只进入 `company_candidates.json`，不会自动写入正式 registry。
- 原始发现记录保存在 `company_mentions.json`，公司身份合并可以回溯到每条来源 mention。
- 试验 intervention 只能生成 `verificationStatus: candidate` 的 program candidate，不自动宣称资产归公司所有。
- 缺少官网、年报或 pipeline 正文支持时，主营业务摘要保持 `provisional`，未来方向保持 Unknown。
- 官网内容只作为有出处的公司自述（`Report`），不会自动升级为独立核验的事实。
- 只有含有明确计划措辞的官网短摘录才进入 `reportedPlans`，并继续标记 `needsReview`。

官方公司来源采集器只保存页面标题、描述、最多 4 条短摘录、语义内容哈希和整页可见文本哈希，不保存完整 HTML 或正文：

```bash
python3 scripts/collect_company_sources.py \
  --company recursion \
  --company crispr-therapeutics \
  --company moderna \
  --company legend-biotech \
  --company guardant-health
python3 scripts/translate_company_sources.py --batch-size 20
python3 scripts/build_company_intelligence.py
```

翻译脚本使用 OpenAI Responses API 将主营业务摘要和措辞明确的未来计划翻译为简体中文。官方原文不会被覆盖；中文、原文、内容哈希、模型、翻译时间和响应 ID 分开保存。内容哈希未变化时直接复用缓存，只有新增或变更文本才产生 API 调用。若有待翻译文本但 `OPENAI_API_KEY` 不可用，工作流会停止，避免静默发布未翻译内容。

`refresh-company-sources.yml` 现在检查全量 `company_profiles.json` 中的官方来源，并按画像类型采用不同刷新周期：重点公司官网每日检查，发现公司默认每周检查，管线和 IR 页面每周检查。采集器使用有限并发、失败重试、失败快照保留和到期跳过；内容不变时保留原始抓取时间和翻译缓存。`data/company_web_overrides.json` 用于补充或修正真实公司官网，市场/监管页面会明确标记为“真实官网待解析”。

画像采集同时输出业务、产品/管线和未来计划摘录，并由 `check_company_source_health.py` 统计成功率、失败原因和失败页面数量。失败率超过阈值时定时任务失败，避免静默发布空画像。

`refresh-company-discovery.yml` 每日刷新 NIH、中国/香港上市公司种子和可用的 SEC 公司发现数据；主数据刷新也会重新处理 ClinicalTrials.gov 中出现的申办方和合作方。

三个定时刷新工作流都在失败时调用 `send_workflow_failure_email.py`。邮箱地址和 SMTP 账号不写入仓库；在 GitHub Actions Variables 中配置 `SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`ALERT_EMAIL`，在 Actions Secrets 中配置 `SMTP_PASSWORD`。Gmail 通常使用 `smtp.gmail.com`、端口 `465` 和应用专用密码。邮件发送失败只产生 warning，不会覆盖原工作流的失败状态。

公司发现与画像输出：

- `data/raw/company_sources_latest.json`: 官方公司页面的轻量快照、短摘录和变更哈希
- `data/raw/company_website_resolution_queue.json`: 仍只有市场/监管链接、等待补充真实官网的队列
- `data/company_web_overrides.json`: 经人工核验的官网、IR 和 pipeline URL 覆盖
- `data/raw/company_translations_latest.json`: 官方页面文本的中文翻译缓存与翻译溯源
- `data/raw/nih_reporter_latest.json`: NIH biotech 相关营利机构项目的紧凑记录
- `data/raw/sec_company_universe_latest.json`: SEC biotech SIC 注册主体（配置后生成）
- `data/raw/china_hk_company_universe_latest.json`: 中证科创生物全部成分股、港交所当前 B/SB biotech 股票和恒生生物科技指数成分股
- `data/raw/company_discovery_latest.json`: mention、实体聚类、评分和候选状态
- `data/raw/company_candidate_reviews_latest.json`: 自动准入审核结果、理由、规则版本和输入哈希
- `data/company_mentions.json`: 发布用的可审计公司 mention 数据
- `data/company_candidates.json`: 发布用的候选公司实体
- `data/company_candidate_reviews.json`: 发布用的公司准入审核记录
- `data/company_candidate_overrides.json`: 少量人工接受、排除或合并结论
- `data/company_universe.json`: 正式画像公司与自动审核通过公司的统一公司池
- `data/company_profiles.json`: 正式 registry 公司的业务与证据画像

定时刷新会在采集和复核之后重建上述文件。CI 和 Pages 部署使用 `--check` 阻止陈旧的公司画像发布。

## PubMed Collection Test

第一版采集脚本使用 NCBI E-utilities 从 PubMed 拉取最近文献，做规则分类，并生成前端使用的 `data.js`：

```bash
python3 scripts/collect_pubmed.py --days 365 --retmax 6 --max-total 24
```

输出：

- `data/raw/pubmed_latest.json`: 原始解析记录、查询词、PMID、自动分类结果
- `data.js`: GitHub Pages 前端直接读取的数据

只测试采集和分类、不覆盖前端数据：

```bash
python3 scripts/collect_pubmed.py --dry-run
```

当前分类是规则分流，不是医学证据评价。所有自动采集的 PubMed signal 默认 `needsReview: true`。

PubMed 标题、摘要、期刊和作者机构会与公司 registry 的正式名称及别名匹配；只有明确名称命中才写入 `companyIds`，不会仅凭研究主题推断公司归属。

## ClinicalTrials.gov Collection Test

ClinicalTrials.gov 采集脚本会拉取试验登记记录，生成 `Registry` 类型 signal，并与当前 `data.js` 合并：

```bash
python3 scripts/collect_clinicaltrials.py --page-size 4 --max-total 24
```

输出：

- `data/raw/clinicaltrials_latest.json`: 原始解析试验记录、查询词、NCT ID、自动分类结果
- `data.js`: 合并后的前端数据

只测试采集和分类、不覆盖前端数据：

```bash
python3 scripts/collect_clinicaltrials.py --dry-run
```

ClinicalTrials.gov 记录只能证明试验登记事实，例如状态、入组数、设计、日期和申办方；不能单独证明疗效、安全性或临床获益。

试验的 lead sponsor、登记机构、标题、摘要和干预名称会与公司 registry 匹配，用于生成稳定的 `companyIds`。

## Company Watchlist

`data/companies.json` 当前包含 AI Drug Discovery、Gene Editing、RNA Therapeutics、Cell Therapy、Antibody / ADC、Targeted Protein Degradation、Precision Diagnostics、Sequencing & Research Tools、Organoids & Disease Models、Longevity 等方向的核心公司。

每家公司使用稳定 ID，并记录：

```text
id
name
aliases
ticker
exchange
ownership
headquarters
directions
modalities
watchTier
officialUrl
irUrl
pipelineUrl
```

修改 registry 后，可以把公司数据同步到前端并重新关联现有 signal：

```bash
python3 scripts/sync_companies.py
```

公司关联只表示来源记录中明确出现了公司名称，不表示公司支持论文结论，也不表示试验结果有效。

## SEC EDGAR Collection

SEC 采集器使用官方 ticker / CIK 映射和 submissions API，追踪 watchlist 中在美国上市或发行 ADR 的公司：

```bash
export SEC_USER_AGENT="BioHealth Radar your-email@example.com"
python3 scripts/collect_sec_edgar.py --days 14 --max-total 80
```

只测试连接、公司解析和表单分类，不写文件：

```bash
python3 scripts/collect_sec_edgar.py --days 7 --company recursion --dry-run
```

默认跟踪：

```text
8-K / 6-K
10-Q / 10-K / 20-F
S-1 / F-1
424B1 / 424B2 / 424B3 / 424B4 / 424B5
```

输出：

- `data/raw/sec_latest.json`: CIK 映射和原始 filing metadata
- `data.js`: 合并后的 `Company & Market` signal

第一版只根据 EDGAR metadata 确认“公司提交了某份表单”，不会自动解释正文或推断临床结果、融资完成、管线变化和商业影响。所有 SEC signal 默认 `needsReview: true`。

SEC signal 使用 `sourceType: Filing`，属于 Primary Sources，不与公司新闻稿混为一类。

SEC 要求自动访问声明带联系方式的 User-Agent，并限制在每秒 10 次请求以内。采集器每次请求间隔 0.15 秒；如果 SEC 返回 403，应先检查 `SEC_USER_AGENT`，也可能是运行环境的出口 IP 被其 fair-access 控制限制。

## OpenAI Review Test

OpenAI 复核脚本用于结构化预复核：检查分类是否被 signal 字段支持、`Fact / Report / Inference / Unknown` 是否分开、证据等级是否合理，并输出 `aiReview` 字段。

先设置环境变量：

```bash
export OPENAI_API_KEY="你的 key"
export OPENAI_REVIEW_MODEL="gpt-4o-mini"
export OPENAI_TRANSLATION_MODEL="gpt-4o-mini"
```

只查看待复核候选项，不调用 API：

```bash
python3 scripts/review_with_openai.py --dry-run --limit 5
```

调用 OpenAI API 并写入 `aiReview`：

```bash
python3 scripts/review_with_openai.py --limit 10
```

输出：

- `data/raw/openai_reviews_latest.json`: OpenAI 返回的结构化复核结果
- `data.js`: 带 `aiReview` 字段的前端数据

默认情况下，脚本不会自动把 `needsReview` 改成 `false`。如果要允许高置信、低风险条目自动移出复核队列：

```bash
python3 scripts/review_with_openai.py --limit 10 --apply-needs-review --auto-clear-threshold 0.85
```

复核判断针对卡片的发布质量，而不是判断医疗干预本身是否有效。仅仅涉及临床、监管或治疗主题不会自动要求人工复核；存在未被来源支持的疗效或安全结论、治疗建议、证据夸大、分类明显不可靠或字段矛盾时，才保留人工复核。

每版审核政策会写入 `aiReview.policyVersion`。旧政策结果会在后续运行中自动重新审核；需要主动重跑当前政策结果时，可以增加 `--force`。

审核输入会同时写入 `aiReview.inputHash`。同一 signal ID 的标题、日期、分类、来源或证据字段发生变化后，旧审核不会被继承，该条目会重新进入复核队列。

## Manual Review

人工复核完成的含义是：确认该 signal 可以从复核队列移出，并把 `needsReview` 改成 `false`。当前 GitHub Pages 是静态站，网页本身不能直接写回仓库；建议用脚本标记，不要手改 `data.js`。

列出待复核条目：

```bash
python3 - <<'PY'
import json
text=open('data.js', encoding='utf-8').read()
payload=json.loads(text.split('=',1)[1].strip().rstrip(';'))
for signal in payload['signals']:
    if signal.get('needsReview'):
        print(signal['id'], '|', signal['sourceType'], '|', signal['title'])
PY
```

标记单条为已复核：

```bash
python3 scripts/mark_reviewed.py pubmed-42443151 --reviewer "liqian" --note "分类和证据分层可接受"
```

标记多条为已复核：

```bash
python3 scripts/mark_reviewed.py pubmed-42443151 clinicaltrials-NCT06155305 --reviewer "liqian"
```

然后提交并推送：

```bash
git add data.js
git commit -m "Mark reviewed signals"
git push
```

被标记的条目会进入网页的 `已复核` 筛选视图，并显示 `Manual Review` 记录。

人工复核也记录对应的输入指纹；后续采集内容变化时，旧人工复核状态不会自动沿用。

## Scheduled Automation

仓库包含定时刷新 workflow：

```text
.github/workflows/refresh-data.yml
```

它会每 6 小时自动运行：

```text
PubMed collection -> ClinicalTrials.gov collection -> optional SEC EDGAR collection -> preserve prior aiReview -> OpenAI pre-review -> company discovery -> deterministic candidate review -> company intelligence build -> deploy GitHub Pages
```

每次自动处理所有尚未获得当前政策版本 AI 审核结果的信号，允许高置信通过自动退出 `Needs Review`。已有当前政策 `aiReview` 的条目会跳过；只有显式启用 `force_review` 才会重复审核。手动点击 `Run workflow` 时无需填写数量。

需要在 GitHub 仓库添加 Secret：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
Name: OPENAI_API_KEY
Value: 你的 OpenAI API key
```

可选添加变量：

```text
Settings -> Secrets and variables -> Actions -> Variables -> New repository variable
Name: OPENAI_REVIEW_MODEL
Value: gpt-4o-mini
```

公司来源翻译可以单独配置模型；未设置时沿用 `OPENAI_REVIEW_MODEL`：

```text
Name: OPENAI_TRANSLATION_MODEL
Value: gpt-4o-mini
```

启用 SEC EDGAR 采集还需要添加仓库变量：

```text
Name: SEC_USER_AGENT
Value: BioHealth Radar your-email@example.com
```

SEC 步骤是非阻断的：未配置时会跳过；SEC 暂时拒绝访问时不会阻止 PubMed、ClinicalTrials.gov 和页面部署。

外部 HTTP 请求会对超时、429 和常见 5xx 错误执行有限次数的指数退避重试；非暂时性配置或权限错误仍会立即失败。

如果 `OPENAI_API_KEY` 不可用，workflow 会在采集前明确失败，避免发布未经预复核的新数据。

GitHub Actions 的 scheduled workflow 不是严格实时系统，可能有延迟。当前实现适合“准实时/定时刷新”的静态站；如果需要用户打开网页时即时抓取和复核，需要迁移到带后端的架构，例如 Cloudflare Workers、Vercel Functions 或自建 API。

## GitHub Pages Deployment

1. 在 GitHub 新建一个仓库。
2. 把本目录内容 push 到仓库默认分支。
3. 在仓库 `Settings -> Pages -> Build and deployment` 里选择 `GitHub Actions`。
4. push 后 Actions 会把根目录作为静态站部署到 GitHub Pages。

### Troubleshooting

如果 Actions 出现以下错误：

```text
Get Pages site failed. Please verify that the repository has Pages enabled and configured to build using GitHub Actions
```

原因通常是仓库还没有启用 GitHub Pages，或者 Pages 的部署来源还不是 `GitHub Actions`。进入：

```text
Settings -> Pages -> Build and deployment -> Source
```

选择：

```text
GitHub Actions
```

保存后重新运行 workflow。

## Data Model

`data.js` 里的每条 signal 使用以下结构：

```text
id
date
title
entity
primaryCategory
subCategory
eventType
sourceType
sourceName
sourceUrl
reliability
evidenceLevel
needsReview
themes
tags
companyIds
fact
report
inference
unknown
```

后续可以把 `data.js` 替换为自动生成文件：

```text
source_registry -> raw_items -> curated_signals -> data.js
```

## Source Reliability

- `High`: 官方监管、注册平台、同行评议论文
- `Medium`: 公司公告、预印本、投资者材料
- `Low`: 行业媒体、二手报道、未核实数据库

医学和大健康内容不能从单个案例或公司声明直接推导治疗建议。

# BioHealth Radar

Biotech / 大健康情报雷达测试原型。

## Scope

这个原型先验证三个设计点：

- 一级分类：`Biotech 技术平台`、`AI Drug Discovery`、`Diagnostics & Precision Medicine`、`Clinical & Regulatory`、`Healthcare AI`、`Longevity & Wellness`
- 前沿专题：`Organoids`、`Virtual Cell`、`AI for Biology`、`Precision Oncology`、`Longevity`
- 证据分层：`Fact`、`Report`、`Inference`、`Unknown`

## Files

- `index.html`: GitHub Pages 入口
- `styles.css`: Dashboard 样式
- `app.js`: 搜索、筛选、视图切换、主题图
- `data.js`: 当前样例数据和来源 watchlist
- `.github/workflows/pages.yml`: GitHub Pages Actions 部署

## Local Test

直接打开 `index.html` 即可测试。也可以在本目录运行：

```bash
python3 -m http.server 8080
```

然后访问：

```text
http://localhost:8080
```

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

## OpenAI Review Test

OpenAI 复核脚本用于结构化预复核：检查分类是否被 signal 字段支持、`Fact / Report / Inference / Unknown` 是否分开、证据等级是否合理，并输出 `aiReview` 字段。

先设置环境变量：

```bash
export OPENAI_API_KEY="你的 key"
export OPENAI_REVIEW_MODEL="gpt-4o-mini"
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

## Scheduled Automation

仓库包含定时刷新 workflow：

```text
.github/workflows/refresh-data.yml
```

它会每 6 小时自动运行：

```text
PubMed collection -> ClinicalTrials.gov collection -> preserve prior aiReview -> OpenAI pre-review -> commit data.js -> deploy GitHub Pages
```

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

如果不设置 `OPENAI_API_KEY`，workflow 仍会自动采集 PubMed 和 ClinicalTrials.gov，但会跳过 OpenAI 预复核。

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

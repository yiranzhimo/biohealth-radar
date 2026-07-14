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

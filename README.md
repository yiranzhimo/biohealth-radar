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

## GitHub Pages Deployment

1. 在 GitHub 新建一个仓库。
2. 把本目录内容 push 到仓库默认分支。
3. 在仓库 `Settings -> Pages -> Build and deployment` 里选择 `GitHub Actions`。
4. push 后 Actions 会把根目录作为静态站部署到 GitHub Pages。

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

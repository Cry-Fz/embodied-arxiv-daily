# 具身智能 arXiv 日报 · 归档

一个可部署到 GitHub Pages 的静态 arXiv 论文归档站。项目默认面向具身智能方向，自动抓取 arXiv 论文，按日期归档，并支持关键词检索、多标签 AND 筛选、开源论文优先展示、明暗主题切换。

这个仓库的重点不是固定做某一个方向，而是提供一套可复用的“论文抓取 + 规则筛选 + 静态归档”模板。想换成其他方向时，主要改 `config.json`，页面和抓取脚本通常不需要改。

## 如何适配不同需求

核心配置文件是 `config.json`。网页里的 `rules.html` 会读取这个文件，展示规则摘要，支持 JSON 校验和导出，便于调整配置。

常用修改点：

- `site`：站点标题、描述、数据源和更新时间说明。
- `categories`：arXiv 分类范围，例如 `cs.RO`、`cs.CV`、`cs.AI`。
- `matching`：决定一篇论文是否进入归档。
- `strong_terms`：强相关词，命中后打分更高。
- `keywords`：普通相关词，用于扩大召回。
- `exclude_terms`：排除词，命中后直接过滤。
- `labels`：前端筛选标签，支持一篇论文命中多个标签。

## 匹配规则

`matching` 分为强锚点和弱锚点：

- `strong_anchor_terms`：强锚点。论文标题、摘要、comment 或分类中命中任意一个，就进入后续打分。
- `weak_anchor_rules`：弱锚点。`term` 必须和 `requires_any` 里的任意上下文词共同出现，才进入后续打分。

这样可以避免只靠宽泛词误收录。例如 `navigation`、`manipulation`、`reinforcement learning` 本身很宽，配置成弱锚点后，必须和机器人、物理环境、操作、移动等上下文共现才会放行。

当前匹配文本由以下字段拼接而成：

- title
- abstract，也就是 arXiv API 里的 `summary`
- arXiv comment
- arXiv categories

通过锚点门槛后，再按 `strong_terms`、`keywords`、标题命中、`cs.RO` 分类等计算分数；低于 `matching.minimum_score` 的论文会被过滤。

## 标签筛选

`labels` 决定前端展示的筛选项。标签之间是并行关系，不互相覆盖。一篇论文可以同时拥有多个标签，例如：

- `开源`
- `机器人操作`
- `VLA/多模态策略`
- `机械臂`

前端多选标签时使用 AND 逻辑：同时选中 `开源`、`机械臂`、`机器人操作`，只显示三个标签都命中的论文。

`开源` 标签不靠关键词判断，而是从摘要和 comment 中解析代码链接生成。目前识别 GitHub、GitLab、Bitbucket、Codeberg、Hugging Face。

## 迁移示例

如果要改成医学图像方向，可以大致这样调整：

- `categories` 改为 `cs.CV`、`eess.IV`、`q-bio.QM` 等。
- `matching.strong_anchor_terms` 放入 `medical imaging`、`radiology`、`segmentation` 等强领域词。
- `matching.weak_anchor_rules` 给 `segmentation`、`detection` 这类宽词增加 `MRI`、`CT`、`lesion`、`organ` 等上下文。
- `labels` 改成 `分割`、`检测`、`配准`、`影像报告`、`数据集/评测` 等。
- `exclude_terms` 加入你不想收录的方向。

如果要提高召回，优先增加强/弱锚点和普通关键词；如果结果太杂，优先收紧弱锚点上下文、提高 `minimum_score` 或补充 `exclude_terms`。

## 本地运行

```bash
python scripts/fetch_arxiv.py
python -m http.server 8000
```

打开：

```text
http://localhost:8000/
```

规则配置页：

```text
http://localhost:8000/rules.html
```

抓取指定日期：

```bash
python scripts/fetch_arxiv.py --date 2026-05-09
```

回填最近 7 天：

```bash
python scripts/fetch_arxiv.py --days 7
```

只根据本地 `data/papers` 重建索引：

```bash
python scripts/fetch_arxiv.py --rebuild-index
```

## 页面功能

- 首页 `index.html`：论文归档、检索、多标签筛选、日期筛选、论文链接。
- 规则页 `rules.html`：查看配置摘要、编辑 JSON、校验配置、导出配置。
- 明暗主题：默认跟随系统，也可以在页面右上角手动切换，选择会保存在浏览器本地。
- 开源优先：任意筛选结果中，带代码链接的论文排在前面。

## GitHub Pages 部署

```bash
git init
git add .
git commit -m "Initial arXiv daily site"
git branch -M main
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

然后在 GitHub 仓库中设置：

1. `Settings -> Pages`
2. `Source` 选择 `Deploy from a branch`
3. 分支选择 `main`
4. 目录选择 `/(root)`
5. 保存

上线地址通常是：

```text
https://你的用户名.github.io/你的仓库名/
```

自动更新由 `.github/workflows/update-arxiv.yml` 执行，默认每天北京时间 13:30 抓取一次。若 workflow 无法提交更新，到 `Settings -> Actions -> General -> Workflow permissions` 选择 `Read and write permissions`。

## 文件结构

```text
.
├── .github/workflows/update-arxiv.yml
├── assets/
│   ├── app.js
│   ├── rules.js
│   ├── styles.css
│   └── theme.js
├── config.json
├── data/
│   ├── index.json
│   └── papers/
├── index.html
├── rules.html
└── scripts/fetch_arxiv.py
```

# AI ContentOps Studio

[English](README.md) | [中文](README.zh-CN.md)

AI ContentOps Studio 是一个面向生产级场景设计的 AI 内容运营平台，用于自动化完成技术情报研究、基于来源的内容生成、质量评估、运行产物追踪和发布。

这个项目不是简单的 prompt demo，而是用来展示成熟 Applied AI Engineering 能力的工程化系统：

- 多步骤 LLM workflow 编排
- 基于来源的 research packet
- 先规划再生成的内容生产流程
- 可重复、可测试的质量评估
- 可观测的运行历史、trace 和 artifacts
- API、CLI、worker、publisher 清晰分层
- Review dashboard：可检查 artifact、source、evaluation、publish plan 和 run comparison
- YAML 定义的 worker jobs：可用于每日/每周内容选题计划
- AWS-ready artifact storage 和 Terraform deployment skeleton
- 本地优先开发，同时预留 AWS 生产化部署边界

## 项目能做什么

给定一个技术主题或一组真实网页来源，系统会创建一次内容运行任务：

1. 收集并标准化信息来源
2. 提取工程信号和关键 claims
3. 规划文章角度和大纲
4. 生成 Markdown 和 HTML 草稿
5. 评估 groundedness、source coverage、source quality、career relevance 和 publish readiness
6. 通过评估后发布到静态站点，或保留为待 review 状态
7. 持久化 artifacts、run metadata 和 trace，方便回溯、审查和对比

第一版 pipeline 采用本地 deterministic 模式，因此不需要 API key 也能在 CI 中运行。OpenAI、搜索 API、GitHub、AWS 等外部能力都通过 provider adapter 接入，后续可以扩展而不需要重写核心领域层。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
contentops run --topic "LLM observability for enterprise RAG systems"
contentops runs
pytest
```

启动 API：

```powershell
uvicorn contentops_api.main:app --reload --app-dir apps/api
```

创建一次内容生成任务：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/runs `
  -ContentType "application/json" `
  -Body '{"topic":"AI evaluation for RAG systems","publish":true}'
```

## 目录结构

```text
apps/
  api/                     FastAPI 后端服务
  cli/                     Typer 命令行工具
  worker/                  后台任务执行入口
packages/
  core/                    领域模型、pipeline 编排、artifact 存储
  providers/               Research、model、search 和外部系统 adapters
  evaluators/              内容质量和 groundedness 检查
  publishing/              静态站点和 GitHub Pages 发布器
  observability/           结构化 run trace
pipelines/                 YAML pipeline 定义
docs/                      架构、部署和评估方法文档
infra/                     Docker 和 AWS 部署说明
tests/                     单元测试和集成测试
```

## 架构原则

- Pipeline 必须有状态、可检查；每一步都写入 artifact。
- 外部服务必须放在 provider interface 后面。
- 生成内容必须先评估，再发布。
- 发布是明确的状态迁移，不是隐藏在生成逻辑里的副作用。
- 本地默认使用 filesystem 和 SQLite，同时预留 S3、RDS、EventBridge 等 AWS 生产边界。

## 当前能力

- 本地 research provider 和 deterministic source packet
- URL research provider：可抓取并标准化用户提供的网页来源
- Source 去重，以及 extraction status、quality、content length 元数据
- 可选 OpenAI Responses API generator，并且放在 provider 边界后面
- 可选 homepage publisher：可发布到 Zack 的 GitHub Pages 个人主页仓库
- Markdown 和 HTML 文章生成
- 内容质量评估报告
- SQLite run metadata
- Filesystem artifact store
- S3-ready artifact mirroring
- Static site publisher
- FastAPI `POST /runs` 和 `GET /runs`
- FastAPI artifact、metrics、rerun、publish-plan、publish、compare endpoints
- Worker 支持单任务或批量 YAML content calendar
- CLI `contentops run`、`contentops runs`、`contentops show`、`contentops artifacts`、`contentops publish`、`contentops metrics`、`contentops rerun`、`contentops publish-plan`、`contentops compare`
- Review dashboard 支持运行列表筛选、详情页审查、发布预览、运行时间线和 run comparison
- 覆盖核心 pipeline 行为的 pytest 测试

## Review workflow

先生成，检查 artifacts，再发布：

```powershell
contentops run --topic "AI quality gates for RAG systems"
contentops artifacts <run_id>
contentops show <run_id> --artifact eval-report.json
contentops publish-plan <run_id>
contentops metrics <run_id>
contentops compare <base_run_id> <candidate_run_id>
contentops rerun <run_id>
contentops publish <run_id>
```

API 也暴露同样的生命周期：

```text
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/artifacts/{artifact_name}
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/metrics
GET  /runs/{base_run_id}/compare/{candidate_run_id}
POST /runs/{run_id}/rerun
POST /runs/{run_id}/publish
```

Dashboard 地址：

```text
GET /dashboard
```

Dashboard 支持按 topic、run id 和 status 筛选运行记录。Run detail 页面包含 Source Review、Publish Plan、Run Timeline，以及对比两个 run 的入口。Run comparison 会展示 evaluation delta、source count delta、shared sources 和只存在于某个 run 的 sources，用于判断重新生成是否真的变好。

## Scheduled worker jobs

Worker 可以校验或执行 YAML 定义的内容选题计划：

```powershell
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --json
```

Job file 兼容旧的单任务格式，也支持更接近生产环境的批量任务：

```yaml
name: daily-ai-roundup
jobs:
  - name: production-llm-systems
    topic: "AI engineering signals for production LLM systems"
    publish: true
    source_urls: []
```

## Provider 配置

默认配置不需要任何外部密钥：

```text
CONTENTOPS_RESEARCH_PROVIDER=hybrid
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
```

在 AWS 部署中将 artifacts 镜像到 S3：

```text
CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3
CONTENTOPS_ARTIFACT_S3_BUCKET=your-artifact-bucket
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
```

启用 S3 镜像前需要安装可选 AWS 依赖：

```powershell
pip install -e ".[aws]"
```

使用真实网页来源：

```powershell
contentops run --topic "Agent observability" --source-url "https://example.com/article"
```

启用 OpenAI 内容生成：

```text
CONTENTOPS_GENERATOR_PROVIDER=openai
CONTENTOPS_OPENAI_API_KEY=...
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
```

发布到个人主页仓库：

```text
CONTENTOPS_PUBLISHER_PROVIDER=homepage
CONTENTOPS_HOMEPAGE_REPO_PATH=C:\Users\wangz\Documents\Codex\2026-05-22\files-mentioned-by-the-user-zackwang\zack-ai-homepage
CONTENTOPS_HOMEPAGE_PUBLIC_BASE_URL=https://zemeng2015.github.io/zack-ai-homepage
```

## 为什么这个项目有价值

它展示的不是“会调用大模型”，而是如何把 AI 能力包装成可靠的生产系统：

- workflow orchestration
- source-grounded generation
- evaluation gates
- artifact tracking
- API/CLI/worker 分层
- observability
- cloud-ready architecture

这类能力更贴近 Applied AI Engineer、LLM Systems Engineer、AI Platform Engineer 等岗位的真实工作。

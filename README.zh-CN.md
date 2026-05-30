# AI ContentOps Studio

[English](README.md) | [中文](README.zh-CN.md)

AI ContentOps Studio 是一个面向生产场景设计的 AI 内容运营平台，用于自动化完成技术情报研究、基于来源的内容生成、质量评估、产物追踪和发布。

这个项目不是简单的 prompt demo，而是用来展示成熟 Applied AI Engineering 能力的工程化系统：

- 多步骤 LLM workflow 编排
- 基于来源的 research packet
- 先规划再生成的内容生产流程
- 可重复、可测试的质量评估
- 可查询的 review queue，支持状态、关键词筛选和分页
- Review queue 支持批量 approve/reject
- 可观测的运行历史、trace 和 artifacts
- Artifact manifest 记录文件大小、类型、更新时间和内容哈希
- reviewed run 发布前必须有显式 approval record
- approve、reject、publish 等操作会追加写入 audit log
- source audit reports，包含来源评分、风险原因和 reviewer 建议
- publish receipts record file hashes, backup artifacts, and rollback hints
- publish receipt 会审计 provider、URL、approval 和变更文件
- incident reports 汇总失败、质量退化、预算超限、发布漂移和通知失败的运行信号
- operations summary 汇总队列深度、incident 严重级别、通过率和预算状态
- 可选 operator API key，用于保护 API 和 Dashboard 的写操作
- `/ready` 和 `contentops doctor` 用于生产部署前诊断
- API、CLI、worker、publisher 清晰分层
- Review dashboard 可检查 artifact、source、evaluation、publish plan 和 run comparison
- YAML 定义的 worker jobs，可用于每日或每周内容选题计划
- AWS-ready artifact storage、RDS、EventBridge 和 Terraform deployment skeleton

## 项目能力

给定一个技术主题或一组真实网页来源，系统会创建一次内容运行任务：

1. 收集并标准化信息来源
2. 提取工程信号和关键 claims
3. 规划文章角度和大纲
4. 生成 Markdown 和 HTML 草稿
5. 评估 groundedness、source coverage、source quality、career relevance 和 publish readiness
6. 保留为待 review 状态，审核批准或拒绝后再发布
7. 持久化 artifacts、run metadata 和 trace，方便回溯、审查和对比

默认 pipeline 采用本地 deterministic 模式，不需要 API key 也能在 CI 中运行。OpenAI、搜索 API、GitHub、AWS 等外部能力都通过 provider adapter 接入，后续扩展时不需要重写核心领域层。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
contentops run --topic "LLM observability for enterprise RAG systems"
contentops runs
contentops doctor
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
- URL research provider，可抓取并标准化用户提供的网页来源
- Feed research provider，可从 RSS/Atom feed 自动发现候选来源
- Search research provider，可接入 Brave-compatible web search API，并可抓取结果页面增强摘要
- Discovery research provider，组合 feed discovery、用户 URL 和本地 portfolio context
- Source 去重，以及 extraction status、quality、content length 元数据
- 可选 OpenAI Responses API generator，并且放在 provider 边界后面
- 可选 homepage publisher，可发布到 Zack 的 GitHub Pages 个人主页仓库
- Markdown 和 HTML 文章生成
- 内容质量评估报告
- SQLite run metadata，AWS 部署可替换为 RDS/Postgres
- Filesystem artifact store，AWS 部署可镜像到 S3
- Static site publisher
- FastAPI `POST /runs`、`GET /runs` 和 `GET /review-queue`
- FastAPI artifact、metrics、rerun、publish-plan、publish、compare endpoints
- FastAPI incident report endpoints，用于运维排障和发布健康检查
- Worker 支持单任务或批量 YAML content calendar
- CLI `contentops run`、`contentops runs`、`contentops show`、`contentops artifacts`
- CLI review 命令包括 `publish`、`metrics`、`rerun`、`publish-plan`、`compare`
- Review dashboard 支持运行列表筛选、分页、队列统计、详情页审查、发布预览、运行时间线和 run comparison
- 覆盖核心 pipeline 行为的 pytest 测试

## Review Workflow

先生成，检查 artifacts，再发布：

```powershell
contentops run --topic "AI quality gates for RAG systems"
contentops artifacts <run_id>
contentops show <run_id> --artifact eval-report.json
contentops publish-plan <run_id>
contentops metrics <run_id>
contentops scorecard <run_id>
contentops scorecards --status needs_review --json
contentops cost-report <run_id>
contentops cost-reports --status needs_review --json
contentops generation-receipt <run_id>
contentops source-audit <run_id>
contentops ops-summary --json
contentops compare <base_run_id> <candidate_run_id>
contentops queue --status needs_review --query "rag" --json
contentops manifest <run_id>
contentops audit-log <run_id>
contentops approve-many <run_id> <run_id> --reviewer "Zack" --json
contentops approve <run_id> --reviewer "Zack" --notes "Ready to publish"
contentops rerun <run_id>
contentops publish <run_id>
contentops publish-receipt <run_id>
contentops verify-publish <run_id>
contentops incident-report <run_id>
contentops incident-reports --status published --json
contentops rollback-publish <run_id> --actor "Zack"
```

API 暴露同样的生命周期：

```text
GET  /runs
GET  /review-queue?status=needs_review&q=rag&limit=20&offset=0
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/artifact-manifest
GET  /runs/{run_id}/bundle
GET  /runs/{run_id}/artifacts/{artifact_name}
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/metrics
GET  /runs/{run_id}/scorecard
GET  /runs/{run_id}/cost-report
GET  /runs/{run_id}/generation-receipt
GET  /runs/{run_id}/source-audit
GET  /runs/{run_id}/approval
GET  /runs/{run_id}/publish-receipt
GET  /runs/{run_id}/publish-verification
GET  /runs/{run_id}/incident-report
GET  /runs/{run_id}/audit-log
GET  /runs/{base_run_id}/compare/{candidate_run_id}
GET  /job-executions?limit=20&offset=0
GET  /job-executions/{execution_id}
GET  /content?limit=20&offset=0
GET  /scorecards?status=needs_review&q=rag&limit=20&offset=0
GET  /cost-reports?status=needs_review&q=rag&limit=20&offset=0
GET  /incident-reports?status=published&q=rag&limit=20&offset=0
GET  /ops-summary?window_size=100
GET  /ready
POST /review-queue/batch-approve
POST /review-queue/batch-reject
POST /runs/{run_id}/approve
POST /runs/{run_id}/reject
POST /runs/{run_id}/rerun
POST /runs/{run_id}/publish
POST /runs/{run_id}/rollback-publish
```

Dashboard 地址：

```text
GET /dashboard
```

Dashboard 支持数据库层面的 topic、run id、slug、status 筛选，并带有队列统计和分页。Run detail 页面包含 Source Review、Publish Plan、Run Timeline、Approval、Publish Receipt，以及对比两个 run 的入口。

待 review 的 run 必须先 approve 才能 publish，除非操作员显式使用 `force=true`。每次 approve 或 reject 都会写入 `approval.json`，每次成功发布都会写入 `publish-receipt.json`。关键 review 和 publish 操作还会追加写入 `audit-log.json`，方便追踪运营动作。

## Scheduled Worker Jobs

Worker 可以校验或执行 YAML 定义的内容选题计划：

```powershell
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
contentops job-executions --json
contentops job-execution <execution_id>
contentops content --json
contentops export-run <run_id> --output run-evidence.zip
```

Every worker execution writes a job receipt JSON file under
`CONTENTOPS_ARTIFACT_ROOT/job-executions` by default. Receipts include execution id, dry-run flag,
timestamps, duration, per-job status, run ids, artifact directories, publish URLs, tags, metadata,
and errors. Worker receipts are queryable from CLI, API, and dashboard, so scheduled content jobs
keep a durable execution history beyond stdout logs.

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

默认配置不需要任何外部密钥。`hybrid` 在没有 URL 时完全本地运行；`discovery` 会抓取配置好的 RSS/Atom feeds，适合每日 AI 技术雷达：

```text
CONTENTOPS_RESEARCH_PROVIDER=discovery
CONTENTOPS_RESEARCH_FEEDS=https://export.arxiv.org/api/query?search_query=cat:cs.AI%20OR%20cat:cs.CL%20OR%20cat:cs.LG&start=0&max_results=25&sortBy=submittedDate&sortOrder=descending
CONTENTOPS_RESEARCH_MAX_SOURCES=6
CONTENTOPS_RESEARCH_RETRY_ATTEMPTS=2
CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS=0.1
CONTENTOPS_RESEARCH_SEARCH_ENDPOINT=https://api.search.brave.com/res/v1/web/search
# CONTENTOPS_RESEARCH_SEARCH_API_KEY=
CONTENTOPS_RESEARCH_SEARCH_ENRICH=true
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_TIMEOUT_SECONDS=60
CONTENTOPS_OPENAI_RETRY_ATTEMPTS=2
CONTENTOPS_OPENAI_RETRY_BACKOFF_SECONDS=0.5
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
# CONTENTOPS_OPERATOR_API_KEY=
# CONTENTOPS_READ_API_KEY=
CONTENTOPS_REQUIRE_READ_API_KEY=false
CONTENTOPS_LATENCY_SLO_MS=120000
CONTENTOPS_MIN_SOURCE_COUNT=1
CONTENTOPS_TOKEN_BUDGET_PER_RUN=12000
```

Research provider 模式：

- `local`：确定性的本地 portfolio context，适合 CI
- `url`：抓取并标准化用户提供的 URL
- `hybrid`：用户 URL 加本地 context
- `feed`：从 RSS/Atom feeds 或 Atom search endpoints 自动发现来源
- `search`：从 Brave-compatible web search API 自动发现来源，并抓取结果 URL 增强来源质量
- `discovery`：feed discovery、用户 URL 和本地 portfolio context 组合模式

在 AWS 部署中将 artifacts 镜像到 S3：

Network-backed research providers retry transient timeouts, connection errors, `429`, and `5xx`
responses according to `CONTENTOPS_RESEARCH_RETRY_ATTEMPTS` and
`CONTENTOPS_RESEARCH_RETRY_BACKOFF_SECONDS`.

```text
CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3
CONTENTOPS_ARTIFACT_S3_BUCKET=your-artifact-bucket
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
```

启用 S3 镜像前需要安装可选 AWS 依赖。该依赖也会安装 RDS/Postgres 部署所需的 Postgres driver：

```powershell
pip install -e ".[aws]"
```

使用 Postgres/RDS 存储 run metadata：

```text
CONTENTOPS_DATABASE_URL=postgresql+psycopg://contentops:password@host:5432/contentops
```

保护共享环境中的写操作：

```text
CONTENTOPS_OPERATOR_API_KEY=replace-with-a-long-random-secret
```

配置后，创建 run、approve、reject、publish、rerun 等 mutation 需要 `X-ContentOps-Api-Key` header 或 `api_key` query 参数；只读接口仍可用于 dashboard 和集成。

使用真实网页来源：

```powershell
contentops run --topic "Agent observability" --source-url "https://example.com/article"
```

启用 OpenAI 内容生成：

```text
CONTENTOPS_GENERATOR_PROVIDER=openai
CONTENTOPS_OPENAI_API_KEY=...
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_TIMEOUT_SECONDS=60
CONTENTOPS_OPENAI_RETRY_ATTEMPTS=2
CONTENTOPS_OPENAI_RETRY_BACKOFF_SECONDS=0.5
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
```

OpenAI provider retries transient timeouts, connection errors, `429`, and `5xx` responses. When
`CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true`, exhausted provider failures fall back to the
deterministic template generator so scheduled runs can still produce reviewable artifacts.

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
- review queue and approval workflow
- API/CLI/worker 分层
- observability
- cloud-ready architecture

这类能力更贴近 Applied AI Engineer、LLM Systems Engineer、AI Platform Engineer 等岗位的真实工作。

# AI ContentOps Studio

[English](README.md) | [中文](README.zh-CN.md)

[![CI](https://github.com/zemeng2015/ai-contentops-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/zemeng2015/ai-contentops-studio/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI ContentOps Studio 是一个开源平台，用来把 AI 和技术选题变成可审核、有来源、可发布的文章。

它可以收集资料、生成草稿、评估质量、进入人工审核队列、发布通过审核的内容，并保存回执和证据，方便之后追踪每一次运行。

![AI ContentOps Studio demo walkthrough](docs/assets/demo-walkthrough.gif)

## 可以用它做什么

- 从技术选题或来源 URL 创建文章。
- 在发布前审核草稿。
- 检查质量、来源覆盖、token 预算和 incident 信号。
- 发布通过审核的内容，并保留文件 hash、发布回执和 rollback 线索。
- 用 YAML 定义定时内容任务，保留执行历史和恢复计划。
- 使用 Docker 和 AWS-ready Terraform 进行部署。

## 界面截图

![AI ContentOps Studio dashboard](docs/assets/dashboard-screenshot.png)

![AI ContentOps Studio operations trends](docs/assets/ops-trends-dashboard.png)

![AI ContentOps Studio architecture overview](docs/assets/architecture-overview.svg)

## 快速 Demo

使用 Docker 运行：

```powershell
docker compose up --build -d api
docker compose run --rm demo-seed
```

打开 Dashboard：

```text
http://localhost:8000/dashboard
```

Demo seed 会创建三类 run：一个已发布、一个已批准、一个等待审核。

## 本地安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
contentops run --topic "LLM observability for enterprise RAG systems"
contentops runs
contentops doctor
```

启动 API：

```powershell
uvicorn contentops_api.main:app --reload --app-dir apps/api
```

创建一次 run：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/runs `
  -ContentType "application/json" `
  -Body '{"topic":"AI evaluation for RAG systems","publish":true}'
```

## 核心流程

```text
Topic or URLs
  -> source research
  -> article planning
  -> draft generation
  -> quality evaluation
  -> human review
  -> publish approved content
  -> verify receipts and release evidence
```

每次运行都会写入可检查的 artifacts，例如：

- `research.json`
- `request.json`
- `workflow-context.json`
- `draft.md`
- `eval-report.json`
- `scorecard.json`
- `approval.json`
- `publish-receipt.json`
- `publish-verification.json`
- `audit-log.json`

## 功能

| 模块 | 能力 |
| --- | --- |
| Research | Local、URL、GitHub、Feed、Search、Discovery 多种研究 provider |
| Generation | 默认模板生成器，可选 OpenAI provider |
| Evaluation | groundedness、source coverage、technical depth、publish readiness |
| Review | review queue、状态过滤、批量 approve/reject、run comparison |
| Publishing | static site 和 git-aware homepage publisher、receipt、verification、rollback |
| Observability | trace、scorecard、token budget、incident、operations summary |
| Scheduling | YAML worker jobs、dry run、receipt、recovery plan |
| Release Evidence | deployment manifest、release readiness gate、CI evidence artifacts |
| Deployment | Docker、Alembic、S3 mirror、RDS、EventBridge、CloudWatch |

## CLI 示例

```powershell
contentops demo-seed
contentops queue --status needs_review --json
contentops scorecard <run_id>
contentops source-audit <run_id>
contentops publish-plan <run_id>
contentops approve <run_id> --reviewer "operator"
contentops publish <run_id>
contentops publish-receipt <run_id>
contentops homepage-handoff <run_id> --output homepage-handoff.zip
contentops release-evidence --output-dir release-evidence
```

## API

代表性接口：

```text
POST /runs
GET  /runs
GET  /dashboard
GET  /review-queue
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/scorecard
GET  /runs/{run_id}/source-audit
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/publish-receipt
GET  /runs/{run_id}/publish-verification
GET  /runs/{run_id}/homepage-handoff
GET  /ops-summary
GET  /deployment-manifest
GET  /release-readiness
GET  /release-evidence
GET  /worker-jobs
GET  /job-executions
```

## 定时任务

Worker job 使用 YAML 定义：

```yaml
name: daily-ai-roundup
jobs:
  - name: production-llm-systems
    topic: "AI engineering signals for production LLM systems"
    publish: false
    source_urls: []
    tags:
      - ai-engineering
      - portfolio
```

运行 worker：

```powershell
contentops worker-jobs --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
```

从 GitHub 项目仓库生成待审核的项目更新文章：

```powershell
$env:CONTENTOPS_RESEARCH_PROVIDER="github"
$env:CONTENTOPS_RESEARCH_GITHUB_TOKEN="..."
contentops-worker run-pipeline pipelines/project_repository_updates.yaml --dry-run --json
contentops-worker run-pipeline pipelines/project_repository_updates.yaml --receipt-dir artifacts/job-executions
```

失败的 worker 执行可以生成 recovery YAML：

```powershell
contentops job-recovery-plan <execution_id> --output recovery.yaml
```

## 配置

默认配置不需要外部密钥：

```text
CONTENTOPS_RESEARCH_PROVIDER=hybrid
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_DATABASE_URL=sqlite:///contentops.db
CONTENTOPS_ARTIFACT_ROOT=artifacts
```

使用 OpenAI：

```text
CONTENTOPS_GENERATOR_PROVIDER=openai
CONTENTOPS_OPENAI_API_KEY=...
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
```

使用 GitHub 仓库作为研究来源：

```text
CONTENTOPS_RESEARCH_PROVIDER=github
CONTENTOPS_RESEARCH_GITHUB_API_BASE_URL=https://api.github.com
CONTENTOPS_RESEARCH_GITHUB_TOKEN=...
```

然后在 `source_urls` 里传入仓库地址，例如 `https://github.com/owner/repo`。系统会把仓库
metadata、README、open issues 和 open pull requests 转成可审核的 research sources。

使用 S3 artifact mirror：

```text
CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3
CONTENTOPS_ARTIFACT_S3_BUCKET=your-artifact-bucket
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
```

使用 Postgres/RDS：

```text
CONTENTOPS_DATABASE_URL=postgresql+psycopg://contentops:password@host:5432/contentops
```

执行数据库迁移：

```powershell
alembic upgrade head
```

启用 S3 或 Postgres 前安装 AWS extras：

```powershell
pip install -e ".[aws]"
```

## 部署

仓库包含：

- Docker image 和 Compose profile
- 生产环境变量模板
- Alembic 数据库迁移
- AWS Terraform skeleton：S3、RDS、ECS task definitions、EventBridge Scheduler、CloudWatch
  dashboard 和 alarms

详见 [Deployment](docs/deployment.md) 和 [Production Runbook](docs/runbook.md)。

## 文档

- [Demo Walkthrough](docs/demo.md)
- [Showcase Package](docs/showcase.md)
- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Production Runbook](docs/runbook.md)
- [Evaluation Methodology](docs/eval-methodology.md)
- [Integration Smoke Tests](docs/integration-smoke.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=zemeng2015/ai-contentops-studio&type=Date)](https://www.star-history.com/#zemeng2015/ai-contentops-studio&Date)

## License

本项目采用 [MIT License](LICENSE)。

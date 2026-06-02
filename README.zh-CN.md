# AI ContentOps Studio

[English](README.md) | [中文](README.zh-CN.md)

[![CI](https://github.com/zemeng2015/ai-contentops-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/zemeng2015/ai-contentops-studio/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI ContentOps Studio 是一个面向生产形态设计的 AI 内容运营平台，用于自动化技术研究、基于来源的文章生成、质量评估、发布证据和内容发布流程。

这个项目的定位不是 prompt demo，而是一个可以展示 Applied AI Engineering 能力的完整作品：它包含 API、CLI、Dashboard、Worker、审计日志、质量门禁、发布回执、恢复计划和 AWS-ready 部署边界。

## 为什么做这个项目

大多数内容生成 demo 只做到“输入 prompt，得到文章”。真实团队还需要后面的工程系统：

- 来源要可追踪、可审计
- 生成过程要能复现、能 review
- 质量、延迟、成本、incident 和 release readiness 要能度量
- 发布前要有审批，发布后要有 receipt 和 rollback 线索
- 定时任务要有执行证据和失败恢复方案
- 本地开发不依赖密钥，同时保留 OpenAI、搜索 API、S3、RDS、ECS、EventBridge 的接入边界

## 目录

- [功能亮点](#功能亮点)
- [快速 Demo](#快速-demo)
- [快速开始](#快速开始)
- [架构](#架构)
- [Review 和运营流程](#review-和运营流程)
- [API 和 CLI](#api-和-cli)
- [Worker Jobs](#worker-jobs)
- [Provider 配置](#provider-配置)
- [测试](#测试)
- [Roadmap](#roadmap)
- [Star History](#star-history)
- [License](#license)

## 功能亮点

| 模块 | 能力 |
| --- | --- |
| Research | Local、URL、Feed、Search、Discovery 多种研究来源 |
| Generation | 默认模板生成器，支持 OpenAI provider 边界 |
| Evaluation | groundedness、source coverage、source quality、career relevance、publish readiness |
| Review | Review queue、状态和关键词过滤、批量 approve/reject、run comparison、Dashboard detail |
| Governance | 审批记录、audit log、operator API key、read API key |
| Publishing | Static site 和 homepage publisher、publish plan、receipt、verification、rollback |
| Observability | trace、scorecard、token budget、incident report、operations summary |
| Release Evidence | deployment manifest、release readiness gate、CI release evidence artifacts |
| Scheduling | YAML worker jobs、dry run、execution receipt、job catalog、recovery plan |
| Deployment | Docker、startup migrations、Alembic、S3 mirror、Terraform skeleton |

## 快速 Demo

```powershell
docker compose up --build -d api
docker compose run --rm demo-seed
```

打开：

```text
http://localhost:8000/dashboard
```

`demo-seed` 会创建 published、approved、needs-review 三类 run，方便直接查看 dashboard、artifacts、receipts、scorecards、incidents、release evidence 和静态站点输出。

更多说明见：[Demo Walkthrough](docs/demo.md)

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

通过 HTTP 创建一次 run：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/runs `
  -ContentType "application/json" `
  -Body '{"topic":"AI evaluation for RAG systems","publish":true}'
```

## 架构

```text
apps/
  api/                     FastAPI service 和 review dashboard
  cli/                     Typer CLI
  worker/                  YAML 定时任务入口
packages/
  core/                    领域模型、pipeline 编排、存储、诊断
  providers/               Research、model、search、external system adapters
  evaluators/              质量和 groundedness 检查
  publishing/              Static site 和 homepage publishers
  observability/           结构化运行 trace
pipelines/                 YAML 内容日历
docs/                      架构、部署、demo、runbook、集成测试文档
infra/                     Terraform 和部署骨架
tests/                     单元测试和集成测试
```

设计原则：

- pipeline 的每一步都写入可检查 artifact
- 生成内容先评估，再发布
- 发布是显式状态流转，有 receipt 和 rollback hints
- 外部服务都通过 provider interface 接入
- 本地默认 deterministic，生产路径 AWS-ready

文档：

- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Production Runbook](docs/runbook.md)
- [Integration Smoke Tests](docs/integration-smoke.md)

## Review 和运营流程

每篇文章都是一次可审计的 run：

1. 收集和标准化来源
2. 提取工程信号和 claims
3. 规划文章角度和大纲
4. 生成 Markdown 和 HTML 草稿
5. 评估质量、来源覆盖和发布准备度
6. 进入 review queue
7. approve、reject、publish、verify 或 rollback
8. 导出证据包，用于 release review 或 incident handoff

常用命令：

```powershell
contentops demo-seed
contentops queue --status needs_review --json
contentops artifacts <run_id>
contentops show <run_id> --artifact eval-report.json
contentops scorecard <run_id>
contentops cost-report <run_id>
contentops source-audit <run_id>
contentops publish-plan <run_id>
contentops approve <run_id> --reviewer "Zack" --notes "Ready to publish"
contentops publish <run_id>
contentops publish-receipt <run_id>
contentops verify-publish <run_id>
contentops rollback-publish <run_id> --actor "Zack"
contentops export-run <run_id> --output run-evidence.zip
```

运营和发布检查：

```powershell
contentops doctor --json
contentops ops-summary --json
contentops deployment-manifest
contentops release-readiness --json
contentops release-evidence --output-dir release-evidence
```

## API 和 CLI

代表性 API：

```text
POST /runs
GET  /runs
GET  /review-queue?status=needs_review&q=rag
GET  /runs/{run_id}/artifacts
GET  /runs/{run_id}/artifact-manifest
GET  /runs/{run_id}/bundle
GET  /runs/{run_id}/scorecard
GET  /runs/{run_id}/cost-report
GET  /runs/{run_id}/source-audit
GET  /runs/{run_id}/publish-plan
GET  /runs/{run_id}/publish-receipt
GET  /runs/{run_id}/publish-verification
GET  /runs/{run_id}/incident-report
GET  /runs/{run_id}/audit-log
GET  /runs/{base_run_id}/compare/{candidate_run_id}
GET  /content
GET  /scorecards
GET  /cost-reports
GET  /incident-reports
GET  /audit-events
GET  /retention-report
GET  /worker-jobs
GET  /job-executions
GET  /job-executions/{execution_id}/recovery-plan
GET  /ops-summary
GET  /deployment-manifest
GET  /release-readiness
GET  /release-evidence
GET  /ready
```

Dashboard：

```text
GET /dashboard
```

Dashboard 包含 review queue、run detail、source review、publish plan、scorecard、token budget、incident report、audit event、retention report、worker job catalog 和 worker execution receipt。

## Worker Jobs

Worker 可以校验和执行 YAML 定义的内容日历：

```powershell
contentops worker-jobs --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --dry-run --json
contentops-worker run-pipeline pipelines/daily_ai_roundup.yaml --receipt-dir artifacts/job-executions
```

示例：

```yaml
name: daily-ai-roundup
jobs:
  - name: production-llm-systems
    topic: "AI engineering signals for production LLM systems"
    publish: true
    source_urls: []
    tags:
      - ai-engineering
      - portfolio
```

Worker 执行 receipt 默认写入 `CONTENTOPS_ARTIFACT_ROOT/job-executions`。失败 receipt 可以生成可重跑的 recovery calendar：

```powershell
contentops job-executions --json
contentops job-execution <execution_id>
contentops job-recovery-plan <execution_id> --output recovery.yaml
```

## Provider 配置

默认本地运行不需要外部密钥：

```text
CONTENTOPS_RESEARCH_PROVIDER=hybrid
CONTENTOPS_GENERATOR_PROVIDER=template
CONTENTOPS_PUBLISHER_PROVIDER=static
CONTENTOPS_DATABASE_URL=sqlite:///contentops.db
CONTENTOPS_ARTIFACT_ROOT=artifacts
```

可选 OpenAI 生成：

```text
CONTENTOPS_GENERATOR_PROVIDER=openai
CONTENTOPS_OPENAI_API_KEY=...
CONTENTOPS_OPENAI_MODEL=gpt-5-mini
CONTENTOPS_OPENAI_FALLBACK_ON_FAILURE=true
```

可选 S3 artifact mirror：

```text
CONTENTOPS_ARTIFACT_STORE_PROVIDER=s3
CONTENTOPS_ARTIFACT_S3_BUCKET=your-artifact-bucket
CONTENTOPS_ARTIFACT_S3_PREFIX=contentops-artifacts
```

可选 Postgres/RDS：

```text
CONTENTOPS_DATABASE_URL=postgresql+psycopg://contentops:password@host:5432/contentops
alembic upgrade head
```

启用 S3 或 Postgres 前安装 AWS extras：

```powershell
pip install -e ".[aws]"
```

生产配置参考：[config/production.env.example](config/production.env.example)

## 测试

```powershell
python -m ruff check .
python -m mypy apps packages tests
python -m pytest
```

可选 live provider smoke tests：

```powershell
$env:CONTENTOPS_RUN_INTEGRATION="1"
pytest -m integration tests/test_integration_smoke.py
```

CI 会验证 Docker image build、Terraform fmt/validate、数据库迁移、worker dry run、release evidence、lint、type check 和测试。

## Roadmap

- CloudWatch dashboard 和 worker alarms
- GitHub repository research provider
- 更强的 Dashboard filtering 和 saved views
- 多 workspace 配置
- queue-backed worker execution
- 可部署的 ECS/EventBridge reference environment

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=zemeng2015/ai-contentops-studio&type=Date)](https://www.star-history.com/#zemeng2015/ai-contentops-studio&Date)

## License

本项目采用 [MIT License](LICENSE)。

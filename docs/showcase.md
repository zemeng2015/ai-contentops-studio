# Showcase Package

This page is the short, recruiter-friendly demo package for AI ContentOps Studio. It explains what
to show, what sample outputs mean, and how to present the project in a portfolio or interview.

## One-Sentence Pitch

AI ContentOps Studio turns technical topics into reviewed, source-backed articles with quality
checks, approval gates, publishing receipts, scheduled workers, and AWS-ready observability.

## Main Screenshot

![AI ContentOps Studio demo walkthrough](assets/demo-walkthrough.gif)

![AI ContentOps Studio dashboard](assets/dashboard-screenshot.png)

![AI ContentOps Studio operations trends](assets/ops-trends-dashboard.png)

## Architecture Snapshot

![AI ContentOps Studio architecture overview](assets/architecture-overview.svg)

## Sample Outputs

| Example | What it demonstrates |
| --- | --- |
| [Production LLM Evaluation Workflow](showcase/production-llm-evaluation-workflow.md) | Evaluation gates, release readiness, and reviewer trust |
| [Agent Reliability Checklist](showcase/agent-reliability-checklist.md) | Practical AI agent operations and failure handling |
| [AI Content Operations Dashboard](showcase/ai-content-operations-dashboard.md) | Dashboard, review queue, publishing receipts, and evidence exports |

These examples are intentionally written as portfolio artifacts. They help non-technical reviewers
understand the business value before they inspect the source code.

## Two-Minute Demo Script

1. Open `/dashboard` and show the three statuses: `needs_review`, `approved`, and `published`.
2. Open `/dashboard/ops-trends` and show daily throughput, quality, budget, and incident posture.
3. Open a run detail page and point to the source review, scorecard, cost report, and incident
   report.
4. Approve a run and explain that publishing is gated by review.
5. Publish the approved run and open the publish receipt.
6. Show `/release-evidence` or `contentops release-evidence` to prove the system has operational
   evidence.
7. Mention the AWS Terraform layer: scheduled worker, S3 artifacts, RDS metadata, CloudWatch
   dashboard, and alarms.

## Interview Talking Points

- The project separates domain logic from providers, which makes it easy to swap local, OpenAI,
  search, S3, or database implementations.
- Every run writes artifacts, so generated content is inspectable instead of opaque.
- Quality gates and approval records make publishing a controlled workflow.
- Operations trends show whether throughput, quality, cost, and incidents are improving over time.
- Worker receipts and recovery plans make scheduled automation debuggable.
- Terraform and CloudWatch resources show how the same app can move from local demo to an
  AWS-shaped production environment.

## Promotion Checklist

- Add the dashboard screenshot to the portfolio project card.
- Link to this showcase page from the personal homepage.
- Record a short screen capture following the two-minute demo script.
- Publish one blog post about the architecture and one blog post about evaluation gates.
- Add GitHub topics: `ai-engineering`, `llmops`, `fastapi`, `aws`, `terraform`, `observability`,
  `content-automation`, `portfolio-project`.

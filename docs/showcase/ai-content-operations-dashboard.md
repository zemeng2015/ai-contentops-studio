# AI Content Operations Dashboard

## Summary

This sample article explains why an AI content workflow needs an operations dashboard, not only a
generation script.

## Draft Article

A content generation script can produce a draft. A content operations dashboard helps a team decide
what to do next. The dashboard should answer practical questions: how many runs need review, which
articles are approved, which ones were published, what failed, and whether the system is ready for
the next release.

AI ContentOps Studio organizes these questions into one operator surface. The dashboard shows queue
depth, run status, scorecards, cost reports, incidents, audit events, worker jobs, worker execution
receipts, published content, and retention reports. A reviewer can move from portfolio-level health
to a single run's evidence without switching tools.

The important design choice is that the dashboard reflects persisted artifacts. It is not a
decorative UI over hidden state. The same evidence is available through the API and CLI.

## What The Platform Would Show

- queue counts for `needs_review`, `approved`, and `published`
- scorecards and token budget reports for recent runs
- incident summaries and action-required signals
- publish plans and receipts
- release evidence and deployment manifest links

## Business Value

This makes AI-generated content easier to review, operate, and explain to stakeholders who care
about reliability more than prompts.

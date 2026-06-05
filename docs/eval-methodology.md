# Evaluation Methodology

The MVP evaluator is deterministic and intentionally simple. It establishes the production
contract that every generated artifact must be scored before publishing.

Current scores:

- `groundedness`: generated claims reference known source titles
- `source_coverage`: generated article uses available sources
- `source_quality`: extracted sources have usable titles, summaries, readable content,
  source-type classification, authority scoring, topic relevance scoring, and duplicate handling
- `career_relevance`: article connects to Zack's target AI engineering positioning
- `technical_depth`: article contains architecture and workflow concepts
- `publish_ready`: all score dimensions meet the configured threshold

Future evaluator upgrades:

- source quote verification
- semantic duplicate detection against previous posts
- LLM-as-judge with calibrated rubrics
- factuality checks against retrieved snippets
- writing style regression tests
- project implication coverage by portfolio project
- provider-metadata review for query planning and repository maturity signals

from __future__ import annotations

from dataclasses import dataclass

from contentops_evaluators.quality import ContentEvaluator
from contentops_observability.tracing import RunTrace
from contentops_providers.research import ResearchProvider
from contentops_publishing.static_site import Publisher

from contentops_core.artifacts import ArtifactWriter
from contentops_core.generator import DraftGenerator
from contentops_core.models import RunRecord, RunRequest, RunStatus
from contentops_core.planner import ContentPlanner
from contentops_core.repository import RunRepository


@dataclass
class PipelineResult:
    run: RunRecord
    published_url: str | None


class ContentOpsPipeline:
    def __init__(
        self,
        repository: RunRepository,
        artifact_store: ArtifactWriter,
        research_provider: ResearchProvider,
        planner: ContentPlanner,
        generator: DraftGenerator,
        evaluator: ContentEvaluator,
        publisher: Publisher,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.research_provider = research_provider
        self.planner = planner
        self.generator = generator
        self.evaluator = evaluator
        self.publisher = publisher

    def run(self, request: RunRequest) -> PipelineResult:
        record = RunRecord.create(request, self.artifact_store.root)
        trace = RunTrace()
        self.artifact_store.prepare(record)
        self.artifact_store.write_json(record, "request.json", request)
        self.repository.save(record)
        try:
            record.touch(RunStatus.RESEARCHING)
            self.repository.save(record)
            trace.add("research", "started")
            packet = self.research_provider.collect(request)
            self.artifact_store.write_json(record, "research.json", packet)
            trace.add("research", "completed", sources=len(packet.sources))

            record.touch(RunStatus.PLANNING)
            self.repository.save(record)
            trace.add("planning", "started")
            plan = self.planner.plan(packet)
            self.artifact_store.write_json(record, "outline.json", plan)
            self.artifact_store.write_text(record, "outline.md", "\n".join(plan.outline))
            trace.add("planning", "completed", slug=plan.slug)

            record.touch(RunStatus.DRAFTING)
            self.repository.save(record)
            trace.add("drafting", "started")
            draft = self.generator.generate(packet, plan)
            self.artifact_store.write_json(record, "draft.json", draft)
            self.artifact_store.write_text(record, "draft.md", draft.markdown)
            self.artifact_store.write_text(record, "final.html", draft.html)
            trace.add("drafting", "completed", characters=len(draft.markdown))

            record.touch(RunStatus.EVALUATING)
            self.repository.save(record)
            trace.add("evaluation", "started")
            report = self.evaluator.evaluate(packet, draft)
            self.artifact_store.write_json(record, "eval-report.json", report)
            trace.add("evaluation", "completed", publish_ready=report.publish_ready)

            if request.publish and report.publish_ready:
                record.touch(RunStatus.PUBLISHING)
                self.repository.save(record)
                trace.add("publishing", "started")
                record.published_url = self.publisher.publish(record, draft, report)
                record.touch(RunStatus.PUBLISHED)
                trace.add("publishing", "completed", url=record.published_url)
            else:
                record.touch(RunStatus.NEEDS_REVIEW)
                trace.add("publishing", "skipped", requested=request.publish)
            self.artifact_store.write_json(record, "trace.json", trace.as_dict())
            self.repository.save(record)
            return PipelineResult(run=record, published_url=record.published_url)
        except Exception as exc:
            record.error = str(exc)
            record.touch(RunStatus.FAILED)
            trace.add("run", "failed", error=str(exc))
            self.artifact_store.write_json(record, "trace.json", trace.as_dict())
            self.repository.save(record)
            raise

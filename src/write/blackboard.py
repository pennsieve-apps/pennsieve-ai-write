"""Shared blackboard schema.

Vendored from `pennsieve-ai-analyze/src/analyze/blackboard.py`, with two
additions on `Hypothesis` for manuscript metadata. Keep the field set
backwards-compatible: every Hypothesis written by analyze must load
cleanly here (the new manuscript_* fields default to empty/zero on
hypotheses that haven't been through the write stage).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Claim:
    text: str
    source: str
    evidence_strength: str
    quote: str = ""
    quote_match: str = "not_checked"
    entailment: str = "not_checked"
    verification_note: str = ""


@dataclass
class DatasetSummary:
    id: str
    title: str
    description: str
    measurements: list[str]
    species: str
    n_subjects: int
    repo: str = ""
    url: str = ""
    doi: str = ""
    readme: str = ""
    file_types: dict = field(default_factory=dict)
    file_tree: str = ""
    record_tables: dict = field(default_factory=dict)
    external_publications: list[dict] = field(default_factory=list)
    bucket_uri: str = ""
    access_type: str = ""
    extracted_topics: list[str] = field(default_factory=list)
    license: str = ""
    size_bytes: int = 0
    file_count: int = 0
    relevance_note: str = ""


@dataclass
class DirectorBrief:
    field_landscape: str
    research_strategy: str
    focus_areas: list[str]
    lab_constraints: list[str]
    acceptance_criteria: list[str]
    suggested_queries: list[str]
    review_papers: list[dict] = field(default_factory=list)


@dataclass
class Hypothesis:
    id: str
    claim: str
    rationale: str
    supporting_evidence: list[int]
    predicted_observation: str
    suggested_experiment: str
    iteration: int = 1
    revises: str | None = None
    evidence_chunks: list[dict] = field(default_factory=list)
    lay_summary: str = ""

    # Analyze-stage fields (set by pennsieve-ai-analyze).
    analysis_workdir: str = ""
    analysis_summary: str = ""
    analysis_cost_usd: float = 0.0
    analysis_tools_called: list[str] = field(default_factory=list)
    analysis_started_at: str = ""
    analysis_finished_at: str = ""
    methods_critique: dict = field(default_factory=dict)

    # Write-stage fields (set by this processor).
    manuscript_path: str = ""               # relative path from OUTPUT_DIR root, e.g. "papers/H1/paper.md"
    manuscript_cost_usd: float = 0.0        # cumulative writer + auditor + revisor cost
    manuscript_iterations: int = 0          # 1 = writer only; 2 = writer + revise pass
    audit_summary: str = ""                 # auditor's one-paragraph summary
    audit_counts: dict = field(default_factory=dict)  # {supported, partial, unsupported, unverifiable}
    manuscript_started_at: str = ""
    manuscript_finished_at: str = ""


@dataclass
class CriticReview:
    hypothesis_id: str
    novelty: int
    plausibility: int
    feasibility: int
    alignment: int
    attacks: list[str]
    verdict: str
    iteration: int = 1


@dataclass
class Blackboard:
    research_question: str
    subsystem: str
    run_id: str = ""
    search_query: str = ""
    search_queries: list[str] = field(default_factory=list)
    max_iterations: int = 3
    iterations_completed: int = 0
    stop_reason: str = ""
    lab_profile: dict = field(default_factory=dict)
    director_brief: DirectorBrief | None = None
    papers_seen: list[dict] = field(default_factory=list)
    literature_claims: list[Claim] = field(default_factory=list)
    deep_evidence: list[dict] = field(default_factory=list)
    deep_read_stats: dict = field(default_factory=dict)
    collaboration_candidates: list[dict] = field(default_factory=list)
    dataset_summaries: list[DatasetSummary] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    critic_reviews: list[CriticReview] = field(default_factory=list)
    papers_enriched: dict = field(default_factory=dict)
    prior_papers: list[dict] = field(default_factory=list)
    cross_dataset_compatibility: list[dict] = field(default_factory=list)
    degraded: list[dict] = field(default_factory=list)
    model_assignments: dict = field(default_factory=dict)
    notebook: list[dict] = field(default_factory=list)

    def log(self, agent: str, action: str, content: str = "") -> None:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "agent": agent,
            "action": action,
            "content": content,
        }
        self.notebook.append(entry)
        suffix = f" — {content}" if content else ""
        print(f"[{entry['ts']}] {agent}: {action}{suffix}")

    def hypotheses_at(self, iteration: int) -> list[Hypothesis]:
        return [h for h in self.hypotheses if h.iteration == iteration]

    def reviews_at(self, iteration: int) -> list[CriticReview]:
        return [r for r in self.critic_reviews if r.iteration == iteration]

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, default=str))

    @classmethod
    def load(cls, path: Path) -> "Blackboard":
        raw = json.loads(Path(path).read_text())

        def _to(cls_, d):
            if d is None:
                return None
            return cls_(**{k: v for k, v in d.items() if k in cls_.__dataclass_fields__})

        bb = cls(
            research_question=raw.get("research_question", ""),
            subsystem=raw.get("subsystem", ""),
        )
        # Copy every plain field by name. A literal allow-list silently drops
        # fields added upstream; nested dataclass collections are rebuilt below.
        dataclass_valued = {
            "literature_claims", "dataset_summaries", "hypotheses",
            "critic_reviews", "director_brief",
        }
        for k, v in raw.items():
            if k in cls.__dataclass_fields__ and k not in dataclass_valued:
                setattr(bb, k, v)
        bb.literature_claims = [_to(Claim, x) for x in raw.get("literature_claims") or []]
        bb.dataset_summaries = [_to(DatasetSummary, x) for x in raw.get("dataset_summaries") or []]
        bb.hypotheses = [_to(Hypothesis, x) for x in raw.get("hypotheses") or []]
        bb.critic_reviews = [_to(CriticReview, x) for x in raw.get("critic_reviews") or []]
        if raw.get("director_brief"):
            bb.director_brief = _to(DirectorBrief, raw["director_brief"])
        return bb

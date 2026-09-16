from write.agents import paper_writer, paper_auditor
from write.blackboard import Blackboard, Hypothesis, DatasetSummary


def test_datacite_metadata_is_shared_with_auditor(monkeypatch):
    doi = "10.26275/pgzg-jlcs"
    bb = Blackboard("q", "pennsieve:405", dataset_summaries=[DatasetSummary(id="pennsieve:405", title="Seed", description="", measurements=[], species="", n_subjects=0, doi=doi)])
    h = Hypothesis("H1", "claim", "rationale", [], "prediction", "experiment")
    metadata = {doi: {"title": "Seed", "authors": "McKeague, Finn", "year": "2024", "journal": "Pennsieve Discover"}}
    monkeypatch.setattr(paper_writer.doi_lookup, "lookup_batch", lambda missing: metadata)
    monkeypatch.setattr(paper_writer.doi_lookup, "author_string", lambda *a, **k: "McKeague et al., 2024")
    assert "[DATASET]" in paper_writer._format_authoritative_bibliography(bb, h)
    assert bb.papers_enriched == metadata
    assert doi in paper_auditor._format_bibliography_for_audit(bb)
    assert doi in paper_auditor._format_dataset_context(bb)

# pennsieve-ai-write

Stage 4 of the `pennsieve-ai-*` research pipeline.

```
scout  →  hypothesize  →  analyze  →  write
                                       │
                                       └─►  scientific manuscript (markdown)
```

Reads the **blackboard** (a JSON document carrying datasets, literature, hypotheses, and per-hypothesis analysis artifacts) produced by `pennsieve-ai-analyze` and generates a focused scientific manuscript for one hypothesis.

## Pipeline

For the chosen hypothesis (set via `VP_WRITE_HYPOTHESIS_ID`, default `H1`):

1. Locate the executed notebook the analyze stage produced (`<analysis_workdir>/analysis.ipynb`).
2. **Paper Writer** (Opus): generate `paper.md` grounded in the notebook cells, the hypothesis context, the literature claims, and a citation-authoritative bibliography pulled from CrossRef/DataCite.
3. **(Optional) Discussion Enhancer** — STORM-style two-stage rewrite of the Discussion section. Disabled with `VP_WRITE_ENHANCE_DISCUSSION=0`. Adds:
   - **Survey** (Sonnet): four fixed personas (Skeptical Reviewer, Methodologist, Domain Expert, Reproducibility Analyst) each generate 2 questions + one-paragraph answers grounded in cell outputs + methods-critic concerns + the authoritative bibliography.
   - **Synthesize** (Opus): fold the 8 Q&A pairs into 4-6 paragraphs of coherent Discussion prose, splicing in place of the existing section.
   - The enhanced Discussion goes through the audit loop below, so synthesizer hallucinations get caught and revised.
4. **Audit ⇄ Revise loop**, up to `VP_WRITE_MAX_AUDIT_ITERS` iterations (default 3):
   - **Paper Auditor** (Sonnet): fact-check every numerical claim, citation, methodology statement, and dataset claim against the source artifacts. Produces per-iteration `audit.iter{N}.json` (and `audit.json` always tracking the latest) with per-claim `supported | partial | unsupported | unverifiable` verdicts.
   - Exit if the audit reports 0 unsupported claims, or max iters reached, or `VP_WRITE_REVISE=0`.
   - Otherwise **Paper Revisor** (Sonnet) runs with an auto-generated note targeting the unsupported claims, producing a new `paper.md`. The pre-revise text is snapshotted to `paper.iter{N}.md` so each audit JSON can be paired against the exact text it reviewed.
5. Write the updated blackboard, manuscript markdown, audit JSON, perspective Q&A, and PDFs to `OUTPUT_DIR/`.

Outputs:

```
OUTPUT_DIR/
├── blackboard.json                # updated with manuscript metadata
├── papers/<HYPOTHESIS_ID>/
│   ├── paper.md                   # final manuscript (post all revise iterations)
│   ├── paper.pdf                  # rendered version of the same
│   ├── paper_audited.pdf          # final text with FINAL audit's highlights
│   ├── paper_audited.md           # the audited-paper markdown (<mark> spans embedded)
│   ├── audit.json                 # final iteration's auditor verdicts (canonical)
│   ├── audit.iter1.json           # iter-1 audit (against writer output)
│   ├── audit.iter2.json           # iter-2 audit (against iter-1 revise output) — if loop ran
│   ├── audit.iter3.json           # iter-3 audit — if loop ran
│   ├── paper.iter1.md             # pre-revise snapshot — matches audit.iter1.json's text
│   ├── paper.iter2.md             # pre-revise snapshot — matches audit.iter2.json's text
│   ├── paper.preDiscussionEnhance.md   # paper.md BEFORE discussion enhancer ran (if it ran)
│   ├── discussion_perspectives.json    # the 4 personas × 2 Q&A pairs from the survey stage
│   └── figures/                   # PNGs extracted from the executed notebook
├── notebook.jsonl                 # blackboard event log
└── usage.jsonl                    # per-LLM-call cost log
```

The two PDFs serve different purposes:
- **`paper.pdf`** — clean rendering of the final manuscript. What you'd hand to a colleague.
- **`paper_audited.pdf`** — the **final** text with `<mark>`-wrapped highlights showing what the **final** audit flagged (yellow = partial, red = unsupported, orange = unverifiable). After the loop converges, this shows what's still concerning in the manuscript that ships — useful for downstream human review.

Each `audit.iter{N}.json` is paired with `paper.iter{N}.md` (the text that iteration audited). A reviewer can trace the convergence: read the iter-1 audit against iter-1 markdown, then see what iter-2 markdown changed in response, and so on.

PDF rendering is best-effort: if WeasyPrint's system libraries aren't available at runtime, `paper.md` and `audit.json` are still produced and the rendering failure is logged but doesn't fail the workflow.

## Environment

The platform injects all the standard processor env vars (`INPUT_DIR`, `OUTPUT_DIR`, `EXECUTION_RUN_ID`, etc.) and the governor-proxy plumbing (`ANTHROPIC_BASE_URL`, `HOME`, `LLM_GOVERNOR_FUNCTION_NAME`). This processor adds two of its own:

| Var | Default | Purpose |
|-----|---------|---------|
| `VP_WRITE_HYPOTHESIS_ID` | `H1` | Which hypothesis on the blackboard to write a manuscript for. |
| `VP_WRITE_ENHANCE_DISCUSSION` | `1` | If `0`, skip the STORM-style Discussion enhancer (saves ~$0.40 / paper, leaves the writer's first-pass Discussion in place). |
| `VP_WRITE_REVISE` | `1` | If `0`, run a single audit pass and skip the revisor entirely. |
| `VP_WRITE_MAX_AUDIT_ITERS` | `3` | Hard cap on audit ⇄ revise iterations. Loop also exits early on 0 unsupported claims. Worst-case cost = N × (one auditor call + one revisor call) ≈ $1-1.50 per iteration at Sonnet rates. |

## Compliance notes

This processor makes outbound HTTPS to `api.crossref.org` and `api.datacite.org` for DOI metadata enrichment. **It will not work on a compliant-mode compute node** — it fails fast at startup if `DEPLOYMENT_MODE=compliant` rather than silently producing manuscripts with fabricated citations (the writer is bibliography-grounded; degrading the bibliography breaks the safety story).

If you need manuscripts on compliant-mode workloads, the path forward is to either (a) cache the relevant DOI metadata into the blackboard at an earlier stage that runs outside the compute node, or (b) add a Pennsieve-controlled VPC endpoint for the metadata services. Not on the v0 roadmap.

## Local development

```bash
pip install -e .[dev]
INPUT_DIR=path/to/analyze-output OUTPUT_DIR=/tmp/write-out python -m write.main
```

`pip install -e .[dev]` brings in pytest + ruff.

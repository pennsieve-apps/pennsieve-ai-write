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
3. **Paper Auditor** (Sonnet): fact-check every numerical claim, citation, methodology statement, and dataset claim against the source artifacts. Produces `audit.json` with per-claim `supported | partial | unsupported | unverifiable` verdicts.
4. **Paper Revisor** (Sonnet): if the audit found any unsupported claims, revise `paper.md` to address them. One revise pass max for v0.
5. Write the updated blackboard, manuscript markdown, and audit JSON to `OUTPUT_DIR/`.

Outputs:

```
OUTPUT_DIR/
├── blackboard.json                          # updated with manuscript metadata
├── papers/<HYPOTHESIS_ID>/
│   ├── paper.md                             # the manuscript (latest, post-revise if applicable)
│   ├── paper.pdf                            # rendered version of the same
│   ├── paper_audited.pdf                    # pre-revise text with auditor highlights inline
│   ├── paper_audited.md                     # the audited-paper markdown (with <mark> spans)
│   ├── audit.json                           # auditor verdicts
│   ├── paper.preRevision.<timestamp>.md     # only if the revisor ran
│   └── figures/                             # PNGs extracted from the executed notebook
├── notebook.jsonl                           # blackboard event log
└── usage.jsonl                              # per-LLM-call cost log
```

The two PDFs serve different purposes:
- **`paper.pdf`** — clean rendering of the final manuscript. What you'd hand to a colleague.
- **`paper_audited.pdf`** — the **pre-revise** text with `<mark>`-wrapped highlights showing what the auditor flagged (yellow = partial, red = unsupported, orange = unverifiable). Useful for understanding what was concerning before the revisor went to work, even after the revisor has produced the cleaned-up text.

PDF rendering is best-effort: if WeasyPrint's system libraries aren't available at runtime, `paper.md` and `audit.json` are still produced and the rendering failure is logged but doesn't fail the workflow.

## Environment

The platform injects all the standard processor env vars (`INPUT_DIR`, `OUTPUT_DIR`, `EXECUTION_RUN_ID`, etc.) and the governor-proxy plumbing (`ANTHROPIC_BASE_URL`, `HOME`, `LLM_GOVERNOR_FUNCTION_NAME`). This processor adds two of its own:

| Var | Default | Purpose |
|-----|---------|---------|
| `VP_WRITE_HYPOTHESIS_ID` | `H1` | Which hypothesis on the blackboard to write a manuscript for. |
| `VP_WRITE_REVISE` | `1` | If `0`, skip the revisor pass (audit-only). |

## Compliance notes

This processor makes outbound HTTPS to `api.crossref.org` and `api.datacite.org` for DOI metadata enrichment. **It will not work on a compliant-mode compute node** — it fails fast at startup if `DEPLOYMENT_MODE=compliant` rather than silently producing manuscripts with fabricated citations (the writer is bibliography-grounded; degrading the bibliography breaks the safety story).

If you need manuscripts on compliant-mode workloads, the path forward is to either (a) cache the relevant DOI metadata into the blackboard at an earlier stage that runs outside the compute node, or (b) add a Pennsieve-controlled VPC endpoint for the metadata services. Not on the v0 roadmap.

## Local development

```bash
pip install -e .[dev]
INPUT_DIR=path/to/analyze-output OUTPUT_DIR=/tmp/write-out python -m write.main
```

`pip install -e .[dev]` brings in pytest + ruff.

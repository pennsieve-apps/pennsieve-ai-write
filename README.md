# pennsieve-ai-write

Stage 4 of the `pennsieve-ai-*` research pipeline.

```
scout  →  hypothesize  →  analyze  →  write
                                       │
                                       └─►  scientific manuscript (markdown)
```

Reads the **blackboard** (a JSON document carrying datasets, literature, hypotheses, and per-hypothesis analysis artifacts) produced by `pennsieve-ai-analyze` and generates a focused scientific manuscript for one hypothesis.

## Pipeline

For the chosen hypothesis (set via `VP_WRITE_HYPOTHESIS_ID`, default `auto`):

1. Locate the executed notebook the analyze stage produced (`<analysis_workdir>/analysis.ipynb`).
2. **Paper Writer** (reasoning role): generate `paper.md` grounded in the notebook cells, the hypothesis context, the literature claims, and a citation-authoritative bibliography pulled from CrossRef/DataCite.
3. **(Optional) Discussion Enhancer** — STORM-style two-stage rewrite of the Discussion section. Disabled with `VP_WRITE_ENHANCE_DISCUSSION=0`. Adds:
   - **Survey** (synthesis role): four fixed personas (Skeptical Reviewer, Methodologist, Domain Expert, Reproducibility Analyst) each generate 2 questions + one-paragraph answers grounded in cell outputs + methods-critic concerns + the authoritative bibliography.
   - **Synthesize** (reasoning role): fold the 8 Q&A pairs into 4-6 paragraphs of coherent Discussion prose, splicing in place of the existing section.
   - The enhanced Discussion goes through the audit loop below, so synthesizer hallucinations get caught and revised.
4. **Audit ⇄ Revise loop**, up to `VP_WRITE_MAX_AUDIT_ITERS` iterations (default 3):
   - **Paper Auditor** (synthesis role): fact-check every numerical claim, citation, methodology statement, and dataset claim against the source artifacts. Produces per-iteration `audit.iter{N}.json` (and `audit.json` always tracking the latest) with per-claim `supported | partial | unsupported | unverifiable` verdicts.
   - Exit successfully when the audit reports 0 unsupported claims. Reaching
     the iteration cap, or disabling revision while unsupported claims remain,
     blocks the stage after retaining all review artifacts.
   - Otherwise **Paper Revisor** (synthesis role) runs with an auto-generated note targeting the unsupported claims, producing a new `paper.md`. The pre-revise text is snapshotted to `paper.iter{N}.md` so each audit JSON can be paired against the exact text it reviewed.
5. Write the updated blackboard, manuscript markdown, audit JSON, perspective Q&A, and PDFs to `OUTPUT_DIR/`.

Outputs:

```
OUTPUT_DIR/
├── blackboard.json                # updated with manuscript metadata
├── papers/<HYPOTHESIS_ID>/
│   ├── paper.md                   # final manuscript (post all revise iterations)
│   ├── paper.tex                  # Pandoc LaTeX export (when Pandoc succeeds)
│   ├── paper.pdf                  # rendered version of the same
│   ├── paper_audited.pdf          # final text with FINAL audit's highlights
│   ├── paper_audited.md           # the audited-paper markdown (<mark> spans embedded)
│   ├── audit.json                 # final iteration's auditor verdicts (canonical)
│   ├── audit.iter1.json           # iter-1 audit (against writer output)
│   ├── audit.iter2.json           # iter-2 audit (against iter-1 revise output) — if loop ran
│   ├── audit.iter3.json           # iter-3 audit — if loop ran
│   ├── review.json                # ready_for_review or blocked, with final counts
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

Each `audit.iter{N}.json` is paired with `paper.iter{N}.md` (the text that
iteration audited, including the final pass). A reviewer can trace the
convergence: read the iter-1 audit against iter-1 markdown, then see what
iter-2 markdown changed in response, and so on.

PDF rendering is best-effort: if WeasyPrint's system libraries aren't available at runtime, `paper.md` and `audit.json` are still produced and the rendering failure is logged but doesn't fail the workflow.

## Environment

The platform injects the standard processor variables and
`LLM_GOVERNOR_FUNCTION_NAME`. Write uses direct governor Lambda transport; it
does not require the Anthropic-compatible sidecar used by Analyze's Agent SDK.
For local testing, you can set `VP_LLM_BACKEND=bedrock`. The stage then calls
Bedrock directly with your own AWS profile. The
[pennsieve-ai-utils README](https://github.com/Pennsieve/pennsieve-ai-utils#llm-client)
explains this setting.

| Var | Default | Purpose |
|-----|---------|---------|
| `INPUT_DIR` | `/mnt/efs/input` | Analyze output containing `blackboard.json` and the executed notebook. |
| `OUTPUT_DIR` | `/mnt/efs/output` | Destination for the updated blackboard and manuscript artifacts. |
| `EXECUTION_RUN_ID` | `local-dev` | Platform run identifier used for governor attribution. |
| `WORKFLOW_INSTANCE_ID` | `local-dev` | Platform workflow execution identifier. |
| `VP_LLM_BACKEND` | `governor` | This chooses where model requests go. Use `bedrock` or `anthropic` only for local testing. |
| `LLM_GOVERNOR_FUNCTION_NAME` | _(required for `governor`)_ | Governor Lambda used for discovery, preflight, and all LLM calls. |
| `AWS_REGION` | _(required for `bedrock`)_ | This is the Bedrock region. Your AWS login comes from `AWS_PROFILE` or AWS keys. |
| `VP_LOG_LLM_IO` | unset | Set this to `1` to save every model request and response, word for word, to `llm-io.write.jsonl`. |
| `VP_WRITE_HYPOTHESIS_ID` | `auto` | Which hypothesis on the blackboard to write a manuscript for. |
| `VP_WRITE_ENHANCE_DISCUSSION` | `1` | If `0`, skip the STORM-style Discussion enhancer (saves ~$0.40 / paper, leaves the writer's first-pass Discussion in place). |
| `VP_WRITE_REVISE` | `1` | If `0`, run a single audit pass and skip the revisor entirely. |
| `VP_WRITE_MAX_AUDIT_ITERS` | `3` | Hard cap on audit ⇄ revise iterations. Loop also exits early on 0 unsupported claims. Worst-case cost = N × (one auditor call + one revisor call) ≈ $1-1.50 per iteration at Sonnet rates. |
| `VP_MODEL_OPUS` | dynamically resolved | Explicit pin for reasoning-role writer/synthesizer calls. |
| `VP_MODEL_SONNET` | dynamically resolved | Explicit pin for synthesis-role survey/auditor/revisor calls. |
| `VP_LLM_MAX_RETRIES` | `1` on the governor, `4` on `bedrock` or `anthropic` | How many times the Anthropic SDK retries a failed request. The governor keeps one retry, because each of its timeouts already takes a minute. Direct backends retry more, to ride out short network dropouts. |

## Model routing

At startup, Write asks the governor which models it allows. It then sends a
tiny test request to each model it plans to use. The reasoning role uses Opus
5.5, then another Opus such as Opus 4.7, then Sonnet 5.5. The synthesis role
uses Sonnet 5.5, or Sonnet 4.6 if 5.5 is not allowed. If no allowed model is
strong enough for a role, the stage stops at startup.

Sometimes the governor refuses a model partway through a run. When that
happens, Write picks the next allowed model and tries again. It tries at most
three times. Responses are streamed. Each request is shaped for the model that
actually answers it, including after a retry.

You can choose a model yourself with a `VP_MODEL_*` setting. Write checks that
model at startup. If it is not allowed, Write stops instead of quietly using a
different model. To use a model weaker than Sonnet 5.5 for reasoning, name it on
purpose with `VP_MODEL_REASONING`. If you do, check the quality of the output
carefully.

## Pennsieve Test smoke check

A healthy run prints the model chosen for each role before `paper_writer`
starts. If the governor allows the 5.5 models, the key lines look like this:

```text
--- LLM preflight ---
  role assignments:
    reasoning  → us.anthropic.claude-opus-5-5 (rank 355)  [ranked]
    synthesis  → us.anthropic.claude-sonnet-5-5 (rank 255)  [ranked]

[llm] → paper_writer  role=opus  model=us.anthropic.claude-opus-5-5 ...
```

Success requires `paper_writer` and every executed auditor/revisor phase to
complete, a nonempty audit with valid claim verdicts, and zero unsupported
claims in the final audit. A blocked run retains its drafts, audit snapshots,
LaTeX export, and `review.json` for inspection. Discussion enhancement remains
optional and logs a skip if its survey or synthesis fails.

## Compliance notes

This processor makes outbound HTTPS to `api.crossref.org` and `api.datacite.org` for DOI metadata enrichment. **It will not work on a compliant-mode compute node** — it fails fast at startup if `DEPLOYMENT_MODE=compliant` rather than silently producing manuscripts with fabricated citations (the writer is bibliography-grounded; degrading the bibliography breaks the safety story).

If you need manuscripts on compliant-mode workloads, the path forward is to either (a) cache the relevant DOI metadata into the blackboard at an earlier stage that runs outside the compute node, or (b) add a Pennsieve-controlled VPC endpoint for the metadata services. Not on the v0 roadmap.

## Local development

```bash
pip install -e .[dev]
INPUT_DIR=path/to/analyze-output \
OUTPUT_DIR=/tmp/write-out \
LLM_GOVERNOR_FUNCTION_NAME=your-governor-lambda-name \
python -m write.main
```

You can also call Bedrock directly. To do that, remove
`LLM_GOVERNOR_FUNCTION_NAME`. Add `VP_LLM_BACKEND=bedrock`,
`AWS_PROFILE=<profile>` and `AWS_REGION=us-east-1`. Then name the models with
`VP_MODEL_REASONING` and `VP_MODEL_SYNTHESIS`.

`pip install -e .[dev]` brings in pytest + ruff.

## Blackboard compatibility

The shared `pennsieve-ai-utils` contract provides schema migrations and
preserves fields introduced by any stage. Write retains upstream diagnostics
and model provenance, then records its assignments under the `write` stage
namespace.

## Status

**v0.0.5 release candidate — locally validated; Pennsieve Test rerun pending.**
This candidate automatically selects the analyzed hypothesis, validates the
accepted hypothesis/methods/notebook handoff, treats unsupported final claims
as a blocking result, and emits paired review snapshots, LaTeX, and a compact
readiness record. It requires the Anthropic 1.x-compatible Governor transport
from `pennsieve-llm` 0.6.1. The rerun will confirm the current Bedrock
assignments.

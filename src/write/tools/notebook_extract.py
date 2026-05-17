"""Extract structured content from an executed Jupyter notebook.

The Paper Writer needs to ground its prose in (1) what the code actually did
and (2) what the cell outputs actually produced. This module parses an
executed `.ipynb` and returns a list of cells with their source, outputs
(stdout, dataframe text, image refs), and any errors — without dumping the
raw 100KB JSON into the LLM prompt.

Image outputs are written to disk as separate PNG files so the markdown
paper can reference them.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractedCell:
    index: int
    cell_type: str
    source: str
    text_outputs: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    error: dict | None = None


def extract(nb_path: Path, figures_dir: Path) -> list[ExtractedCell]:
    """Parse an executed notebook and return per-cell extracted content."""
    figures_dir = Path(figures_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)

    nb = json.loads(Path(nb_path).read_text())
    cells: list[ExtractedCell] = []

    for i, raw in enumerate(nb.get("cells", [])):
        ec = ExtractedCell(
            index=i,
            cell_type=raw.get("cell_type", "code"),
            source="".join(raw.get("source", [])),
        )
        for j, out in enumerate(raw.get("outputs") or []):
            otype = out.get("output_type")
            if otype == "stream":
                ec.text_outputs.append("".join(out.get("text") or []))
            elif otype in ("execute_result", "display_data"):
                data = out.get("data") or {}
                png_b64 = data.get("image/png")
                if png_b64:
                    fname = f"cell{i:02d}_out{j}.png"
                    fpath = figures_dir / fname
                    fpath.write_bytes(base64.b64decode(png_b64))
                    ec.image_paths.append(str(fpath.relative_to(figures_dir.parent)))
                txt = data.get("text/plain")
                if txt:
                    ec.text_outputs.append("".join(txt) if isinstance(txt, list) else str(txt))
            elif otype == "error":
                ec.error = {
                    "ename": out.get("ename", ""),
                    "evalue": out.get("evalue", ""),
                    "traceback": (out.get("traceback") or [])[-10:],
                }
        cells.append(ec)
    return cells


def find_notebook(workdir: Path, hypothesis_id: str) -> Path | None:
    """Find the executed notebook the analyze stage produced for this hypothesis.

    The agentic analyst's task prompt directs it to write `analysis.ipynb`
    in its cwd. We look there first, then fall back to any *_executed.ipynb
    pattern for compatibility with hand-run notebooks.
    """
    primary = workdir / "analysis.ipynb"
    if primary.exists():
        return primary
    candidates = sorted(
        list(workdir.glob(f"{hypothesis_id}*executed.ipynb"))
        + list(workdir.glob("*.ipynb")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def summarize_for_prompt(cells: list[ExtractedCell],
                         max_text_per_cell: int = 1500,
                         max_total_chars: int = 30000) -> str:
    """Render the extracted notebook as a prompt-friendly text block.

    Two-tier truncation: every cell ALWAYS appears in the output with at
    least its index, type, and any image_paths / error metadata. Only the
    verbose source + stdout body is dropped for cells beyond the budget.
    Prevents downstream prompts from hallucinating cell indices for figures
    that live in cells past the budget — a real failure mode when notebooks
    get long.
    """
    parts: list[str] = []
    total = 0
    in_compact = False
    for c in cells:
        header = f"### CELL {c.index} ({c.cell_type})"
        compact_lines = [header]
        if c.cell_type == "code":
            if c.image_paths:
                compact_lines.append(f"**figures produced:** {', '.join(c.image_paths)}")
            if c.error:
                compact_lines.append(
                    f"**ERROR:** `{c.error.get('ename','')}: {c.error.get('evalue','')[:120]}`"
                )
            first_src_line = next(
                (ln.strip() for ln in c.source.splitlines() if ln.strip()), ""
            )
            if first_src_line and (in_compact or c.image_paths or c.error):
                compact_lines.append(f"_first line: `{first_src_line[:120]}`_")
        elif c.cell_type == "markdown" and in_compact:
            md_first = (c.source.strip().splitlines() or [""])[0][:120]
            if md_first:
                compact_lines.append(f"_(markdown)_ {md_first}")
        compact_block = "\n".join(compact_lines)

        if in_compact:
            parts.append(compact_block)
            total += len(compact_block)
            continue

        full_lines = [header]
        if c.cell_type == "markdown":
            src = c.source.strip()
            full_lines.append(f"_(markdown)_\n{src[:max_text_per_cell]}")
        else:
            full_lines.append("```python\n" + c.source.strip()[:max_text_per_cell] + "\n```")
            if c.text_outputs:
                joined = "\n".join(c.text_outputs)
                full_lines.append("**stdout/result:**\n```\n" + joined[:max_text_per_cell].strip() + "\n```")
            if c.image_paths:
                full_lines.append(f"**figures produced:** {', '.join(c.image_paths)}")
            if c.error:
                tb = "\n".join(c.error.get("traceback") or [])
                full_lines.append(
                    f"**ERROR:** `{c.error['ename']}: {c.error['evalue']}`\n```\n{tb[:600]}\n```"
                )
        full_block = "\n\n".join(full_lines)
        parts.append(full_block)
        total += len(full_block)
        if total > max_total_chars:
            parts.append("\n(... budget exceeded; remaining cells shown in compact form — figure paths and errors preserved ...)")
            in_compact = True
    return "\n\n".join(parts)

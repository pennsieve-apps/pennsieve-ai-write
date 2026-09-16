"""Export the audited Markdown verbatim through Pandoc for LaTeX review."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def export_tex(markdown_path: Path) -> str | None:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return "pandoc unavailable; install it to export paper.tex (included in the Docker image)"
    try:
        subprocess.run(
            [pandoc, markdown_path.name, "--from=markdown-raw_tex-raw_html",
             "--to=latex", "--standalone", "--output=paper.tex"],
            cwd=markdown_path.parent, check=True, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"LaTeX export failed: {type(exc).__name__}"
    return None

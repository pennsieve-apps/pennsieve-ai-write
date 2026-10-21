# pennsieve-ai-write — manuscript-generation processor (stage 4).
#
# Reads an analyzed hypothesis + executed notebook from the analyze stage's
# blackboard, runs writer → auditor → (optional) revisor, writes paper.md
# back to OUTPUT_DIR for downstream consumption.
#
# Runtime contract (platform-managed, no Dockerfile changes needed):
#   - Runs as uid:gid 1000:1000 (ECS task-def override).
#   - HOME=/tmp and LLM_GOVERNOR_FUNCTION_NAME are injected by the
#     provisioner for direct governor Lambda transport.
#
# Note on compliance: this processor makes outbound HTTPS to api.crossref.org
# and api.datacite.org for DOI metadata enrichment (authoritative
# bibliography). That breaks "no internet egress" in compliant mode. The
# processor will not function on a compliant-mode compute node; we fail
# fast at startup rather than silently producing manuscripts with fabricated
# citations.

# Local builds can use a local copy of pennsieve-ai-utils instead of the
# version on PyPI. To do that, build with:
#   docker build --build-context utils=../pennsieve-ai-utils ...
# Without that option, this stage is empty and the PyPI version is used.
FROM scratch AS utils

FROM python:3.12-slim

# WeasyPrint runtime deps. Without these, importing weasyprint inside
# Python raises OSError at import time; pdf_render.render_pdf catches
# that and returns a clear error, but rendering would never succeed.
#  - libpango / libpangoft2 / libharfbuzz : text shaping
#  - libcairo2 : vector + raster compositor
#  - libfontconfig1 + fonts-dejavu : font resolution + a baseline font
#  - shared-mime-info : MIME sniffing for embedded images
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libfontconfig1 \
        fonts-dejavu-core \
        pandoc \
        shared-mime-info \
# LaTeX, for the bioRxiv preprint. bioRxiv does not typeset submissions and
# asks for LaTeX to be compiled before upload, so this stage has to produce
# the PDF itself: pdflatex through latexmk, the same toolchain as the lab's
# other manuscripts.
#
# Sizes, measured: the four base packages are 131MB, texlive-latex-extra adds
# 198MB and brings cleveref, titlesec, enumitem and changepage, which the
# preprint class uses. texlive-fonts-extra would add 1859MB and is only needed
# for Montserrat, so the class uses Helvetica instead and we leave it out.
# biorxiv-preprint.cls still degrades where any of these are missing, so the
# paper folder rebuilds on a plain TeX installation too.
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-fonts-recommended \
        texlive-latex-extra \
        lmodern \
        latexmk \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Source must be in place before `pip install .` because pyproject.toml's
# [tool.setuptools.packages.find] points at src/.
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .
COPY --from=utils / /tmp/pennsieve-ai-utils/
RUN if [ -f /tmp/pennsieve-ai-utils/pyproject.toml ]; then \
        pip install --no-cache-dir /tmp/pennsieve-ai-utils; \
    fi && rm -rf /tmp/pennsieve-ai-utils

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "write.main"]

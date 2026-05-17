# pennsieve-ai-write — manuscript-generation processor (stage 4).
#
# Reads an analyzed hypothesis + executed notebook from the analyze stage's
# blackboard, runs writer → auditor → (optional) revisor, writes paper.md
# back to OUTPUT_DIR for downstream consumption.
#
# Runtime contract (platform-managed, no Dockerfile changes needed):
#   - Runs as uid:gid 1000:1000 (ECS task-def override).
#   - HOME=/tmp, ANTHROPIC_BASE_URL=http://localhost:8765, and the
#     llm-governor-proxy sidecar are injected by the provisioner.
#
# Note on compliance: this processor makes outbound HTTPS to api.crossref.org
# and api.datacite.org for DOI metadata enrichment (authoritative
# bibliography). That breaks "no internet egress" in compliant mode. The
# processor will not function on a compliant-mode compute node; we fail
# fast at startup rather than silently producing manuscripts with fabricated
# citations.

FROM python:3.12-slim

WORKDIR /app

# Source must be in place before `pip install .` because pyproject.toml's
# [tool.setuptools.packages.find] points at src/.
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app/src

ENTRYPOINT ["python", "-m", "write.main"]

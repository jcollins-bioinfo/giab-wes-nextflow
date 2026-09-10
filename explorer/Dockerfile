# Build from repository root: docker build -f explorer/Dockerfile .
# Official Python linux/amd64 manifest verified 2026-09-10. Deploy the resulting
# project image by its ECR digest, never a mutable tag.
FROM python:3.13-slim-bookworm@sha256:2f2e5a876c71a6757f55ec57f2add0225ddaf01c802a33fcc29073943f94d907 AS build
WORKDIR /build
COPY explorer/requirements.lock /build/requirements.lock
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY explorer/pyproject.toml ./explorer/pyproject.toml
COPY explorer/src ./explorer/src
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels . ./explorer

FROM python:3.13-slim-bookworm@sha256:2f2e5a876c71a6757f55ec57f2add0225ddaf01c802a33fcc29073943f94d907
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --no-deps /wheels/*.whl \
    && rm -rf /wheels \
    && groupadd --gid 10001 explorer \
    && useradd --uid 10001 --gid 10001 --no-create-home explorer
USER 10001:10001
WORKDIR /tmp
EXPOSE 8050
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8050/research/giab-wes-nextflow/explorer/readyz', timeout=3)"]
CMD ["gunicorn", "pipeline_evidence_explorer.wsgi:server", "--bind", "0.0.0.0:8050", "--workers", "1", "--threads", "2", "--timeout", "60", "--graceful-timeout", "30", "--worker-tmp-dir", "/tmp", "--no-control-socket", "--access-logfile", "-", "--error-logfile", "-"]

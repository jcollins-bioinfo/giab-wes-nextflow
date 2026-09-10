# Support stages validate inputs/evidence in their own Nextflow container.
# This image contains no Docker/Apptainer/udocker or scientific tool runtime.
FROM python:3.13-slim-bookworm@sha256:2f2e5a876c71a6757f55ec57f2add0225ddaf01c802a33fcc29073943f94d907 AS build
WORKDIR /build
COPY containers/support-requirements.lock ./requirements.lock
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.13-slim-bookworm@sha256:2f2e5a876c71a6757f55ec57f2add0225ddaf01c802a33fcc29073943f94d907
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --no-deps /wheels/*.whl && rm -rf /wheels
# Nextflow supplies the task command and working directory.
CMD ["python", "--version"]

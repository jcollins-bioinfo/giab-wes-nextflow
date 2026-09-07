#!/usr/bin/env bash
# Canonical, restart-safe M2.1 verification/recovery launcher. It never publishes Gate B.
set -euo pipefail
MODE=${1:-verify}
REQUESTED_REF=${REPOSITORY_REF:-HEAD}
EXPECTED_REPOSITORY=jcollins-bioinfo/giab-wes-nextflow
PYTHON=${PYTHON:-python}
STAGING=${STAGING:-/content/m2-stage}
DRIVE_ROOT=${DRIVE_ROOT:-/content/drive/MyDrive/giab-wes-nextflow-private}
RUN_ID=${RUN_ID:-}
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
remote=$(git remote get-url origin 2>/dev/null || true)
# Match the entire origin; never print unexpected credential-bearing URLs.
case "$remote" in
  "https://github.com/${EXPECTED_REPOSITORY}"|"https://github.com/${EXPECTED_REPOSITORY}.git"|"git@github.com:${EXPECTED_REPOSITORY}.git"|"ssh://git@github.com/${EXPECTED_REPOSITORY}.git") ;;
  *) echo 'Refusing missing or unexpected repository origin.' >&2; exit 2 ;;
esac
RESOLVED_SHA=$(git rev-parse --verify --end-of-options "${REQUESTED_REF}^{commit}")
[[ $(git rev-parse HEAD) == "$RESOLVED_SHA" ]] || {
  echo 'Requested ref is not the checked-out commit. Check out the reviewed SHA first.' >&2; exit 2;
}
[[ -z $(git status --porcelain --untracked-files=normal) ]] || {
  echo 'Refusing modified or untracked source. Use a clean checkout of the reviewed SHA.' >&2; exit 2;
}
printf 'repository=%s requested_ref=%s resolved_sha=%s mode=%s\n' "$EXPECTED_REPOSITORY" "$REQUESTED_REF" "$RESOLVED_SHA" "$MODE"
[[ "$MODE" != identity ]] || exit 0
"$PYTHON" -I -m pip install --disable-pip-version-check "$ROOT"
"$PYTHON" -I -m giab_wes_nextflow.runtime_identity --source-root "$ROOT" --expected-sha "$RESOLVED_SHA"

verify_code() {
  git ls-files '*.json' '*.ipynb' | xargs -n1 "$PYTHON" -I -m json.tool >/dev/null
  "$PYTHON" -I scripts/validate_contracts.py
  "$PYTHON" -I -m giab_wes_nextflow.validation
  "$PYTHON" -I -m unittest discover -s tests/unit -v
  # Fixtures must exist before any samplesheet path check.
  "$PYTHON" -I tests/data/generate_fixture.py
  "$PYTHON" -I scripts/check_samplesheets.py
  "$PYTHON" -I scripts/check_repository.py
  "$PYTHON" -I scripts/validate_orchestration.py
  bash -n scripts/run_m2_readiness.sh
  echo 'CODE_VERIFICATION_COMPLETE (static/local; not Colab execution and not Gate B)'
}

case "$MODE" in
  verify) verify_code ;;
  preflight)
    [[ -n "$RUN_ID" ]] || { echo 'Set a deliberate, reusable RUN_ID.' >&2; exit 2; }
    "$PYTHON" -I -m giab_wes_nextflow.acquisition --workspace "$STAGING" --preflight-only
    echo 'DATA_OPERATION_CONFIGURED_ONLY: zero-download preflight completed.' ;;
  acquire)
    [[ -n "$RUN_ID" ]] || { echo 'Set RUN_ID.' >&2; exit 2; }
    mkdir -p "$STAGING"
    "$PYTHON" -I -m giab_wes_nextflow.acquisition --workspace "$STAGING" --run-id "$RUN_ID"
    echo 'Acquisition executed; canonical preparation/publication remains Gate B blocked.' ;;
  hydrate)
    [[ -n "$RUN_ID" ]] || { echo 'Set RUN_ID.' >&2; exit 2; }
    mkdir -p "$STAGING"
    hydrate_args=()
    [[ -z ${SOURCE_MANIFEST:-} ]] || hydrate_args+=(--source-manifest "$SOURCE_MANIFEST")
    [[ -z ${RECOVERY_RUN_ID:-} ]] || hydrate_args+=(--recovery-run-id "$RECOVERY_RUN_ID")
    "$PYTHON" -I -m giab_wes_nextflow.mirror --hydrate --drive-root "$DRIVE_ROOT" --staging "$STAGING" --run-id "$RUN_ID" --repository-sha "$RESOLVED_SHA" "${hydrate_args[@]}"
    echo 'Verified hydration executed; this is not Gate B completion.' ;;
  mirror)
    [[ -n "$RUN_ID" ]] || { echo 'Set RUN_ID.' >&2; exit 2; }
    "$PYTHON" -I -m giab_wes_nextflow.mirror --drive-root "$DRIVE_ROOT" --staging "$STAGING" --run-id "$RUN_ID" --repository-sha "$RESOLVED_SHA"
    echo 'Verified source mirror executed; no COMPLETED.json was created.' ;;
  prepare)
    command -v samtools >/dev/null || { echo 'samtools is required; in Colab run: apt-get update && apt-get install -y samtools' >&2; exit 3; }
    echo 'Preparation is configured but Gate B remains unresolved; refusing canonical preparation.' >&2; exit 4 ;;
  *) echo 'Usage: run_m2_readiness.sh {identity|verify|preflight|acquire|hydrate|mirror|prepare}' >&2; exit 2 ;;
esac

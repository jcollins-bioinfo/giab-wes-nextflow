#!/usr/bin/env bash
# Canonical, restart-safe M2.1 verification/recovery launcher. It never publishes Gate B.
set -euo pipefail
MODE=${1:-verify}
REQUESTED_REF=${REPOSITORY_REF:-HEAD}
EXPECTED_REPOSITORY=${EXPECTED_REPOSITORY:-jcollins-bioinfo/giab-wes-nextflow}
STAGING=${STAGING:-/content/m2-stage}
DRIVE_ROOT=${DRIVE_ROOT:-/content/drive/MyDrive/giab-wes-nextflow-private}
RUN_ID=${RUN_ID:-}
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
remote=$(git remote get-url origin 2>/dev/null || true)
if [[ -n "$remote" && "$remote" != *"${EXPECTED_REPOSITORY}"* ]]; then
  echo "Refusing repository with unexpected origin: $remote" >&2; exit 2
fi
RESOLVED_SHA=$(git rev-parse --verify "${REQUESTED_REF}^{commit}")
[[ $(git rev-parse --show-toplevel) == "$ROOT" ]] || exit 2
printf 'repository=%s requested_ref=%s resolved_sha=%s mode=%s\n' "$EXPECTED_REPOSITORY" "$REQUESTED_REF" "$RESOLVED_SHA" "$MODE"
python -m pip install --disable-pip-version-check "$ROOT"
python -c 'import giab_wes_nextflow; print("package", giab_wes_nextflow.__version__)'

verify_code() {
  git ls-files '*.json' '*.ipynb' | xargs -n1 python -m json.tool >/dev/null
  python scripts/validate_contracts.py
  python -m giab_wes_nextflow.validation
  python -m unittest discover -s tests/unit -v
  # Fixtures must exist before any samplesheet path check.
  python tests/data/generate_fixture.py
  python scripts/check_samplesheets.py
  python scripts/check_repository.py
  bash -n scripts/run_m2_readiness.sh
  echo 'CODE_VERIFICATION_COMPLETE (static/local; not Colab execution and not Gate B)'
}

case "$MODE" in
  verify) verify_code ;;
  preflight)
    [[ -n "$RUN_ID" ]] || { echo 'Set a deliberate, reusable RUN_ID.' >&2; exit 2; }
    giab-wes-acquire-m2 --workspace "$STAGING" --preflight-only
    echo 'DATA_OPERATION_CONFIGURED_ONLY: zero-download preflight completed.' ;;
  acquire)
    [[ -n "$RUN_ID" ]] || { echo 'Set RUN_ID.' >&2; exit 2; }
    mkdir -p "$STAGING"
    giab-wes-acquire-m2 --workspace "$STAGING" --run-id "$RUN_ID"
    echo 'Acquisition executed; canonical preparation/publication remains Gate B blocked.' ;;
  hydrate)
    [[ -n "$RUN_ID" ]] || { echo 'Set RUN_ID.' >&2; exit 2; }
    mkdir -p "$STAGING"
    giab-wes-mirror-m2 --hydrate --drive-root "$DRIVE_ROOT" --staging "$STAGING" --run-id "$RUN_ID"
    echo 'Verified hydration executed; this is not Gate B completion.' ;;
  mirror)
    [[ -n "$RUN_ID" ]] || { echo 'Set RUN_ID.' >&2; exit 2; }
    giab-wes-mirror-m2 --drive-root "$DRIVE_ROOT" --staging "$STAGING" --run-id "$RUN_ID" --repository-sha "$RESOLVED_SHA"
    echo 'Verified source mirror executed; no COMPLETED.json was created.' ;;
  prepare)
    command -v samtools >/dev/null || { echo 'samtools is required; in Colab run: apt-get update && apt-get install -y samtools' >&2; exit 3; }
    echo 'Preparation is configured but Gate B remains unresolved; refusing canonical preparation.' >&2; exit 4 ;;
  *) echo 'Usage: run_m2_readiness.sh {verify|preflight|acquire|hydrate|mirror|prepare}' >&2; exit 2 ;;
esac

# M2.1.1 source-cache recovery

Author: John Patrick Collins. This runbook restores source bytes and validates
provenance. It does not run Nextflow, prepare canonical domains or publish Gate B.
Use the exact repair commit and green required CI from the handoff. The recorded
source-cache revision is not the code revision to execute.

## Code and source identities

The latest observed source run is `m2-20260907T060256Z`, produced at
`568ad18bf6745c80d9aac346e9be151d7a850877`. Its exact source-manifest SHA-256 is
`fc880482cfae3e5eb89a40599f0d7804936ef7cfa4e0d2a53f3e2bf800d9ebda`.
The mirror control-record SHA-256 observed in Drive is
`1a2302fa7f28bea57860ecd98293981f09d9b0d92913d8862bc043b5d4a633a2`.
Ten source objects total 4,900,011,445 bytes according to that record and matching
current size metadata. This audit did not rehash those objects.

## Ordered owner-run cache recovery

Open the M2 notebook at the exact reviewed repair commit. Fill its required
`REPOSITORY_REF` with that commit, run code verification, then mount the existing
project folder. In a Colab Python cell after the bootstrap and mount cells, use:

```python
import hashlib
from pathlib import Path
import subprocess

LEGACY_SHA = "568ad18bf6745c80d9aac346e9be151d7a850877"
LEGACY_RUN = "m2-20260907T060256Z"
RECOVERY_RUN = "m2-recovery-20260907-01"  # retain for retries of the same operation
HISTORICAL_MANIFEST = Path("/content/m2-source-manifest-original.json")
payload = subprocess.run(
    ["git", "-C", str(REPOSITORY_DIR), "show", f"{LEGACY_SHA}:config/m2-resources.json"],
    check=True, capture_output=True,
).stdout
expected = "fc880482cfae3e5eb89a40599f0d7804936ef7cfa4e0d2a53f3e2bf800d9ebda"
if hashlib.sha256(payload).hexdigest() != expected:
    raise ValueError("Historical manifest identity mismatch; stop before copying data.")
HISTORICAL_MANIFEST.write_bytes(payload)
ENV.update(RUN_ID=LEGACY_RUN, SOURCE_MANIFEST=str(HISTORICAL_MANIFEST),
           RECOVERY_RUN_ID=RECOVERY_RUN)
subprocess.run(["bash", "scripts/run_m2_readiness.sh", "hydrate"],
               cwd=REPOSITORY_DIR, env=ENV, check=True)
subprocess.run([sys.executable, "-I", "-m", "giab_wes_nextflow.validation",
                "--workspace", str(STAGING), "--run-id", RECOVERY_RUN], check=True)
# Persist the newly validated acquisition record and source-cache identity.
ENV["RUN_ID"] = RECOVERY_RUN
subprocess.run(["bash", "scripts/run_m2_readiness.sh", "mirror"],
               cwd=REPOSITORY_DIR, env=ENV, check=True)
```

Hydration checks historical manifest identity and unchanged current resource
contracts before copying. It hashes source and destination bytes using declared
MD5, recorded SHA-256 and size. The new acquisition/hydration records retain the
historical run, repository, manifest and mirror hashes. No download is performed.
The selected Python runs isolated from inherited `PYTHONPATH`; installed code and
resources are compared with the clean reviewed checkout before data operations.

Expected local records under the staging root are
`registry/runs/<RECOVERY_RUN>/acquisition.json` and `hydration.json`. The mirror
operation adds a schema-validated `verified-source-mirror.json` under the same
new logical run in the established private registry. Capture the launcher identity
output and validator output. Successful source validation reports
`verified_sources_only`; it is not evidence of prepared references or domains.
Return only small control records/logs for follow-up validation, never FASTQ,
reference, truth, BAM or VCF bytes through Git or chat.

## Storage and failure behavior

Hydration needs approximately 4.9 GB of local source capacity plus headroom.
Reference decompression and BWA-MEM2 indexes require further measured capacity;
no sufficient-full-workflow-space claim follows from source preflight. The source
manifest contains unknown sizes, which preflight reports explicitly rather than
pretending the known-size sum is the full storage estimate. Existing verified
Drive objects are reused; Nextflow work directories and transient scratch are
never copied to the mirror.

Use the same run IDs after a runtime interruption. Existing destination bytes are
rehash-verified, and conflicts fail without deleting unexplained objects. Preserve
error messages and control files if any check fails. An unexpected hash, inventory,
source contract or repository identity is a stop condition, not permission to
substitute a different file. Choose a new run ID when intentionally recording a
new code/environment operation; prior records remain immutable.

The source cache does not resolve capture-design Gate B. No canonical publication
or alternative estimand is authorized by these commands.


## A lock remains after abrupt runtime loss

Per-object locks prevent overlapping acquisition/hydration/mirror writers. They
are never stolen automatically. If an operation fails with `lock busy`, first
stop and confirm that the former runtime and every writer using that workspace
have terminated. Preserve the lock and error as audit evidence. Only after that
confirmation may the owner move the specific stale `.lock` file to a separate
private audit location and rerun the same operation; do not remove cache objects,
source records or completion markers. A new runtime by itself does not prove
that another runtime has stopped writing to the shared Drive folder.

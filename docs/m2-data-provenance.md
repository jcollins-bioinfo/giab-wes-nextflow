# M2 data and provenance operations

## Completion gates

**Gate A** means code, contracts, tiny synthetic tests, documentation, and the Colab driver are ready. **Gate B** additionally requires real checksum observations, a confirmed capture-design identity, audited canonical domains, and a completed immutable Drive publication. This checkout establishes Gate A implementation; Gate B is blocked by the unresolved exact capture design and has not been executed.

## Storage and recovery

Budget at least 100 GB ephemeral space and 100 GB Drive space; operators must confirm actual `Content-Length` and free space before download because upstream sizes can change. Downloads go to `/content/m2-stage`, not Drive, and use `.part`, a per-object lock, bounded retry/backoff, MD5 verification, and atomic rename. Existing bytes are reverified; corrupt finals are quarantined. Re-run the same command after interruption. URLs recorded in observations omit query strings.

```bash
python scripts/acquire_m2.py --workspace /content/m2-stage --run-id m2-YYYYMMDD
python scripts/prepare_m2.py --workspace /content/m2-stage --run-id m2-YYYYMMDD
```

The second command prepares only reference resources while the target gate is unresolved. Once authoritative evidence confirms the exact target file, update the reviewed target evidence record, then provide `--target-bed` and `--source-dict`. Do not manually bypass the gate.

Publication is deliberately unavailable until `transformation.json` says canonical domains were materialized:

Before publication, the publisher requires a complete acquisition inventory tied to the current source-manifest hash and rehashes every downloaded and prepared artifact. The immutable run contains the decompressed FASTA and its generated indexes, the lifted target BED, all four canonical domain BEDs, and acquisition/transformation evidence; it does not depend on the ephemeral staging workspace after completion.

```bash
python scripts/publish_m2_workspace.py \
  --staging /content/m2-stage \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private \
  --run-id m2-YYYYMMDD
```

The publisher rejects the `DO NOT ACCESS WITH CHATGPT` marker, stages under `_incomplete`, rehashes destination bytes, atomically promotes the run, appends its registry record, and writes `COMPLETED.json` last. It never uses Drive as Nextflow `work/` or mutable cache.

## Interval semantics

BED is 0-based half-open; Picard interval lists are 1-based closed. A BED `[start,end)` becomes interval-list `[start+1,end]` without changing base count. Domains use only `chr1`–`chr22`,`chrX`; unknown contigs and out-of-bound coordinates fail. Summary JSON records definitions, parents, dictionary/output hashes, total and per-contig counts/bases, command implementation/version, run ID, timestamp, and status.

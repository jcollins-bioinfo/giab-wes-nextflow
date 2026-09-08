# Colab capability check and durable Drive storage

The owner selected Colab Pro. The launcher inspects the actual allocated runtime
before any index construction or real HG001 run. A Pro subscription does not
establish this session's RAM, disk, instruction support or container capability.

The owner returned the 8 September 2026 capability report from pinned commit
`676718ed6c02c3076a26b48fb82d684251fb7892`. Its 43 packaged Python/JSON file
identities were independently reconstructed. This is a consistency-checked
owner-supplied report, not cryptographic attestation of the remote host.

Observed: Linux/x86_64, eight logical CPUs, SSE4.1/SSE4.2/AVX, 54,750,404,608
bytes (50.99 GiB) physical/effective memory, unknown cgroup limit, and 205.69 GiB
free `/content` scratch. Docker is absent. The owner confirmed High-RAM was
already enabled. No source hydration, container installation, index build,
pipeline run or Drive publication occurred. See the [report](orchestration/evidence/colab-capability-observed-20260908.json)
and [assessment](orchestration/evidence/colab-capability-assessment.json).

The report records physical/cgroup memory ceilings, CPU architecture and selected
instruction flags, logical CPU count, local free disk and Docker daemon
reachability. Unknown values remain null. Drive filesystem free space is not
verified account quota. `canonical_ready` is always false at this stage.

BWA-MEM2's documented index-construction estimate is 28 times reference size:
86,797,831,148 bytes (about 80.84 GiB) for the 3,099,922,541-base reference,
before headroom. This is an estimate, not measured RSS or a guarantee of fit.
See the pinned [BWA-MEM2 2.3 documentation](https://github.com/bwa-mem2/bwa-mem2/tree/v2.3).
A verified compatible existing index could avoid rebuilding; none is verified yet.

## Storage contract

Permitted root: `/content/drive/MyDrive/giab-wes-nextflow-private`.

| Material | Durable location beneath that root |
|---|---|
| Verified FASTQs, reference/truth and independently sourced known-sites | `cache/verified-sources/` |
| Reference derivatives and BWA-MEM2 index, keyed by reference and index-manifest SHA-256 | `cache/reference-assets/sha256/<reference-id>/<index-manifest-id>/` |
| Validated BAM/BAI, calls, benchmark artifacts and run evidence | `runs/<run-id>/` |
| Append-only run records | `registry/runs/<run-id>/` |

Index construction uses Colab CPU/RAM and temporary Colab `/content` scratch.
Active Nextflow `work/`, sort temporaries and container working storage also
remain on Colab scratch. Large durable files are stored on Drive after destination
rehashing and inventory validation; the completion marker is written last.
Reuse requires validating the reference, tool/index identity, sizes and hashes.
Never access a folder marked `DO NOT ACCESS WITH CHATGPT`.

These paths define the required implementation contract; the capability check
does not create indexes or implement their publisher. Colab scratch can disappear
with the session. No source-cache copy or index has been published in this turn.

## Remaining execution gates

Qualify the actual runtime and pinned images; validate the approved coding-domain
implementation; hydrate and rehash the existing source cache; verify independent
BQSR known-sites against the reference; qualify index reuse or construction and
Drive publication; preserve the now-verified M4 synthetic acceptance; implement
and qualify canonical interfaces and common benchmarking. The current synthetic
drivers are not a real HG001 launcher.

## Reusable-index candidate and accelerator boundary

The Hartwig GRCh38 archive linked by nf-core/oncoanalyser 1.0.0 is labelled
BWA-MEM2 2.2.1 and reports 8,797,807,834 compressed bytes. Its 7,804-byte FAI
exactly matches the pinned GIAB FAI: 195 contigs, 3,099,922,541 bases. Its
36,113-byte sequence dictionary contains per-contig MD5 fields, not yet compared
against freshly authenticated project reference bases. FAI equality does not
prove reference-base or index equality. Reader compatibility with the pinned
BWA-MEM2 2.3 distribution remains unqualified; the candidate is not accepted.

The observed allocation does not qualify index construction. GPUs/TPUs do not
provide the CPU indexer's missing system RAM. More system RAM on a different
Colab allocation or qualified index reuse are distinct routes; container
isolation remains a separate gate. Never construct the index on the owner's Mac.

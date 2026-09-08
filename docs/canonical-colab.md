# Colab capability check and durable Drive storage

The owner selected Colab Pro. The launcher inspects the actual allocated runtime
before any index construction or real HG001 run. A Pro subscription does not
establish this session's RAM, disk, instruction support or container capability.

Run the pinned capability notebook in [the notebook launch center](../notebooks/README.md).
It verifies the repository checkout and installed package, mounts Drive through
Colab's native authorization prompt, and invokes the package-owned capability
probe. Return its `canonical-host-capability.json`. This observation does not
install Docker, pull tool images, download genomic files or construct an index.
The notebook has no saved output and has not yet been executed in the owner's
Colab session.

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
Drive publication; resolve M4's native synthetic acceptance failure; then implement
and qualify canonical interfaces and common benchmarking. The current synthetic
drivers are not a real HG001 launcher.

# v1.0 release-candidate preparation

No release candidate tag or GitHub release is published by this implementation.
The package remains the unreleased `0.5.0-dev.1` development line, with exact
reviewed commit and installed-file inventory as code identity. M5 is
synthetically verified; canonical Colab runtime/index/BQSR/full-reference gates
must pass in the owner's actual allocation before a canonical result or scoped
v1.0 candidate can be accepted.

The release checklist requires: clean source/origin/full SHA; Python3.12/3.13
unit and negative tests; wheel/sdist inventory and installed imports; Nextflow
lint and nf-tests; retained M3/M4/M5 evidence reconciliation; canonical public
bundle hash/schema/arithmetic/input-symmetry and private source lineage;
uncached-versus-cached resource distinctions; actual runtime qualification;
privacy/credential/sequence/large-file scans; tool/data license inventory;
claim-ledger and environment-status audit; Dash model/callback/browser checks;
and the website's data import/build/route/accessibility tests.

The tool inventory is `config/m3-tools.json`, `m4-tools.json`, `m5-tools.json`,
`canonical-assets.json` and `canonical-runtime.json`. BWA0.7.17 and its public
source/container provenance are distinct from historical BWA-MEM2. Data terms
and authoritative source links are retained in M2/canonical asset manifests.
Broad known-sites are not GIAB benchmark truth. No bundled tool binary, source
sequence, reference, index, BAM or VCF belongs in either repository.

After the real chr20–22 bundle is accepted, produce scoped release notes naming
HG001, the single original lane, full-reference alignment, exact approved coding
domain, both callers' effective quality inputs, native/normalized artifact hashes,
counts and resource limitations. The title/abstract must say chr20–22 and must
not claim whole-exome or population performance. Canonical full-domain execution
is a separate incomplete extension. Recompute all website/Explorer data from the
accepted bundle; do not hand-copy metrics.

Only after the owner explicitly authorizes a release may the reviewed commit be
tagged `v1.0.0-rc.1` and a prerelease created. The exact commands and final commit
must be supplied for that concrete reviewed state; no tag or release action is
automatically inferred from this checklist. Final `v1.0.0` additionally requires
explicit owner authorization and completion of its defining acceptance gate.

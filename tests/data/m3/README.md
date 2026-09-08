# M3 invented preprocessing fixture

This fixture is generated from the installed `giab_wes_nextflow.m3_fixture` package. No human, GIAB, vendor, reference-genome, nf-core, or externally downloaded sequence appears in the recipe. The original foundation fixture remains separate and unchanged.

Generate it after installing this repository as a package:

```bash
python tests/data/generate_m3_fixture.py --output tests/data/m3-generated
```

The fixture has two independently invented contigs totaling 20,000 bases, two sequencing lanes/read groups for `SYNTHETIC01`, and 24 paired 150-base reads. It includes 44 mapped and four unmapped reads, one three-copy fragment spanning both lanes (exactly two duplicate pairs should be marked and retained), overlapping mates, and a few deterministic mismatches. The 12 independent invented known sites test the mandatory BQSR plumbing. They are not a benchmark truth set. Original qualities vary by cycle and read; final OQ must match those actual original values, accounting for SAM strand orientation.

A SHA-256 counter supplies the invented reference alphabet. FASTQ gzip uses explicit stored-DEFLATE blocks with fixed headers and CRCs, so the bytes do not depend on a zlib compression heuristic, current time, filesystem path, or Python PRNG behavior. Samplesheet paths are relative to the samplesheet directory. The generator refuses conflicting pre-existing output bytes.

`expected-hashes.json` records the public source identities. The generated reference, reads, VCF, samplesheet, and full per-read expectations remain in the ignored `tests/data/m3-generated/` directory. Only this recipe, documentation, and small hash inventory belong in Git.

`m3_cli preflight` validates each input against the installed recipe before indexing. A user-supplied `synthetic: true` label or self-consistent alternate manifest cannot admit unrelated data. These tests establish preprocessing and provenance invariants for invented data; they establish no HG001 execution, caller accuracy, clinical validity, capture-domain resolution, or external deployment.

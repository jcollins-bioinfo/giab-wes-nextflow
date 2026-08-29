# Synthetic fixture

These four 32-base paired reads are deterministic, invented, nonhuman, and copied from no human, GIAB, vendor, or nf-core data. Generate with `python tests/data/generate_fixture.py` (Python PRNG fixed seed 1729, gzip mtime 0). `hashes.sha256` records the expected SHA-256 provenance. The generated gzip files are intentionally ignored rather than committed because the review transport rejects binary files. The tracked generator and expected hashes are the fixture contract. They test parsing/contracts/wiring only—not alignment or calling.

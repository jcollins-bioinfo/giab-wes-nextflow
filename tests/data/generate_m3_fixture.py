#!/usr/bin/env python3
"""Launch the installed package's deterministic M3 fixture recipe."""
import argparse
from giab_wes_nextflow.m3_fixture import generate_fixture


def main() -> None:
    """Write invented fixture bytes to the explicitly selected output directory."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="tests/data/m3-generated")
    args = parser.parse_args()
    result = generate_fixture(args.output)
    print(f"generated={len(result['files']) + 1} synthetic_pairs={result['pair_count']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Backward-compatible wrapper; implementation lives in the installed package."""
from giab_wes_nextflow.acquisition import main
if __name__ == "__main__":
    raise SystemExit(main())

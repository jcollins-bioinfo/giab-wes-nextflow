"""Installed-package-safe access to canonical configuration and schemas."""
from importlib.resources import files

def config_path(name: str):
    return files("giab_wes_nextflow").joinpath("data", "config", name)

def schema_path(name: str):
    return files("giab_wes_nextflow").joinpath("data", "schemas", name)

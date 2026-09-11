"""Gunicorn entrypoint with an explicit validated deployment prefix."""
import os
from .app import DEFAULT_PREFIX, create_app

app = create_app(prefix=os.environ.get("EXPLORER_PREFIX", DEFAULT_PREFIX))
server = app.server

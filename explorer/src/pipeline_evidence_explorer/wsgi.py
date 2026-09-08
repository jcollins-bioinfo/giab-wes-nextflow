"""Gunicorn entry point with synthetic default and optional trusted canonical bundle."""
from .app import create_app

app = create_app()
server = app.server

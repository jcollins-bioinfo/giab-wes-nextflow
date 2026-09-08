"""Gunicorn entry point for the explicitly noncanonical prototype."""
from .app import create_app

app = create_app()
server = app.server

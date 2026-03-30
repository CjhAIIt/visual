"""Stable ASGI import target for deployment tooling.

This keeps `uvicorn plantbackend.asgi:app` working even if the internal app
factory evolves again later.
"""

try:
    from .app import app
except ImportError:
    from app import app

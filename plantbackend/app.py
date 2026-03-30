"""Compatibility wrapper for the Plant backend app factory.

Keeping this module tiny preserves the `plantbackend.app:app` import path for
Uvicorn and other tooling while the real construction logic lives in
`plantbackend.factory`.
"""

try:
    from .factory import create_app
except ImportError:
    from factory import create_app


app = create_app()


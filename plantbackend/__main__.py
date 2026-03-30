"""Allow `python -m plantbackend` to start the API locally."""

from __future__ import annotations

import socket

import uvicorn

try:
    from .asgi import app
    from .config import settings
except ImportError:
    from asgi import app
    from config import settings


def _is_port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            candidate.bind((host, port))
        return True
    except OSError:
        return False


def _choose_port(host: str, preferred_port: int) -> int:
    for candidate_port in (preferred_port, preferred_port + 1, preferred_port + 2, 8000, 8001):
        if _is_port_available(host, candidate_port):
            return candidate_port
    return preferred_port


def main() -> None:
    """Run the backend with the configured host and port."""

    selected_port = _choose_port(settings.api_host, settings.api_port)
    uvicorn.run(app, host=settings.api_host, port=selected_port)


if __name__ == "__main__":
    main()

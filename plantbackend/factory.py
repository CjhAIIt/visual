"""FastAPI application factory for the Plant backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from .api_router import router
    from .config import settings
    from .metadata import APP_DESCRIPTION, APP_NAME
except ImportError:
    from api_router import router
    from config import settings
    from metadata import APP_DESCRIPTION, APP_NAME


def create_app() -> FastAPI:
    """Build the ASGI app with middleware and the shared API router."""

    application = FastAPI(
        title=settings.api_title or APP_NAME,
        version=settings.api_version,
        description=APP_DESCRIPTION,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


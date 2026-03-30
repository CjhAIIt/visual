"""Plant backend package."""

try:
    from .metadata import APP_NAME
except ImportError:
    from metadata import APP_NAME

__all__ = ["APP_NAME"]

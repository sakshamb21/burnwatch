"""BurnWatch configuration alias for backwards compatibility."""

from burnwatch.config.settings import (
    DataSource,
    Settings,
    StorageBackend,
    get_settings,
)

__all__ = ["DataSource", "Settings", "StorageBackend", "get_settings"]

"""Stores for the namespace-package fixture constellation."""

from kente.config import get_setting
from kente.service import health

__all__ = ["cache_url"]


def cache_url() -> str:
    """Return the configured cache URL.

    Returns:
        The cache URL, defaulting to an in-memory one.
    """
    health.ping()
    return get_setting("data.cache_url", "memory://")

"""Core primitives for the namespace-package fixture constellation."""

__all__ = ["KenteError"]


class KenteError(Exception):
    """Root error type every fixture package raises."""

"""Settings for the namespace-package fixture constellation."""

from kente.core import KenteError

__all__ = ["get_setting"]


def get_setting(name: str, default=None):
    """Look up a setting value.

    Args:
        name: Dotted setting name.
        default: Value returned when the setting is unset.

    Returns:
        The configured value, or ``default``.

    Raises:
        KenteError: If ``name`` is empty.
    """
    if not name:
        raise KenteError("empty setting name")
    return default

"""`ds.config_hash` (API.md, "config_hash"): SHA-256 over the canonical
config encoding. Does **not** embed the space fingerprint — "the globally
unique observation key is the pair `(space.fingerprint(), ds.config_hash
(config, space))`", so the two are combined by the caller, not here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from designspace.builder._space import Space
from designspace.identity._config_encode import encode_config
from designspace.identity._jcs import canonical_digest

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


def config_hash(config: dict[str, Any], space: Space) -> str:
    """A stable digest identifying one configuration.

    The key to use for an experiment record, a results cache, or
    deduplicating trials: two configurations hash the same exactly when
    they are the same configuration, regardless of dict ordering. Values
    are type-tagged, so `1` and `1.0` are distinct.

    The hash is **exact**. A configuration that has been through a
    representation's `encode`/`decode` may differ in the last bits of a
    float and therefore hash differently, so key your observations on the
    configuration you hold, not on a round-tripped copy.

    The configuration is not validated first.

    Parameters
    ----------
    config : dict[str, Any]
        A configuration, in nested form.
    space : Space
        The space it belongs to, which supplies the structure to walk.

    Returns
    -------
    str
        The digest.

    Examples
    --------
    >>> s = ds.space(
    ...     ds.param("algo").categorical("greedy", "exact"),
    ...     ds.param("depth").integer(1, 4),
    ... )
    >>> a = {"algo": "greedy", "depth": 2}
    >>> b = {"depth": 2, "algo": "greedy"}
    >>> ds.config_hash(a, s) == ds.config_hash(b, s)
    True
    >>> ds.config_hash({"algo": "exact", "depth": 2}, s) == ds.config_hash(a, s)
    False
    """
    return canonical_digest(encode_config(config, space))

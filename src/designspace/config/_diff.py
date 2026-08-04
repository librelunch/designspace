"""`ds.config_diff` (API.md, "Config Utilities"): structural, no
magnitude.

Built entirely on `flatten()` — a variant switch "decomposes into the
discriminator diff... plus newly-inactive/newly-active payload diffs" and a
"repeat length change aligns positionally" fall out for free from how
`flatten` already keys a choice (discriminator string at the choice's own
path, payload leaves nested under `path.variant.*`, only for whichever
variant is active) and a lift (positionally-indexed `path[i].*` leaves): a
plain key-set diff over the two flattened dicts reproduces exactly those
two rules without any choice/lift-specific code here.

Equality is plain Python `==` on flattened leaf values, not the type-tagged
comparison `config_hash`/`fingerprint` use — DECISIONS.md D-35.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from designspace.build._space import Space
from designspace.config._flatten import flatten
from designspace.ir import ParamDiff

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


def config_diff(a: dict[str, Any], b: dict[str, Any], space: Space) -> list[ParamDiff]:
    """What changed between two configurations.

    Compares by path, so a variant switch decomposes properly: the
    discriminator shows the change, and the parameters that only existed
    under the old variant show as having gone away (`new=None`).

    Values are compared with plain `==`, and neither configuration is
    validated — this is a reporting tool, usable on configurations that
    are partial or no longer valid.

    Parameters
    ----------
    a : dict[str, Any]
        The earlier configuration.
    b : dict[str, Any]
        The later configuration.
    space : Space
        The space both belong to.

    Returns
    -------
    list[ParamDiff]
        One entry per differing path, each with `.param`, `.old`, `.new`.

    Examples
    --------
    >>> s = ds.space(
    ...     ds.param("opt").choice("adagrad", sgd=ds.space(ds.param("momentum").real(0, 1))),
    ...     ds.param("lr").real(0, 1),
    ... )
    >>> a = {"opt": {"sgd": {"momentum": 0.5}}, "lr": 0.1}
    >>> b = {"opt": "adagrad", "lr": 0.2}
    >>> [(d.param, d.old, d.new) for d in ds.config_diff(a, b, s)]
    [('opt', 'sgd', 'adagrad'), ('opt.sgd.momentum', 0.5, None), ('lr', 0.1, 0.2)]
    """
    flat_a = flatten(a, space)
    flat_b = flatten(b, space)
    diffs: list[ParamDiff] = []
    seen: set[str] = set()
    for key, va in flat_a.items():
        seen.add(key)
        if key not in flat_b:
            diffs.append(ParamDiff(param=key, old=va, new=None))
        elif va != flat_b[key]:
            diffs.append(ParamDiff(param=key, old=va, new=flat_b[key]))
    for key, vb in flat_b.items():
        if key not in seen:
            diffs.append(ParamDiff(param=key, old=None, new=vb))
    return diffs

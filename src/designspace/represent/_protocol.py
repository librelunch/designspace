"""`Encoding`: the per-param genotype arrow.

See API.md, "Protocols" and "The Representation Layer".

The `Protocol` declares the required surface only. `target` and `decode` are
the two methods every `Encoding` must supply. `encode`, `decode_expr`,
`prop_expr`, `rewrite` and `measure_preserving` are optional capabilities,
duck-typed through `hasattr` at each call site, as `ParamType`'s `sample`,
`cardinality`, `properties` and `extract` are in `custom/_protocol.py`, and
as the external `Prior` protocol's optional `.cdf()` is in `ir/_priors.py`
and `charts/_external.py`. None of the five belongs to this `Protocol`'s
static shape, so an encoding author never has to stub a capability they do
not support.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from designspace.ir import ParamDef

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


class Encoding(Protocol):
    """The genotype for **one** param.

    Required:

    - `target(self, param: ParamDef) -> ParamDef`, the genotype `ParamDef`
      at `param`'s own path. Returning any other path is a resolution
      error.
    - `decode(self, param: ParamDef, value: Any) -> Any`, genotype value
      to phenotype value; must be **total** over `target`'s domain.
      Repair inside `decode` when the phenotype domain
      carries an invariant the genotype cannot express, or choose a
      genotype that cannot represent an invalid value.

    Optional capabilities (checked via `hasattr`, not part of this
    `Protocol`'s static shape):

    - `encode(self, param: ParamDef, value: Any) -> Any`, phenotype to
      genotype; present iff this one param direction is invertible.
    - `decode_expr(self, param: ParamDef) -> Expr | None`, decode as an
      expression, for structural (leaf-substitution) transport; `None`
      opts this param out of structural transport for conditions/
      constraints that reference it (opaque transport, or `rewrite`,
      covers it instead).
    - `prop_expr(self, param: ParamDef, name: str) -> Expr | None`, a
      phenotype property (`.prop(name)`) as a genotype expression; the
      repair that lets a `.prop()`-read param be encoded at all. Absent,
      or returning `None` for a property something still reads,
      `represent()` raises rather than encoding it.
    - `rewrite(self, param: ParamDef, node: Expr) -> Expr | None`, per-node
      structural rewrite where leaf substitution cannot reach (a one-vs-
      rest categorical bridge turning `algo == "adam"` into a pairwise
      comparison between two of its own coordinates); tried before leaf
      substitution at each node touching this param.
    - `measure_preserving(self) -> bool`, declared and never assumed.
      Absence means "not asserted" rather than "false"; silence implies
      neither. `_build.py` treats absence as `False` for the
      `Representation.measure_preserving` conjunction.

    Examples
    --------
    An encoding re-expressing an integer parameter as a real coordinate,
    so a continuous solver can propose values for it. `decode` rounds,
    which is what makes it total: every real in range decodes to a legal
    integer.

    >>> import dataclasses
    >>> class RoundedInteger:
    ...     def target(self, param):
    ...         return dataclasses.replace(
    ...             param,
    ...             type_kind="real",
    ...             domain=ds.RealDomain(float(param.domain.lo), float(param.domain.hi)),
    ...             default=None,
    ...             chart=None,
    ...         )
    ...
    ...     def decode(self, param, value):
    ...         return int(round(value))
    ...
    ...     def encode(self, param, value):
    ...         return float(value)

    A rule decides which parameters it applies to:

    >>> def rule(param):
    ...     return RoundedInteger() if param.type_kind == "integer" else None
    >>> s = ds.space(ds.param("depth").integer(1, 8))
    >>> rep = s.represent(rule)
    >>> rep.target.params["depth"].type_kind
    'real'
    >>> rep.decode({"depth": 4.4})
    {'depth': 4}
    >>> rep.check(n=50, seed=0).ok
    True
    """

    def target(self, param: ParamDef) -> ParamDef:
        """The genotype parameter replacing `param`.

        Must keep `param`'s own path, since a different path is a resolution
        error, but may change everything else: kind, domain, prior.

        Parameters
        ----------
        param : ParamDef
            The phenotype parameter being re-expressed.

        Returns
        -------
        ParamDef
            The genotype parameter, at the same path.
        """
        ...

    def decode(self, param: ParamDef, value: Any) -> Any:
        """Turn a genotype value back into a phenotype value.

        Must be **total** over the target's domain: every value a solver
        can produce has to decode to something valid. Where the phenotype
        carries an invariant the genotype cannot express, either repair it
        here or choose a genotype that cannot represent a violation.
        those are the two honest options, and failing on some inputs is
        not one of them.

        Parameters
        ----------
        param : ParamDef
            The phenotype parameter being decoded to.
        value : Any
            A value from the target parameter's domain.

        Returns
        -------
        Any
            A valid phenotype value.
        """
        ...


EncodingRule = Callable[["ParamDef"], "Encoding | None"]
"""A rule assigning encodings to parameters.

Called with each `ParamDef` in turn; return an `Encoding` to re-express
that parameter, or `None` to decline and let the next rule (ultimately the
induced chart encoding) handle it. Rules are tried in the order given to
`Space.represent()`.
"""


def can_encode(encoding: Any) -> bool:
    """`encode()` present ⇒ this one param direction is invertible."""
    return hasattr(encoding, "encode")


def has_decode_expr(encoding: Any) -> bool:
    return hasattr(encoding, "decode_expr")


def has_prop_expr(encoding: Any) -> bool:
    return hasattr(encoding, "prop_expr")


def has_rewrite(encoding: Any) -> bool:
    return hasattr(encoding, "rewrite")


def is_measure_preserving(encoding: Any) -> bool:
    """Whether this encoding declares itself measure-preserving.

    `False` when the capability is absent. API.md, "Obligations" requires
    the property to be declared and never assumed, so silence reads as not
    asserted, which `Representation.measure_preserving`'s conjunction treats
    identically to an explicit `False`.
    """
    if not hasattr(encoding, "measure_preserving"):
        return False
    return bool(encoding.measure_preserving())

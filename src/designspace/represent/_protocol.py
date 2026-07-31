"""`Encoding`: the per-param genotype arrow (API.md, "Protocols"; "The
Representation Layer"; DECISIONS.md D-52/D-53/D-56/D-63).

**Required surface only.** `target`/`decode` are the two methods every
`Encoding` must supply; `encode`/`decode_expr`/`prop_expr`/`rewrite`/
`measure_preserving` are documented-optional capabilities — duck-typed via
`hasattr` at each call site, exactly like `custom/_protocol.py`'s own
`ParamType` (`sample`/`cardinality`/`properties`+`extract`) and the
external-`Prior` protocol's optional `.cdf()` (`ir/_priors.py`,
`charts/_external.py`). None of the optional five are part of this
`Protocol`'s static shape, so an encoding author is never forced to stub a
capability they don't support.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from designspace.ir import ParamDef


class Encoding(Protocol):
    """The genotype for **one** param (API.md, "The Representation Layer").

    Required:

    - `target(self, param: ParamDef) -> ParamDef` — the genotype `ParamDef`
      at `param`'s own path (row 31: a different path is a resolution
      error).
    - `decode(self, param: ParamDef, value: Any) -> Any` — genotype value
      to phenotype value; must be **total** over `target`'s domain (API.md,
      "Obligations") — repair inside `decode` when the phenotype domain
      carries an invariant the genotype cannot express, or choose a
      genotype that cannot represent an invalid value.

    Optional capabilities (checked via `hasattr`, not part of this
    `Protocol`'s static shape):

    - `encode(self, param: ParamDef, value: Any) -> Any` — phenotype to
      genotype; present iff this one param direction is invertible.
    - `decode_expr(self, param: ParamDef) -> Expr | None` — decode as an
      expression, for structural (leaf-substitution) transport; `None`
      opts this param out of structural transport for conditions/
      constraints that reference it (opaque transport, or `rewrite`,
      covers it instead).
    - `prop_expr(self, param: ParamDef, name: str) -> Expr | None` — a
      phenotype property (`.prop(name)`) as a genotype expression; the
      repair that lets a `.prop()`-read param be encoded at all (row 32;
      DECISIONS.md D-63) — absent, or returning `None` for a live
      property, row 32 still fires.
    - `rewrite(self, param: ParamDef, node: Expr) -> Expr | None` — per-node
      structural rewrite where leaf substitution cannot reach (one-hot's
      `algo == "adam"` becoming an argmax comparison); tried before leaf
      substitution at each node touching this param.
    - `measure_preserving(self) -> bool` — declared, never assumed (D-56):
      absent means "not asserted", not "false" is not implied either way
      by silence — `_build.py` treats absence as `False` for the
      `Representation.measure_preserving` conjunction.
    """

    def target(self, param: ParamDef) -> ParamDef: ...
    def decode(self, param: ParamDef, value: Any) -> Any: ...


EncodingRule = Callable[["ParamDef"], "Encoding | None"]


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
    """`False` when the capability is absent — "declared, never assumed"
    (API.md, "Obligations"; DECISIONS.md D-56) means silence reads as *not
    asserted*, which `Representation.measure_preserving`'s conjunction
    treats identically to an explicit `False`."""
    if not hasattr(encoding, "measure_preserving"):
        return False
    return bool(encoding.measure_preserving())

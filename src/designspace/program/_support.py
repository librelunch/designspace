"""Support types for `.symbolic()`/`.code()` (API.md, "Support Types";
"Parameter Types" > "Program"; DECISIONS.md D-83…D-90).

Core defines and checks the `.symbolic()` AST's *structure* — vocabulary
this param declared, arity where a `Primitive` declares one, variable
names, literal bounds, tree depth — but ships no evaluator, and a bare
string primitive carries no arity or meaning of its own (D-83's second and
third user answers): `Primitive.fn` and a bare string are declared
metadata a consumer's own interpreter uses, never called by core.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from designspace.charts import build_chart
from designspace.ir import Chart, IntegerDomain, RealDomain


@dataclass(frozen=True)
class Signature:
    """`ds.Signature(args, returns)` — a `.symbolic()`/`.code()` param's
    argument names/types and return type. `args`/`returns` accept a Python
    `type` (normalized to `type.__name__`) or a bare string, so the
    fingerprint preimage is canonical and this type carries no
    unserializable object (DECISIONS.md D-86). Argument order is
    meaningful and preserved."""

    args: MappingProxyType[str, str]
    returns: str

    def __init__(self, args: Mapping[str, type | str], returns: type | str) -> None:
        normalized = {name: t.__name__ if isinstance(t, type) else t for name, t in args.items()}
        object.__setattr__(self, "args", MappingProxyType(normalized))
        object.__setattr__(
            self, "returns", returns.__name__ if isinstance(returns, type) else returns
        )


@dataclass(frozen=True)
class FloatLiteral:
    """`ds.FloatLiteral(lo, hi)` — an ephemeral real constant declarable
    inside a `.symbolic()` param's `primitives`; a `{"const": v}` AST node
    is valid only within some declared literal's bounds (DECISIONS.md
    D-83). `.chart` is a consumer-only convenience — core never draws from
    it (no evaluator ships)."""

    lo: float
    hi: float

    @property
    def chart(self) -> Chart:
        chart = build_chart("<literal>", "real", RealDomain(self.lo, self.hi), None, None)
        assert chart is not None
        return chart


@dataclass(frozen=True)
class IntLiteral:
    """`ds.IntLiteral(lo, hi)` — likewise, for an integer constant (the
    floor rule: `.chart` is an `IntegerChart`, matching `.integer()`'s own
    grid semantics)."""

    lo: int
    hi: int

    @property
    def chart(self) -> Chart:
        chart = build_chart("<literal>", "integer", IntegerDomain(self.lo, self.hi), None, None)
        assert chart is not None
        return chart


@dataclass(frozen=True)
class Primitive:
    """`ds.Primitive(name, arity, fn=None)` — a user-declared `.symbolic()`
    operator. `arity` is an int (exact) or a `(lo, hi)` pair (`hi=None`
    unbounded); a bare string primitive carries no arity at all — core
    checks nothing about it beyond vocabulary membership (DECISIONS.md
    D-89/D-90). `fn`, if given, is never called by core (no evaluator
    ships); it rides the same raise/mark/drop opacity as any other
    closed-set callable in the non-serializable set."""

    name: str
    arity: int | tuple[int, int | None]
    fn: Any = None

    @property
    def arity_range(self) -> tuple[int, int | None]:
        if isinstance(self.arity, tuple):
            return self.arity
        return (self.arity, self.arity)

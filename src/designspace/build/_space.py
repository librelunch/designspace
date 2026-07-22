"""Space: the resolved container returned by `ds.space()` (API.md, "Space").

M1 exposes only what flat scalar spaces need; M2 adds feasibility
(`.forbid()`/`.encourage()`), Kleene-aware validation, and the reference
sampler. `.anchor()` and space-level `.meta()` are added at M8 (API.md,
"Constraints and Feasibility"; DECISIONS.md D-40) — they were deferred
past M2 and have no assigned milestone until M8's structural operations
need to interact with them (`freeze`/`slice` re-validate anchors).

`anchors`/`meta_map` default empty and are omitted from the preimage/
`to_json` document when empty (identity/_ir_codec.py's byte-identity
guarantee for additive fields), so every pre-M8 space is unaffected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from designspace.build._paramexpr import ParamExpr
from designspace.expr import ArithExpr, BoolExpr
from designspace.ir import (
    Condition,
    Constraint,
    ConstraintEval,
    ListDomain,
    ParamDef,
    PartialEval,
    RealDomain,
    RemainingDomain,
    SubspaceInfo,
    ValidationResult,
)

if TYPE_CHECKING:
    from designspace.identity._fingerprint import FingerprintScope, FingerprintUnserializable
    from designspace.identity._ir_codec import OnUnserializable

Seed = int | np.random.Generator | None


@dataclass(frozen=True)
class Space:
    params: MappingProxyType[str, ParamDef]
    conditions: tuple[Condition, ...]
    constraints: tuple[Constraint, ...] = field(default_factory=tuple)
    # M8: named reference configs (API.md, ".anchor()") and space-level
    # metadata (".meta()"). `meta_map`, not `meta` — a same-named field and
    # method collide (the `def meta` statement would overwrite the field's
    # class-level default), mirroring ParamExpr's `meta_map`/`.meta()` split.
    anchors: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    meta_map: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def n_params(self) -> int:
        return len(self.params)

    @property
    def is_conditional(self) -> bool:
        return any(p.condition is not None for p in self.params.values())

    @property
    def is_hierarchical(self) -> bool:
        return any(pd.type_kind in ("space", "choice") for pd in self.params.values())

    @property
    def has_variable_length(self) -> bool:
        return any(
            pd.type_kind == "list" and _has_dynamic_count(pd.domain)
            for pd in self.params.values()
            if isinstance(pd.domain, ListDomain)
        )

    @property
    def is_finite(self) -> bool:
        """Cheap, declaration-only check (API.md, "Space — Introspection"):
        `False` iff an unquantized real appears anywhere (top-level or as a
        `.repeat()` element); does not account for a constraint that might
        happen to reduce a continuous domain to finitely many points — that
        is `.cardinality()`'s job, deferred past M8 (no enumeration/CSP
        machinery yet — DECISIONS.md D-43)."""
        return all(_is_finite_domain(pd) for pd in self.params.values())

    @property
    def subspaces(self) -> dict[str, SubspaceInfo]:
        from designspace.ops._introspect import subspaces as _subspaces

        return _subspaces(self)

    @property
    def dependency_graph(self) -> dict[str, frozenset[str]]:
        from designspace.ops._introspect import dependency_graph as _dependency_graph

        return _dependency_graph(self)

    def param_constraints(self, path: str) -> list[Constraint]:
        return [c for c in self.constraints if path in c.params]

    def param_conditions(self, path: str) -> list[Condition]:
        return [c for c in self.conditions if c.target == path or path in c.params]

    def slice(self, values: dict[str, Any] | None = None, **kw: Any) -> Space:
        from designspace.ops._structural import parse_path_values, slice_space

        return slice_space(self, parse_path_values(values, kw, call=".slice()"))

    def freeze(self, values: dict[str, Any] | None = None, **kw: Any) -> Space:
        from designspace.ops._structural import freeze as _freeze
        from designspace.ops._structural import parse_path_values

        return _freeze(self, parse_path_values(values, kw, call=".freeze()"))

    def active_subspace(self, config: dict[str, Any]) -> Space:
        from designspace.ops._structural import active_subspace as _active_subspace

        return _active_subspace(self, config)

    def select(self, *paths: str, strict: bool = False) -> Space:
        from designspace.ops._structural import select as _select

        return _select(self, paths, strict=strict)

    def filter(self, tags: tuple[str, ...] = (), mode: str = "any", strict: bool = False) -> Space:
        from designspace.ops._structural import filter_space

        return filter_space(self, tags, mode=mode, strict=strict)

    def extend(self, *exprs: ParamExpr) -> Space:
        from designspace.ops._structural import extend as _extend

        return _extend(self, exprs)

    def forbid(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        from designspace.resolve._constraints import add_constraints

        return add_constraints(self, conditions, hard=True, tags=tags, meta=meta)

    def require(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        from designspace.resolve._constraints import add_constraints

        return add_constraints(
            self, conditions, hard=True, tags=tags, meta=meta, origin="require"
        )

    def encourage(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        from designspace.resolve._constraints import add_constraints

        return add_constraints(self, conditions, hard=False, tags=tags, meta=meta)

    def discourage(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        from designspace.resolve._constraints import add_constraints

        return add_constraints(
            self, conditions, hard=False, tags=tags, meta=meta, origin="discourage"
        )

    def anchor(self, configs: dict[str, dict[str, Any]]) -> Space:
        from designspace.resolve._anchors import add_anchors

        return add_anchors(self, configs)

    def meta(self, mapping: dict[str, Any] | None = None, **kwargs: Any) -> Space:
        from designspace.resolve._anchors import add_meta

        return add_meta(self, mapping, kwargs)

    def map_params(self, fn: Callable[[ParamDef], ParamDef]) -> Space:
        """Sugar (API.md, "Space — Metaprogramming"): rewrite every
        `ParamDef` through `fn` and re-validate via `space_from_ir` —
        "resolution re-validates whatever comes in" covers whatever `fn`
        produces, however coarse or otherwise transformed."""
        from designspace.meta._meta import space_from_ir

        new_params = [fn(pd) for pd in self.params.values()]
        return space_from_ir(
            new_params, self.conditions, self.constraints, dict(self.anchors), dict(self.meta_map)
        )

    def without_constraints(self, tags: tuple[str, ...] = ()) -> Space:
        """Sugar: drop every constraint (of any kind — forbid/require/
        encourage/discourage/bound) whose own `tags` intersect `tags`, then
        re-validate via `space_from_ir`."""
        from designspace.meta._meta import space_from_ir

        tag_set = frozenset(tags)
        kept = [c for c in self.constraints if not (c.tags & tag_set)]
        return space_from_ir(
            self.params, self.conditions, kept, dict(self.anchors), dict(self.meta_map)
        )

    def validate(self, config: dict[str, Any]) -> ValidationResult:
        from designspace.validate import validate as _validate

        return _validate(self, config)

    def validate_param(
        self, path: str, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        from designspace.validate import validate_param as _validate_param

        return _validate_param(self, path, value, context)

    def is_feasible(self, config: dict[str, Any]) -> bool:
        from designspace.validate import is_feasible as _is_feasible

        return _is_feasible(self, config)

    def infeasibility_reasons(self, config: dict[str, Any]) -> list[str]:
        from designspace.validate import infeasibility_reasons as _infeasibility_reasons

        return _infeasibility_reasons(self, config)

    def evaluate_constraints(self, config: dict[str, Any]) -> list[ConstraintEval]:
        from designspace.validate import evaluate_constraints as _evaluate_constraints

        return _evaluate_constraints(self, config)

    def sample_one(self, seed: Seed = None, reject_soft: bool = False) -> dict[str, Any]:
        from designspace.sample import sample_one as _sample_one

        return _sample_one(self, seed=seed, reject_soft=reject_soft)

    def sample_dicts(
        self, n: int, seed: Seed = None, reject_soft: bool = False
    ) -> list[dict[str, Any]]:
        from designspace.sample import sample_dicts as _sample_dicts

        return _sample_dicts(self, n, seed=seed, reject_soft=reject_soft)

    def apply_defaults(self, config: dict[str, Any]) -> dict[str, Any]:
        from designspace.defaults import apply_defaults as _apply_defaults

        return _apply_defaults(self, config)

    @property
    def has_complete_defaults(self) -> bool:
        from designspace.defaults import apply_defaults as _apply_defaults
        from designspace.partial import is_complete as _is_complete

        return _is_complete(self, _apply_defaults(self, {}))

    def evaluate_partial(self, config: dict[str, Any]) -> PartialEval:
        from designspace.partial import evaluate_partial as _evaluate_partial

        return _evaluate_partial(self, config)

    def remaining_domain(self, path: str, config: dict[str, Any]) -> RemainingDomain | None:
        from designspace.partial import remaining_domain as _remaining_domain

        return _remaining_domain(self, path, config)

    def param_activity(self, config: dict[str, Any]) -> dict[str, str]:
        from designspace.partial import param_activity as _param_activity

        return _param_activity(self, config)

    def is_complete(self, config: dict[str, Any]) -> bool:
        from designspace.partial import is_complete as _is_complete

        return _is_complete(self, config)

    def missing_params(self, config: dict[str, Any]) -> list[str]:
        from designspace.partial import missing_params as _missing_params

        return _missing_params(self, config)

    @property
    def topological_order(self) -> list[str]:
        from designspace.partial import topological_order as _topological_order

        return _topological_order(self)

    def next_assignable(self, config: dict[str, Any]) -> list[str]:
        from designspace.partial import next_assignable as _next_assignable

        return _next_assignable(self, config)

    def to_json(self, on_unserializable: OnUnserializable = "raise") -> dict[str, Any]:
        from designspace.serialize import to_json as _to_json

        return _to_json(self, on_unserializable=on_unserializable)

    @classmethod
    def from_json(
        cls, data: dict[str, Any], custom_types: dict[str, Any] | None = None
    ) -> Space:
        from designspace.serialize import from_json as _from_json

        return _from_json(data, custom_types=custom_types)

    def fingerprint(
        self,
        scope: FingerprintScope = "full",
        on_unserializable: FingerprintUnserializable = "raise",
    ) -> str:
        from designspace.identity import fingerprint as _fingerprint

        return _fingerprint(self, scope=scope, on_unserializable=on_unserializable)


def _has_dynamic_count(domain: ListDomain) -> bool:
    if isinstance(domain.count, ArithExpr):
        return True
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _has_dynamic_count(domain.element_domain)
    return False


def _is_finite_domain(pd: ParamDef) -> bool:
    if isinstance(pd.domain, RealDomain):
        return pd.quantized is not None
    if isinstance(pd.domain, ListDomain):
        return _is_finite_list_domain(pd.domain)
    return True


def _is_finite_list_domain(domain: ListDomain) -> bool:
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _is_finite_list_domain(domain.element_domain)
    if domain.element_kind == "real":
        assert isinstance(domain.element_domain, RealDomain)
        return domain.element_quantized is not None
    return True

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

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from designspace.build._paramexpr import ParamExpr
from designspace.custom import has_cardinality, is_generative
from designspace.expr import ArithExpr, BoolExpr
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    Condition,
    Constraint,
    ConstraintEval,
    CustomDomain,
    IntegerDomain,
    ListDomain,
    OrdinalDomain,
    ParamDef,
    PartialEval,
    PermutationDomain,
    QuantizedSpec,
    RealDomain,
    RemainingDomain,
    SamplingReport,
    StructDomain,
    SubsetDomain,
    SubspaceInfo,
    ValidationResult,
)

if TYPE_CHECKING:
    import polars as pl

    from designspace.identity._fingerprint import FingerprintScope, FingerprintUnserializable
    from designspace.identity._ir_codec import OnUnserializable
    from designspace.represent._protocol import EncodingRule
    from designspace.represent._representation import Representation

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
    # M10.7: a lazily-built, cached index backing `_direct_children` below —
    # a pure function of `params`, so excluded from `__eq__`/`__repr__`
    # (`compare=False, repr=False`) rather than treated as part of a space's
    # identity. Lazy rather than built at every one of the ~12 construction
    # sites (`_emit`, `from_json`, `space_from_ir`, `extend`, `freeze`, the
    # two throwaway `skeleton = Space(...)` spaces in `ops/_structural.py`,
    # and every `dataclasses.replace(space, ...)` call) — those would all
    # need to remember to (re)build it; laziness needs none of them to.
    _child_index: dict[str, tuple[str, ...]] | None = field(
        default=None, init=False, compare=False, repr=False
    )

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
    def has_nongenerative_params(self) -> bool:
        """API.md, "Space — Introspection" — replaces `has_code_params`.
        `True` iff any param is **non-generative**: through M9, that means a
        full-protocol custom whose `ParamType` declares no `sample()`
        (`.code()`/`.symbolic()` without `sampler=` join this at M12).
        Every other kind, and a shorthand custom (always generative by
        construction), is generative (DECISIONS.md D-46)."""
        for pd in self.params.values():
            if pd.type_kind == "custom":
                domain = pd.domain
                assert isinstance(domain, CustomDomain)
                if domain.param_type is not None and not is_generative(domain.param_type):
                    return True
        return False

    def cardinality(self) -> int | None:
        """API.md, "Space — Introspection": finite-config count over the
        structural product, or `None` if infinite/continuous/unquantized-real
        or not enumerable. Recurses through each root param's own domain
        shape (real/integer/quantized grid, categorical/ordinal/bool,
        subset/permutation, choice/struct nesting, static-count list,
        custom), never a flat scan of `.params` — a choice/struct's own
        relocation-injected condition is therefore handled implicitly by
        the variant-sum / field-product formula, needing no CSP/enumeration
        machinery for the common (structural) case.

        A param carrying its own **independent** condition — one that
        references anything beyond what its struct/choice nesting alone
        would inject — makes the whole result `None` (DECISIONS.md D-48):
        general conditional enumeration ("sum over finite-discrete
        condition-driving params... when tractable") is out of scope here;
        this is sound (never over-counts), just conservative.
        """
        from designspace.resolve._pipeline import check_fully_resolved

        check_fully_resolved(self)
        roots = [p for p in self.params if "." not in p and "[" not in p]
        total = 1
        for path in roots:
            pd = self.params[path]
            if pd.condition is not None:
                return None  # a root param's own .when() -- not structural injection
            n = _param_cardinality(path, pd, self)
            if n is None:
                return None
            total *= n
        return total

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

    def _direct_children(self, prefix: str) -> tuple[str, ...]:
        """Template paths one segment below `prefix` (M10.7 — the traversal
        primitive every space-guided walker shares): `""` for the root,
        `"algo.svm."` inside a chosen variant, `"edges[]."` inside a lift's
        element template. `prefix` must be `""` or end in `"."` — the only
        two forms any caller constructs; a bare non-empty, non-dot-terminated
        prefix (e.g. `"algo"`) is not a valid query and returns `()`.

        Backed by a lazily-built, cached index (`_child_index`) rather than a
        per-call scan of `space.params` — the scan is quadratic in param
        count (a struct with many fields pays it for every field), the index
        is one pass, and `Space` is frozen, so caching is safe."""
        index = self._child_index
        if index is None:
            index = _build_child_index(self.params)
            object.__setattr__(self, "_child_index", index)
        return index.get(prefix, ())

    def coordinate_paths(self) -> tuple[str, ...]:
        from designspace.config._coordinates import coordinate_paths as _coordinate_paths

        return _coordinate_paths(self)

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

    def sample(self, n: int, seed: Seed = None, reject_soft: bool = False) -> pl.DataFrame:
        from designspace.frame import sample_frame as _sample_frame

        return _sample_frame(self, n, seed=seed, reject_soft=reject_soft)

    def sampling_report(
        self, n: int = 1000, seed: Seed = None, tighten_bounds: bool = False
    ) -> SamplingReport:
        from designspace.sample import sampling_report as _sampling_report

        return _sampling_report(self, n, seed=seed, tighten_bounds=tighten_bounds)

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

    def represent(self, *rules: EncodingRule) -> Representation:
        from designspace.represent._build import represent as _represent

        return _represent(self, *rules)

    def fingerprint(
        self,
        scope: FingerprintScope = "full",
        on_unserializable: FingerprintUnserializable = "raise",
    ) -> str:
        from designspace.identity import fingerprint as _fingerprint

        return _fingerprint(self, scope=scope, on_unserializable=on_unserializable)


def _build_child_index(params: Mapping[str, ParamDef]) -> dict[str, tuple[str, ...]]:
    """One pass over `space.params`, bucketing each path by its parent
    prefix (`path[: path.rfind(".") + 1]`, `""` when dotless) — exactly the
    set the old per-call predicate (`startswith(prefix)` and a dot-free
    remainder) selected, for the `""`/dot-terminated prefixes every caller
    builds. Dict order preserves `params`' declaration order (already
    `flatten`'s order, already the DataFrame column order)."""
    buckets: dict[str, list[str]] = {}
    for path in params:
        prefix = path[: path.rfind(".") + 1]
        buckets.setdefault(prefix, []).append(path)
    return {prefix: tuple(paths) for prefix, paths in buckets.items()}


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


# -- .cardinality() (M9) ------------------------------------------------------


def _condition_matches_injection(actual: BoolExpr | None, expected: BoolExpr | None) -> bool:
    """Whether `actual` (a struct-field/choice-variant descendant's stored,
    folded `.condition`) is *exactly* what structural relocation alone
    would inject — i.e. the field/variant carries no independent `.when()`
    of its own. Structural (not identity) comparison via the canonical AST
    encoder, since `relocate_child`'s choice-variant path builds a fresh
    `and_(...)` composite rather than reusing an existing object.

    A condition referencing a `ds.value(...)` (M10.8) makes `encode_expr`
    raise (opaque, uncalled-with-no-context here) rather than return a
    comparable tree — this is a *structural-equality* check, not
    serialization, so that is degraded to identity comparison instead of
    propagating the error: an opaque condition can never structurally equal
    a freshly-built injection object anyway, so `.cardinality()`'s callers
    (`_struct_cardinality`/`_choice_cardinality`) correctly see "not
    enumerable" (`None`) for it."""
    from designspace.errors import SerializationError
    from designspace.identity._tags import encode_expr

    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False
    try:
        return encode_expr(actual) == encode_expr(expected)
    except SerializationError:
        return actual is expected


def _grid_cardinality(lo: float, hi: float, quantized: QuantizedSpec) -> int:
    from designspace.charts._grid import build_grid_shape

    shape = build_grid_shape(lo, hi, quantized.step, quantized.factor, quantized.include_hi)
    return shape.K + 1 + (1 if shape.has_extra_hi else 0)


def _struct_cardinality(path: str, pd: ParamDef, space: Space) -> int | None:
    total = 1
    for child_path in space._direct_children(f"{path}."):
        child_pd = space.params[child_path]
        if not _condition_matches_injection(child_pd.condition, pd.condition):
            return None  # an independent .when() on a struct field
        n = _param_cardinality(child_path, child_pd, space)
        if n is None:
            return None
        total *= n
    return total


def _choice_cardinality(path: str, domain: ChoiceDomain, pd: ParamDef, space: Space) -> int | None:
    from designspace.expr import Compare, Literal
    from designspace.resolve._relocate import and_

    total = 0
    for variant in domain.variants:
        if variant not in domain.has_payload:
            total += 1
            continue
        prefix = f"{path}.{variant}."
        discriminator_eq = Compare("eq", ParamExpr(path=path), Literal(variant))
        expected = and_(pd.condition, discriminator_eq)
        variant_total = 1
        for child_path in space._direct_children(prefix):
            child_pd = space.params[child_path]
            if not _condition_matches_injection(child_pd.condition, expected):
                return None  # an independent .when() on a variant's own field
            n = _param_cardinality(child_path, child_pd, space)
            if n is None:
                return None
            variant_total *= n
        total += variant_total
    return total


def _list_cardinality(path: str, domain: ListDomain, space: Space) -> int | None:
    if isinstance(domain.count, ArithExpr):
        return None  # dynamic (runtime-dependent) count -- not enumerable here
    n = domain.count
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        elem = _list_cardinality(f"{path}[]", domain.element_domain, space)
    elif domain.element_kind in ("space", "choice"):
        elem_pd = ParamDef(
            path=f"{path}[]", type_kind=domain.element_kind, domain=domain.element_domain,
            prior=None, periodic=False, default=None, condition=None, tags=frozenset(),
            meta=MappingProxyType({}),
        )
        elem = _param_cardinality(f"{path}[]", elem_pd, space)
    else:
        elem_pd = ParamDef(
            path=f"{path}[]", type_kind=domain.element_kind, domain=domain.element_domain,
            prior=None, periodic=domain.element_periodic, default=None, condition=None,
            tags=frozenset(), meta=MappingProxyType({}), quantized=domain.element_quantized,
        )
        elem = _param_cardinality(f"{path}[]", elem_pd, space)
    if elem is None:
        return None
    return int(elem**n)


def _param_cardinality(path: str, pd: ParamDef, space: Space) -> int | None:
    domain = pd.domain
    if isinstance(domain, RealDomain):
        if pd.quantized is None:
            return None
        assert isinstance(domain.lo, int | float) and isinstance(domain.hi, int | float)
        return _grid_cardinality(float(domain.lo), float(domain.hi), pd.quantized)
    if isinstance(domain, IntegerDomain):
        assert isinstance(domain.lo, int) and isinstance(domain.hi, int)
        if pd.quantized is not None:
            return _grid_cardinality(float(domain.lo), float(domain.hi), pd.quantized)
        return domain.hi - domain.lo + 1
    if isinstance(domain, CategoricalDomain | OrdinalDomain):
        return len(domain.values)
    if isinstance(domain, BoolDomain):
        return 2
    if isinstance(domain, SubsetDomain):
        n_items = len(domain.items)
        max_size = domain.max_size if domain.max_size is not None else n_items
        return sum(math.comb(n_items, k) for k in range(domain.min_size, max_size + 1))
    if isinstance(domain, PermutationDomain):
        return math.factorial(len(domain.items))
    if isinstance(domain, ChoiceDomain):
        return _choice_cardinality(path, domain, pd, space)
    if isinstance(domain, StructDomain):
        return _struct_cardinality(path, pd, space)
    if isinstance(domain, CustomDomain):
        if domain.param_type is not None and has_cardinality(domain.param_type):
            return cast("int | None", domain.param_type.cardinality())
        return None
    if isinstance(domain, ListDomain):
        return _list_cardinality(path, domain, space)
    return None  # pragma: no cover - unreachable: every Domain variant handled above

"""ConfigSpace binding.

`translate(space)` converts a space into a `ConfigurationSpace`, returned as
a `Translation` paired with an exact `decode` and `encode`. `KINDS` holds the
parameter kinds it places, `list` among them with a static count; the program
and custom kinds have no ConfigSpace counterpart.

A `.when()` condition and a hard constraint translate where ConfigSpace has a
form for them, and are handled differently where it does not. A condition
that does not translate is refused by path, every such path at once, rather
than placed unconditionally. A constraint that does not is reported on
`Translation.untranslated_constraints` rather than raised: a reported
constraint is a relaxation the search does not see and `space.is_feasible`
still catches, never a restriction that hides a feasible configuration from
the search. A soft constraint is neither translated nor reported.

Notes
-----
A real or integer parameter is placed as ConfigSpace's own `Float` or
`Integer` when unquantized and either unshaped or log-scaled, and in unit
coordinates decoded through its chart otherwise. Every other generative kind
is placed as an index into its declared values rather than as the value
itself, so a decoded value is never one of the NumPy scalar types
`ConfigurationSpace` returns. A permutation is placed as one continuous
coordinate per item and read back by sorting.

A `.repeat()` lift with a static count unrolls into one placement per index,
`xs[0]` through `xs[n-1]`, each by the rule for its own element kind. A
struct or choice element additionally places every field underneath it,
`workers[0].timeout_s`, with a choice's discriminator-equality condition
rewritten to that instance; a nested lift recurses one bracket level deeper.

A subset's declared size is spelled out as the combinations it excludes,
ConfigSpace stating a forbidden combination one at a time and having no
clause over a sum. Bounding a size therefore costs one clause per excluded
combination, and a bound costing more than `MAX_SUBSET_CLAUSES` is refused by
path rather than translated with the size dropped.

Examples
--------
A conditional space, its activity exact under translation:

>>> import designspace as ds
>>> from designspace_solvers.configspace import translate
>>> space = ds.space(
...     ds.param("optimizer").categorical("sgd", "adam"),
...     ds.param("nesterov").bool().when(ds.param("optimizer") == "sgd"),
... )
>>> translation = translate(space)
>>> translation.config_space.seed(0)
>>> configuration = translation.config_space.sample_configuration()
>>> config = translation.decode(configuration)
>>> space.is_complete(config)
True
>>> ("nesterov" in config) == (config["optimizer"] == "sgd")
True

A constraint multiplying two parameters has no forbidden-clause form, so it
is reported rather than raised:

>>> budget = ds.space(
...     ds.param("workers").integer(1, 16), ds.param("memory_gb").integer(1, 64)
... ).forbid(ds.param("workers") * ds.param("memory_gb") > 64)
>>> translate(budget).untranslated_constraints[0].kind
'forbid'

A static-count lift unrolls into one hyperparameter per index:

>>> lifted = ds.space(ds.param("xs").real(0.0, 1.0).repeat(3))
>>> sorted(translate(lifted).config_space.keys())
['xs[0]', 'xs[1]', 'xs[2]']

A refusal names the parameter and the reason, matching the other bindings:

>>> from designspace_solvers import UnsupportedSpace
>>> dynamic = ds.space(
...     ds.param("n").integer(1, 5),
...     ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
... )
>>> try:
...     translate(dynamic)
... except UnsupportedSpace as exc:
...     print(exc)
the ConfigSpace binding cannot search this space: xs (list): length is an
expression, and this backend needs a fixed width
"""

from __future__ import annotations

import dataclasses
import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import designspace as ds
from designspace.expr import BoolOp, Compare, Implies, IsIn, Literal, Not
from designspace_solvers._placement import (
    GENERATIVE_KINDS,
    decode_random_keys,
    encode_random_keys,
    item_paths,
    native_scalar,
    require_backend,
    subset_bounds,
)
from designspace_solvers._profile import Rejection, UnsupportedSpace, require

if TYPE_CHECKING:
    from ConfigSpace import Configuration, ConfigurationSpace

__all__ = ["KINDS", "MAX_SUBSET_CLAUSES", "Translation", "translate"]

#: The parameter kinds this binding places: every generative kind. `list`
#: is placed with a static count over any element kind, `_place_list`
#: unrolling one placement per index; a dynamic count is caught by
#: `variable_length=False` below. The program and custom kinds are absent
#: outright, having no ConfigSpace counterpart at all.
KINDS = GENERATIVE_KINDS

#: How many forbidden clauses a subset's size bound may cost before the
#: parameter is refused instead. ConfigSpace states a forbidden combination
#: one at a time, so bounding a size costs one clause per excluded
#: combination, which grows combinatorially in the number of items. A space
#: past this is refused by path rather than translated with the bound
#: silently dropped.
MAX_SUBSET_CLAUSES = 512

_NEGATE_OP = {"eq": "ne", "ne": "eq", "gt": "le", "lt": "ge", "ge": "lt", "le": "gt"}


def _require_configspace() -> Any:
    return require_backend(
        "ConfigSpace", binding="ConfigSpace", needs="ConfigSpace", extra="configspace"
    )


class _Unsupported(Exception):
    """A subtree has no ConfigSpace counterpart. Caught by the caller, which
    knows whether that means a refusal (a condition) or an omission (a
    constraint)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _Slot:
    """Where and how one designspace parameter sits in the ConfigurationSpace."""

    path: str
    kind: ds.TypeKind
    hp_names: tuple[str, ...]
    values: tuple[Any, ...]  # index-coded native values; () for real/integer
    chart: ds.Chart | None  # set only for a unit-coded real/integer
    unit_coded: bool
    size_bounds: tuple[int, int] | None = None  # set only for a subset


def _is_native_scalar(slot: _Slot) -> bool:
    """Whether `slot` is eligible to sit on one side of a condition or a
    forbidden clause: exactly one hyperparameter, comparable directly."""
    return len(slot.hp_names) == 1


def _to_wire(slot: _Slot, value: Any) -> Any:
    if slot.unit_coded:
        assert slot.chart is not None
        return slot.chart.to_unit(value)
    if slot.values:
        for index, candidate in enumerate(slot.values):
            if type(candidate) is type(value) and candidate == value:
                return index
        raise _Unsupported(f"{value!r} is not one of {slot.path}'s declared values")
    return value


def _from_wire(slot: _Slot, wire: Any) -> Any:
    if slot.unit_coded:
        assert slot.chart is not None
        return slot.chart.from_unit(float(wire))
    if slot.values:
        return slot.values[int(wire)]
    return wire


# -- Placement ----------------------------------------------------------


def _place_one(
    path: str, defn: ds.ParamDef, cs: Any, effective_default: Any
) -> tuple[_Slot, list[Any]]:
    kind = defn.type_kind
    domain = defn.domain

    if kind in ("real", "integer"):
        chart = defn.chart
        assert chart is not None
        native = native_scalar(defn)
        log = isinstance(defn.prior, ds.Log)
        ctor = cs.Float if kind == "real" else cs.Integer
        if native:
            lo, hi = chart.from_unit(0.0), chart.from_unit(1.0)
            kwargs: dict[str, Any] = {"log": log}
            if effective_default is not None:
                kwargs["default"] = effective_default
            hp = ctor(path, (lo, hi), **kwargs)
            slot = _Slot(path, kind, (path,), (), None, False)
        else:
            kwargs = {}
            if effective_default is not None:
                kwargs["default"] = chart.to_unit(effective_default)
            hp = cs.Float(path, (0.0, 1.0), **kwargs)
            slot = _Slot(path, kind, (path,), (), chart, True)
        return slot, [hp]

    if kind == "bool":
        values: tuple[Any, ...] = (False, True)
        weights = _weights_for(defn)
        kwargs = {"weights": weights} if weights is not None else {}
        if effective_default is not None:
            kwargs["default"] = values.index(effective_default)
        hp = cs.Categorical(path, list(range(len(values))), **kwargs)
        return _Slot(path, kind, (path,), values, None, False), [hp]

    if kind == "categorical":
        assert isinstance(domain, ds.CategoricalDomain)
        values = domain.values
        weights = _weights_for(defn)
        kwargs = {"weights": weights} if weights is not None else {}
        if effective_default is not None:
            kwargs["default"] = _index_of(values, effective_default)
        hp = cs.Categorical(path, list(range(len(values))), **kwargs)
        return _Slot(path, kind, (path,), values, None, False), [hp]

    if kind == "ordinal":
        assert isinstance(domain, ds.OrdinalDomain)
        values = domain.values
        kwargs = {}
        if effective_default is not None:
            kwargs["default_value"] = _index_of(values, effective_default)
        hp = cs.OrdinalHyperparameter(path, list(range(len(values))), **kwargs)
        return _Slot(path, kind, (path,), values, None, False), [hp]

    if kind == "choice":
        assert isinstance(domain, ds.ChoiceDomain)
        values = domain.variants
        kwargs = {}
        if effective_default is not None:
            kwargs["default"] = _index_of(values, effective_default)
        hp = cs.Categorical(path, list(range(len(values))), **kwargs)
        return _Slot(path, kind, (path,), values, None, False), [hp]

    if kind == "subset":
        assert isinstance(domain, ds.SubsetDomain)
        items = domain.items
        item_weights = None
        if isinstance(defn.prior, ds.Weights):
            item_weights = defn.prior.values
        hp_names = item_paths(path, len(items))
        low, high = subset_bounds(domain)
        # Every flag defaults to excluded, which is a size of zero and outside
        # a `min_size` above it. ConfigSpace refuses a default configuration
        # its own clauses forbid, so the declared default decides the flags
        # where there is one, and the first `min_size` items where there is
        # not.
        included: set[int]
        if effective_default is not None:
            included = {_index_of(items, value) for value in effective_default}
        else:
            included = set(range(low))
        hps = []
        for i, name in enumerate(hp_names):
            kwargs = {"default": 1 if i in included else 0}
            if item_weights is not None:
                p = float(item_weights[i])
                kwargs["weights"] = [1.0 - p, p]
            hps.append(cs.Categorical(name, [0, 1], **kwargs))
        return _Slot(path, kind, hp_names, items, None, False, (low, high)), hps

    if kind == "permutation":
        assert isinstance(domain, ds.PermutationDomain)
        items = domain.items
        hp_names = item_paths(path, len(items))
        hps = [cs.Float(name, (0.0, 1.0)) for name in hp_names]
        return _Slot(path, kind, hp_names, items, None, False), hps

    if kind == "space":
        return _Slot(path, kind, (), (), None, False), []

    raise UnsupportedSpace(
        "the ConfigSpace binding",
        [Rejection(path=path, kind=kind, reason="no placement is defined for this kind")],
    )


def _rewrite_instance_path[ExprT: ds.Expr](expr: ExprT, lift_path: str, index: int) -> ExprT:
    """Rewrite every reference to `lift_path[]` in `expr` into `lift_path[index]`.

    A struct or choice element's own condition, and a constraint declared
    inside its space, are written against the template marker: the bare
    `choices[]` a discriminator equality compares, or a sibling field such
    as `workers[].timeout_s`. Both are `ParamExpr` leaves whose `.path`
    starts with that marker; substituting the index there and leaving the
    rest of the tree to recurse is the whole rewrite. A node kind neither
    `_build_condition` nor `_build_forbidden` walks, an aggregate over a
    struct field for instance, is returned as is: an unrewritten reference
    inside it is harmless, since that node is refused before either walker
    ever reads the reference.
    """
    marker = f"{lift_path}[]"
    if isinstance(expr, ds.ParamExpr):
        if expr.path == marker or expr.path.startswith(marker + "."):
            new_path = f"{lift_path}[{index}]" + expr.path[len(marker) :]
            return dataclasses.replace(expr, path=new_path)
        return expr
    if isinstance(expr, Not):
        return dataclasses.replace(
            expr, operand=_rewrite_instance_path(expr.operand, lift_path, index)
        )
    if isinstance(expr, Compare):
        return dataclasses.replace(
            expr,
            left=_rewrite_instance_path(expr.left, lift_path, index),
            right=_rewrite_instance_path(expr.right, lift_path, index),
        )
    if isinstance(expr, BoolOp):
        return dataclasses.replace(
            expr,
            left=_rewrite_instance_path(expr.left, lift_path, index),
            right=_rewrite_instance_path(expr.right, lift_path, index),
        )
    if isinstance(expr, Implies):
        return dataclasses.replace(
            expr,
            left=_rewrite_instance_path(expr.left, lift_path, index),
            right=_rewrite_instance_path(expr.right, lift_path, index),
        )
    if isinstance(expr, IsIn):
        return dataclasses.replace(
            expr, operand=_rewrite_instance_path(expr.operand, lift_path, index)
        )
    return expr


#: What `_place_list`, `_place_struct_descendants`, and their shared
#: constraint handling all build: the per-instance slots and hyperparameters
#: placed, a struct or choice descendant's own condition keyed by its
#: instance path (never a `space.topological_order` entry itself, so
#: `_apply_conditions` cannot find it there), and every per-instance
#: constraint a struct element's own space declared.
_Placed = tuple[
    dict[str, _Slot],
    list[Any],
    list[str],
    dict[str, ds.BoolExpr],
    list[ds.Constraint],
]


def _place_struct_descendants(
    lift_path: str,
    index: int,
    templates: list[tuple[str, ds.ParamDef]],
    cs: Any,
    default_overrides: dict[str, Any],
    space: ds.Space,
) -> _Placed:
    """Place every descendant field a struct or choice element relocated.

    Core flattens a struct or choice lift's descendants into `space.params`
    under a template path, `workers[].timeout_s`, whatever the descendant's
    own kind and however deep its own nesting: a further struct or choice
    field is already its own flat entry the same way, and a nested
    `.repeat()` is one `ListDomain` entry, recursable through `_place_list`
    exactly as a top-level one is. Resolution refuses a struct or choice
    element nested under a second `.repeat()` level before this ever runs,
    so a nested list found here is guaranteed a scalar element, and its own
    `element_constraints` is always empty.
    """
    element_slots: dict[str, _Slot] = {}
    hyperparameters: list[Any] = []
    hp_names: list[str] = []
    conditions: dict[str, ds.BoolExpr] = {}
    constraints: list[ds.Constraint] = []

    marker_len = len(lift_path) + 2  # "{lift_path}[]"
    for template_path, template_defn in templates:
        instance_path = f"{lift_path}[{index}]" + template_path[marker_len:]
        instance_condition = (
            None
            if template_defn.condition is None
            else _rewrite_instance_path(template_defn.condition, lift_path, index)
        )
        if instance_condition is not None:
            conditions[instance_path] = instance_condition

        if template_defn.type_kind == "list":
            assert isinstance(template_defn.domain, ds.ListDomain)
            sub_slots, sub_hps, sub_hp_names, sub_conditions, sub_constraints = _place_list(
                instance_path, template_defn.domain, cs, default_overrides, space
            )
            element_slots.update(sub_slots)
            hyperparameters.extend(sub_hps)
            hp_names.extend(sub_hp_names)
            conditions.update(sub_conditions)
            constraints.extend(sub_constraints)
            continue

        effective_default = default_overrides.get(instance_path, template_defn.default)
        instance_defn = dataclasses.replace(
            template_defn, path=instance_path, condition=instance_condition
        )
        slot, hps = _place_one(instance_path, instance_defn, cs, effective_default)
        element_slots[instance_path] = slot
        hyperparameters.extend(hps)
        hp_names.extend(slot.hp_names)

    return element_slots, hyperparameters, hp_names, conditions, constraints


def _place_list(
    path: str, domain: ds.ListDomain, cs: Any, default_overrides: dict[str, Any], space: ds.Space
) -> _Placed:
    """Unroll a static-count lift into one placement per index.

    `require`'s `variable_length=False` already refused a dynamic count
    before this runs, so `domain.count` is a literal integer here. A
    scalar, subset, permutation, or choice element is placed by
    `_place_one` under a synthetic `ParamDef` built from the lift's own
    element facts, exactly reusing the rule for that element's kind; a
    struct or choice element additionally places every field
    `_place_struct_descendants` finds relocated under it, and a nested
    lift recurses here again over `domain.element_domain`.

    Returns
    -------
    _Placed
        Every slot placed, keyed by instance path, the container's own
        `hp_names` the concatenation of every index's; every
        hyperparameter built; every condition a struct or choice
        descendant carries, rewritten to its instance and keyed by that
        instance path; and every per-instance constraint a struct
        element's own space declared.
    """
    assert isinstance(domain.count, int)

    element_slots: dict[str, _Slot] = {}
    hyperparameters: list[Any] = []
    hp_names: list[str] = []
    conditions: dict[str, ds.BoolExpr] = {}
    constraints: list[ds.Constraint] = []

    templates = (
        [(p, d) for p, d in space.params.items() if p.startswith(f"{path}[].")]
        if domain.element_kind in ("space", "choice")
        else []
    )

    for i in range(domain.count):
        elem_path = f"{path}[{i}]"

        if domain.element_kind == "list":
            assert isinstance(domain.element_domain, ds.ListDomain)
            sub_slots, sub_hps, sub_hp_names, sub_conditions, sub_constraints = _place_list(
                elem_path, domain.element_domain, cs, default_overrides, space
            )
            element_slots.update(sub_slots)
            hyperparameters.extend(sub_hps)
            hp_names.extend(sub_hp_names)
            conditions.update(sub_conditions)
            constraints.extend(sub_constraints)
            continue

        declared_default = (
            domain.list_default[i] if domain.list_default is not None else domain.element_default
        )
        effective_default = default_overrides.get(elem_path, declared_default)
        elem_defn = ds.ParamDef(
            path=elem_path,
            type_kind=domain.element_kind,
            domain=domain.element_domain,
            prior=domain.element_prior,
            periodic=domain.element_periodic,
            default=None,
            condition=None,
            tags=frozenset(),
            meta=MappingProxyType({}),
            chart=domain.element_chart,
            quantized=domain.element_quantized,
        )
        slot, hps = _place_one(elem_path, elem_defn, cs, effective_default)
        element_slots[elem_path] = slot
        hyperparameters.extend(hps)
        hp_names.extend(slot.hp_names)

        if domain.element_kind in ("space", "choice"):
            desc_slots, desc_hps, desc_hp_names, desc_conditions, desc_constraints = (
                _place_struct_descendants(path, i, templates, cs, default_overrides, space)
            )
            element_slots.update(desc_slots)
            hyperparameters.extend(desc_hps)
            hp_names.extend(desc_hp_names)
            conditions.update(desc_conditions)
            constraints.extend(desc_constraints)
            for constraint in domain.element_constraints:
                constraints.append(
                    dataclasses.replace(
                        constraint, expr=_rewrite_instance_path(constraint.expr, path, i)
                    )
                )

    container = _Slot(path, "list", tuple(hp_names), (), None, False)
    element_slots[path] = container
    return element_slots, hyperparameters, hp_names, conditions, constraints


def _index_of(values: tuple[Any, ...], value: Any) -> int:
    for index, candidate in enumerate(values):
        if type(candidate) is type(value) and candidate == value:
            return index
    raise ValueError(f"{value!r} is not one of {values!r}")


def _weights_for(defn: ds.ParamDef) -> list[float] | None:
    if not isinstance(defn.prior, ds.Weights):
        return None
    weights = [float(w) for w in defn.prior.values]
    total = sum(weights)
    return [w / total for w in weights]


# -- Conditions -----------------------------------------------------------


def _leaf_path(expr: ds.Expr) -> str | None:
    return expr.path if isinstance(expr, ds.ParamExpr) else None


def _leaf_literal(expr: ds.Expr) -> Any:
    if isinstance(expr, Literal) or expr.kind == "literal":
        return expr.value  # type: ignore[attr-defined]
    raise _Unsupported("operand is not a literal")


def _require_native(path: str, slots: dict[str, _Slot]) -> _Slot:
    slot = slots.get(path)
    if slot is None or not _is_native_scalar(slot):
        raise _Unsupported(f"{path} is not placed as a single comparable hyperparameter")
    return slot


def _require_value_coded(path: str, slot: _Slot) -> None:
    """Refuse comparing a unit-coded slot against a literal.

    A quantized scalar, or one carrying a shaped prior, sits in `[0, 1]` and
    reaches its declared value through its chart. A literal therefore
    converts to the edge of the cell that decodes to it rather than to a
    point inside that cell, so a strict comparison drops the whole cell and
    an equality never fires. Both are silent, and neither is the kind of
    miss `is_feasible` reports downstream.
    """
    if slot.unit_coded:
        raise _Unsupported(
            f"{path} sits in unit coordinates, where a literal marks a cell edge "
            "rather than the value itself"
        )


def _build_condition(
    expr: ds.BoolExpr,
    child: Any,
    hp_by_path: dict[str, Any],
    slots: dict[str, _Slot],
    cs: Any,
    negate: bool,
) -> Any:
    if isinstance(expr, Not):
        return _build_condition(expr.operand, child, hp_by_path, slots, cs, not negate)

    if isinstance(expr, BoolOp):
        left = _build_condition(expr.left, child, hp_by_path, slots, cs, negate)
        right = _build_condition(expr.right, child, hp_by_path, slots, cs, negate)
        conj = cs.OrConjunction if (expr.op == "and") == negate else cs.AndConjunction
        return conj(left, right)

    if isinstance(expr, Implies):
        if not negate:
            left = _build_condition(expr.left, child, hp_by_path, slots, cs, True)
            right = _build_condition(expr.right, child, hp_by_path, slots, cs, False)
            return cs.OrConjunction(left, right)
        left = _build_condition(expr.left, child, hp_by_path, slots, cs, False)
        right = _build_condition(expr.right, child, hp_by_path, slots, cs, True)
        return cs.AndConjunction(left, right)

    if isinstance(expr, ds.ParamExpr):
        slot = _require_native(expr.path, slots)
        wire = _to_wire(slot, True)
        cls = cs.NotEqualsCondition if negate else cs.EqualsCondition
        return cls(child, hp_by_path[expr.path], wire)

    if isinstance(expr, Compare):
        return _build_compare_condition(expr, child, hp_by_path, slots, cs, negate)

    if isinstance(expr, IsIn):
        return _build_is_in_condition(expr, child, hp_by_path, slots, cs, negate)

    raise _Unsupported(f"{expr.kind!r} has no ConfigSpace condition counterpart")


def _build_compare_condition(
    expr: Compare,
    child: Any,
    hp_by_path: dict[str, Any],
    slots: dict[str, _Slot],
    cs: Any,
    negate: bool,
) -> Any:
    path = _leaf_path(expr.left)
    if path is None or _leaf_path(expr.right) is not None:
        raise _Unsupported("a condition comparing two parameters has no ConfigSpace form")
    slot = _require_native(path, slots)
    _require_value_coded(path, slot)
    value = _leaf_literal(expr.right)
    op = _NEGATE_OP[expr.op] if negate else expr.op
    if op in ("ge", "le"):
        raise _Unsupported("ConfigSpace conditions have no >= or <= counterpart")
    wire = _to_wire(slot, value)
    parent = hp_by_path[path]
    return {
        "eq": cs.EqualsCondition,
        "ne": cs.NotEqualsCondition,
        "gt": cs.GreaterThanCondition,
        "lt": cs.LessThanCondition,
    }[op](child, parent, wire)


def _build_is_in_condition(
    expr: IsIn,
    child: Any,
    hp_by_path: dict[str, Any],
    slots: dict[str, _Slot],
    cs: Any,
    negate: bool,
) -> Any:
    path = _leaf_path(expr.operand)
    if path is None:
        raise _Unsupported("is_in over a non-parameter operand has no ConfigSpace form")
    slot = _require_native(path, slots)
    if not slot.values:
        raise _Unsupported(f"{path} is not an enumerable kind, so is_in has no complement")
    wire_values = [_to_wire(slot, v) for v in expr.values]
    if negate:
        wire_values = [i for i in range(len(slot.values)) if i not in wire_values]
    return cs.InCondition(child, hp_by_path[path], wire_values)


def _apply_conditions(
    space: ds.Space,
    slots: dict[str, _Slot],
    hp_by_path: dict[str, Any],
    hp_by_name: dict[str, Any],
    cs: Any,
    extra: dict[str, ds.BoolExpr],
) -> list[Any]:
    """Build a ConfigSpace condition for every conditional path.

    `space.topological_order` carries every top-level condition; `extra`
    carries a struct or choice descendant's own, already rewritten to its
    instance path by `_place_list`, since a descendant path is never a
    `topological_order` entry for this loop to find on its own.

    A parameter placing several hyperparameters, a lift or a subset, gates
    every one of them on the same condition: ConfigSpace then withholds them
    together, which is the activity the space declares. A parameter placing
    none, a struct, gates nothing, core having copied its condition onto
    each field underneath it already. Where one hyperparameter carries both
    its own condition and one inherited from a lift it sits inside, the two
    combine into a conjunction, ConfigSpace taking one condition per child.

    Every path whose condition has no counterpart is collected before any is
    raised, so a space is not fixed one parameter per run.
    """
    conditional: list[tuple[str, ds.TypeKind, ds.BoolExpr]] = []
    for path in space.topological_order:
        condition = space.params[path].condition
        if condition is not None:
            conditional.append((path, space.params[path].type_kind, condition))
    for path, expr in extra.items():
        conditional.append((path, slots[path].kind, expr))

    by_child: dict[str, Any] = {}
    refused: list[Rejection] = []
    for path, kind, expr in conditional:
        for name in slots[path].hp_names:
            try:
                built = _build_condition(expr, hp_by_name[name], hp_by_path, slots, cs, False)
            except _Unsupported as exc:
                refused.append(Rejection(path=path, kind=kind, reason=exc.reason))
                break
            carried = by_child.get(name)
            by_child[name] = built if carried is None else cs.AndConjunction(carried, built)
    if refused:
        raise UnsupportedSpace("the ConfigSpace binding", refused)
    return list(by_child.values())


# -- Forbidden clauses ------------------------------------------------------


def _relation_eligible(a: _Slot, b: _Slot) -> bool:
    """Whether comparing `a` and `b`'s wire values agrees with comparing
    their designspace values. True for two natively-placed reals/integers,
    wire being the value itself, and for two index-coded parameters sharing
    the identical declared values in the identical order, wire being a
    shared, order-preserving relabeling."""
    if a.kind in ("real", "integer") and b.kind in ("real", "integer"):
        return not a.unit_coded and not b.unit_coded
    if a.values and b.values and a.kind == b.kind:
        return a.values == b.values
    return False


def _build_forbidden(
    expr: ds.BoolExpr,
    hp_by_path: dict[str, Any],
    slots: dict[str, _Slot],
    cs: Any,
    negate: bool,
) -> Any:
    if isinstance(expr, Not):
        return _build_forbidden(expr.operand, hp_by_path, slots, cs, not negate)

    if isinstance(expr, BoolOp):
        left = _build_forbidden(expr.left, hp_by_path, slots, cs, negate)
        right = _build_forbidden(expr.right, hp_by_path, slots, cs, negate)
        want_and = (expr.op == "and") != negate
        conj = cs.ForbiddenAndConjunction if want_and else cs.ForbiddenOrConjunction
        return conj(left, right)

    if isinstance(expr, Implies):
        if not negate:
            left = _build_forbidden(expr.left, hp_by_path, slots, cs, True)
            right = _build_forbidden(expr.right, hp_by_path, slots, cs, False)
            return cs.ForbiddenOrConjunction(left, right)
        left = _build_forbidden(expr.left, hp_by_path, slots, cs, False)
        right = _build_forbidden(expr.right, hp_by_path, slots, cs, True)
        return cs.ForbiddenAndConjunction(left, right)

    if isinstance(expr, ds.ParamExpr):
        slot = _require_native(expr.path, slots)
        wire = _to_wire(slot, not negate)
        return cs.ForbiddenEqualsClause(hp_by_path[expr.path], wire)

    if isinstance(expr, Compare):
        return _build_forbidden_compare(expr, hp_by_path, slots, cs, negate)

    if isinstance(expr, IsIn):
        return _build_forbidden_is_in(expr, hp_by_path, slots, cs, negate)

    raise _Unsupported(f"{expr.kind!r} has no ConfigSpace forbidden-clause counterpart")


#: The forbidden clause each comparison against a literal becomes. `ge` and
#: `le` are absent deliberately, and `_STRICT_PART_OF` builds them from the
#: two entries here instead: as of ConfigSpace 1.2.2, the release that
#: introduced them, `ForbiddenLessThanEqualsClause` compares with `>=` where
#: it samples and with `<=` where it validates, so a space carrying one is
#: searched over exactly the region it forbids, and
#: `ForbiddenGreaterThanEqualsClause` writes to stdout on every validation.
#: A disjunction of the strict clause and the equality clause says the same
#: thing through two that agree with themselves.
_FORBIDDEN_CLAUSE_BY_OP: dict[str, str] = {
    "eq": "ForbiddenEqualsClause",
    "gt": "ForbiddenGreaterThanClause",
    "lt": "ForbiddenLessThanClause",
}
_STRICT_PART_OF: dict[str, str] = {"ge": "gt", "le": "lt"}
_FORBIDDEN_RELATION_BY_OP: dict[str, str] = {
    "eq": "ForbiddenEqualsRelation",
    "gt": "ForbiddenGreaterThanRelation",
    "lt": "ForbiddenLessThanRelation",
    "ge": "ForbiddenGreaterThanEqualsRelation",
    "le": "ForbiddenLessThanEqualsRelation",
}


def _build_forbidden_compare(
    expr: Compare,
    hp_by_path: dict[str, Any],
    slots: dict[str, _Slot],
    cs: Any,
    negate: bool,
) -> Any:
    op = _NEGATE_OP[expr.op] if negate else expr.op
    left_path = _leaf_path(expr.left)
    right_path = _leaf_path(expr.right)

    if left_path is not None and right_path is not None:
        a, b = _require_native(left_path, slots), _require_native(right_path, slots)
        if not _relation_eligible(a, b):
            raise _Unsupported(f"{left_path} and {right_path} do not share a comparable wire form")
        if op == "ne":
            lt = cs.ForbiddenLessThanRelation(hp_by_path[left_path], hp_by_path[right_path])
            gt = cs.ForbiddenGreaterThanRelation(hp_by_path[left_path], hp_by_path[right_path])
            return cs.ForbiddenOrConjunction(lt, gt)
        cls = getattr(cs, _FORBIDDEN_RELATION_BY_OP[op])
        return cls(hp_by_path[left_path], hp_by_path[right_path])

    if left_path is None:
        raise _Unsupported("a forbidden comparison needs a parameter operand")

    slot = _require_native(left_path, slots)
    _require_value_coded(left_path, slot)
    value = _leaf_literal(expr.right)
    wire = _to_wire(slot, value)
    parent = hp_by_path[left_path]
    if op == "ne":
        if slot.values:
            complement = [i for i in range(len(slot.values)) if i != wire]
            return cs.ForbiddenInClause(parent, complement)
        lt = cs.ForbiddenLessThanClause(parent, wire)
        gt = cs.ForbiddenGreaterThanClause(parent, wire)
        return cs.ForbiddenOrConjunction(lt, gt)
    if op in _STRICT_PART_OF:
        strict = getattr(cs, _FORBIDDEN_CLAUSE_BY_OP[_STRICT_PART_OF[op]])(parent, wire)
        return cs.ForbiddenOrConjunction(strict, cs.ForbiddenEqualsClause(parent, wire))
    cls = getattr(cs, _FORBIDDEN_CLAUSE_BY_OP[op])
    return cls(parent, wire)


def _build_forbidden_is_in(
    expr: IsIn,
    hp_by_path: dict[str, Any],
    slots: dict[str, _Slot],
    cs: Any,
    negate: bool,
) -> Any:
    path = _leaf_path(expr.operand)
    if path is None:
        raise _Unsupported("is_in over a non-parameter operand has no ConfigSpace form")
    slot = _require_native(path, slots)
    if not slot.values:
        raise _Unsupported(f"{path} is not an enumerable kind, so is_in has no complement")
    wire_values = [_to_wire(slot, v) for v in expr.values]
    if negate:
        wire_values = [i for i in range(len(slot.values)) if i not in wire_values]
    return cs.ForbiddenInClause(hp_by_path[path], wire_values)


def _cardinality_clauses(slot: _Slot, hp_by_name: dict[str, Any], cs: Any) -> list[Any]:
    """Forbid the subset sizes a subset's own domain excludes.

    A subset places one inclusion flag per item, and the flags on their own
    admit every combination: nothing in ConfigSpace ties them together, so a
    declared `min_size` or `max_size` would be lost and the space would call
    the sampled value out of bounds. ConfigSpace states a forbidden
    combination one at a time and has no clause over a sum, so the bound is
    spelled as the combinations it excludes. Exceeding `max_size` means some
    `max_size + 1` items are all included, and falling short of `min_size`
    means some `n - min_size + 1` are all excluded; forbidding each such
    combination forbids exactly the sizes outside the bounds and no
    configuration inside them.
    """
    assert slot.size_bounds is not None
    low, high = slot.size_bounds
    count = len(slot.hp_names)
    clauses: list[Any] = []
    if high < count:
        for combination in itertools.combinations(slot.hp_names, high + 1):
            clauses.append(
                cs.ForbiddenAndConjunction(
                    *[cs.ForbiddenEqualsClause(hp_by_name[name], 1) for name in combination]
                )
            )
    if low > 0:
        for combination in itertools.combinations(slot.hp_names, count - low + 1):
            clauses.append(
                cs.ForbiddenAndConjunction(
                    *[cs.ForbiddenEqualsClause(hp_by_name[name], 0) for name in combination]
                )
            )
    return clauses


def _cardinality_count(slot: _Slot) -> int:
    """How many clauses `_cardinality_clauses` would build for `slot`."""
    assert slot.size_bounds is not None
    low, high = slot.size_bounds
    count = len(slot.hp_names)
    total = 0
    if high < count:
        total += math.comb(count, high + 1)
    if low > 0:
        total += math.comb(count, count - low + 1)
    return total


def _apply_cardinality(slots: dict[str, _Slot], hp_by_name: dict[str, Any], cs: Any) -> list[Any]:
    """Bound every subset's size, or refuse the ones costing too much to bound.

    Every offending parameter is collected before any is raised, matching how
    a kind or a condition outside the envelope is reported.
    """
    clauses: list[Any] = []
    refused: list[Rejection] = []
    for slot in slots.values():
        if slot.kind != "subset" or slot.size_bounds is None:
            continue
        low, high = slot.size_bounds
        if low <= 0 and high >= len(slot.hp_names):
            continue
        if _cardinality_count(slot) > MAX_SUBSET_CLAUSES:
            refused.append(
                Rejection(
                    path=slot.path,
                    kind=slot.kind,
                    reason=f"a size bound of ({low}, {high}) over {len(slot.hp_names)} items "
                    f"needs {_cardinality_count(slot)} forbidden clauses, past the "
                    f"{MAX_SUBSET_CLAUSES} this backend spells out",
                )
            )
            continue
        clauses.extend(_cardinality_clauses(slot, hp_by_name, cs))
    if refused:
        raise UnsupportedSpace("the ConfigSpace binding", refused)
    return clauses


def _apply_forbidden(
    space: ds.Space,
    slots: dict[str, _Slot],
    hp_by_path: dict[str, Any],
    cs: Any,
    extra: list[ds.Constraint],
) -> tuple[list[Any], list[ds.Constraint]]:
    """Build a forbidden clause for every translatable hard constraint.

    `space.constraints` carries every top-level one; `extra` carries a
    struct element's own `element_constraints`, already rewritten to each
    instance by `_place_list`, since it is never one of `space.constraints`
    itself, only realized per instance.
    """
    clauses = []
    untranslated = []
    for constraint in [*space.constraints, *extra]:
        if not constraint.hard:
            continue
        try:
            clause = _build_forbidden(
                constraint.expr, hp_by_path, slots, cs, constraint.feasible_when_satisfied
            )
        except _Unsupported:
            untranslated.append(constraint)
            continue
        clauses.append(clause)
    return clauses, untranslated


# -- decode / encode --------------------------------------------------------


def _decode_slot(slot: _Slot, raw: dict[str, Any]) -> Any:
    if slot.kind == "subset":
        return [
            item for name, item in zip(slot.hp_names, slot.values, strict=True) if bool(raw[name])
        ]
    if slot.kind == "permutation":
        keys = [float(raw[name]) for name in slot.hp_names]
        return decode_random_keys(keys, slot.values)
    return _from_wire(slot, raw[slot.hp_names[0]])


def _encode_slot(slot: _Slot, value: Any, out: dict[str, Any]) -> None:
    if slot.kind == "list":
        # A lift's own flat key holds `ds.flatten`'s bookkeeping count, not
        # a value any hyperparameter represents; the fixed set of `[i]`
        # sub-entries already fixes the width. Nothing to write here.
        return
    if slot.kind == "subset":
        included = list(value)
        for name, item in zip(slot.hp_names, slot.values, strict=True):
            out[name] = 1 if item in included else 0
        return
    if slot.kind == "permutation":
        keys = encode_random_keys(value, slot.values)
        for name, key in zip(slot.hp_names, keys, strict=True):
            out[name] = key
        return
    out[slot.hp_names[0]] = _to_wire(slot, value)


@dataclass(frozen=True)
class Translation:
    """A space, translated into a `ConfigurationSpace`.

    Attributes
    ----------
    space : designspace.Space
        The space this translation was built from.
    config_space : ConfigSpace.ConfigurationSpace
        The translated space. Hand this to any ConfigSpace-based tool.
    unit_coded : tuple[str, ...]
        Real or integer parameters placed in `[0, 1]` and decoded through
        their chart, rather than as ConfigSpace's own distribution.
    index_coded : tuple[str, ...]
        Parameters placed as an index into their declared values.
    untranslated_constraints : tuple[designspace.Constraint, ...]
        Hard constraints with no forbidden-clause counterpart. Each is a
        relaxation the search will not see; `space.is_feasible` still catches
        it downstream.
    """

    space: ds.Space
    config_space: ConfigurationSpace
    unit_coded: tuple[str, ...]
    index_coded: tuple[str, ...]
    untranslated_constraints: tuple[ds.Constraint, ...]
    _slots: Mapping[str, _Slot]

    def decode(self, configuration: Configuration) -> dict[str, Any]:
        """Read one `Configuration` back into a configuration in domain units.

        Parameters
        ----------
        configuration : ConfigSpace.Configuration
            A configuration drawn from `config_space`.

        Returns
        -------
        dict[str, Any]
            A complete configuration this translation's `space` validates.
        """
        raw = dict(configuration)
        config: dict[str, Any] = {}
        while True:
            assignable = self.space.next_assignable(config)
            if not assignable:
                return ds.unflatten(config, self.space)
            for path in assignable:
                config[path] = _decode_slot(self._slots[path], raw)

    def encode(self, config: dict[str, Any]) -> Configuration:
        """Build a `Configuration` from a configuration in domain units.

        Parameters
        ----------
        config : dict[str, Any]
            A complete configuration this translation's `space` validates.

        Returns
        -------
        ConfigSpace.Configuration
            The same configuration, in `config_space`'s own terms.
        """
        from ConfigSpace import Configuration

        flat = ds.flatten(config, self.space)
        values: dict[str, Any] = {}
        for path, value in flat.items():
            slot = self._slots.get(path)
            if slot is not None:
                _encode_slot(slot, value, values)
        return Configuration(self.config_space, values=values)


def translate(space: ds.Space, *, default: dict[str, Any] | None = None) -> Translation:
    """Convert a space into a `ConfigurationSpace`, with exact decode and encode.

    Parameters
    ----------
    space : designspace.Space
        The space to translate.
    default : dict[str, Any] | None
        A complete configuration to seed hyperparameter defaults from, in
        place of each parameter's own declared default. `ConfigurationSpace`
        raises when its default configuration is itself forbidden; pass one
        known feasible to work around that.

    Returns
    -------
    Translation
        The translated space, paired with `decode` and `encode`.

    Raises
    ------
    UnsupportedSpace
        When a parameter's kind, or its condition, has no ConfigSpace
        counterpart. Every reason is reported at once.

    Examples
    --------
    >>> import designspace as ds
    >>> from designspace_solvers.configspace import translate
    >>> space = ds.space(ds.param("n").integer(1, 8))
    >>> translation = translate(space)
    >>> translation.config_space.seed(0)
    >>> config = translation.decode(translation.config_space.sample_configuration())
    >>> space.is_complete(config)
    True
    """
    cs = _require_configspace()
    require(space, backend="the ConfigSpace binding", kinds=KINDS, variable_length=False)

    default_overrides = ds.flatten(default, space) if default is not None else {}

    slots: dict[str, _Slot] = {}
    hyperparameters: list[Any] = []
    extra_conditions: dict[str, ds.BoolExpr] = {}
    extra_constraints: list[ds.Constraint] = []
    for path in space.topological_order:
        defn = space.params[path]
        if defn.type_kind == "list":
            assert isinstance(defn.domain, ds.ListDomain)
            list_slots, hps, _hp_names, list_conditions, list_constraints = _place_list(
                path, defn.domain, cs, default_overrides, space
            )
            slots.update(list_slots)
            hyperparameters.extend(hps)
            extra_conditions.update(list_conditions)
            extra_constraints.extend(list_constraints)
            continue
        effective_default = default_overrides.get(path, defn.default)
        slot, hps = _place_one(path, defn, cs, effective_default)
        slots[path] = slot
        hyperparameters.extend(hps)

    config_space = cs.ConfigurationSpace()
    if hyperparameters:
        config_space.add(hyperparameters)
    hp_by_name = {name: config_space[name] for name in config_space}
    hp_by_path = {
        path: hp_by_name[slot.hp_names[0]]
        for path, slot in slots.items()
        if len(slot.hp_names) == 1
    }

    conditions = _apply_conditions(space, slots, hp_by_path, hp_by_name, cs, extra_conditions)
    if conditions:
        config_space.add(conditions)

    forbidden, untranslated = _apply_forbidden(space, slots, hp_by_path, cs, extra_constraints)
    forbidden = [*_apply_cardinality(slots, hp_by_name, cs), *forbidden]
    if forbidden:
        config_space.add(forbidden)

    unit_coded = tuple(p for p, s in slots.items() if s.unit_coded)
    index_coded = tuple(
        p for p, s in slots.items() if s.values and s.kind not in ("subset", "permutation", "list")
    )
    return Translation(
        space=space,
        config_space=config_space,
        unit_coded=unit_coded,
        index_coded=index_coded,
        untranslated_constraints=tuple(untranslated),
        _slots=MappingProxyType(slots),
    )

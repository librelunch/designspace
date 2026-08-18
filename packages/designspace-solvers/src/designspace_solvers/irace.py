"""irace binding: iterated racing for algorithm configuration.

irace owns its loop. It proposes configurations, races them over a set of
instances, discards the ones losing statistically, and spends the surviving
budget on the rest, so `run(space, evaluate, scenario)` hands it a function
that scores a configuration rather than asking it for one.

`translate(space)` returns a `Translation`, which holds no R: every
specification is ordinary Python and every condition and forbidden entry is R
expression text, so a space is translated, inspected and refused where R is
not installed. `run` turns that text into R at the point it starts a race.
`KINDS` holds the parameter kinds this binding places, which is what the
ConfigSpace binding places; a dynamic count is refused on the same ground, a
fixed set of parameters being declared before the race starts.

Notes
-----
irace parses a condition as R rather than reading a clause vocabulary, and
two things follow. Parameters take names R parses as single symbols, because
irace resolves the names a condition mentions and a definition path is not
one. In exchange conditions and constraints reach further than a forbidden
clause does: an order comparison, a comparison between two parameters, and
arithmetic all translate, so a constraint another backend can only report is
expressed here.

Examples
--------
A space with a conditional parameter, translated:

>>> import designspace as ds
>>> from designspace_solvers.irace import translate
>>> space = ds.space(
...     ds.param("lr").real(1e-4, 1e-1).log_scale(),
...     ds.param("warmup").bool(),
...     ds.param("steps").integer(1, 100).when(ds.param("warmup")),
... )
>>> translation = translate(space)
>>> [(s.name, s.type, s.transf) for s in translation.params]
[('lr', 'r', 'log'), ('warmup', 'c', ''), ('steps', 'i', '')]

A log scale is irace's own transform, so `lr` is searched in its declared
units. The condition is R that names the parameter it reads:

>>> translation.params[-1].condition
'warmup == "1"'

A configuration comes back in domain units, and carries a parameter only
where it applies:

>>> translation.decode({"lr": 0.01, "warmup": "0", "steps": None})
{'lr': 0.01, 'warmup': False}

A constraint multiplying two parameters is one R expression, where a
forbidden clause has no form for it:

>>> budget = space.forbid(ds.param("lr") * ds.param("steps") > 1.0)
>>> translate(budget).forbidden
('(lr * steps) > 1.0',)

A space this binding cannot place is refused by path, every reason at once:

>>> from designspace_solvers import UnsupportedSpace
>>> dynamic = ds.space(
...     ds.param("n").integer(1, 5),
...     ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
... )
>>> try:
...     translate(dynamic)
... except UnsupportedSpace as exc:
...     print(exc)
the irace binding cannot search this space: xs (list): length is an
expression, and this backend needs a fixed width
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import designspace as ds
from designspace.expr import ArithOp, BoolOp, Compare, Implies, IsIn, Literal, Not
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

__all__ = [
    "KINDS",
    "Experiment",
    "ParamSpec",
    "Scenario",
    "Translation",
    "run",
    "translate",
]

#: The parameter kinds this binding places: every generative kind. `list` is
#: placed with a static count over any element kind; a dynamic count is caught
#: by `variable_length=False`. The program and custom kinds have no irace
#: counterpart at all.
KINDS = GENERATIVE_KINDS

_BACKEND = "the irace binding"

_NEGATE_OP = {"eq": "ne", "ne": "eq", "gt": "le", "lt": "ge", "ge": "lt", "le": "gt"}

#: The R operator each comparison and arithmetic node emits. R spells power
#: `^` and modulo `%%`, neither matching Python's spelling.
_R_COMPARE = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
_R_ARITH = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "^", "mod": "%%"}
_R_BOOL = {"and": "&", "or": "|"}

#: A name R parses as one symbol: a letter, or a dot not followed by a digit,
#: then letters, digits, dots and underscores.
_R_SYMBOL = re.compile(r"^(?:[a-zA-Z]|\.(?![0-9]))[a-zA-Z0-9._]*$")

#: R's reserved words. Each parses as syntax rather than as a name, so a
#: condition mentioning one never resolves to a parameter.
_R_RESERVED = frozenset(
    {
        "if",
        "else",
        "repeat",
        "while",
        "function",
        "for",
        "next",
        "break",
        "TRUE",
        "FALSE",
        "NULL",
        "Inf",
        "NaN",
        "NA",
        "NA_integer_",
        "NA_real_",
        "NA_character_",
        "in",
    }
)


def _require_rpy2() -> Any:
    """Import rpy2, or report which prerequisite is missing.

    rpy2 loads `libR` as it imports, and locates it by reading `R_HOME` or, in
    the absence of one, by running `R` from `PATH`. An installed rpy2 that
    reaches neither is a different absence from an absent rpy2, and the two
    report differently: the second names the extra to install, the first names
    what an interpreter has to be told to find R.
    """
    situation = require_backend("rpy2.situation", binding="irace", needs="rpy2", extra="irace")
    if situation.get_r_home() is None:
        raise RuntimeError(
            "the irace binding needs R, and rpy2 cannot find an installation. rpy2 reads "
            "R_HOME, and runs `R` from PATH where that is unset, so an interpreter started "
            "with neither reaches no R at all. Set R_HOME to an R installation, or start "
            "the interpreter from an environment holding `R` on PATH."
        )
    return require_backend("rpy2.robjects", binding="irace", needs="rpy2", extra="irace")


class _Unsupported(Exception):
    """One reason a parameter, condition or constraint has no irace form."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# -- Names ------------------------------------------------------------------


def r_name(path: str) -> str:
    """The irace parameter name a definition path is placed under.

    A path spells a lift's index and a struct's field with characters R reads
    as syntax: `workers[0].timeout_s` parses as an indexing expression, so
    `all.vars` on a condition mentioning it reports `workers` and irace
    rejects the condition as naming an unknown parameter. Replacing the
    brackets with the dot R already accepts inside a name leaves one symbol,
    `workers.0.timeout_s`, and leaves a plain path untouched.

    Parameters
    ----------
    path : str
        A definition or instance path.

    Returns
    -------
    str
        The name to place it under.
    """
    return path.replace("[", ".").replace("]", "")


def _name_rejection(path: str, kind: ds.TypeKind, name: str) -> Rejection | None:
    """Why `name` cannot be an irace parameter name, if it cannot."""
    if name in _R_RESERVED:
        return Rejection(
            path=path,
            kind=kind,
            reason=f"{name!r} is a reserved word in R, which parses it as syntax "
            "rather than as a parameter name",
        )
    if _R_SYMBOL.match(name) is None:
        return Rejection(
            path=path,
            kind=kind,
            reason=f"{name!r} is not one R symbol, so a condition naming this "
            "parameter would not parse",
        )
    return None


# -- Wire form --------------------------------------------------------------


@dataclass(frozen=True)
class _Slot:
    """Where and how one designspace parameter sits among irace's parameters."""

    path: str
    kind: ds.TypeKind
    names: tuple[str, ...]
    values: tuple[Any, ...]  # index-coded declared values; () for real/integer
    chart: ds.Chart | None  # set only for a unit-coded real/integer
    unit_coded: bool
    size_bounds: tuple[int, int] | None = None  # set only for a subset


def _single(slot: _Slot) -> bool:
    """Whether the slot sits on one parameter, so it can be compared."""
    return len(slot.names) == 1


def _index_of(values: tuple[Any, ...], value: Any) -> int:
    for index, candidate in enumerate(values):
        if type(candidate) is type(value) and candidate == value:
            return index
    raise _Unsupported(f"{value!r} is not one of {values!r}")


def _to_wire(slot: _Slot, value: Any) -> Any:
    """A domain value in irace's terms.

    An enumerable kind travels as its index. A categorical domain travels as
    the string of it, irace coercing such a domain with `as.character`, so a
    string is what it holds whatever is handed in and an index keeps a value
    of any type representable. An ordinal is placed as an integer and travels
    as the number.
    """
    if slot.unit_coded:
        assert slot.chart is not None
        return slot.chart.to_unit(value)
    if slot.values:
        index = _index_of(slot.values, value)
        return index if slot.kind == "ordinal" else str(index)
    return value


def _from_wire(slot: _Slot, wire: Any) -> Any:
    if slot.unit_coded:
        assert slot.chart is not None
        return slot.chart.from_unit(float(wire))
    if slot.values:
        return slot.values[int(wire)]
    return wire


# -- Specifications ---------------------------------------------------------


@dataclass(frozen=True)
class ParamSpec:
    """One irace parameter, as `run` will declare it.

    Attributes
    ----------
    name : str
        The irace parameter name.
    path : str
        The definition path it was placed from.
    type : str
        irace's own letter: `r` real, `i` integer, `c` categorical. An
        ordinal is placed as an integer over an index of its levels, so `o`
        is never emitted.
    domain : tuple
        Two bounds for a real or integer, the wire values for a categorical.
    transf : str
        `log` where irace samples on a logarithmic scale, otherwise empty.
    condition : str | None
        The R expression deciding when this parameter is active, or None where
        it always is.
    """

    name: str
    path: str
    type: str
    domain: tuple[Any, ...]
    transf: str = ""
    condition: str | None = None


def _index_domain(count: int) -> tuple[str, ...]:
    """The wire domain of an unordered enumerable kind: one index per value.

    irace coerces a categorical domain with `as.character`, so its values are
    strings whatever is handed in, and an index string keeps a declared value
    of any type representable. An ordinal is placed as an integer instead and
    does not pass through here.
    """
    return tuple(str(i) for i in range(count))


def _place_one(path: str, defn: ds.ParamDef) -> tuple[_Slot, list[ParamSpec]]:
    """Place one parameter, returning its slot and every irace parameter."""
    kind = defn.type_kind
    domain = defn.domain
    name = r_name(path)

    if kind in ("real", "integer"):
        chart = defn.chart
        assert chart is not None
        if native_scalar(defn):
            # The domain's own ends rather than the chart's, which round-trip
            # a log scale to within a rounding error of them. irace holds a
            # real to a fixed number of digits and reports a bound it cannot
            # represent, so the ends it is given are the declared ones.
            assert isinstance(domain, ds.RealDomain | ds.IntegerDomain)
            transf = "log" if isinstance(defn.prior, ds.Log) else ""
            letter = "r" if kind == "real" else "i"
            spec = ParamSpec(name, path, letter, (domain.lo, domain.hi), transf)
            return _Slot(path, kind, (name,), (), None, False), [spec]
        # A grid or a shaped prior is a coordinate system irace has no form
        # for, so the parameter sits in `[0, 1]` and the chart reads it back.
        spec = ParamSpec(name, path, "r", (0.0, 1.0))
        return _Slot(path, kind, (name,), (), chart, True), [spec]

    if kind == "bool":
        values: tuple[Any, ...] = (False, True)
        spec = ParamSpec(name, path, "c", _index_domain(2))
        return _Slot(path, kind, (name,), values, None, False), [spec]

    if kind == "categorical":
        assert isinstance(domain, ds.CategoricalDomain)
        values = domain.values
        spec = ParamSpec(name, path, "c", _index_domain(len(values)))
        return _Slot(path, kind, (name,), values, None, False), [spec]

    if kind == "ordinal":
        assert isinstance(domain, ds.OrdinalDomain)
        values = domain.values
        # An index over the levels is the order the levels declare, and irace
        # searches an integer the way it searches its own ordinal type: a
        # truncated normal over that index. Placing it as an integer rather
        # than as `param_ord` buys two things. The value is a number in R, so
        # an order comparison is the comparison as written rather than a
        # string comparison that puts `"10"` below `"2"`.
        # irace also currently has a bug with conditional ordinal parameters:
        # https://github.com/MLopez-Ibanez/irace/issues/94.
        spec = ParamSpec(name, path, "i", (0, len(values) - 1))
        return _Slot(path, kind, (name,), values, None, False), [spec]

    if kind == "choice":
        assert isinstance(domain, ds.ChoiceDomain)
        values = domain.variants
        spec = ParamSpec(name, path, "c", _index_domain(len(values)))
        return _Slot(path, kind, (name,), values, None, False), [spec]

    if kind == "subset":
        assert isinstance(domain, ds.SubsetDomain)
        items = domain.items
        names = tuple(r_name(p) for p in item_paths(path, len(items)))
        specs = [ParamSpec(n, path, "c", _index_domain(2)) for n in names]
        return _Slot(path, kind, names, items, None, False, subset_bounds(domain)), specs

    if kind == "permutation":
        assert isinstance(domain, ds.PermutationDomain)
        items = domain.items
        names = tuple(r_name(p) for p in item_paths(path, len(items)))
        specs = [ParamSpec(n, path, "r", (0.0, 1.0)) for n in names]
        return _Slot(path, kind, names, items, None, False), specs

    if kind == "space":
        # A struct declares no value of its own; its fields are placed under
        # their own relocated paths.
        return _Slot(path, kind, (), (), None, False), []

    raise UnsupportedSpace(
        _BACKEND,
        [Rejection(path=path, kind=kind, reason="no placement is defined for this kind")],
    )


# -- Lifts ------------------------------------------------------------------


def _rewrite_instance_path[ExprT: ds.Expr](expr: ExprT, lift_path: str, index: int) -> ExprT:
    """Rewrite every reference to `lift_path[]` in `expr` into `lift_path[index]`.

    A struct or choice element's own condition, and a constraint declared
    inside its space, are written against the template marker. Both are
    `ParamExpr` leaves whose `.path` starts with it, so substituting the index
    there and recursing over the rest is the whole rewrite.
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
    if isinstance(expr, ArithOp):
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


#: What the two lift walks build: the slots placed keyed by instance path,
#: every specification, a struct or choice descendant's own condition keyed by
#: its instance path, and every per-instance constraint a struct element's own
#: space declared.
_Placed = tuple[
    dict[str, _Slot],
    list[ParamSpec],
    dict[str, ds.BoolExpr],
    list[ds.Constraint],
]


def _place_struct_descendants(
    lift_path: str,
    index: int,
    templates: list[tuple[str, ds.ParamDef]],
    space: ds.Space,
) -> _Placed:
    """Place every descendant field a struct or choice element relocated.

    Core flattens such a lift's descendants into `space.params` under a
    template path, `workers[].timeout_s`, whatever their own kind and however
    deep their own nesting.
    """
    slots: dict[str, _Slot] = {}
    specs: list[ParamSpec] = []
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
            sub = _place_list(instance_path, template_defn.domain, space)
            slots.update(sub[0])
            specs.extend(sub[1])
            conditions.update(sub[2])
            constraints.extend(sub[3])
            continue

        instance_defn = dataclasses.replace(
            template_defn, path=instance_path, condition=instance_condition
        )
        slot, placed = _place_one(instance_path, instance_defn)
        slots[instance_path] = slot
        specs.extend(placed)

    return slots, specs, conditions, constraints


def _place_list(path: str, domain: ds.ListDomain, space: ds.Space) -> _Placed:
    """Unroll a static-count lift into one placement per index.

    `require`'s `variable_length=False` already refused a dynamic count, so
    `domain.count` is a literal integer here.
    """
    assert isinstance(domain.count, int)

    slots: dict[str, _Slot] = {}
    specs: list[ParamSpec] = []
    conditions: dict[str, ds.BoolExpr] = {}
    constraints: list[ds.Constraint] = []

    templates = (
        [(p, d) for p, d in space.params.items() if p.startswith(f"{path}[].")]
        if domain.element_kind in ("space", "choice")
        else []
    )

    names: list[str] = []
    for i in range(domain.count):
        elem_path = f"{path}[{i}]"

        if domain.element_kind == "list":
            assert isinstance(domain.element_domain, ds.ListDomain)
            sub = _place_list(elem_path, domain.element_domain, space)
            slots.update(sub[0])
            specs.extend(sub[1])
            conditions.update(sub[2])
            constraints.extend(sub[3])
            names.extend(sub[0][elem_path].names)
            continue

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
        slot, placed = _place_one(elem_path, elem_defn)
        slots[elem_path] = slot
        specs.extend(placed)
        names.extend(slot.names)

        if domain.element_kind in ("space", "choice"):
            sub = _place_struct_descendants(path, i, templates, space)
            slots.update(sub[0])
            specs.extend(sub[1])
            conditions.update(sub[2])
            constraints.extend(sub[3])
            names.extend(spec.name for spec in sub[1])
            for constraint in domain.element_constraints:
                constraints.append(
                    dataclasses.replace(
                        constraint, expr=_rewrite_instance_path(constraint.expr, path, i)
                    )
                )

    slots[path] = _Slot(path, "list", tuple(names), (), None, False)
    return slots, specs, conditions, constraints


# -- R expressions ----------------------------------------------------------


def _r_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return f'"{value}"'
    return repr(value)


def _leaf_path(expr: ds.Expr) -> str | None:
    return expr.path if isinstance(expr, ds.ParamExpr) else None


def _leaf_literal(expr: ds.Expr) -> Any:
    if isinstance(expr, Literal) or expr.kind == "literal":
        return expr.value  # type: ignore[attr-defined]
    raise _Unsupported("operand is not a literal")


def _require_single(path: str, slots: dict[str, _Slot]) -> _Slot:
    slot = slots.get(path)
    if slot is None or not _single(slot):
        raise _Unsupported(f"{path} is not placed as one comparable parameter")
    return slot


def _require_value_coded(path: str, slot: _Slot) -> None:
    """Refuse comparing a unit-coded slot against a literal.

    A quantized scalar, or one carrying a shaped prior, sits in `[0, 1]` and
    reaches its declared value through its chart. A literal therefore converts
    to the edge of the cell that decodes to it rather than to a point inside
    it, so a strict comparison drops the whole cell and an equality never
    fires. Both are silent.
    """
    if slot.unit_coded:
        raise _Unsupported(
            f"{path} sits in unit coordinates, where a literal marks a cell edge "
            "rather than the value itself"
        )


def _r_compare_value(slot: _Slot, value: Any) -> str:
    """A literal in the terms the operand it is compared against uses."""
    return _r_literal(_to_wire(slot, value))


def _r_arith_expr(expr: ds.Expr, slots: dict[str, _Slot]) -> str:
    """One arithmetic operand: a parameter, a literal, or a tree of both."""
    if isinstance(expr, ds.ParamExpr):
        slot = _require_single(expr.path, slots)
        _require_value_coded(expr.path, slot)
        if slot.values:
            raise _Unsupported(f"{expr.path} is index-coded, so arithmetic on it means nothing")
        return slot.names[0]
    if isinstance(expr, ArithOp):
        if expr.op not in _R_ARITH:
            raise _Unsupported(f"{expr.op!r} has no R operator")
        left = _r_arith_expr(expr.left, slots)
        right = _r_arith_expr(expr.right, slots)
        return f"({left} {_R_ARITH[expr.op]} {right})"
    return _r_literal(_leaf_literal(expr))


def _r_compare(expr: Compare, slots: dict[str, _Slot], negate: bool) -> str:
    op = _NEGATE_OP[expr.op] if negate else expr.op
    left_path, right_path = _leaf_path(expr.left), _leaf_path(expr.right)

    if left_path is not None and right_path is not None:
        a = _require_single(left_path, slots)
        b = _require_single(right_path, slots)
        if not _relation_eligible(a, b):
            raise _Unsupported(f"{left_path} and {right_path} do not share a comparable wire form")
        return f"{a.names[0]} {_R_COMPARE[op]} {b.names[0]}"

    if left_path is not None:
        slot = _require_single(left_path, slots)
        _require_value_coded(left_path, slot)
        value = _leaf_literal(expr.right)
        return f"{slot.names[0]} {_R_COMPARE[op]} {_r_compare_value(slot, value)}"

    # Anything else is arithmetic on one or both sides, which R evaluates as
    # written. An index-coded operand inside it is refused there.
    left = _r_arith_expr(expr.left, slots)
    right = _r_arith_expr(expr.right, slots)
    return f"{left} {_R_COMPARE[op]} {right}"


def _r_is_in(expr: IsIn, slots: dict[str, _Slot], negate: bool) -> str:
    path = _leaf_path(expr.operand)
    if path is None:
        raise _Unsupported("is_in over a non-parameter operand has no R form")
    slot = _require_single(path, slots)
    if not slot.values:
        raise _Unsupported(f"{path} is not an enumerable kind, so is_in has no members")
    members = ", ".join(_r_literal(_to_wire(slot, v)) for v in expr.values)
    test = f"{slot.names[0]} %in% c({members})"
    return f"!({test})" if negate else test


def _r_bool(expr: ds.BoolExpr, slots: dict[str, _Slot], negate: bool) -> str:
    """One boolean expression as R text, with negation pushed to the leaves.

    Pushing rather than wrapping keeps what irace logs readable: a `require`
    becomes the comparison the caller would have written by hand, rather than
    a negation of the one they did write.
    """
    if isinstance(expr, Not):
        return _r_bool(expr.operand, slots, not negate)

    if isinstance(expr, BoolOp):
        left = _r_bool(expr.left, slots, negate)
        right = _r_bool(expr.right, slots, negate)
        op = "or" if (expr.op == "and") == negate else "and"
        return f"({left}) {_R_BOOL[op]} ({right})"

    if isinstance(expr, Implies):
        # `a implies b` is `!a or b`, and its negation is `a and !b`.
        left = _r_bool(expr.left, slots, not negate)
        right = _r_bool(expr.right, slots, negate)
        op = "and" if negate else "or"
        return f"({left}) {_R_BOOL[op]} ({right})"

    if isinstance(expr, ds.ParamExpr):
        slot = _require_single(expr.path, slots)
        wire = _to_wire(slot, not negate)
        return f"{slot.names[0]} == {_r_literal(wire)}"

    if isinstance(expr, Compare):
        return _r_compare(expr, slots, negate)

    if isinstance(expr, IsIn):
        return _r_is_in(expr, slots, negate)

    raise _Unsupported(f"{expr.kind!r} has no R expression counterpart")


def _relation_eligible(a: _Slot, b: _Slot) -> bool:
    """Whether comparing two wire values agrees with comparing their domain
    values. True for two natively placed scalars, the wire being the value,
    and for two index-coded parameters sharing declared values in the same
    order, the wire being one order-preserving relabeling."""
    if a.kind in ("real", "integer") and b.kind in ("real", "integer"):
        return not a.unit_coded and not b.unit_coded
    if a.values and b.values and a.kind == b.kind:
        return a.values == b.values
    return False


# -- Assembly ---------------------------------------------------------------


def _conditions(
    space: ds.Space, slots: dict[str, _Slot], extra: dict[str, ds.BoolExpr]
) -> dict[str, str]:
    """The R condition each placed name is gated on.

    A parameter placing several names, a subset or a lift, gates every one of
    them on the same expression. One carrying both its own condition and one
    inherited from the lift it sits in conjoins the two.
    """
    declared: list[tuple[str, ds.TypeKind, ds.BoolExpr]] = []
    for path in space.topological_order:
        condition = space.params[path].condition
        if condition is not None:
            declared.append((path, space.params[path].type_kind, condition))
    for path, expr in extra.items():
        declared.append((path, slots[path].kind, expr))

    by_name: dict[str, str] = {}
    refused: list[Rejection] = []
    for path, kind, expr in declared:
        try:
            text = _r_bool(expr, slots, False)
        except _Unsupported as exc:
            refused.append(Rejection(path=path, kind=kind, reason=exc.reason))
            continue
        for name in slots[path].names:
            carried = by_name.get(name)
            by_name[name] = text if carried is None else f"({carried}) & ({text})"
    if refused:
        raise UnsupportedSpace(_BACKEND, refused)
    return by_name


def _cardinality(slots: dict[str, _Slot]) -> list[str]:
    """Forbid the subset sizes a subset's own domain excludes.

    A subset sits across one flag per item, which loses the size bounds the
    domain declares: nothing stops every flag being set. Their sum is
    arithmetic, so R states the bounds directly, and a race that could
    otherwise return a configuration the space calls out of bounds does not.
    """
    expressions: list[str] = []
    for slot in slots.values():
        if slot.kind != "subset" or slot.size_bounds is None:
            continue
        low, high = slot.size_bounds
        count = len(slot.names)
        if low <= 0 and high >= count:
            continue
        total = " + ".join(f"as.numeric({name})" for name in slot.names)
        if low > 0:
            expressions.append(f"({total}) < {low}")
        if high < count:
            expressions.append(f"({total}) > {high}")
    return expressions


def _forbidden(
    space: ds.Space, slots: dict[str, _Slot], extra: list[ds.Constraint]
) -> tuple[tuple[str, ...], tuple[ds.Constraint, ...]]:
    """An R expression for every hard constraint that has one.

    A constraint with no expression is returned rather than raised. It is
    always a relaxation and never a restriction: the race may propose a
    configuration the space calls infeasible, and never loses one it calls
    feasible.
    """
    expressions: list[str] = _cardinality(slots)
    untranslated: list[ds.Constraint] = []
    for constraint in [*space.constraints, *extra]:
        if not constraint.hard:
            continue
        try:
            text = _r_bool(constraint.expr, slots, constraint.feasible_when_satisfied)
        except _Unsupported:
            untranslated.append(constraint)
            continue
        expressions.append(text)
    return tuple(expressions), tuple(untranslated)


def _decode_slot(slot: _Slot, raw: Mapping[str, Any]) -> Any:
    if slot.kind == "subset":
        return [
            item for name, item in zip(slot.names, slot.values, strict=True) if int(raw[name]) == 1
        ]
    if slot.kind == "permutation":
        keys = [float(raw[name]) for name in slot.names]
        return decode_random_keys(keys, slot.values)
    return _from_wire(slot, raw[slot.names[0]])


def _encode_slot(slot: _Slot, value: Any, out: dict[str, Any]) -> None:
    if slot.kind in ("list", "space"):
        # A lift's own flat key holds `ds.flatten`'s bookkeeping count and a
        # struct declares no value, neither being anything a parameter holds.
        return
    if slot.kind == "subset":
        included = list(value)
        for name, item in zip(slot.names, slot.values, strict=True):
            out[name] = "1" if item in included else "0"
        return
    if slot.kind == "permutation":
        for name, key in zip(slot.names, encode_random_keys(value, slot.values), strict=True):
            out[name] = key
        return
    out[slot.names[0]] = _to_wire(slot, value)


@dataclass(frozen=True)
class Translation:
    """A space, placed in irace's terms.

    Holds no R. Every specification is ordinary Python and every condition and
    forbidden entry is R expression text, so a space translates, and is
    refused, where R is not installed.

    Attributes
    ----------
    space : designspace.Space
        The space this translation was built from.
    params : tuple[ParamSpec, ...]
        One specification per irace parameter, in placement order.
    names : Mapping[str, tuple[str, ...]]
        The irace parameter names each definition path was placed under.
    forbidden : tuple[str, ...]
        One R expression per translated hard constraint. A configuration
        satisfying any of them is one irace will not run.
    unit_coded : tuple[str, ...]
        Real or integer parameters placed in `[0, 1]` and read back through
        their chart rather than searched in their declared units.
    index_coded : tuple[str, ...]
        Parameters placed as an index into their declared values.
    untranslated_constraints : tuple[designspace.Constraint, ...]
        Hard constraints with no R expression. Each is a relaxation the race
        will not see; `space.is_feasible` still catches it.
    """

    space: ds.Space
    params: tuple[ParamSpec, ...]
    names: Mapping[str, tuple[str, ...]]
    forbidden: tuple[str, ...]
    unit_coded: tuple[str, ...]
    index_coded: tuple[str, ...]
    untranslated_constraints: tuple[ds.Constraint, ...]
    _slots: Mapping[str, _Slot] = field(repr=False)

    def decode(self, configuration: Mapping[str, Any]) -> dict[str, Any]:
        """Read one irace configuration back into domain units.

        Parameters
        ----------
        configuration : Mapping[str, Any]
            A configuration keyed by irace parameter name. A parameter its
            condition left inactive may be absent or hold a missing value;
            either way it is not read.

        Returns
        -------
        dict[str, Any]
            A configuration this translation's `space` validates.
        """
        config: dict[str, Any] = {}
        while True:
            assignable = self.space.next_assignable(config)
            if not assignable:
                return ds.unflatten(config, self.space)
            for path in assignable:
                config[path] = _decode_slot(self._slots[path], configuration)

    def encode(self, config: dict[str, Any]) -> dict[str, Any]:
        """Write a configuration in domain units into irace's terms.

        Parameters
        ----------
        config : dict[str, Any]
            A configuration this translation's `space` validates.

        Returns
        -------
        dict[str, Any]
            The same configuration, keyed by irace parameter name.
        """
        values: dict[str, Any] = {}
        for path, value in ds.flatten(config, self.space).items():
            slot = self._slots.get(path)
            if slot is not None:
                _encode_slot(slot, value, values)
        return values


def translate(space: ds.Space) -> Translation:
    """Place a space in irace's terms, with exact decode and encode.

    Parameters
    ----------
    space : designspace.Space
        The space to place.

    Returns
    -------
    Translation
        The placed space, paired with `decode` and `encode`.

    Raises
    ------
    UnsupportedSpace
        When a parameter's kind, its name, or its condition has no irace
        counterpart. Every reason is reported at once.
    """
    require(space, backend=_BACKEND, kinds=KINDS, variable_length=False)

    slots: dict[str, _Slot] = {}
    specs: list[ParamSpec] = []
    extra_conditions: dict[str, ds.BoolExpr] = {}
    extra_constraints: list[ds.Constraint] = []
    for path in space.topological_order:
        defn = space.params[path]
        if defn.type_kind == "list":
            assert isinstance(defn.domain, ds.ListDomain)
            placed = _place_list(path, defn.domain, space)
            slots.update(placed[0])
            specs.extend(placed[1])
            extra_conditions.update(placed[2])
            extra_constraints.extend(placed[3])
            continue
        slot, placed_specs = _place_one(path, defn)
        slots[path] = slot
        specs.extend(placed_specs)

    refused = [
        rejection
        for spec in specs
        if (rejection := _name_rejection(spec.path, slots[spec.path].kind, spec.name)) is not None
    ]
    if refused:
        raise UnsupportedSpace(_BACKEND, refused)

    conditions = _conditions(space, slots, extra_conditions)
    specs = [
        dataclasses.replace(spec, condition=conditions[spec.name])
        if spec.name in conditions
        else spec
        for spec in specs
    ]

    forbidden, untranslated = _forbidden(space, slots, extra_constraints)

    return Translation(
        space=space,
        params=tuple(specs),
        names=MappingProxyType({path: slot.names for path, slot in slots.items()}),
        forbidden=forbidden,
        unit_coded=tuple(p for p, s in slots.items() if s.unit_coded),
        index_coded=tuple(
            p
            for p, s in slots.items()
            if s.values and s.kind not in ("subset", "permutation", "list")
        ),
        untranslated_constraints=untranslated,
        _slots=MappingProxyType(slots),
    )


# -- Racing -----------------------------------------------------------------


def _named(value: Any) -> dict[str, Any]:
    """An R named list as a plain dict.

    Everything crossing back from R does so here or in `_scalar`, so the rest
    of this module reads ordinary Python.
    """
    names = list(value.names) if value.names is not None else []
    return {str(name): item for name, item in zip(names, list(value), strict=False)}


def _scalar(value: Any) -> Any:
    """The one element of a length-one R vector.

    R has no scalars: a single number arrives as a vector holding it. A value
    that is already plain, which is what a nested conversion can yield, is
    returned as it is.
    """
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    items = list(value)
    return items[0] if items else None


@dataclass(frozen=True)
class Experiment:
    """What irace is asking a configuration to be scored on.

    Attributes
    ----------
    configuration_id : str
        irace's own identifier for the configuration being run.
    instance : Any
        The instance to score against, as it was passed to `Scenario`.
    instance_id : int | None
        Its position in `Scenario.instances`, or None where none were given.
    seed : int
        The seed irace drew for this run. A target function using randomness
        reseeds from it, so a rerun of the same pair repeats.
    """

    configuration_id: str
    instance: Any
    instance_id: int | None
    seed: int


@dataclass(frozen=True)
class Scenario:
    """How a race is run.

    A deliberately small part of what irace accepts, covering the options a
    race needs rather than every option it has.

    Attributes
    ----------
    max_experiments : int | None
        The total number of target-function calls the race may spend.
    min_experiments : int | None
        The fewest it should spend.
    instances : tuple[Any, ...]
        The instances to race over, as arbitrary Python objects. They reach
        the target function through `Experiment.instance` unchanged.
    elitist : bool
        Whether elite configurations survive between iterations.
    deterministic : bool
        Whether one instance need be evaluated only once per configuration.
    log_file : str | None
        Where irace writes its own log. None writes none: left to itself irace
        saves `irace.Rdata` into the working directory, which is not a
        side effect a caller asked for by starting a race.
    exec_dir : str | None
        The directory the race runs in.
    n_jobs : int
        How many target-function calls run at once.
    seed : int | None
        The race's own seed.
    verbose : int
        How much irace reports as it runs.
    """

    max_experiments: int | None = None
    min_experiments: int | None = None
    instances: tuple[Any, ...] = ()
    elitist: bool = True
    deterministic: bool = False
    log_file: str | None = None
    exec_dir: str | None = None
    n_jobs: int = 1
    seed: int | None = None
    verbose: int = 0


def run(
    space: ds.Space,
    evaluate: Any,
    scenario: Scenario | None = None,
) -> list[dict[str, Any]]:
    """Race configurations from `space` and return the elites.

    Parameters
    ----------
    space : designspace.Space
        The space to search.
    evaluate : Callable[[dict[str, Any], Experiment], float]
        Scores one configuration, lower being better. It receives the
        configuration in domain units and the experiment it is being scored
        for.
    scenario : Scenario | None
        How to run the race. Defaults to `Scenario()`.

    Returns
    -------
    list[dict[str, Any]]
        The elite configurations, in domain units, best first.

    Raises
    ------
    ImportError
        When rpy2 is absent, naming the extra that installs it.
    UnsupportedSpace
        When the space has no irace form. Every reason is reported at once.
    """
    robjects = _require_rpy2()
    from rpy2.robjects.packages import importr

    translation = translate(space)
    scenario = scenario if scenario is not None else Scenario()

    try:
        irace_pkg = importr("irace")
    except Exception as exc:
        raise RuntimeError(
            "the irace binding needs the R package irace, version 4.4 or later. "
            "Install R, then run "
            "`Rscript -e \"install.packages('irace', repos='https://cloud.r-project.org')\"`."
        ) from exc

    failure: list[BaseException] = []
    elites = _race(robjects, irace_pkg, translation, evaluate, scenario, failure)
    if failure:
        raise RuntimeError("the target function raised, which stopped the race") from failure[0]
    return elites


def _race(
    robjects: Any,
    irace_pkg: Any,
    translation: Translation,
    evaluate: Any,
    scenario: Scenario,
    failure: list[BaseException],
) -> list[dict[str, Any]]:
    """Build the R parameter space, install the runner, and race."""
    from rpy2.rinterface import rternalize
    from rpy2.robjects import ListVector, StrVector

    def r_expression(text: str) -> Any:
        return robjects.r(f"expression({text})")

    parameters = []
    for spec in translation.params:
        common: dict[str, Any] = {"name": spec.name}
        if spec.condition is not None:
            common["condition"] = r_expression(spec.condition)
        if spec.type in ("r", "i"):
            ctor = irace_pkg.param_real if spec.type == "r" else irace_pkg.param_int
            parameters.append(
                ctor(lower=spec.domain[0], upper=spec.domain[1], transf=spec.transf, **common)
            )
        else:
            ctor = irace_pkg.param_cat if spec.type == "c" else irace_pkg.param_ord
            parameters.append(ctor(values=StrVector(list(spec.domain)), **common))

    kwargs: dict[str, Any] = {}
    if translation.forbidden:
        # irace forbids a configuration matching any entry, so the whole set
        # is one disjunction.
        joined = " | ".join(f"({text})" for text in translation.forbidden)
        kwargs["forbidden"] = r_expression(joined)
    r_params = irace_pkg.parametersNew(*parameters, **kwargs)

    instances = scenario.instances or (0,)

    def run_one(experiment: Any, _scenario: Any) -> Any:
        try:
            fields = _named(experiment)
            raw = {name: _scalar(value) for name, value in _named(fields["configuration"]).items()}
            index = int(_scalar(fields["id_instance"])) - 1
            cost = evaluate(
                translation.decode(raw),
                Experiment(
                    configuration_id=str(_scalar(fields["id_configuration"])),
                    instance=instances[index],
                    instance_id=None if not scenario.instances else index,
                    seed=int(_scalar(fields["seed"])),
                ),
            )
        except BaseException as exc:
            # `error` is irace's own channel for a failing target function: it
            # stops the race and reports the message. Holding the exception
            # keeps the traceback, which the R-side stop would otherwise lose.
            failure.append(exc)
            return ListVector({"error": f"{type(exc).__name__}: {exc}"})
        return ListVector({"cost": float(cost)})

    # Bound to a name for the duration of the race, not passed inline. R holds
    # the wrapped function by handle rather than by reference, so a temporary
    # is collectable the moment this expression ends and the first callback
    # then dereferences freed memory.
    target_runner = rternalize(run_one)
    r_scenario = _r_scenario(robjects, scenario, target_runner, r_params, instances)
    try:
        result = irace_pkg.irace(scenario=r_scenario)
    except Exception:
        if failure:
            return []
        raise
    return _elites(translation, result)


def _r_scenario(
    robjects: Any, scenario: Scenario, target_runner: Any, r_params: Any, instances: Sequence[Any]
) -> Any:
    """The R scenario list, holding only what `Scenario` states."""
    from rpy2.robjects import IntVector, ListVector

    fields: dict[str, Any] = {
        "targetRunner": target_runner,
        "parameters": r_params,
        # Instances travel as indices, so an instance may be any Python
        # object: the runner maps the index back before scoring.
        "instances": IntVector(list(range(1, len(instances) + 1))),
        "elitist": int(scenario.elitist),
        "deterministic": int(scenario.deterministic),
        "parallel": scenario.n_jobs,
        "debugLevel": scenario.verbose,
        # Always stated, because the default is to write a file: irace saves
        # `irace.Rdata` beside whatever started it unless told otherwise.
        "logFile": "" if scenario.log_file is None else scenario.log_file,
    }
    if scenario.max_experiments is not None:
        fields["maxExperiments"] = scenario.max_experiments
    if scenario.min_experiments is not None:
        fields["minExperiments"] = scenario.min_experiments
    if scenario.seed is not None:
        fields["seed"] = scenario.seed
    if scenario.exec_dir is not None:
        fields["execDir"] = scenario.exec_dir
    return robjects.r["checkScenario"](ListVector(fields))


def _elites(translation: Translation, result: Any) -> list[dict[str, Any]]:
    """Read irace's elite configurations back into domain units."""
    names = [str(name) for name in (result.names or ())]
    rows = len(result[0]) if names else 0
    placed = {spec.name for spec in translation.params}
    elites: list[dict[str, Any]] = []
    for row in range(rows):
        # irace returns its own bookkeeping columns alongside the parameters,
        # so only the names this translation placed are read back.
        raw: dict[str, Any] = {
            name: result[column][row] for column, name in enumerate(names) if name in placed
        }
        elites.append(translation.decode(raw))
    return elites

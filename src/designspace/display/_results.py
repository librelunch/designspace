"""Rendering results, reports, and program support types (API.md,
"Human-Readable Rendering", "IR", "Support Types").

Small blocks rather than tables: each of these types is usually read as a
single value, printed alone or in a Python `repr`-of-a-list context, so the
rendering optimizes for a short, informative line or a handful of them
rather than for column alignment across many instances.
"""

from __future__ import annotations

from typing import Any

from designspace.display._domain import render_signature
from designspace.display._expr import render_expr
from designspace.display._values import render_elidable, render_value


def render_constraint_eval(ce: Any) -> str:
    if not ce.applicable:
        status = "inapplicable"
    elif ce.violated:
        status = "VIOLATED"
    else:
        status = "OK"
    where = f" at {ce.instance_path}" if ce.instance_path is not None else ""
    margin = "" if ce.margin is None else f" margin={render_value(ce.margin)}"
    body = render_expr(ce.constraint.expr)
    return f"{ce.constraint.kind}{where}: {status}{margin}: {body}"


def render_param_error(pe: Any) -> str:
    tail = f" (value={render_value(pe.value)})" if pe.value is not None else ""
    return f"{pe.param}: {pe.reason}{tail}"


def render_validation_result(vr: Any) -> str:
    if vr.valid:
        return "Validation: OK"
    lines = [
        f"Validation: INVALID "
        f"({len(vr.param_errors)} param error(s), "
        f"{sum(1 for ce in vr.constraint_evals if ce.violated)} constraint(s) violated)"
    ]
    lines.extend(f"  {render_param_error(pe)}" for pe in vr.param_errors)
    lines.extend(f"  {render_constraint_eval(ce)}" for ce in vr.constraint_evals if ce.violated)
    return "\n".join(lines)


def render_partial_eval(pe: Any) -> str:
    counts: dict[str, int] = {}
    for status in pe.param_status.values():
        counts[status] = counts.get(status, 0) + 1
    order = ("set", "active_unset", "inactive", "unknown")
    tally = ", ".join(f"{counts[k]} {k}" for k in order if k in counts)
    return (
        f"Partial config: {tally}; {pe.n_remaining} remaining, "
        f"{len(pe.pending_constraints)} constraint(s) pending"
    )


def render_real_remaining(r: Any) -> str:
    lo = "[" if r.lo_inclusive else "("
    hi = "]" if r.hi_inclusive else ")"
    return f"{lo}{render_value(r.lo)}, {render_value(r.hi)}{hi}"


def render_integer_remaining(r: Any) -> str:
    return f"[{render_value(r.lo)}, {render_value(r.hi)}]"


def render_value_remaining(r: Any) -> str:
    return render_elidable([render_value(v) for v in r.values], open="{", close="}")


def render_subset_remaining(r: Any) -> str:
    forced = render_elidable([render_value(v) for v in r.forced_in], open="{", close="}")
    free = render_elidable([render_value(v) for v in r.free], open="{", close="}")
    return f"forced {forced}, free {free}, size {r.min_size}..{r.max_size}"


def render_permutation_remaining(r: Any) -> str:
    items = render_elidable([render_value(v) for v in r.items], open="{", close="}")
    return f"ordering of {items}"


def render_param_diff(d: Any) -> str:
    return f"{d.param}: {render_value(d.old)} -> {render_value(d.new)}"


def render_subspace_info(s: Any) -> str:
    tail = f" ({s.variant_name!r})" if s.variant_name is not None else ""
    return f"{s.kind}{tail} at {s.prefix!r}: {len(s.member_paths)} member(s)"


def render_constraint_report(r: Any) -> str:
    return (
        f"{r.constraint.kind}: applicable={r.applicable:.0%} "
        f"satisfied={r.satisfied:.0%} violation_rate={r.violation_rate:.0%}"
    )


def render_sampling_report(r: Any) -> str:
    lines = [f"Sampling report: n={r.n}, acceptance_rate={r.acceptance_rate:.0%}"]
    lines.extend(f"  {render_constraint_report(c)}" for c in r.constraints)
    return "\n".join(lines)


def render_representation_check_failure(f: Any) -> str:
    return f"{f.law} x{f.count}: {f.detail}"


def render_representation_check(c: Any) -> str:
    if c.ok:
        return f"Representation check: OK (n={c.n})"
    lines = [f"Representation check: {len(c.failures)} law(s) violated (n={c.n})"]
    lines.extend(f"  {render_representation_check_failure(f)}" for f in c.failures)
    return "\n".join(lines)


def render_representation(rep: Any) -> str:
    lines = [
        f"Representation: {len(rep.source.params)} params -> "
        f"{len(rep.target.params)} params "
        f"(invertible={rep.invertible}, measure_preserving={rep.measure_preserving})"
    ]
    if rep.encoded:
        lines.append(f"  encoded: {render_elidable(list(rep.encoded), open='', close='')}")
    if rep.excluded_by_prop:
        lines.append(
            f"  excluded by prop/count: "
            f"{render_elidable(list(rep.excluded_by_prop), open='', close='')}"
        )
    if rep.opaque_conditions:
        lines.append(f"  opaque conditions: {len(rep.opaque_conditions)}")
    if rep.opaque_constraints:
        lines.append(f"  opaque constraints: {len(rep.opaque_constraints)}")
    if rep.dropped_defaults:
        lines.append(f"  dropped defaults: {len(rep.dropped_defaults)}")
    if rep.dropped_anchors:
        lines.append(f"  dropped anchors: {len(rep.dropped_anchors)}")
    return "\n".join(lines)


def render_signature_standalone(sig: Any) -> str:
    return render_signature(sig)


def render_float_literal(lit: Any) -> str:
    return f"[{render_value(lit.lo)}, {render_value(lit.hi)}]"


def render_int_literal(lit: Any) -> str:
    return f"[{render_value(lit.lo)}, {render_value(lit.hi)}]"


def render_primitive(p: Any) -> str:
    lo, hi = p.arity_range
    arity = str(lo) if hi == lo else f"{lo}.." if hi is None else f"{lo}..{hi}"
    return f"{p.name}({arity})"

"""Example 5 — Flow Chemistry: the expression vocabulary.

The first four examples grow the *shape* of a space (flat, hierarchical,
variable-length, custom-typed). This one holds the shape deliberately plain
— a continuous-flow chemistry rig's reagent set, step order, and process
conditions — so the *constraints* can carry the example: every boolean and
arithmetic expression form the spec defines, in one runnable space.

Concepts introduced here
-------------------------
- Subset queries: ``.contains(item)``, ``.size()``, ``.sum_over(mapping)`` —
  a literal ``dict`` of per-item weights, evaluated as Σ over included items.
- Permutation queries: ``.position_of(item)`` — an ordering constraint
  compares two positions directly.
- The boolean fold operators ``ds.all_(*exprs)`` / ``ds.any_(*exprs)``, and
  ``ds.count(*bool_exprs) <= k`` — how many of several conditions hold at
  once, as an arithmetic value.
- ``.implies(other)`` and ``.is_in(*values)``.
- ``.is_active()`` — a condition that is always determined (True/False,
  never Unknown), unlike referencing the param itself when it may be absent.
- ``.if_inactive(fallback)`` — shown paired with the unguarded form on the
  *same* aggregate, so the Kleene-rule-4 swallowing (an inapplicable, not
  failing, constraint whenever the optional param is inactive) is visible
  side by side with the guarded version that stays applicable throughout.
- ``ds.value(fn, *operands, returns=type)`` (M10.8): an opaque derived
  quantity over *ordinary* reals — the case the spec calls out as the
  motivation for this construct, since without it a physical model like a
  reaction-yield curve would force the author to wrap unrelated params in a
  sham custom type just to get a scalar function into an expression.
  ``fn`` is called with exactly the operand *values*, never the config —
  the reference set is exactly the operands' own references, which is what
  keeps `dependency_graph` trustworthy.
- A ``ds.ResolutionError`` from a non-scalar ``returns=`` (error row 30).

Run it:  ``uv run python examples/05_flow_chemistry.py``

See ``examples/README.md`` for the full feature -> example index.
"""

from __future__ import annotations

import designspace as ds

REAGENTS = ("acid", "base", "catalyst", "solvent")
REAGENT_COST_USD_PER_L = {"acid": 3.0, "base": 1.5, "catalyst": 12.0, "solvent": 0.5}
STEPS = ("charge", "heat", "quench", "wash")


def _yield_fraction(temp_c: float, residence_min: float) -> float:
    """A toy first-order conversion model: yield rises with time at
    temperature, saturating exponentially. Ordinary Python — no ``Expr`` in
    sight — which is exactly what ``ds.value`` exists to admit."""
    rate = residence_min * temp_c / 500.0
    return 1.0 - pow(2.718281828, -rate)


def build_space() -> ds.Space:
    return (
        ds.space(
            # Independent inclusion probabilities (not normalized weights):
            # catalyst is included half the time, absent the rest.
            ds.param("reagents").subset(REAGENTS, min_size=1).prior(weights=[0.9, 0.5, 0.2, 0.8]),
            ds.param("order").permutation(STEPS),
            ds.param("temp_c").real(20.0, 200.0),
            ds.param("residence_min").real(1.0, 60.0).log_scale(),
            ds.param("recycle").bool(),
            ds.param("recycle_ratio").real(0.05, 0.8).when(ds.param("recycle")),
            ds.param("mode").categorical("batch", "flow", "semi-batch"),
        )
        # Ordering law: you must charge the reactor before heating it.
        # `.position_of()` returns the item's index in the sampled order.
        .require(
            ds.param("order").position_of("charge") < ds.param("order").position_of("heat"),
        )
        # Feasibility: catalyst chemistry above 150C runs away. `.contains()`
        # tests subset membership directly.
        .forbid(
            ds.param("reagents").contains("catalyst") & (ds.param("temp_c") > 150.0),
        )
        # A hard cost cap: `.sum_over()` looks up each *included* item in the
        # mapping and sums; an included item absent from the mapping would
        # contribute 0 (none are, here).
        .require(
            ds.param("reagents").sum_over(REAGENT_COST_USD_PER_L) <= 15.0,
        )
        # `ds.all_` folds a variadic AND — a lean-process preference: few
        # reagents, and a mode that supports continuous operation.
        .encourage(
            ds.all_(
                ds.param("reagents").size() <= 3,
                ds.param("mode").is_in("flow", "semi-batch"),
            ),
            tags=("lean-process",),
        )
        # `.implies()`: recycling only ever makes sense at a bounded ratio.
        .require(
            ds.param("recycle").implies(ds.param("recycle_ratio") < 0.5),
        )
        # `ds.count(...)`: how many of these three "run it hot" signals are
        # active at once, capped at two.
        .encourage(
            ds.count(
                ds.param("recycle"),
                ds.param("temp_c") > 120.0,
                ds.param("reagents").contains("catalyst"),
            )
            <= 2,
            tags=("intensity-cap",),
        )
        # The physical model: a real function of two ordinary reals, opaque
        # to the expression language, still usable in a `.require()` with a
        # real margin (`returns=float`).
        .require(
            ds.value(_yield_fraction, ds.param("temp_c"), ds.param("residence_min"), returns=float)
            >= 0.2,
        )
        # `.if_inactive(0.0)` vs. the bare param, on the identical aggregate:
        # the guarded form stays applicable even when recycling is off; the
        # unguarded one goes Unknown there and is silently accepted (Kleene
        # rule 4) -- see the applicability readout in `main()`.
        .encourage(
            ds.param("recycle_ratio") + ds.param("temp_c") / 1000.0 <= 0.5,
            tags=("thermal-budget-unguarded",),
        )
        .encourage(
            ds.param("recycle_ratio").if_inactive(0.0) + ds.param("temp_c") / 1000.0 <= 0.5,
            tags=("thermal-budget-guarded",),
        )
        # `.is_active()` is total -- always True/False, never Unknown -- so
        # it is safe to use even where the param it names might be absent.
        .encourage(
            ds.param("recycle_ratio").is_active(),
            tags=("prefers-recycle",),
        )
    )


def main() -> None:
    space = build_space()
    print(
        f"Flow Chemistry space: {space.n_params} parameters, conditional={space.is_conditional}\n"
    )

    config = space.sample_one(seed=0)
    print("A sampled configuration:")
    for key, val in config.items():
        print(f"  {key:16} = {val!r}")
    print(f"\nis_feasible: {space.is_feasible(config)}")

    print("\nAll constraints on that config (kind, tags, applicable, satisfied):")
    for ce in space.evaluate_constraints(config):
        c = ce.constraint
        tag = ", ".join(sorted(c.tags)) or "-"
        margin = f"{ce.margin:+.4f}" if ce.margin is not None else "  n/a "
        print(
            f"  {c.kind:10}[{tag:28}] applicable={ce.applicable!s:5} "
            f"satisfied={ce.satisfied!s:5} margin={margin}"
        )

    # Rule 4 in the flesh: the unguarded thermal-budget constraint is
    # inapplicable (and therefore silently accepted) on every draw where
    # recycling is off; the `.if_inactive()`-guarded twin stays applicable
    # throughout, because it substitutes 0.0 rather than going Unknown.
    print("\nUnguarded vs. guarded aggregate, across 200 draws with recycle=False:")
    off_configs = [c for c in space.sample_dicts(400, seed=2) if not c["recycle"]][:200]
    unguarded_applicable = sum(
        1
        for c in off_configs
        for ce in space.evaluate_constraints(c)
        if "thermal-budget-unguarded" in ce.constraint.tags and ce.applicable
    )
    guarded_applicable = sum(
        1
        for c in off_configs
        for ce in space.evaluate_constraints(c)
        if "thermal-budget-guarded" in ce.constraint.tags and ce.applicable
    )
    print(
        f"  unguarded applicable: {unguarded_applicable}/{len(off_configs)} "
        "(Unknown-swallowed the rest)"
    )
    print(
        f"  guarded   applicable: {guarded_applicable}/{len(off_configs)} "
        "(the `.if_inactive(0.0)` fallback keeps it evaluable)"
    )

    # ds.value's construction-time guard: a non-scalar `returns=` is a
    # row-30 ResolutionError, caught here rather than left to resolution.
    print("\nds.value(..., returns=list) misuse:")
    try:
        ds.value(_yield_fraction, ds.param("temp_c"), ds.param("residence_min"), returns=list)
    except ds.ResolutionError as e:
        print(f"  ResolutionError: {e}")


if __name__ == "__main__":
    main()

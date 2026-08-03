"""Example 7 — Solver Portfolio: a space in aggregate.

The first six examples look at *one* config at a time. This one looks at
the space as a whole: what a batch of draws tells you before you trust it,
and what the introspection surface reports without drawing anything at all.
Domain: a solver portfolio — which backends to run, in what mode, with an
optional warm start.

Concepts introduced here
-------------------------
- ``space.sample(n) -> pl.DataFrame`` (M10, needs the ``polars`` extra —
  ``sample_dicts``/``sample_one`` need no extra and are unaffected): the
  dtype table in the flesh — ``Boolean``, ``Float64``, ``Int64``, a
  ``Utf8`` discriminator plus one nullable ``Struct`` per parameterized
  choice variant, ``Array(dtype, n)`` for a *static*-count scalar lift vs.
  ``List(dtype)`` for a *dynamic*-count one, and null for every inactive
  cell (the dict-config "absent" convention has no columnar analogue).
  Struct-lift and lifted-choice DataFrame columns follow the identical
  per-level rule; see ``examples/06_thermal_controller.py`` for that shape
  and ``API.md``, "Config Representation" for the full table.
- ``sample(reject_soft=True)`` — additionally rejects declared
  (``.encourage()``/``.discourage()``) violations, off by default.
- **``sampling_report()``** (M10.6): drawn from the *unconditioned* measure
  (before rejection), so both pathologies `sample()`'s output hides stay
  visible — an unguarded optional aggregate's low ``applicable`` (Unknown-
  swallowing, Kleene rule 4) next to its ``.if_inactive()``-guarded twin at
  ``applicable == 1.0``, and ``tighten_bounds`` on vs. off (D-74).
  ``ConstraintReport.satisfied`` is a raw fraction, not polarity-resolved
  the way ``ConstraintEval.violated`` is (examples 2-4) —
  ``violation_rate`` (M10.10) is the aggregate analog, printed alongside
  ``constraint.kind`` so a ``forbid``'s low ``satisfied`` (bad-state
  fraction) isn't misread against an ``encourage``'s high one (good-state
  fraction).
- ``ds.config_diff(a, b, space)`` / ``ParamDiff`` across two draws.
- The plain introspection block: ``dependency_graph``, ``topological_order``,
  ``param_constraints``, ``param_conditions``, ``is_finite``,
  ``cardinality()``, ``has_complete_defaults``, and ``apply_defaults`` on a
  no-default static-count lift (left implicit, per the Defaults cascade;
  M10.9 fixed a crash here — see ``PLAN.md``).
- ``fingerprint(scope="sampling")`` vs. ``"full"``: a change that only
  touches identity-level bookkeeping (here, ``.meta()``) moves one and not
  the other.

Run it:  ``uv run python examples/07_portfolio_observability.py``

See ``examples/README.md`` for the full feature -> example index.
"""

from __future__ import annotations

import designspace as ds

SOLVERS = ("cplex", "gurobi", "heuristic")


def build_space() -> ds.Space:
    return (
        ds.space(
            ds.param("enabled_solvers").subset(SOLVERS, min_size=1),
            ds.param("solver_mode").choice(
                "single",
                ensemble=ds.space(ds.param("n_workers").integer(2, 8)),
            ),
            ds.param("priority").ordinal("low", "normal", "high"),
            ds.param("warm_start").bool(),
            ds.param("warm_start_frac").real(0.05, 0.9).when(ds.param("warm_start")),
            ds.param("time_limit_s").integer(10, 3600),
            # A static-count scalar lift -> DataFrame `Array(Float64, 4)`.
            # No default on it anywhere -- see `apply_defaults` below.
            ds.param("weights").real(-1.0, 1.0).repeat(4),
            ds.param("n_checkpoints").integer(0, 5),
            # A dynamic-count scalar lift -> DataFrame `List(Float64)`.
            ds.param("checkpoints").real(0.0, 1.0).repeat(ds.param("n_checkpoints")),
        )
        # At least one solver must run.
        .forbid(
            ds.count(*(ds.param("enabled_solvers").contains(s) for s in SOLVERS)) < 1,
        )
        # The unguarded/guarded pair on the identical aggregate: this one
        # goes Unknown (and is silently accepted) on every draw where
        # `warm_start` is off.
        .encourage(
            ds.param("warm_start_frac") + ds.param("time_limit_s") / 3600.0 <= 1.0,
            tags=("budget-unguarded",),
        )
        .encourage(
            ds.param("warm_start_frac").if_inactive(0.0) + ds.param("time_limit_s") / 3600.0 <= 1.0,
            tags=("budget-guarded",),
        )
    )


def main() -> None:
    space = build_space()
    print(f"Solver Portfolio space: {space.n_params} parameters\n")

    # -- DataFrame output ------------------------------------------------------
    print("--- DataFrame output (space.sample) ---")
    df = space.sample(6, seed=0)
    print(df)
    print("\nschema:")
    for name, dtype in df.schema.items():
        print(f"  {name:22} {dtype}")

    soft_rejecting = space.sample(6, seed=0, reject_soft=True)
    print(
        f"\nsample(reject_soft=True): {soft_rejecting.height} rows, "
        "every declared (.encourage) violation also rejected"
    )

    # -- Sampling diagnostics ----------------------------------------------------
    print("\n--- sampling_report() ---")
    report = space.sampling_report(n=500, seed=0)
    print(
        f"acceptance_rate: {report.acceptance_rate:.3f}  (fraction of {report.n} "
        "unconditioned draws that would survive rejection)"
    )
    for row in report.constraints:
        tag = ", ".join(sorted(row.constraint.tags)) or "-"
        # `satisfied` is raw: a forbid/discourage names a *bad* state (a
        # high `satisfied` there is unhealthy), a require/encourage/bound a
        # *good* one -- reading a table of mixed verbs by `satisfied` alone
        # means re-deriving that flip by hand per row, which is exactly
        # what tripped this up the first time. `violation_rate` (M10.10) is
        # the polarity-resolved reading -- the aggregate analog of
        # `ConstraintEval.violated` -- so it means "unhealthy fraction" the
        # same way regardless of which verb produced the row.
        print(
            f"  {row.constraint.kind:10}[{tag:20}] applicable={row.applicable:.3f} "
            f"satisfied={row.satisfied:.3f} violation_rate={row.violation_rate:.3f}"
        )
    print(
        "\nUnknown-swallowing: the unguarded budget constraint is inapplicable "
        "whenever warm_start is off; its .if_inactive()-guarded twin stays "
        "applicable throughout -- same space, same draws, only the guard differs."
    )
    print(
        f"activity['warm_start_frac']: {report.activity['warm_start_frac']:.3f}  "
        "(the fraction of draws where warm_start was on)"
    )

    tightened = space.sampling_report(n=500, seed=0, tighten_bounds=True)
    print(f"\ntighten_bounds=False (default) acceptance_rate: {report.acceptance_rate:.3f}")
    print(f"tighten_bounds=True            acceptance_rate: {tightened.acceptance_rate:.3f}")
    print(
        "(off by default (D-74): this space has no bound-origin coupling to tighten, "
        "so the two agree here; tighten_bounds only ever matters when one exists.)"
    )

    # -- config_diff --------------------------------------------------------------
    print("\n--- ds.config_diff ---")
    a = space.sample_one(seed=0)
    b = space.sample_one(seed=1)
    for d in ds.config_diff(a, b, space)[:6]:
        print(f"  {d.param:24} {d.old!r} -> {d.new!r}")
    print(f"  ... {max(0, len(ds.config_diff(a, b, space)) - 6)} more")

    # -- Introspection --------------------------------------------------------
    print("\n--- Introspection ---")
    print(f"dependency_graph['warm_start_frac']: {space.dependency_graph['warm_start_frac']}")
    print(f"topological_order[:5]: {space.topological_order[:5]}")
    print(
        f"param_constraints('warm_start_frac'): "
        f"{len(space.param_constraints('warm_start_frac'))} constraint(s) reference it"
    )
    print(
        f"param_conditions('warm_start_frac'): "
        f"{len(space.param_conditions('warm_start_frac'))} condition(s) (its own .when, "
        "plus any that merely reference it)"
    )
    print(f"is_finite: {space.is_finite}  (an unquantized real makes it so)")
    print(f"cardinality(): {space.cardinality()!r}")
    print(f"has_complete_defaults: {space.has_complete_defaults}")

    # `weights` has no default anywhere, including no default on its own
    # static-count lift -- per the Defaults cascade it is left implicit
    # entirely (`apply_defaults` "emits only default values"), matching a
    # dynamic-count lift with the same no-defaults shape, not treated as an
    # error just because its count happens to be a literal (M10.9).
    print(f"apply_defaults({{}}): {space.apply_defaults({})}")

    # -- fingerprint scopes -----------------------------------------------------
    print("\n--- fingerprint(scope=...) ---")
    tagged = space.meta(experiment="portfolio-v2")  # identity-level, not sampling-level
    print(
        f"sampling-scope equal after .meta(): "
        f"{space.fingerprint(scope='sampling') == tagged.fingerprint(scope='sampling')}"
    )
    print(
        f"full-scope equal after .meta():     "
        f"{space.fingerprint(scope='full') == tagged.fingerprint(scope='full')}"
    )


if __name__ == "__main__":
    main()

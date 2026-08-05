"""Solver portfolio: a space in aggregate.

The first six examples look at *one* config at a time. This one looks at the
space as a whole: what a batch of draws reports before the space is trusted,
and what the introspection surface reports without drawing anything at all.
The domain is a solver portfolio, covering which backends to run, in what mode,
and with an optional warm start.

Concepts introduced
-------------------
- ``space.sample(n) -> pl.DataFrame``, which needs the ``polars`` extra.
  ``sample_dicts`` and ``sample_one`` need no extra and are unaffected. The
  dtype table appears here in the flesh: ``Boolean``, ``Float64``, ``Int64``, a
  ``Utf8`` discriminator plus one nullable ``Struct`` per parameterized choice
  variant, ``Array(dtype, n)`` for a *static*-count scalar lift against
  ``List(dtype)`` for a *dynamic*-count one, and null for every inactive cell,
  since the dict-config "absent" convention has no columnar analogue.
  Struct-lift and lifted-choice columns follow the identical per-level rule;
  see ``examples/06_thermal_controller.py`` for that shape and ``API.md``,
  "Config Representation", for the full table.
- ``sample(reject_soft=True)``, which additionally rejects declared
  ``.encourage()`` and ``.discourage()`` violations. It is off by default.
- **``sampling_report()``**, drawn from the *unconditioned* measure before
  rejection, so both pathologies that ``sample()``'s output hides stay visible.
  An unguarded optional aggregate's low ``applicable``, from Unknown-swallowing
  under Kleene rule 4, sits next to its ``.if_inactive()``-guarded twin at
  ``applicable == 1.0``, and ``tighten_bounds`` is shown on and off (D-74).
  ``ConstraintReport.satisfied`` is a raw fraction and is not polarity-resolved
  the way ``ConstraintEval.violated`` is in examples 02 to 04.
  ``violation_rate`` is the aggregate analogue, printed alongside
  ``constraint.kind`` so that a ``forbid``'s low ``satisfied``, a bad-state
  fraction, is not misread against an ``encourage``'s high one, a good-state
  fraction.
- ``ds.config_diff(a, b, space)`` and ``ParamDiff`` across two draws.
- The plain introspection block: ``dependency_graph``, ``topological_order``,
  ``param_constraints``, ``param_conditions``, ``is_finite``,
  ``cardinality()``, ``has_complete_defaults``, and ``apply_defaults`` on a
  no-default static-count lift, which the Defaults cascade leaves implicit.
- ``fingerprint(scope="sampling")`` against ``"full"``. A change touching only
  identity-level bookkeeping, here ``.meta()``, moves one and not the other.

Run with ``uv run python examples/07_portfolio_observability.py``.
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
            # A static-count scalar lift, giving a DataFrame `Array(Float64,
            # 4)`. It carries no default anywhere; see `show_introspection`.
            ds.param("weights").real(-1.0, 1.0).repeat(4),
            ds.param("n_checkpoints").integer(0, 5),
            # A dynamic-count scalar lift, giving a DataFrame `List(Float64)`.
            ds.param("checkpoints").real(0.0, 1.0).repeat(ds.param("n_checkpoints")),
        )
        # At least one solver must run.
        .forbid(
            ds.count(*(ds.param("enabled_solvers").contains(s) for s in SOLVERS)) < 1,
        )
        # The unguarded and guarded pair on the identical aggregate. This one
        # goes Unknown, and is therefore silently accepted, on every draw where
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


def show_summary(space: ds.Space) -> None:
    print(f"Solver portfolio space: {space.n_params} parameters\n")


def show_dataframe(space: ds.Space) -> None:
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


def show_sampling_report(space: ds.Space) -> None:
    print("\n--- sampling_report() ---")
    report = space.sampling_report(n=500, seed=0)
    print(
        f"acceptance_rate: {report.acceptance_rate:.3f}  (fraction of {report.n} "
        "unconditioned draws that would survive rejection)"
    )
    for row in report.constraints:
        tag = ", ".join(sorted(row.constraint.tags)) or "-"
        # `satisfied` is raw. A forbid or discourage names a *bad* state, where
        # a high `satisfied` is unhealthy; a require, encourage or bound names a
        # *good* one. Reading a table of mixed verbs by `satisfied` alone means
        # re-deriving that flip by hand for every row. `violation_rate` is the
        # polarity-resolved reading, the aggregate analogue of
        # `ConstraintEval.violated`, and means "unhealthy fraction" regardless
        # of which verb produced the row.
        print(
            f"  {row.constraint.kind:10}[{tag:20}] applicable={row.applicable:.3f} "
            f"satisfied={row.satisfied:.3f} violation_rate={row.violation_rate:.3f}"
        )
    print(
        "\nUnknown-swallowing: the unguarded budget constraint is inapplicable "
        "whenever warm_start is off, while its .if_inactive()-guarded twin stays "
        "applicable throughout. Same space, same draws, only the guard differs."
    )
    print(
        f"activity['warm_start_frac']: {report.activity['warm_start_frac']:.3f}  "
        "(the fraction of draws where warm_start was on)"
    )

    tightened = space.sampling_report(n=500, seed=0, tighten_bounds=True)
    print(f"\ntighten_bounds=False (default) acceptance_rate: {report.acceptance_rate:.3f}")
    print(f"tighten_bounds=True            acceptance_rate: {tightened.acceptance_rate:.3f}")
    print(
        "(Off by default, per D-74. This space has no bound-origin coupling to "
        "tighten, so the two agree here; tighten_bounds matters only where one exists.)"
    )


def show_config_diff(space: ds.Space) -> None:
    print("\n--- ds.config_diff ---")
    a = space.sample_one(seed=0)
    b = space.sample_one(seed=1)
    diffs = ds.config_diff(a, b, space)
    for d in diffs[:6]:
        print(f"  {d.param:24} {d.old!r} -> {d.new!r}")
    print(f"  ... {max(0, len(diffs) - 6)} more")


def show_introspection(space: ds.Space) -> None:
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

    # `weights` has no default anywhere, including on its own static-count
    # lift. The Defaults cascade leaves it implicit entirely, since
    # `apply_defaults` emits only default values. That matches a dynamic-count
    # lift with the same no-defaults shape, and is not an error just because
    # this count happens to be a literal.
    print(f"apply_defaults({{}}): {space.apply_defaults({})}")


def show_fingerprint_scopes(space: ds.Space) -> None:
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


def main() -> None:
    space = build_space()
    show_summary(space)
    show_dataframe(space)
    show_sampling_report(space)
    show_config_diff(space)
    show_introspection(space)
    show_fingerprint_scopes(space)


if __name__ == "__main__":
    main()

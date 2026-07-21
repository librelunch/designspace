"""Example 3 — Memetic Algorithm: variable-length pipelines and aggregates.

The most expressive shape: the configuration is not a fixed record but a
*sequence of operators of runtime-determined length*, plus a schedule that is
itself a small vector. A Memetic Algorithm interleaves evolutionary operators
with local-search refinement; here we search over the operator pipeline itself.

Concepts introduced here
------------------------
- The lift: ``.repeat(count)`` turns an element definition into a list. The
  count may reference another parameter (``ds.param("n_ops")``), giving a
  *variable-length* list whose length is part of the config.
- A **lifted choice** — a heterogeneous list whose elements are different
  operator variants (bare strings and parameterized dicts side by side).
- A ``.subset(...)`` payload inside a variant: an unordered set of neighborhoods.
- Vector aggregates over a lift: ``.count_of(...)`` (in a feasibility
  ``forbid``) and ``.is_sorted(...)`` / ``.sum()`` over a scalar lift.
- The constraint quartet — hard ``forbid``/``require`` (feasibility) and soft
  ``encourage``/``discourage`` (declared, reported, never enforced) — read back
  polarity-agnostically via ``constraint.kind`` and ``ConstraintEval.violated``.
- Batch sampling with ``sample_dicts`` and a ``flatten`` / ``unflatten``
  round-trip on a nested config.

Run it:  ``uv run python examples/03_memetic_algorithm.py``
"""

from __future__ import annotations

import designspace as ds

MIN_OPS = 2
MAX_OPS = 6
RESTART_STAGES = 3


def build_space() -> ds.Space:
    # One element of the pipeline: a choice among operators. `shuffle` is a
    # bare (parameterless) variant; the rest carry their own sub-space. The
    # local_search variant even nests a subset of neighborhoods to explore.
    pipeline_op = ds.param("pipeline").choice(
        "shuffle",
        crossover=ds.space(ds.param("swap_p").real(0.05, 0.5)),
        mutation=ds.space(ds.param("rate").real(0.01, 0.5)),
        local_search=ds.space(
            ds.param("iters").integer(1, 100),
            ds.param("neighborhoods").subset(("swap", "insert", "2opt"), min_size=1),
        ),
    )

    return (
        ds.space(
            # How many operators the pipeline has this run. The list length is
            # itself a searched parameter.
            ds.param("n_ops").integer(MIN_OPS, MAX_OPS),
            # The pipeline: `n_ops` operators drawn from the choice above. The
            # count references `n_ops`, so it joins the dependency graph and is
            # assigned first.
            pipeline_op.repeat(ds.param("n_ops")),
            ds.param("population_size").integer(10, 200).quantized(step=10),
            # A restart schedule: three decreasing "intensities" (a scalar
            # lift of fixed length). Log-scaled because they span decades.
            ds.param("restart_intensity")
            .real(0.01, 5.0)
            .log_scale()
            .repeat(RESTART_STAGES),
        )
        # Feasibility: a *memetic* algorithm is evolution + local search, so a
        # pipeline with no local_search step is not a memetic algorithm at all.
        # `count_of` over the lifted choice counts matching variants.
        .forbid(
            ds.param("pipeline").count_of("local_search") < 1,
        )
        # Declared, *bad*-state polarity: discourage a mutation-heavy pipeline.
        # `discourage(e)` names the undesirable state (the soft sibling of
        # `forbid`); it is reported with a margin but never affects feasibility.
        .discourage(
            ds.param("pipeline").count_of("mutation") > 2,
            tags=("diversity-cap",),
        )
        # Declared, *good*-state polarity: encourage restart intensities that
        # decrease across stages (a cooling schedule). `encourage(e)` names the
        # desired state (the soft sibling of `require`); `is_sorted` is boolean,
        # so its margin is None.
        .encourage(
            ds.param("restart_intensity").is_sorted(descending=True),
            tags=("annealing-schedule",),
        )
    )


def main() -> None:
    space = build_space()
    print(f"Memetic Algorithm space: {space.n_params} parameters, "
          f"conditional={space.is_conditional}\n")

    # Batch sampling. Every config below is feasible by construction: the
    # sampler rejects any pipeline lacking a local_search step (the forbid).
    configs = space.sample_dicts(500, seed=0)
    lengths = [len(c["pipeline"]) for c in configs]
    with_local = sum(
        any(isinstance(op, dict) and "local_search" in op for op in c["pipeline"])
        for c in configs
    )
    print(f"Sampled {len(configs)} configs:")
    print(f"  pipeline length: min={min(lengths)}, max={max(lengths)}, "
          f"mean={sum(lengths) / len(lengths):.2f}")
    print(f"  configs with >=1 local_search step: {with_local}/{len(configs)} "
          f"(the forbid guarantees 100%)")

    # Show one concrete pipeline in full.
    cfg = configs[0]
    print("\nOne sampled pipeline:")
    print(f"  n_ops = {cfg['n_ops']}, population_size = {cfg['population_size']}")
    for i, op in enumerate(cfg["pipeline"]):
        print(f"  [{i}] {op!r}")
    print(f"  restart_intensity = {cfg['restart_intensity']}")

    # A nested config round-trips through the flat, path-keyed representation.
    flat = ds.flatten(cfg, space)
    restored = ds.unflatten(flat, space)
    print("\nflatten / unflatten round-trip:")
    print(f"  flat keys: {list(flat)[:4]} ... ({len(flat)} total)")
    print(f"  unflatten(flatten(cfg)) == cfg: {restored == cfg}")

    # Constraints on that config, read through the polarity-aware accessors so
    # the display is correct regardless of the verb. `constraint.kind` labels it
    # ("forbid"/"require"/"encourage"/"discourage") and `ce.violated` folds in
    # each verb's polarity — a forbid/discourage names a *bad* state (violated
    # when satisfied), a require/encourage a *good* one — so you never re-derive
    # it from `satisfied` by hand. Swap any .forbid<->.require or
    # .encourage<->.discourage above (flipping the condition) and this block
    # still reads right.
    print("\nConstraints on the sampled config:")
    for ce in space.evaluate_constraints(cfg):
        c = ce.constraint
        tag = ", ".join(sorted(c.tags)) or "-"
        if c.hard:  # forbid / require -> feasibility
            if not ce.applicable:
                verdict = "inapplicable (Unknown)"
            else:
                verdict = "TRIPPED  -> infeasible" if ce.violated else "clear    -> feasible"
            print(f"  {c.kind:10}[{tag:18}] {verdict}")
        else:  # encourage / discourage -> reported, never enforced
            margin = f"{ce.margin:+.2f}" if ce.margin is not None else " n/a"
            flag = "flagged" if ce.violated else "ok     "
            print(f"  {c.kind:10}[{tag:18}] {flag} satisfied={ce.satisfied!s:5} margin={margin}")

    # And a hand-written infeasible one: a pipeline of only evolutionary ops.
    print("\nA pipeline with no local_search step:")
    bad = {
        "n_ops": 2,
        "pipeline": ["shuffle", {"mutation": {"rate": 0.1}}],
        "population_size": 50,
        "restart_intensity": [3.0, 1.0, 0.1],
    }
    print(f"  is_feasible: {space.is_feasible(bad)}")
    for reason in space.infeasibility_reasons(bad):
        print(f"  reason: {reason}")


if __name__ == "__main__":
    main()

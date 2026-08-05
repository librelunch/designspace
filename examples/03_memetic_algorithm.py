"""Memetic algorithm: variable-length pipelines and aggregates.

The most expressive shape a space takes: the configuration is not a fixed
record but a *sequence of operators of runtime-determined length*, plus a
schedule that is itself a small vector. A memetic algorithm interleaves
evolutionary operators with local-search refinement, and the space below
searches over the operator pipeline itself.

Concepts introduced
-------------------
- The lift. ``.repeat(count)`` turns an element definition into a list. The
  count may reference another parameter (``ds.param("n_ops")``), giving a
  *variable-length* list whose length is part of the config.
- A **lifted choice**: a heterogeneous list whose elements are different
  operator variants, bare strings and parameterized dicts side by side.
- A ``.subset(...)`` payload inside a variant, holding an unordered set of
  neighborhoods.
- Vector aggregates over a lift: ``.count_of(...)`` in a feasibility
  ``forbid``, plus ``.is_sorted(...)``, ``.length()``, ``.distinct()``,
  ``.sum()``, ``.min()`` and ``.max()`` over a scalar lift.
- Negative instance indexing (``restart_intensity[-1]``), resolved against the
  lift's realized length.
- The constraint quartet, hard ``forbid``/``require`` for feasibility and soft
  ``encourage``/``discourage`` for declared reporting, read back
  polarity-agnostically via ``constraint.kind`` and ``ConstraintEval.violated``.
- Batch sampling with ``sample_dicts``, and a ``flatten``/``unflatten``
  round-trip on a nested config.
- ``.map_params(fn)``, which rewrites every ``ParamDef`` in the space through a
  function. The transformation reaches parameters wherever they live, including
  inside a lifted choice's variant payloads.
- ``.without_constraints(tags=...)``, which drops declared constraints by tag.

Run with ``uv run python examples/03_memetic_algorithm.py``.
"""

from __future__ import annotations

from dataclasses import replace

import designspace as ds
from designspace.ir import ParamDef, QuantizedSpec, RealDomain

MIN_OPS = 2
MAX_OPS = 6
RESTART_STAGES = 3


def build_space() -> ds.Space:
    # One element of the pipeline: a choice among operators. `shuffle` is a
    # bare (parameterless) variant; the rest carry their own sub-space. The
    # local_search variant nests a subset of neighborhoods to explore.
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
            # A restart schedule: three decreasing "intensities", a scalar
            # lift of fixed length. Log-scaled because they span decades.
            ds.param("restart_intensity").real(0.01, 5.0).log_scale().repeat(RESTART_STAGES),
        )
        # Feasibility: a *memetic* algorithm is evolution plus local search, so
        # a pipeline with no local_search step is not a memetic algorithm at
        # all. `count_of` over the lifted choice counts matching variants.
        .forbid(
            ds.param("pipeline").count_of("local_search") < 1,
        )
        # Declared, *bad*-state polarity: discourage a mutation-heavy pipeline.
        # `discourage(e)` names the undesirable state, as the soft sibling of
        # `forbid`. It is reported with a margin and never affects feasibility.
        .discourage(
            ds.param("pipeline").count_of("mutation") > 2,
            tags=("diversity-cap",),
        )
        # Declared, *good*-state polarity: encourage restart intensities that
        # decrease across stages, giving a cooling schedule. `encourage(e)`
        # names the desired state, as the soft sibling of `require`.
        # `is_sorted` is boolean, so its margin is None.
        .encourage(
            ds.param("restart_intensity").is_sorted(descending=True),
            tags=("annealing-schedule",),
        )
        # `.length()` and `.distinct()`: the schedule has exactly
        # RESTART_STAGES entries, which is trivially true for this static-count
        # lift and applies the same way to a dynamic one, and no two stages
        # repeat the same intensity.
        .require(
            (ds.param("restart_intensity").length() == RESTART_STAGES)
            & ds.param("restart_intensity").distinct(),
        )
        # `.min()` and `.max()`: keep the whole schedule inside a sane range.
        .encourage(
            (ds.param("restart_intensity").max() <= 4.5)
            & (ds.param("restart_intensity").min() >= 0.02),
            tags=("intensity-range",),
        )
        # `.sum()`: a soft budget on total restart intensity across stages.
        .encourage(
            ds.param("restart_intensity").sum() <= 8.0,
            tags=("intensity-budget",),
        )
        # Negative instance indexing. `[-1]` resolves against the realized
        # length, and the last stage should land gently.
        .encourage(
            ds.param("restart_intensity[-1]") <= 0.5,
            tags=("gentle-finish",),
        )
    )


def show_summary(space: ds.Space) -> None:
    print(
        f"Memetic algorithm space: {space.n_params} parameters, "
        f"conditional={space.is_conditional}\n"
    )


def show_batch_sampling(space: ds.Space) -> None:
    # Batch sampling. Every config below is feasible by construction: the
    # sampler rejects any pipeline lacking a local_search step, per the forbid.
    configs = space.sample_dicts(500, seed=0)
    lengths = [len(c["pipeline"]) for c in configs]
    with_local = sum(
        any(isinstance(op, dict) and "local_search" in op for op in c["pipeline"]) for c in configs
    )
    print(f"Sampled {len(configs)} configs:")
    print(
        f"  pipeline length: min={min(lengths)}, max={max(lengths)}, "
        f"mean={sum(lengths) / len(lengths):.2f}"
    )
    print(
        f"  configs with >=1 local_search step: {with_local}/{len(configs)} "
        f"(the forbid guarantees 100%)"
    )


def show_one_pipeline(space: ds.Space) -> None:
    # One concrete pipeline in full, then a round-trip through the flat,
    # path-keyed representation.
    cfg = space.sample_one(seed=0)
    print("\nOne sampled pipeline:")
    print(f"  n_ops = {cfg['n_ops']}, population_size = {cfg['population_size']}")
    for i, op in enumerate(cfg["pipeline"]):
        print(f"  [{i}] {op!r}")
    print(f"  restart_intensity = {cfg['restart_intensity']}")

    flat = ds.flatten(cfg, space)
    restored = ds.unflatten(flat, space)
    print("\nflatten / unflatten round-trip:")
    print(f"  flat keys: {list(flat)[:4]} ... ({len(flat)} total)")
    print(f"  unflatten(flatten(cfg)) == cfg: {restored == cfg}")


def show_constraint_polarity(space: ds.Space) -> None:
    # Constraints on a sampled config, read through the polarity-aware
    # accessors so the display is correct at either verb. `constraint.kind`
    # labels it ("forbid", "require", "encourage", "discourage") and
    # `ce.violated` folds in each verb's polarity: a forbid or discourage names
    # a *bad* state and is violated when satisfied, a require or encourage names
    # a *good* one. Nothing here re-derives polarity from `satisfied` by hand,
    # so swapping any .forbid for .require, or .encourage for .discourage, and
    # flipping the condition leaves this block correct.
    cfg = space.sample_one(seed=0)
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


def show_infeasible_pipeline(space: ds.Space) -> None:
    # A hand-written infeasible config: a pipeline of only evolutionary ops.
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


def show_map_params(space: ds.Space) -> None:
    # A follow-up sweep only needs coarse precision. `.map_params()` rewrites
    # every ParamDef through `fn`, reaching a real parameter wherever it lives,
    # including inside a lifted choice's variant payloads (`swap_p`, `rate`),
    # without needing to know each one's path in advance.
    def coarsen(pd: ParamDef) -> ParamDef:
        if isinstance(pd.domain, RealDomain) and pd.quantized is None:
            return replace(pd, quantized=QuantizedSpec(step=0.05, factor=None, include_hi=False))
        return pd

    coarsened = space.map_params(coarsen)
    newly_coarsened = [
        p
        for p, pd in coarsened.params.items()
        if space.params[p].quantized is None and pd.quantized is not None
    ]
    print(
        f"\nmap_params(coarsen): {len(newly_coarsened)} previously-unquantized real param(s) "
        f"now on a 0.05 grid: {newly_coarsened}"
    )


def show_without_constraints(space: ds.Space) -> None:
    # The diversity cap was a suggestion for early exploration. A later,
    # focused run drops it and reports fewer declared constraints.
    relaxed = space.without_constraints(tags=("diversity-cap",))
    print(
        f"\nwithout_constraints(tags=('diversity-cap',)): "
        f"{len(relaxed.constraints)} constraint(s), was {len(space.constraints)}"
    )


def main() -> None:
    space = build_space()
    show_summary(space)
    show_batch_sampling(space)
    show_one_pipeline(space)
    show_constraint_polarity(space)
    show_infeasible_pipeline(space)
    print("\n--- Structural operations ---")
    show_map_params(space)
    show_without_constraints(space)


if __name__ == "__main__":
    main()

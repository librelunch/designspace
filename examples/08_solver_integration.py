"""Example 8 — Pump Configurator: handing a space to a consumer.

The first seven examples build and inspect spaces. This one is about what a
*consumer* does with one: a solver walking a config together one field at a
time, a positional vector in and out, and rebuilding a space from its own
resolved IR. Domain: a pump configurator with a bound-origin coupling
(impeller diameter tracks the flow rate that was actually assigned).

Concepts introduced here
-------------------------
- The **full partial-config surface**: ``evaluate_partial`` (``param_status``,
  ``evaluable_constraints``, ``pending_constraints``, ``n_remaining``),
  ``param_activity``'s three values, ``remaining_domain``'s five descriptor
  kinds (``RealRemaining`` / ``IntegerRemaining`` / ``ValueRemaining`` /
  ``SubsetRemaining`` / ``PermutationRemaining``), the ``next_assignable``
  -> ``missing_params`` -> ``is_complete`` driver loop, and
  ``validate_param(path, value, context=...)``.
- **``coordinate_paths()``** (M10.7): pack a config into a positional vector
  and back via ``flatten``/``unflatten`` on a fixed-layout space, then a
  caught ``ds.ResolutionError`` (row 33) on a conditional space — deriving
  "which flat keys are coordinates, not lift-length bookkeeping" by hand
  fails *silently* (a config that still validates and differs), which is
  exactly what this method exists to avoid.
- **Metaprogramming**: ``ds.param_from_def(pd)`` round-tripping a
  ``ParamDef`` back to a builder expression, walking a constraint's own
  expression tree via the ``.kind``/``.children``/``.params`` triple every
  ``BoolExpr``/``ArithExpr`` exposes, ``ds.space_from_ir(...)``
  reconstructing a fingerprint-equal space, and a registry-driven
  generation loop using ``ds.all_(*prereqs)`` (including its zero-operand
  identity) — the ``compiler_pipeline`` corpus pattern.
- ``.custom(sampler, validator)``, the callback shorthand: generative but
  not serializable — a ``ds.SerializationError`` from ``to_json()``, and
  ``fingerprint(on_unserializable="mark")`` succeeding where the default
  raises.

Run it:  ``uv run python examples/08_solver_integration.py``

See ``examples/README.md`` for the full feature -> example index.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import designspace as ds
from designspace.config import flatten, unflatten

CERTIFICATIONS = ("CE", "UL", "ATEX")
STAGE_ORDER = ("intake", "boost", "discharge")


@dataclass(frozen=True)
class _KernelBandwidth:
    """A minimal non-serializable payload for the `.custom(sampler,
    validator)` shorthand demo -- there is no `describe()`/`type_key` here
    on purpose, since the shorthand carries no structural encoding at all.
    """

    value: float = 0.0


def build_space() -> ds.Space:
    return (
        ds.space(
            ds.param("flow_rate_lpm").real(100.0, 500.0),
            # Expression bound: the impeller can be no larger than whatever
            # flow rate this draw actually assigned.
            ds.param("impeller_diameter_mm").real(20.0, ds.param("flow_rate_lpm")),
            ds.param("num_stages").integer(1, 5),
            ds.param("max_pressure_bar").real(1.0, ds.param("num_stages") * 10.0),
            ds.param("seal_type").categorical("mechanical", "packing", "magnetic"),
            ds.param("certifications").subset(CERTIFICATIONS, min_size=0, max_size=3),
            ds.param("stage_order").permutation(STAGE_ORDER),
            # A literal, unconditional lift -- keeps this a *fixed-layout*
            # space (every count static, no param carries a condition).
            ds.param("vibration_profile").real(0.0, 1.0).repeat(4),
        )
        # Packing seals are discontinued -- a single unset-bare-operand
        # exclusion, fully reducible by `remaining_domain`.
        .forbid(
            ds.param("seal_type") == "packing",
        )
        # Magnetic seals aren't ATEX-rated -- a *compound* coupling across
        # two params, deliberately left unreduced: `remaining_domain` is
        # sound (never excludes a still-feasible value) but not complete,
        # and a conjunction of two bare-operand comparisons isn't the
        # single-unset-operand shape it reduces.
        .forbid(
            (ds.param("seal_type") == "magnetic") & ds.param("certifications").contains("ATEX"),
        )
    )


def main() -> None:
    space = build_space()
    print(f"Pump Configurator space: {space.n_params} parameters\n")

    config = space.sample_one(seed=0)
    flat = flatten(config, space)

    # -- coordinate_paths() -------------------------------------------------------
    print("--- coordinate_paths() ---")
    paths = space.coordinate_paths()
    print(f"  {len(paths)} coordinates: {paths}")
    vector = [flat[p] for p in paths]
    restored = unflatten(dict(zip(paths, vector, strict=True)), space)
    print(f"  positional vector -> unflatten round-trips to the same config: "
          f"{restored == config}")

    print("\n  A hand-rolled filter fails silently -- it can't tell 'x' (a "
          "coordinate) from 'x' being a count-bookkeeping entry without "
          "walking the ListDomain chain, which is exactly what this method "
          "does for you. And it is only defined when the layout doesn't "
          "depend on the config:")
    conditional_space = ds.space(
        ds.param("flag").bool(),
        ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
    )
    try:
        conditional_space.coordinate_paths()
    except ds.ResolutionError as e:
        print(f"  ResolutionError: {e}")

    # -- The partial-config surface --------------------------------------------
    print("\n--- Partial configs ---")
    partial: dict[str, Any] = {}
    print(f"  param_activity({{}}): {space.param_activity(partial)}")
    pe = space.evaluate_partial(partial)
    print(f"  evaluate_partial({{}}): n_remaining={pe.n_remaining}, "
          f"pending_constraints={len(pe.pending_constraints)}")

    print("\n  remaining_domain, one call per descriptor kind:")
    print(f"    flow_rate_lpm                        -> "
          f"{space.remaining_domain('flow_rate_lpm', {})}")
    print(f"    impeller_diameter_mm | flow=300       -> "
          f"{space.remaining_domain('impeller_diameter_mm', {'flow_rate_lpm': 300.0})}")
    print(f"    seal_type                             -> "
          f"{space.remaining_domain('seal_type', {})}")
    print(f"    certifications | seal_type=magnetic   -> "
          f"{space.remaining_domain('certifications', {'seal_type': 'magnetic'})}"
          "   (unreduced -- the compound coupling above, sound not complete)")
    print(f"    stage_order                           -> "
          f"{space.remaining_domain('stage_order', {})}")

    print("\n  validate_param(..., context=...): the bound-origin coupling only "
          "evaluates once flow_rate_lpm is in context --")
    print(f"    impeller=350, no context      -> valid="
          f"{space.validate_param('impeller_diameter_mm', 350.0).valid} "
          "(constraint omitted -- under-determined, not guessed)")
    ctx_result = space.validate_param(
        "impeller_diameter_mm", 350.0, context={"flow_rate_lpm": 300.0}
    )
    print(f"    impeller=350, flow=300 context -> valid={ctx_result.valid}")

    print("\n  Driver loop -- next_assignable -> missing_params -> is_complete, "
          "revealing the sampled config's own values one step at a time:")
    partial = {}
    step = 0
    while not space.is_complete(partial):
        step += 1
        path = space.next_assignable(partial)[0]
        if "[" in path:
            list_path = path[: path.index("[")]
            partial[list_path] = config[list_path]
            print(f"    step {step}: assign {list_path} (all "
                  f"{len(config[list_path])} element(s) at once)")
        else:
            partial[path] = flat[path]
            print(f"    step {step}: assign {path} = {flat[path]!r}")
    print(f"  is_complete: {space.is_complete(partial)}, "
          f"missing_params: {space.missing_params(partial)}")

    # -- Metaprogramming ------------------------------------------------------
    print("\n--- Metaprogramming ---")
    pd = space.params["num_stages"]
    rebuilt_expr = ds.param_from_def(pd)
    print(f"  param_from_def(params['num_stages']) -> {type(rebuilt_expr).__name__}")

    # `BoolExpr`/`ArithExpr` are walkable ASTs (`.kind`, `.children`,
    # `.params`) -- the facility a rewrite tool builds on. Walk the compound
    # "magnetic seals aren't ATEX-rated" forbid one level deep.
    compound = space.constraints[-1].expr
    print(f"  {compound.kind!r} node over {sorted(compound.params)}, "
          f"{len(compound.children)} children:")
    for child in compound.children:
        print(f"    {child.kind!r} node over {sorted(child.params)}")

    rebuilt_space = ds.space_from_ir(space.params, space.conditions, space.constraints)
    print(f"  space_from_ir(...) fingerprint-equal to the original: "
          f"{rebuilt_space.fingerprint() == space.fingerprint()}")

    # A registry-driven generation loop: one bool flag per manufacturing
    # step, `require`d against its own prerequisites via `ds.all_(*prereqs)`
    # -- including the zero-operand identity for a prereq-free step
    # (Degeneracy Table: "ds.all_() | Literal True").
    step_prereqs: dict[str, tuple[str, ...]] = {
        "cast_housing": (),
        "machine_bore": ("cast_housing",),
        "balance_impeller": (),
        "assemble": ("machine_bore", "balance_impeller"),
    }
    flags = {name: ds.param(f"do_{name}").bool() for name in step_prereqs}
    build_order_space = ds.space(*flags.values())
    for name, prereqs in step_prereqs.items():
        build_order_space = build_order_space.require(
            flags[name].implies(ds.all_(*(flags[p] for p in prereqs)))
        )
    print(f"  registry-generated space: {build_order_space.n_params} bool flags, "
          f"{len(build_order_space.constraints)} generated `require`s "
          f"(cast_housing's is `all_()` -> trivially satisfied)")

    # -- .custom(sampler, validator) shorthand --------------------------------
    print("\n--- .custom(sampler, validator) shorthand ---")
    noise_space = ds.space(
        ds.param("kernel_bandwidth").custom(
            sampler=lambda rng: replace(_KernelBandwidth(), value=rng.random()),
            validator=lambda v: isinstance(v, _KernelBandwidth),
        ),
    )
    sampled = noise_space.sample_one(seed=0)
    print(f"  shorthand sample_one(): {sampled}")
    try:
        noise_space.to_json()
    except ds.SerializationError as e:
        print(f"  to_json() raises SerializationError: {e}")
    marked = noise_space.fingerprint(on_unserializable="mark")
    print(f"  fingerprint(on_unserializable='mark') succeeds: {marked[:24]}...")


if __name__ == "__main__":
    main()

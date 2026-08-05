"""Pump configurator: handing a space to a consumer.

The first seven examples build and inspect spaces. This one covers what a
*consumer* does with one: a solver walking a config together one field at a
time, a positional vector in and out, and rebuilding a space from its own
resolved IR. The domain is a pump configurator with a bound-origin coupling,
where impeller diameter tracks the flow rate that was actually assigned.

Concepts introduced
-------------------
- The **full partial-config surface**: ``evaluate_partial`` with
  ``param_status``, ``evaluable_constraints``, ``pending_constraints`` and
  ``n_remaining``; ``param_activity``'s three values; ``remaining_domain``'s
  five descriptor kinds (``RealRemaining``, ``IntegerRemaining``,
  ``ValueRemaining``, ``SubsetRemaining``, ``PermutationRemaining``); the
  ``next_assignable`` to ``missing_params`` to ``is_complete`` driver loop; and
  ``validate_param(path, value, context=...)``.
- **``coordinate_paths()``**, which packs a config into a positional vector and
  back via ``flatten`` and ``unflatten`` on a fixed-layout space, followed by a
  caught ``ds.ResolutionError`` (row 33) on a conditional space. Deriving which
  flat keys are coordinates, as opposed to lift-length bookkeeping, by hand
  fails *silently*, producing a config that still validates and differs. That
  silent failure is what this method exists to avoid.
- **Metaprogramming**: ``ds.param_from_def(pd)`` round-tripping a ``ParamDef``
  back to a builder expression; walking a constraint's own expression tree via
  the ``.kind``/``.children``/``.params`` triple every ``BoolExpr`` and
  ``ArithExpr`` exposes; ``ds.space_from_ir(...)`` reconstructing a
  fingerprint-equal space; and a registry-driven generation loop using
  ``ds.all_(*prereqs)``, including its zero-operand identity. This is the
  ``compiler_pipeline`` corpus pattern.
- ``.custom(sampler, validator)``, the callback shorthand. It is generative but
  not serializable, giving a ``ds.SerializationError`` from ``to_json()`` and a
  ``fingerprint(on_unserializable="mark")`` that succeeds where the default
  raises.

Run with ``uv run python examples/08_solver_integration.py``.
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
    """A minimal non-serializable payload for the ``.custom(sampler,
    validator)`` shorthand.

    It deliberately declares no ``describe()`` and no ``type_key``, because the
    shorthand carries no structural encoding at all.
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
            # A literal, unconditional lift. It keeps this a *fixed-layout*
            # space: every count is static and no parameter carries a condition.
            ds.param("vibration_profile").real(0.0, 1.0).repeat(4),
        )
        # Packing seals are discontinued. This is a single unset-bare-operand
        # exclusion, fully reducible by `remaining_domain`.
        .forbid(
            ds.param("seal_type") == "packing",
        )
        # Magnetic seals are not ATEX-rated. This is a *compound* coupling
        # across two parameters, deliberately left unreduced: `remaining_domain`
        # is sound, meaning it never excludes a still-feasible value, but it is
        # not complete, and a conjunction of two bare-operand comparisons is not
        # the single-unset-operand shape it reduces.
        .forbid(
            (ds.param("seal_type") == "magnetic") & ds.param("certifications").contains("ATEX"),
        )
    )


def show_summary(space: ds.Space) -> None:
    print(f"Pump configurator space: {space.n_params} parameters\n")


def show_coordinate_paths(space: ds.Space) -> None:
    print("--- coordinate_paths() ---")
    config = space.sample_one(seed=0)
    flat = flatten(config, space)

    paths = space.coordinate_paths()
    print(f"  {len(paths)} coordinates: {paths}")
    vector = [flat[p] for p in paths]
    restored = unflatten(dict(zip(paths, vector, strict=True)), space)
    print(f"  positional vector -> unflatten round-trips to the same config: {restored == config}")

    print(
        "\n  A hand-rolled filter fails silently. It cannot tell a coordinate "
        "'x' from an 'x' that is count-bookkeeping without walking the "
        "ListDomain chain, which is what this method does. It is defined only "
        "where the layout does not depend on the config:"
    )
    conditional_space = ds.space(
        ds.param("flag").bool(),
        ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
    )
    try:
        conditional_space.coordinate_paths()
    except ds.ResolutionError as e:
        print(f"  ResolutionError: {e}")


def show_partial_configs(space: ds.Space) -> None:
    print("\n--- Partial configs ---")
    config = space.sample_one(seed=0)
    flat = flatten(config, space)

    partial: dict[str, Any] = {}
    print(f"  param_activity({{}}): {space.param_activity(partial)}")
    pe = space.evaluate_partial(partial)
    print(
        f"  evaluate_partial({{}}): n_remaining={pe.n_remaining}, "
        f"pending_constraints={len(pe.pending_constraints)}"
    )

    print("\n  remaining_domain, one call per descriptor kind:")
    print(
        f"    flow_rate_lpm                        -> {space.remaining_domain('flow_rate_lpm', {})}"
    )
    print(
        f"    impeller_diameter_mm | flow=300       -> "
        f"{space.remaining_domain('impeller_diameter_mm', {'flow_rate_lpm': 300.0})}"
    )
    print(f"    seal_type                             -> {space.remaining_domain('seal_type', {})}")
    print(
        f"    certifications | seal_type=magnetic   -> "
        f"{space.remaining_domain('certifications', {'seal_type': 'magnetic'})}"
        "   (unreduced: the compound coupling above, sound but not complete)"
    )
    print(
        f"    stage_order                           -> {space.remaining_domain('stage_order', {})}"
    )

    print(
        "\n  validate_param(..., context=...): the bound-origin coupling "
        "evaluates only once flow_rate_lpm is in context."
    )
    print(
        f"    impeller=350, no context      -> valid="
        f"{space.validate_param('impeller_diameter_mm', 350.0).valid} "
        "(the constraint is omitted as under-determined, never guessed)"
    )
    ctx_result = space.validate_param(
        "impeller_diameter_mm", 350.0, context={"flow_rate_lpm": 300.0}
    )
    print(f"    impeller=350, flow=300 context -> valid={ctx_result.valid}")

    print(
        "\n  Driver loop, next_assignable to missing_params to is_complete, "
        "revealing the sampled config's own values one step at a time:"
    )
    partial = {}
    step = 0
    while not space.is_complete(partial):
        step += 1
        path = space.next_assignable(partial)[0]
        if "[" in path:
            list_path = path[: path.index("[")]
            partial[list_path] = config[list_path]
            print(
                f"    step {step}: assign {list_path} (all "
                f"{len(config[list_path])} element(s) at once)"
            )
        else:
            partial[path] = flat[path]
            print(f"    step {step}: assign {path} = {flat[path]!r}")
    print(
        f"  is_complete: {space.is_complete(partial)}, "
        f"missing_params: {space.missing_params(partial)}"
    )


def show_metaprogramming(space: ds.Space) -> None:
    print("\n--- Metaprogramming ---")
    pd = space.params["num_stages"]
    rebuilt_expr = ds.param_from_def(pd)
    print(f"  param_from_def(params['num_stages']) -> {type(rebuilt_expr).__name__}")

    # `BoolExpr` and `ArithExpr` are walkable ASTs through `.kind`,
    # `.children` and `.params`, which is the facility a rewrite tool builds
    # on. This walks the compound "magnetic seals are not ATEX-rated" forbid
    # one level deep.
    compound = space.constraints[-1].expr
    print(
        f"  {compound.kind!r} node over {sorted(compound.params)}, "
        f"{len(compound.children)} children:"
    )
    for child in compound.children:
        print(f"    {child.kind!r} node over {sorted(child.params)}")

    rebuilt_space = ds.space_from_ir(space.params, space.conditions, space.constraints)
    print(
        f"  space_from_ir(...) fingerprint-equal to the original: "
        f"{rebuilt_space.fingerprint() == space.fingerprint()}"
    )

    # A registry-driven generation loop: one bool flag per manufacturing step,
    # `require`d against its own prerequisites via `ds.all_(*prereqs)`. A
    # prereq-free step uses the zero-operand identity, per the Degeneracy
    # Table's "ds.all_() | Literal True" row.
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
    print(
        f"  registry-generated space: {build_order_space.n_params} bool flags, "
        f"{len(build_order_space.constraints)} generated `require`s "
        f"(cast_housing's is `all_()`, so it is trivially satisfied)"
    )


def show_custom_shorthand() -> None:
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


def main() -> None:
    space = build_space()
    show_summary(space)
    show_coordinate_paths(space)
    show_partial_configs(space)
    show_metaprogramming(space)
    show_custom_shorthand()


if __name__ == "__main__":
    main()

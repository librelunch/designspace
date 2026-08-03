"""Example 9 — The Representation Layer: a genotype is a Space too.

A NAS-shaped hyperparameter space handed to a solver that only understands
continuous unit coordinates: `space.represent()` builds the *induced* chart
representation — the one representation core ships, derived mechanically
from the charts already on the declaration, never chosen. Then a small
*supplied* morphism, written entirely against the public surface, shows
what the escape hatch looks like when the induced representation isn't the
answer (core ships none of these; DECISIONS.md D-60).

Concepts introduced here
-------------------------
- **`space.represent()`** with no rules: the induced chart representation.
  Touches every param carrying a chart at its own level or at any element
  level of its `ListDomain` chain — a scalar lift's chart lives in
  `ListDomain.element_chart`, not `ParamDef.chart` — while a `.repeat()`
  count (`n_layers`, here) is excluded, reported in `excluded_by_prop`,
  since transport rewrites conditions and constraints but never a count.
- **`rep.decode`/`rep.encode`**: value-level maps between the genotype
  (`rep.target`, an ordinary `Space` of `real(0, 1)` coordinates) and the
  phenotype (`rep.source`). `rep.target.sample_dicts(...)` draws genotypes
  the same way any space samples; decoding one is guaranteed **total** —
  every genotype the target calls valid decodes to a phenotype the source
  calls valid too.
- **`rep.check(n, seed)`**: the conformance laws as a callable tool — decode
  totality, feasibility agreement, and (when invertible) the one-directional
  round-trip `decode(encode(x)) == x`. Returns a report, never raises.
- **Mixed genotypes**: representing with an explicit rule (rather than none)
  means the rule chooses what changes — anything it doesn't match passes
  through in its original phenotype units, alongside whatever the rule did
  convert.
- **A supplied morphism**: `Representation(source=, target=, decode=,
  encode=)` constructed directly — a hierarchy-flattening bridge (a struct
  param's namespace erased entirely, `ds.flatten`/`ds.unflatten` doing the
  value-level work) that the derived tier could never express, since it
  must preserve the source's key set exactly.

Run it:  ``uv run python examples/09_representation.py``

See ``examples/README.md`` for the full feature -> example index.
"""

from __future__ import annotations

from dataclasses import replace

import designspace as ds
from designspace.config import flatten, unflatten


def build_space() -> ds.Space:
    return ds.space(
        ds.param("lr").real(1e-5, 1.0).log_scale(),
        ds.param("weight_decay").real(1e-6, 1e-2).log_scale(),
        ds.param("n_layers").integer(1, 5),
        ds.param("width").integer(8, 256).log_scale().repeat(ds.param("n_layers")),
        ds.param("optimizer").categorical("adam", "sgd"),
    ).forbid(ds.param("lr") > 0.5)


def main() -> None:
    space = build_space()
    print(f"Source space: {space.n_params} parameters\n")

    # -- The induced chart representation -------------------------------------
    print("--- space.represent() (induced) ---")
    rep = space.represent()
    print(f"  encoded: {rep.encoded}")
    print(f"  excluded_by_prop: {rep.excluded_by_prop}  (n_layers -- a repeat() count)")
    print(f"  invertible: {rep.invertible}   measure_preserving: {rep.measure_preserving}")
    print(f"  target params: {list(rep.target.params)}")
    print(
        f"  target['lr']: {rep.target.params['lr'].type_kind}, "
        f"domain={rep.target.params['lr'].domain}"
    )

    genotype = rep.target.sample_one(seed=0)
    print(f"\n  a genotype draw: {genotype}")
    phenotype = rep.decode(genotype)
    print(f"  decoded phenotype: {phenotype}")
    print(
        f"  source.validate(phenotype).param_errors == (): "
        f"{space.validate(phenotype).param_errors == ()}"
    )
    print(
        f"  target.is_feasible(genotype) == source.is_feasible(phenotype): "
        f"{rep.target.is_feasible(genotype) == space.is_feasible(phenotype)}"
    )

    back = rep.encode(phenotype)
    print(
        f"\n  encode(decode(genotype)) == genotype: {back == genotype}   "
        "(expected False here -- width's integer chart is many-to-one, "
        "API.md: 'encode(decode(g)) == g' is explicitly not a law)"
    )

    # -- rep.check(): the conformance laws as a tool --------------------------
    print("\n--- rep.check(n=200, seed=1) ---")
    result = rep.check(n=200, seed=1)
    print(f"  ok: {result.ok}   (n={result.n}, failures={result.failures})")

    # -- Mixed genotypes: an explicit rule converts only what it matches ------
    print("\n--- Mixed genotypes (an explicit rule) ---")

    class _UnitEncoding:
        """A minimal, self-written chart bridge for one param -- `param`
        (passed by `represent()`) is the *source*'s own `ParamDef`, so its
        already-built `.chart` does the real work; this is most of what
        the induced representation does per param, spelled out by hand."""

        def target(self, param: ds.ParamDef) -> ds.ParamDef:
            return replace(
                param,
                type_kind="real",
                domain=ds.RealDomain(0.0, 1.0),
                prior=None,
                quantized=None,
                chart=None,
            )

        def decode(self, param: ds.ParamDef, value: float) -> float:
            assert param.chart is not None
            return param.chart.from_unit(value)

        def encode(self, param: ds.ParamDef, value: float) -> float:
            assert param.chart is not None
            return param.chart.to_unit(value)

    def only_lr(pd: ds.ParamDef) -> ds.Encoding | None:
        return _UnitEncoding() if pd.path == "lr" else None

    mixed = space.represent(only_lr)
    print(f"  encoded: {mixed.encoded}")
    print(
        f"  target['weight_decay'] domain (untouched, still phenotype units): "
        f"{mixed.target.params['weight_decay'].domain}"
    )

    # -- A supplied morphism: hierarchy flattening ----------------------------
    print("\n--- A supplied morphism: hierarchy flattening ---")
    nested_space = ds.space(
        ds.param("model").space(
            ds.param("lr").real(0.0, 1.0),
            ds.param("depth").integer(1, 10),
        ),
        ds.param("seed").integer(0, 100),
    )
    print(f"  source params (hierarchical): {list(nested_space.params)}")

    rename = {
        p: p.replace(".", "__")
        for p, pd in nested_space.params.items()
        if pd.type_kind not in ("space", "choice")
    }
    reverse = {flat: original for original, flat in rename.items()}
    flat_target_params = [
        replace(nested_space.params[original], path=flat) for original, flat in rename.items()
    ]
    flat_target = ds.space_from_ir(flat_target_params, (), ())

    def flat_decode(genotype: dict) -> dict:
        renamed_back = {reverse[k]: v for k, v in genotype.items()}
        return unflatten(renamed_back, nested_space)

    def flat_encode(phenotype: dict) -> dict:
        flat = flatten(phenotype, nested_space)
        return {rename[k]: v for k, v in flat.items()}

    flattening_rep = ds.Representation(
        source=nested_space, target=flat_target, decode=flat_decode, encode=flat_encode
    )
    print(f"  target params (flat, no struct container): {list(flattening_rep.target.params)}")
    original_config = nested_space.sample_one(seed=2)
    print(f"  original: {original_config}")
    print(f"  encode -> {flattening_rep.encode(original_config)}")
    print(
        f"  decode(encode(original)) == original: "
        f"{flattening_rep.decode(flattening_rep.encode(original_config)) == original_config}"
    )
    flattening_check = flattening_rep.check(n=100, seed=3)
    print(f"  flattening_rep.check(): ok={flattening_check.ok}")


if __name__ == "__main__":
    main()

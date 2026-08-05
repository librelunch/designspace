"""The representation layer: a genotype is a Space too.

A NAS-shaped hyperparameter space is handed to a solver that only understands
continuous unit coordinates. ``space.represent()`` builds the *induced* chart
representation, the one representation core ships, derived mechanically from
the charts already on the declaration and never chosen. A small *supplied*
morphism, written entirely against the public surface, then shows what the
escape hatch looks like where the induced representation is not the answer.
Core ships none of these; see DECISIONS.md D-60.

Concepts introduced
-------------------
- **``space.represent()``** with no rules, giving the induced chart
  representation. It touches every parameter carrying a chart at its own level
  or at any element level of its ``ListDomain`` chain, since a scalar lift's
  chart lives in ``ListDomain.element_chart`` and not ``ParamDef.chart``. A
  ``.repeat()`` count, here ``n_layers``, is excluded and reported in
  ``excluded_by_prop``, because transport rewrites conditions and constraints
  but never a count.
- **``rep.decode`` and ``rep.encode``**, value-level maps between the genotype
  (``rep.target``, an ordinary ``Space`` of ``real(0, 1)`` coordinates) and the
  phenotype (``rep.source``). ``rep.target.sample_dicts(...)`` draws genotypes
  the way any space samples, and decoding one is guaranteed **total**: every
  genotype the target calls valid decodes to a phenotype the source calls valid.
- **``rep.check(n, seed)``**, the conformance laws as a callable tool. It
  covers decode totality, feasibility agreement, and, where invertible, the
  one-directional round-trip ``decode(encode(x)) == x``. It returns a report
  and never raises.
- **Mixed genotypes.** Representing with an explicit rule means the rule
  chooses what changes. Anything it does not match passes through in its
  original phenotype units, alongside whatever the rule did convert.
- **A supplied morphism**: ``Representation(source=, target=, decode=,
  encode=)`` constructed directly, giving a hierarchy-flattening bridge that
  erases a struct param's namespace entirely, with ``ds.flatten`` and
  ``ds.unflatten`` doing the value-level work. The derived tier could never
  express this, since it must preserve the source's key set exactly.

Run with ``uv run python examples/09_representation.py``.
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


class UnitEncoding:
    """A minimal, self-written chart bridge for one parameter.

    ``param``, passed by ``represent()``, is the *source*'s own ``ParamDef``,
    so its already-built ``.chart`` does the real work. This is most of what
    the induced representation does per parameter, spelled out by hand.
    """

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


def show_summary(space: ds.Space) -> None:
    print(f"Source space: {space.n_params} parameters\n")


def show_induced_representation(space: ds.Space) -> None:
    print("--- space.represent() (induced) ---")
    rep = space.represent()
    print(f"  encoded: {rep.encoded}")
    print(f"  excluded_by_prop: {rep.excluded_by_prop}  (n_layers, a repeat() count)")
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
        "(False here, because width's integer chart is many-to-one. API.md "
        "states that 'encode(decode(g)) == g' is not a law.)"
    )


def show_check(space: ds.Space) -> None:
    print("\n--- rep.check(n=200, seed=1) ---")
    rep = space.represent()
    result = rep.check(n=200, seed=1)
    print(f"  ok: {result.ok}   (n={result.n}, failures={result.failures})")


def show_mixed_genotype(space: ds.Space) -> None:
    # An explicit rule converts only what it matches.
    print("\n--- Mixed genotypes (an explicit rule) ---")

    def only_lr(pd: ds.ParamDef) -> ds.Encoding | None:
        return UnitEncoding() if pd.path == "lr" else None

    mixed = space.represent(only_lr)
    print(f"  encoded: {mixed.encoded}")
    print(
        f"  target['weight_decay'] domain (untouched, still phenotype units): "
        f"{mixed.target.params['weight_decay'].domain}"
    )


def show_supplied_morphism() -> None:
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


def main() -> None:
    space = build_space()
    show_summary(space)
    show_induced_representation(space)
    show_check(space)
    show_mixed_genotype(space)
    show_supplied_morphism()


if __name__ == "__main__":
    main()

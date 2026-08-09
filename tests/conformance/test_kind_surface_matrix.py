"""Conformance law: every param kind satisfies every stated cross-kind law.

A representative space per param kind, including the domain-modifier
variants that change chart or dtype behaviour, meaning log-scaled, periodic
and quantized, and each lift shape, is crossed against the surfaces carrying
a stated law:

- `fingerprint()` is computable, and `Space.from_json(s.to_json())`
  reproduces it, which is the round-trip law;
- `unflatten(flatten(c)) == c`;
- `config_hash` is computable, and `config_diff(c, c) == []`;
- `apply_defaults` is idempotent;
- `validate(sample_one())` is valid;
- the induced representation's `check()` passes;
- the DataFrame column dtype matches the "Config Representation" table,
  including the `Array`-against-`List` static and dynamic rule per level;
- a non-generative kind raises `SamplingError` rather than materializing.

The value is regression coverage at the point a new kind or a new surface is
added: every existing law is then asserted against it by construction rather
than by remembering to. Adding a kind means adding one row here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pytest

import designspace as ds

_SIG = ds.Signature(args={"x": float}, returns=float)


@dataclass(frozen=True)
class Widget:
    """A full-protocol `ParamType`: sample + properties + cardinality, so a
    `custom` row exercises the generative and modeling channels both."""

    size: int = 3

    @property
    def type_key(self) -> str:
        return "widget"

    def sample(self, rng: Any) -> dict[str, Any]:
        return {"n": int(rng.integers(0, self.size))}

    def validate(self, value: Any) -> bool:
        return isinstance(value, dict) and isinstance(value.get("n"), int)

    def to_json(self, value: Any) -> Any:
        return dict(value)

    def from_json(self, data: Any) -> Any:
        return dict(data)

    def describe(self) -> dict[str, Any]:
        return asdict(self)

    def properties(self) -> dict[str, type]:
        return {"n": int}

    def extract(self, value: Any, prop: str) -> Any:
        return value[prop]

    def cardinality(self) -> int | None:
        return self.size


REGISTRY = {"widget": lambda d: Widget(**d)}

# kind -> (builder, expected polars dtype string)
KINDS: dict[str, tuple[Any, str]] = {
    "real": (lambda: ds.param("p").real(0.0, 1.0), "Float64"),
    "real_log": (lambda: ds.param("p").real(1e-3, 1.0).log_scale(), "Float64"),
    "real_periodic": (lambda: ds.param("p").real(0.0, 6.28, periodic=True), "Float64"),
    "real_quantized": (lambda: ds.param("p").real(0.0, 1.0).quantized(step=0.25), "Float64"),
    "integer": (lambda: ds.param("p").integer(0, 7), "Int64"),
    "integer_quantized": (lambda: ds.param("p").integer(0, 8).quantized(step=2), "Int64"),
    "bool": (lambda: ds.param("p").bool(), "Boolean"),
    "categorical": (lambda: ds.param("p").categorical("a", "b", "c"), "String"),
    "ordinal": (lambda: ds.param("p").ordinal("lo", "mid", "hi"), "String"),
    "subset": (lambda: ds.param("p").subset(["a", "b", "c"], min_size=1), "List(String)"),
    "permutation": (lambda: ds.param("p").permutation(["a", "b", "c"]), "List(String)"),
    "choice_bare": (lambda: ds.param("p").choice("a", "b"), "String"),
    "choice_payload": (
        lambda: ds.param("p").choice("a", b=ds.space(ds.param("w").real(0.0, 1.0))),
        "String",
    ),
    "struct": (lambda: ds.param("p").space(ds.param("w").real(0.0, 1.0)), "Struct({'w': Float64})"),
    "custom": (lambda: ds.param("p").custom(Widget()), "String"),
    "scalar_lift": (lambda: ds.param("p").real(0.0, 1.0).repeat(3), "Array(Float64, shape=(3,))"),
    # polars collapses a nested *static* lift into one multi-dimensional
    # Array rather than Array(Array(...)); the shape reads outermost-first,
    # so `.repeat(2).repeat(3)`, outer 3 and inner 2, is shape (3, 2). That
    # is the convention `.repeat(*counts)`'s numpy-shape sugar desugars to.
    "nested_lift": (
        lambda: ds.param("p").real(0.0, 1.0).repeat(2).repeat(3),
        "Array(Float64, shape=(3, 2))",
    ),
    "subset_lift": (
        lambda: ds.param("p").subset(["a", "b"], min_size=1).repeat(2),
        "Array(List(String), shape=(2,))",
    ),
}

# Kinds whose dtype is asserted structurally rather than by exact string
# (the struct/choice element schemas are long and already pinned by
# test_dataframe.py's own table); they still run every other law.
DTYPE_PREFIX_ONLY = {
    "struct_lift": (lambda: ds.param("p").space(ds.param("w").real(0.0, 1.0)).repeat(3), "Array"),
    "choice_lift": (
        lambda: ds.param("p").choice("a", b=ds.space(ds.param("w").real(0.0, 1.0))).repeat(2),
        "Array",
    ),
}

NON_GENERATIVE: dict[str, Any] = {
    "symbolic": lambda: ds.param("p").symbolic(_SIG, primitives=["add"], max_depth=3),
    "code": lambda: ds.param("p").code(_SIG),
}


def _space(builder: Any) -> ds.Space:
    return ds.space(builder())


ALL_GENERATIVE = {
    **{k: v[0] for k, v in KINDS.items()},
    **{k: v[0] for k, v in DTYPE_PREFIX_ONLY.items()},
}


class TestEveryKindSatisfiesEveryLaw:
    @pytest.mark.parametrize("kind", sorted(ALL_GENERATIVE))
    def test_fingerprint_and_json_round_trip(self, kind: str) -> None:
        space = _space(ALL_GENERATIVE[kind])
        assert space.fingerprint()
        rebuilt = ds.Space.from_json(space.to_json(), custom_types=REGISTRY)
        assert rebuilt.fingerprint() == space.fingerprint()
        assert rebuilt.fingerprint(scope="sampling") == space.fingerprint(scope="sampling")

    @pytest.mark.parametrize("kind", sorted(ALL_GENERATIVE))
    def test_sample_validates(self, kind: str) -> None:
        space = _space(ALL_GENERATIVE[kind])
        for seed in range(5):
            assert space.validate(space.sample_one(seed=seed)).valid

    @pytest.mark.parametrize("kind", sorted(ALL_GENERATIVE))
    def test_flatten_unflatten_round_trip(self, kind: str) -> None:
        space = _space(ALL_GENERATIVE[kind])
        for seed in range(5):
            config = space.sample_one(seed=seed)
            assert ds.unflatten(ds.flatten(config, space), space) == config

    @pytest.mark.parametrize("kind", sorted(ALL_GENERATIVE))
    def test_config_hash_and_self_diff(self, kind: str) -> None:
        space = _space(ALL_GENERATIVE[kind])
        config = space.sample_one(seed=0)
        assert ds.config_hash(config, space) == ds.config_hash(config, space)
        assert ds.config_diff(config, config, space) == []

    @pytest.mark.parametrize("kind", sorted(ALL_GENERATIVE))
    def test_apply_defaults_is_idempotent(self, kind: str) -> None:
        space = _space(ALL_GENERATIVE[kind])
        once = space.apply_defaults({})
        assert space.apply_defaults(once) == once

    @pytest.mark.parametrize("kind", sorted(ALL_GENERATIVE))
    def test_induced_representation_checks_out(self, kind: str) -> None:
        space = _space(ALL_GENERATIVE[kind])
        assert space.represent().check(n=40, seed=1).ok

    @pytest.mark.requires_polars
    @pytest.mark.parametrize("kind", sorted(KINDS))
    def test_dataframe_dtype_matches_the_table(self, kind: str) -> None:
        builder, expected = KINDS[kind]
        frame = ds.space(builder()).sample(4, seed=0)
        assert str(frame.schema["p"]) == expected

    @pytest.mark.requires_polars
    @pytest.mark.parametrize("kind", sorted(DTYPE_PREFIX_ONLY))
    def test_container_lift_dtype_is_an_array(self, kind: str) -> None:
        builder, prefix = DTYPE_PREFIX_ONLY[kind]
        frame = ds.space(builder()).sample(4, seed=0)
        assert str(frame.schema["p"]).startswith(prefix)


class TestNonGenerativeKinds:
    @pytest.mark.parametrize("kind", sorted(NON_GENERATIVE))
    def test_materialization_raises(self, kind: str) -> None:
        space = _space(NON_GENERATIVE[kind])
        assert space.has_nongenerative_params is True
        with pytest.raises(ds.SamplingError):
            space.sample_one(seed=0)

    @pytest.mark.parametrize("kind", sorted(NON_GENERATIVE))
    def test_still_round_trips_and_is_opaque_to_cardinality(self, kind: str) -> None:
        space = _space(NON_GENERATIVE[kind])
        assert ds.Space.from_json(space.to_json()).fingerprint() == space.fingerprint()
        assert space.cardinality() is None

    @pytest.mark.parametrize("kind", sorted(NON_GENERATIVE))
    def test_a_default_satisfies_materialization(self, kind: str) -> None:
        """A `.default()` satisfies the materialization obligation.

        API.md says the `SamplingError` fires "iff it must materialize a
        value", and a `.default()` is one of the three documented escapes.
        """
        value = {"ast": {"var": "x"}} if kind == "symbolic" else {"source": "def f(x): return x"}
        space = ds.space(NON_GENERATIVE[kind]().default(value))
        assert space.sample_one(seed=0) == {"p": value}

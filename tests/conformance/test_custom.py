"""Conformance laws: custom types.

See API.md, "Protocols" for `ParamType` and the custom-type contract laws,
`.custom()` in both forms, `.prop()`, the `from_json` registry, and error
rows 16, 23 and 27.

Covered here: `factory(x.describe()) == x`; that `extract` runs only after
`validate`; that the shorthand form is poisoned for `to_json` and
`fingerprint`, under both raise and mark; row 16, for an undeclared
property, a non-scalar property type and a comparison type mismatch; row 23,
for a non-JSON `describe()`; row 27, for a missing `custom_types` entry;
`.has_nongenerative_params`; `.cardinality()`; and freeze-on-custom, which
is fingerprint-equal to the hand-written pin, samples and validates only the
fixed value, and raises for the shorthand form.

`tests/corpus/vi_family.py` covers the end-to-end happy path, meaning
sample, validate, round-trip and the canonical-ordering law. This file
covers the laws and the misuse paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pytest

import designspace as ds
from designspace.errors import ResolutionError, SamplingError, SerializationError


@dataclass(frozen=True)
class Probability:
    """A minimal full-protocol ParamType wrapping a float in [0, 1].

    Generative, with no declared properties.
    """

    @property
    def type_key(self) -> str:
        return "probability"

    def sample(self, rng: Any) -> float:
        return float(rng.random())

    def validate(self, value: Any) -> bool:
        is_number = isinstance(value, int | float) and not isinstance(value, bool)
        return is_number and 0.0 <= value <= 1.0

    def to_json(self, value: Any) -> Any:
        return float(value)

    def from_json(self, data: Any) -> Any:
        return float(data)

    def describe(self) -> dict[str, Any]:
        return {}


def probability_factory(described: dict[str, Any]) -> Probability:
    return Probability(**described)


@dataclass(frozen=True)
class TaggedValue:
    """A full-protocol ParamType with declared int/bool properties, for
    row-16 misuse tests."""

    tag: str = "x"

    @property
    def type_key(self) -> str:
        return "tagged_value"

    def sample(self, rng: Any) -> dict[str, Any]:
        return {"n": int(rng.integers(0, 10)), "ok": bool(rng.random() < 0.5)}

    def validate(self, value: Any) -> bool:
        return (
            isinstance(value, dict)
            and isinstance(value.get("n"), int)
            and isinstance(value.get("ok"), bool)
        )

    def to_json(self, value: Any) -> Any:
        return dict(value)

    def from_json(self, data: Any) -> Any:
        return dict(data)

    def describe(self) -> dict[str, Any]:
        return asdict(self)

    def properties(self) -> dict[str, type]:
        return {"n": int, "ok": bool}

    def extract(self, value: Any, prop: str) -> Any:
        return value[prop]


def tagged_value_factory(described: dict[str, Any]) -> TaggedValue:
    return TaggedValue(**described)


@dataclass(frozen=True)
class Unserializable:
    """A full-protocol type whose `describe()` output is not
    JSON-serializable, which is row 23."""

    @property
    def type_key(self) -> str:
        return "unserializable"

    def sample(self, rng: Any) -> float:
        return float(rng.random())

    def validate(self, value: Any) -> bool:
        return True

    def to_json(self, value: Any) -> Any:
        return value

    def from_json(self, data: Any) -> Any:
        return data

    def describe(self) -> dict[str, Any]:
        return {"payload": object()}


# -- .custom() construction / row 2 -------------------------------------------


class TestConstruction:
    def test_full_form(self):
        space = ds.space(ds.param("p").custom(Probability()))
        assert space.params["p"].type_kind == "custom"

    def test_shorthand_form(self):
        space = ds.space(
            ds.param("p").custom(
                sampler=lambda rng: float(rng.random()), validator=lambda v: 0.0 <= v <= 1.0
            )
        )
        assert space.params["p"].type_kind == "custom"

    def test_neither_form_raises(self):
        with pytest.raises(ResolutionError):
            ds.param("p").custom()

    def test_both_forms_raises(self):
        with pytest.raises(ResolutionError):
            ds.param("p").custom(Probability(), sampler=lambda rng: 0.5, validator=lambda v: True)

    def test_shorthand_missing_validator_raises(self):
        with pytest.raises(ResolutionError):
            ds.param("p").custom(sampler=lambda rng: 0.5)

    def test_second_type_method_raises(self):
        with pytest.raises(ResolutionError):
            ds.param("p").custom(Probability()).real(0.0, 1.0)


# -- describe()/factory round-trip law ----------------------------------------


class TestDescribeRoundTrip:
    def test_factory_describe_equivalence(self):
        pt = TaggedValue(tag="hello")
        rebuilt = tagged_value_factory(pt.describe())
        assert rebuilt == pt


# -- extract only-after-validate -----------------------------------------------


class TestExtractOnlyAfterValidate:
    def test_prop_on_invalid_value_is_unknown_not_a_crash(self):
        space = ds.space(ds.param("t").custom(TaggedValue())).require(ds.param("t").prop("n") >= 0)
        # A malformed submitted value (extract() would KeyError/crash on
        # arbitrary garbage): validate() must report it as a ParamError,
        # never let a crash escape through constraint evaluation.
        result = space.validate({"t": "not-a-tagged-value"})
        assert not result.valid
        assert any(e.param == "t" for e in result.param_errors)
        ce = result.constraint_evals[0]
        assert ce.applicable is False  # Unknown -- extract() was never called


# -- .prop() as a bare BoolExpr --------------------------------------------------


class TestPropAsBoolExpr:
    """A bool-declared prop is dual-typed like a param reference itself
    (`ParamExpr(ArithExpr, BoolExpr, VectorExpr)`), so it is usable
    directly as a condition rather than only inside a `Compare`. This
    matches the codebase's
    existing convention that a bare `BoolExpr` leaf coerces via
    `bool(value)`, with no extra "must be bool-declared" gate on that
    specific position (row 16's undeclared/non-scalar checks still apply
    uniformly, since they run on every `Prop` node regardless of position)."""

    def test_require_accepts_a_bare_bool_prop(self):
        space = ds.space(ds.param("t").custom(TaggedValue())).require(ds.param("t").prop("ok"))
        assert space.is_feasible({"t": {"n": 1, "ok": True}})
        assert not space.is_feasible({"t": {"n": 1, "ok": False}})

    def test_bare_and_explicit_comparison_agree(self):
        bare = ds.space(ds.param("t").custom(TaggedValue())).require(ds.param("t").prop("ok"))
        explicit = ds.space(ds.param("t").custom(TaggedValue())).require(
            ds.param("t").prop("ok") == True  # noqa: E712
        )
        for value in ({"n": 1, "ok": True}, {"n": 1, "ok": False}):
            cfg = {"t": value}
            assert bare.is_feasible(cfg) == explicit.is_feasible(cfg)

    def test_composes_with_and_or_not(self):
        space = ds.space(ds.param("t").custom(TaggedValue()), ds.param("gate").bool()).require(
            ds.param("t").prop("ok") & ds.param("gate")
        )
        assert space.is_feasible({"t": {"n": 1, "ok": True}, "gate": True})
        assert not space.is_feasible({"t": {"n": 1, "ok": True}, "gate": False})

    def test_margin_is_none_matching_a_bare_bool_param(self):
        # A bare boolean leaf (Prop or plain param) is not Compare/BoolOp/
        # Not-shaped, so it has no signed margin -- same for both.
        space = ds.space(ds.param("t").custom(TaggedValue())).require(ds.param("t").prop("ok"))
        (ce,) = space.evaluate_constraints({"t": {"n": 1, "ok": True}})
        assert ce.margin is None

    def test_extract_only_after_validate_holds_in_bool_position_too(self):
        space = ds.space(ds.param("t").custom(TaggedValue())).require(ds.param("t").prop("ok"))
        result = space.validate({"t": "not-a-tagged-value"})
        assert not result.valid
        ce = result.constraint_evals[0]
        assert ce.applicable is False  # Unknown, not a crash from extract()


# -- row 16 --------------------------------------------------------------------


class TestRow16:
    def test_prop_on_non_custom_param_raises(self):
        space = ds.space(ds.param("x").integer(0, 10))
        with pytest.raises(ResolutionError, match="not a custom param"):
            space.require(ds.param("x").prop("n") >= 0)

    def test_undeclared_property_raises(self):
        space = ds.space(ds.param("t").custom(TaggedValue()))
        with pytest.raises(ResolutionError, match="not a declared property"):
            space.require(ds.param("t").prop("nope") >= 0)

    def test_shorthand_has_no_properties(self):
        space = ds.space(ds.param("t").custom(sampler=lambda rng: 0.5, validator=lambda v: True))
        with pytest.raises(ResolutionError, match="not a declared property"):
            space.require(ds.param("t").prop("anything") >= 0)

    def test_non_scalar_property_type_raises(self):
        @dataclass(frozen=True)
        class BadProps:
            @property
            def type_key(self) -> str:
                return "bad_props"

            def sample(self, rng: Any) -> Any:
                return {}

            def validate(self, value: Any) -> bool:
                return True

            def to_json(self, value: Any) -> Any:
                return value

            def from_json(self, data: Any) -> Any:
                return data

            def describe(self) -> dict[str, Any]:
                return {}

            def properties(self) -> dict[str, type]:
                return {"bad": list}

            def extract(self, value: Any, prop: str) -> Any:
                return []

        space = ds.space(ds.param("t").custom(BadProps()))
        with pytest.raises(ResolutionError, match="non-scalar type"):
            space.require(ds.param("t").prop("bad") == 1)

    def test_comparison_type_mismatch_raises(self):
        space = ds.space(ds.param("t").custom(TaggedValue()))
        with pytest.raises(
            ResolutionError, match=r"prop\('n'\) is 'int'-typed, compared against 'not-an-int'"
        ):
            space.require(ds.param("t").prop("n") == "not-an-int")

    def test_two_prop_type_mismatch_raises(self):
        space = ds.space(
            ds.param("a").custom(TaggedValue(tag="a")),
            ds.param("b").custom(TaggedValue(tag="b")),
        )
        with pytest.raises(
            ResolutionError, match=r"prop\('n'\) \('int'\) compared against prop\('ok'\) \('bool'\)"
        ):
            space.require(ds.param("a").prop("n") == ds.param("b").prop("ok"))


# -- row 23 ---------------------------------------------------------------------


class TestRow23:
    def test_non_json_describe_raises_on_to_json(self):
        space = ds.space(ds.param("u").custom(Unserializable()))
        with pytest.raises(
            SerializationError, match=r"describe\(\) output is not JSON-serializable"
        ):
            space.to_json()

    def test_non_json_describe_raises_on_fingerprint(self):
        space = ds.space(ds.param("u").custom(Unserializable()))
        with pytest.raises(
            SerializationError, match=r"describe\(\) output is not JSON-serializable"
        ):
            space.fingerprint()


# -- shorthand poisoning: raise + mark -----------------------------------------


class TestShorthandPoisoning:
    def _space(self):
        return ds.space(
            ds.param("p").custom(
                sampler=lambda rng: float(rng.random()), validator=lambda v: 0.0 <= v <= 1.0
            )
        )

    def test_to_json_raises_by_default(self):
        with pytest.raises(SerializationError):
            self._space().to_json()

    def test_to_json_mark_sentinel(self):
        doc = self._space().to_json(on_unserializable="mark")
        (entry,) = doc["params"]
        assert entry["domain"] == {"kind": "opaque", "$opaque": True}

    def test_fingerprint_raises_by_default(self):
        with pytest.raises(SerializationError):
            self._space().fingerprint()

    def test_fingerprint_mark_succeeds(self):
        fp = self._space().fingerprint(on_unserializable="mark")
        assert isinstance(fp, str) and fp.startswith("1:full:")


# -- row 27 -----------------------------------------------------------------------


class TestRow27:
    def test_missing_registry_entry_raises(self):
        space = ds.space(ds.param("p").custom(Probability()))
        doc = space.to_json()
        from designspace import Space

        with pytest.raises(SerializationError, match="has no entry in custom_types"):
            Space.from_json(doc)  # no custom_types registry at all

        with pytest.raises(SerializationError, match="has no entry in custom_types"):
            Space.from_json(doc, custom_types={"other_key": probability_factory})


# -- has_nongenerative_params ---------------------------------------------------


class TestHasNongenerativeParams:
    def test_generative_full_form_is_false(self):
        space = ds.space(ds.param("p").custom(Probability()))
        assert space.has_nongenerative_params is False

    def test_shorthand_is_always_generative(self):
        space = ds.space(ds.param("p").custom(sampler=lambda rng: 0.5, validator=lambda v: True))
        assert space.has_nongenerative_params is False

    def test_sample_less_full_form_is_nongenerative(self):
        @dataclass(frozen=True)
        class NoSample:
            @property
            def type_key(self) -> str:
                return "no_sample"

            def validate(self, value: Any) -> bool:
                return isinstance(value, int)

            def to_json(self, value: Any) -> Any:
                return value

            def from_json(self, data: Any) -> Any:
                return data

            def describe(self) -> dict[str, Any]:
                return {}

        space = ds.space(ds.param("p").custom(NoSample()))
        assert space.has_nongenerative_params is True

    def test_no_custom_param_is_false(self):
        space = ds.space(ds.param("x").integer(0, 10))
        assert space.has_nongenerative_params is False


# -- freeze-on-custom -------------------------------------------------------------


@dataclass(frozen=True)
class Coin:
    """A small, discretely valued generative full-protocol type.

    Freeze pins it by rejection, as it does bool, an opaque value having no
    domain to narrow. That is practical only when the sample space is small
    enough for rejection to hit the pinned value within the retry budget. A
    continuous-valued custom's freeze is validated structurally instead, in
    `TestFreezeOnCustom.test_frozen_space_validates_only_fixed_value` below.
    """

    @property
    def type_key(self) -> str:
        return "coin"

    def sample(self, rng: Any) -> int:
        return int(rng.integers(0, 2))

    def validate(self, value: Any) -> bool:
        return value in (0, 1)

    def to_json(self, value: Any) -> Any:
        return int(value)

    def from_json(self, data: Any) -> Any:
        return int(data)

    def describe(self) -> dict[str, Any]:
        return {}


class TestFreezeOnCustom:
    def test_fingerprint_equal_to_hand_written_pin(self):
        # `.freeze()` also sets `default = value`, diverging from bool's
        # bare pin: unlike bool, a custom may be non-generative, and the
        # default is what makes ".freeze() removes the non-generative
        # SamplingError" hold. The hand-written equivalent matches that.
        space = ds.space(ds.param("p").custom(Coin()))
        frozen = space.freeze(p=1)
        hand_built = ds.space(ds.param("p").custom(Coin()).default(1)).require(ds.param("p") == 1)
        assert frozen.fingerprint("full") == hand_built.fingerprint("full")

    def test_frozen_space_samples_only_fixed_value(self):
        space = ds.space(ds.param("p").custom(Coin()))
        frozen = space.freeze(p=1)
        for cfg in frozen.sample_dicts(20, seed=0):
            assert cfg["p"] == 1

    def test_frozen_space_validates_only_fixed_value(self):
        space = ds.space(ds.param("p").custom(Probability()))
        frozen = space.freeze(p=0.5)
        assert frozen.validate({"p": 0.5}).valid
        assert not frozen.validate({"p": 0.7}).valid

    def test_shorthand_freeze_raises(self):
        space = ds.space(ds.param("p").custom(sampler=lambda rng: 0.5, validator=lambda v: True))
        with pytest.raises(ResolutionError):
            space.freeze(p=0.5)

    def test_frozen_nongenerative_no_longer_raises_sampling_error(self):
        @dataclass(frozen=True)
        class NoSample:
            @property
            def type_key(self) -> str:
                return "no_sample_freeze"

            def validate(self, value: Any) -> bool:
                return isinstance(value, int)

            def to_json(self, value: Any) -> Any:
                return value

            def from_json(self, data: Any) -> Any:
                return data

            def describe(self) -> dict[str, Any]:
                return {}

        space = ds.space(ds.param("p").custom(NoSample()))
        with pytest.raises(SamplingError):
            space.sample_one(seed=0)
        frozen = space.freeze(p=7)
        assert frozen.sample_one(seed=0) == {"p": 7}


# -- .slice() does not support a custom param -----------------------------------


class TestSliceOnCustom:
    def test_slicing_a_custom_param_raises(self):
        space = ds.space(ds.param("p").custom(Probability()), ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError):
            space.slice(p=0.5)

    def test_slicing_other_params_unaffected_by_a_prop_expression_elsewhere(self):
        # A .prop() expression on an UNRELATED (non-sliced) custom param must
        # not break ordinary substitution elsewhere in the same space.
        space = ds.space(ds.param("t").custom(TaggedValue()), ds.param("x").integer(0, 10)).require(
            ds.param("t").prop("n") >= 0
        )
        sliced = space.slice(x=5)
        assert "x" not in sliced.params
        assert "t" in sliced.params


# -- cardinality() / is_finite consistency ---------------------------------------


class TestCardinalityIsFiniteConsistency:
    def test_none_on_flat_hpo_shaped_continuous_space(self):
        import sys
        from pathlib import Path

        corpus_dir = Path(__file__).resolve().parents[1] / "corpus"
        if str(corpus_dir) not in sys.path:
            sys.path.insert(0, str(corpus_dir))
        from flat_hpo import build_space as build_flat_hpo

        space = build_flat_hpo()
        assert space.is_finite is False
        assert space.cardinality() is None

    def test_exact_on_a_purely_discrete_space(self):
        space = ds.space(
            ds.param("a").categorical("x", "y", "z"),
            ds.param("b").bool(),
            ds.param("c").integer(1, 4),
        )
        assert space.is_finite is True
        assert space.cardinality() == 3 * 2 * 4

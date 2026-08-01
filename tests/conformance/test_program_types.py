"""Conformance laws: M12 program types (`.symbolic()`/`.code()`; API.md,
"Parameter Types" > "Program"; "Support Types"; DECISIONS.md D-83…D-90).

Gate items covered here (Stage 1 — declaration, AST/value validation,
generativity): the rewritten error row 15 (DECISIONS.md D-90 — the fixed
built-in primitive list is dropped, a user-directed change to a stated
law: declaration checks left are shape/duplicate/arity, never vocabulary
membership); AST structural validation (D-83); arity binds only where a
`Primitive` declares one (D-89); validators run after the structural
check and never escape a public call; `.symbolic()`/`.code()`
generativity and `has_nongenerative_params` (incl. under `.repeat()`).

Identity/serialization, freeze/slice, and downstream-surface laws (Stage
2) and the corpus fixture + known-answer vector (Stage 3) live in their
own sections of this file, added as those stages land.
"""

from __future__ import annotations

from typing import Any

import pytest

import designspace as ds
from designspace.errors import ResolutionError, SamplingError, SerializationError

# -- shared fixtures ----------------------------------------------------------


def _cooling_signature() -> ds.Signature:
    return ds.Signature({"step": int, "total": int}, float)


def _cooling_primitives() -> list[Any]:
    return ["cos", "pi", ds.Primitive("*", 2), ds.Primitive("/", 2)]


def _cooling_ast() -> dict[str, Any]:
    return {
        "op": "cos",
        "args": [
            {
                "op": "*",
                "args": [
                    {"op": "pi", "args": []},
                    {"op": "/", "args": [{"var": "step"}, {"var": "total"}]},
                ],
            }
        ],
    }


def _cooling_value() -> dict[str, Any]:
    return {"ast": _cooling_ast(), "source": "cos(pi * step / total)"}


# -- 1. Declaration: the rewritten row 15 (D-90) -----------------------------


class TestDeclarationRewrittenRow15:
    def test_open_vocabulary_resolves(self):
        # The law D-90 turns on: no name is "unknown" at declaration time —
        # a closed built-in set no longer exists.
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), ["sqrt", "where", "cso", "anything"], 3
            )
        )
        assert space.n_params == 1

    def test_duplicate_primitive_name_raises(self):
        with pytest.raises(ResolutionError, match="duplicate primitive"):
            ds.space(ds.param("sched").symbolic(_cooling_signature(), ["cos", "cos"], 3))

    def test_duplicate_primitive_name_across_str_and_primitive_raises(self):
        with pytest.raises(ResolutionError, match="duplicate primitive"):
            ds.space(
                ds.param("sched").symbolic(_cooling_signature(), ["cos", ds.Primitive("cos", 1)], 3)
            )

    def test_empty_primitive_name_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(ds.param("sched").symbolic(_cooling_signature(), [""], 3))

    def test_malformed_arity_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(ds.param("sched").symbolic(_cooling_signature(), [ds.Primitive("cos", -1)], 3))

    def test_arity_hi_less_than_lo_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(
                ds.param("sched").symbolic(_cooling_signature(), [ds.Primitive("cos", (3, 1))], 3)
            )

    def test_max_depth_zero_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(ds.param("sched").symbolic(_cooling_signature(), ["cos"], 0))

    def test_negative_max_depth_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(ds.param("sched").symbolic(_cooling_signature(), ["cos"], -1))

    def test_literal_lo_gt_hi_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(
                ds.param("sched").symbolic(_cooling_signature(), [ds.FloatLiteral(1.0, 0.0)], 3)
            )

    def test_literal_non_finite_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(
                ds.param("sched").symbolic(
                    _cooling_signature(), [ds.FloatLiteral(0.0, float("inf"))], 3
                )
            )

    def test_bad_signature_arg_name_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(
                ds.param("sched").symbolic(
                    ds.Signature({"not an identifier": int}, float), ["cos"], 3
                )
            )

    def test_primitive_shadowing_a_common_name_resolves(self):
        # Shadowing is legal — it is the supported mechanism for pinning an
        # otherwise-unchecked name's arity (D-89/D-90).
        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), [ds.Primitive("cos", 1)], 3)
        )
        assert space.n_params == 1

    def test_bad_primitives_entry_type_raises(self):
        with pytest.raises(ResolutionError, match="'sched'"):
            ds.space(ds.param("sched").symbolic(_cooling_signature(), [123], 3))  # type: ignore[list-item]

    def test_code_examples_must_be_json_serializable(self):
        with pytest.raises(ResolutionError, match="row 23"):
            ds.space(ds.param("p").code(ds.Signature({}, "bool"), examples=[object()]))

    def test_code_bad_signature_arg_name_raises(self):
        with pytest.raises(ResolutionError, match="'p'"):
            ds.space(ds.param("p").code(ds.Signature({"1bad": int}, "bool")))


# -- 2. AST structural validation (D-83) -------------------------------------


class TestAstValidation:
    def test_well_formed_tree_validates(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        result = space.validate({"sched": _cooling_value()})
        assert result.valid

    def test_undeclared_op_is_invalid(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), ["cos"], 3))
        value = {"ast": {"op": "sin", "args": []}}
        result = space.validate({"sched": value})
        assert not result.valid

    def test_undeclared_var_is_invalid(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), ["cos"], 3))
        value = {"ast": {"op": "cos", "args": [{"var": "nope"}]}}
        result = space.validate({"sched": value})
        assert not result.valid

    def test_const_outside_every_literal_bound_is_invalid(self):
        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), [ds.FloatLiteral(0.0, 1.0)], 3)
        )
        value = {"ast": {"const": 5.0}}
        result = space.validate({"sched": value})
        assert not result.valid

    def test_const_with_no_declared_literal_is_invalid(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), ["cos"], 3))
        value = {"ast": {"const": 0.5}}
        result = space.validate({"sched": value})
        assert not result.valid

    def test_depth_exactly_max_depth_is_valid(self):
        # A leaf is depth 1: {"var": "step"} alone has depth 1.
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), [], 1))
        value = {"ast": {"var": "step"}}
        assert space.validate({"sched": value}).valid

    def test_depth_max_depth_plus_one_is_invalid(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), ["cos"], 1))
        value = {"ast": {"op": "cos", "args": [{"var": "step"}]}}
        assert not space.validate({"sched": value}).valid

    def test_vocabulary_still_checked_at_value_time(self):
        # D-90 dropped declaration-time vocabulary checking, not value-time
        # checking: an op the param never declared is still invalid.
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), ["cso"], 3))
        value = {"ast": {"op": "cos", "args": []}}
        assert not space.validate({"sched": value}).valid

    def test_code_missing_source_is_invalid(self):
        space = ds.space(ds.param("p").code(ds.Signature({}, "bool")))
        assert not space.validate({"p": {}}).valid

    def test_code_non_str_source_is_invalid(self):
        space = ds.space(ds.param("p").code(ds.Signature({}, "bool")))
        assert not space.validate({"p": {"source": 123}}).valid

    def test_code_well_formed_source_validates(self):
        space = ds.space(ds.param("p").code(ds.Signature({}, "bool")))
        assert space.validate({"p": {"source": "x > 0"}}).valid


# -- 3. Arity binds only where declared (D-89) -------------------------------


class TestArityBindsOnlyWhereDeclared:
    def _ast(self, n: int) -> dict[str, Any]:
        return {"op": "+", "args": [{"var": "step"}] * n}

    def test_bare_string_accepts_any_arity(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), ["+"], 3))
        assert space.validate({"sched": {"ast": self._ast(0)}}).valid
        assert space.validate({"sched": {"ast": self._ast(3)}}).valid

    def test_exact_int_arity_rejects_mismatch(self):
        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), [ds.Primitive("+", 2)], 3)
        )
        assert not space.validate({"sched": {"ast": self._ast(3)}}).valid
        assert space.validate({"sched": {"ast": self._ast(2)}}).valid

    def test_lower_bound_only_range(self):
        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), [ds.Primitive("+", (2, None))], 3)
        )
        assert space.validate({"sched": {"ast": self._ast(5)}}).valid
        assert not space.validate({"sched": {"ast": self._ast(1)}}).valid

    def test_bounded_range(self):
        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), [ds.Primitive("+", (1, 2))], 3)
        )
        assert space.validate({"sched": {"ast": self._ast(1)}}).valid
        assert space.validate({"sched": {"ast": self._ast(2)}}).valid
        assert not space.validate({"sched": {"ast": self._ast(3)}}).valid

    # `Primitive("+", 2)` vs `Primitive("+", (2, 2))` fingerprint-equality
    # (the arity sugar-equivalence law) needs identity/serialization
    # support for the new domain kinds — see TestIdentity, added in Stage 2.


# -- 4. Validators run after the structural check, never escape -------------


class TestValidators:
    def test_false_validator_is_invalid(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, validators=[lambda ast: False]
            )
        )
        assert not space.validate({"sched": _cooling_value()}).valid

    def test_true_validator_passes(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, validators=[lambda ast: True]
            )
        )
        assert space.validate({"sched": _cooling_value()}).valid

    def test_raising_validator_never_escapes(self):
        def boom(ast: Any) -> bool:
            raise RuntimeError("boom")

        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, validators=[boom]
            )
        )
        result = space.validate({"sched": _cooling_value()})
        assert not result.valid

    def test_validator_only_runs_after_structural_check(self):
        # A structurally-invalid tree fails before any validator runs; a
        # validator that always raises must not be reached.
        def boom(ast: Any) -> bool:
            raise RuntimeError("boom")

        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), ["cos"], 3, validators=[boom])
        )
        result = space.validate({"sched": {"ast": {"op": "sin", "args": []}}})
        assert not result.valid

    def test_code_validator_over_source_string(self):
        space = ds.space(
            ds.param("p").code(ds.Signature({}, "bool"), validators=[lambda src: "TODO" not in src])
        )
        assert space.validate({"p": {"source": "return True"}}).valid
        assert not space.validate({"p": {"source": "# TODO"}}).valid


# -- 5. Generativity ----------------------------------------------------------


class TestGenerativity:
    def test_symbolic_without_default_or_sampler_raises(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        with pytest.raises(SamplingError):
            space.sample_one(seed=0)

    def test_symbolic_with_default_satisfies_sampling(self):
        space = ds.space(
            ds.param("sched")
            .symbolic(_cooling_signature(), _cooling_primitives(), 4)
            .default(_cooling_value())
        )
        assert space.sample_one(seed=0) == {"sched": _cooling_value()}

    def test_symbolic_with_sampler_draws(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(),
                _cooling_primitives(),
                3,
                sampler=lambda rng: _cooling_value(),
            )
        )
        assert space.sample_one(seed=0) == {"sched": _cooling_value()}

    def test_code_always_nongenerative_without_default(self):
        space = ds.space(ds.param("p").code(ds.Signature({}, "bool")))
        with pytest.raises(SamplingError):
            space.sample_one(seed=0)

    def test_code_with_default_satisfies_sampling(self):
        space = ds.space(ds.param("p").code(ds.Signature({}, "bool")).default({"source": "True"}))
        assert space.sample_one(seed=0) == {"p": {"source": "True"}}

    # `freeze` satisfying the non-generative obligation (D-87) needs
    # `ops/_structural.py::_pin_program` — see TestFreeze, added in Stage 2.
    # `.slice()`'s D-87 asymmetry (supported, unlike custom) needs no new
    # code — `_validate_fixed_value` already routes through
    # `program_value_error` (Stage 1) — so its law is testable now.

    def test_slice_removes_the_nongenerative_param(self):
        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4),
            ds.param("x").real(0.0, 1.0),
        )
        sliced = space.slice(sched=_cooling_value())
        assert "sched" not in sliced.params
        sliced.sample_one(seed=0)  # must not raise

    def test_inactive_param_never_triggers_sampling_error(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("sched")
            .symbolic(_cooling_signature(), _cooling_primitives(), 4)
            .when(ds.param("flag") == True),  # noqa: E712
        )
        # An *active* draw legitimately raises (no default/sampler) — that
        # is `test_symbolic_without_default_or_sampler_raises`'s law. What
        # this law asserts is narrower: at least one *inactive* draw must
        # complete with no error and no "sched" key at all.
        found_inactive = False
        for seed in range(20):
            try:
                cfg = space.sample_one(seed=seed)
            except SamplingError:
                continue  # flag=True this draw -- expected, not this law's concern
            if "sched" not in cfg:
                found_inactive = True
        assert found_inactive

    def test_has_nongenerative_params_true_for_symbolic(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        assert space.has_nongenerative_params is True

    def test_has_nongenerative_params_true_for_code(self):
        space = ds.space(ds.param("p").code(ds.Signature({}, "bool")))
        assert space.has_nongenerative_params is True

    def test_has_nongenerative_params_false_once_sampler_given(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(),
                _cooling_primitives(),
                3,
                sampler=lambda rng: _cooling_value(),
            )
        )
        assert space.has_nongenerative_params is False

    def test_has_nongenerative_params_true_under_repeat(self):
        space = ds.space(ds.param("progs").code(ds.Signature({}, "bool")).repeat(3))
        assert space.has_nongenerative_params is True

    def test_has_nongenerative_params_true_under_repeat_symbolic(self):
        space = ds.space(
            ds.param("scheds").symbolic(_cooling_signature(), _cooling_primitives(), 4).repeat(2)
        )
        assert space.has_nongenerative_params is True

    def test_has_nongenerative_params_false_when_no_program_param(self):
        space = ds.space(ds.param("x").integer(0, 10))
        assert space.has_nongenerative_params is False


# -- 6. Identity: round-trip, sugar-equivalence, per-field opacity (D-88) ----


class TestIdentity:
    def test_round_trip_fingerprint_equal(self):
        space = ds.space(
            ds.param("sched")
            .symbolic(_cooling_signature(), _cooling_primitives(), 4)
            .default(_cooling_value())
        )
        round_tripped = ds.Space.from_json(space.to_json())
        assert round_tripped.fingerprint("full") == space.fingerprint("full")

    def test_code_round_trip_fingerprint_equal(self):
        space = ds.space(
            ds.param("p")
            .code(
                ds.Signature({"x": int}, "bool"),
                description="acceptance test",
                constraints=["must terminate"],
                examples=[{"x": 1}],
            )
            .default({"source": "x > 0"})
        )
        round_tripped = ds.Space.from_json(space.to_json())
        assert round_tripped.fingerprint("full") == space.fingerprint("full")

    def test_signature_arg_order_is_fingerprint_relevant(self):
        forward = ds.space(
            ds.param("sched").symbolic(ds.Signature({"a": int, "b": int}, float), ["cos"], 3)
        )
        backward = ds.space(
            ds.param("sched").symbolic(ds.Signature({"b": int, "a": int}, float), ["cos"], 3)
        )
        assert forward.fingerprint("full") != backward.fingerprint("full")

    def test_exact_int_arity_fingerprint_equal_to_equivalent_range(self):
        # The sugar-equivalence law D-89 promises: Primitive("+", 2) and
        # Primitive("+", (2, 2)) are the same declaration, just spelled
        # differently.
        space_int = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), [ds.Primitive("+", 2)], 3)
        )
        space_range = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), [ds.Primitive("+", (2, 2))], 3)
        )
        assert space_int.fingerprint("full") == space_range.fingerprint("full")

    def test_config_hash_distinguishes_different_asts(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        other_value = {"ast": {"op": "pi", "args": []}, "source": "pi"}
        h1 = ds.config_hash({"sched": _cooling_value()}, space)
        h2 = ds.config_hash({"sched": other_value}, space)
        assert h1 != h2

    def test_config_hash_stable_across_dict_key_order(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        value_a = _cooling_value()
        value_b = {"source": value_a["source"], "ast": value_a["ast"]}
        h1 = ds.config_hash({"sched": value_a}, space)
        h2 = ds.config_hash({"sched": value_b}, space)
        assert h1 == h2


class TestOpacityRaiseMarkDrop:
    """Per-field opacity (DECISIONS.md D-88): `validators`/`sampler`/
    `Primitive.fn` ride raise/mark/drop *in place* — never poisoning the
    whole domain the way `.custom(sampler, validator)`'s shorthand does."""

    def test_validators_raise_by_default(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, validators=[lambda ast: True]
            )
        )
        with pytest.raises(SerializationError):
            space.to_json()

    def test_validators_mark_yields_opaque_sentinel(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, validators=[lambda ast: True]
            )
        )
        doc = space.to_json(on_unserializable="mark")
        assert doc["params"][0]["domain"]["validators"] == {"kind": "opaque", "$opaque": True}

    def test_validators_drop_marks_plus_manifest(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, validators=[lambda ast: True]
            )
        )
        doc = space.to_json(on_unserializable="drop")
        assert doc["params"][0]["domain"]["validators"] == {"kind": "opaque", "$opaque": True}
        assert any("validators" in entry for entry in doc["dropped"])

    def test_marked_validators_field_raises_on_decode(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, validators=[lambda ast: True]
            )
        )
        doc = space.to_json(on_unserializable="mark")
        with pytest.raises(SerializationError):
            ds.Space.from_json(doc)

    def test_symbolic_sampler_raises_by_default(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, sampler=lambda rng: _cooling_value()
            )
        )
        with pytest.raises(SerializationError):
            space.to_json()

    def test_symbolic_sampler_mark_and_decode_raises(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), _cooling_primitives(), 4, sampler=lambda rng: _cooling_value()
            )
        )
        doc = space.to_json(on_unserializable="mark")
        assert doc["params"][0]["domain"]["sampler"] == {"kind": "opaque", "$opaque": True}
        with pytest.raises(SerializationError):
            ds.Space.from_json(doc)

    def test_primitive_fn_raises_by_default(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), [ds.Primitive("cos", 1, fn=lambda x: x)], 3
            )
        )
        with pytest.raises(SerializationError):
            space.to_json()

    def test_primitive_fn_drop_marks_that_entry_plus_manifest_naming_it(self):
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), [ds.Primitive("cos", 1, fn=lambda x: x)], 3
            )
        )
        doc = space.to_json(on_unserializable="drop")
        prim_entry = doc["params"][0]["domain"]["primitives"][0]
        assert prim_entry["fn"] == {"kind": "opaque", "$opaque": True}
        assert any("cos" in entry and "fn" in entry for entry in doc["dropped"])

    def test_code_validators_ride_the_same_opacity(self):
        space = ds.space(
            ds.param("p").code(ds.Signature({}, "bool"), validators=[lambda src: True])
        )
        with pytest.raises(SerializationError):
            space.to_json()
        doc = space.to_json(on_unserializable="mark")
        assert doc["params"][0]["domain"]["validators"] == {"kind": "opaque", "$opaque": True}

    def test_structural_fields_alongside_an_opaque_field_still_serialize(self):
        # Only the opaque field degrades -- the rest of the domain (and the
        # rest of that one Primitive entry) is untouched.
        space = ds.space(
            ds.param("sched").symbolic(
                _cooling_signature(), [ds.Primitive("cos", 1, fn=lambda x: x)], 3
            )
        )
        doc = space.to_json(on_unserializable="mark")
        prim_entry = doc["params"][0]["domain"]["primitives"][0]
        assert prim_entry["name"] == "cos"
        assert prim_entry["arity"] == {"lo": 1, "hi": 1}


# -- 7. Freeze / slice (D-87) -------------------------------------------------


class TestFreeze:
    def test_fingerprint_equal_to_hand_written_pin(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        frozen = space.freeze(sched=_cooling_value())
        hand_built = ds.space(
            ds.param("sched")
            .symbolic(_cooling_signature(), _cooling_primitives(), 4)
            .default(_cooling_value())
        ).require(ds.param("sched") == _cooling_value())
        assert frozen.fingerprint("full") == hand_built.fingerprint("full")

    def test_frozen_space_samples_only_the_fixed_value(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        frozen = space.freeze(sched=_cooling_value())
        for cfg in frozen.sample_dicts(10, seed=0):
            assert cfg["sched"] == _cooling_value()

    def test_frozen_space_validates_only_the_fixed_value(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        frozen = space.freeze(sched=_cooling_value())
        assert frozen.validate({"sched": _cooling_value()}).valid
        other = {"ast": {"op": "pi", "args": []}, "source": "pi"}
        assert not frozen.validate({"sched": other}).valid

    def test_freeze_satisfies_the_nongenerative_sampling_error(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        with pytest.raises(SamplingError):
            space.sample_one(seed=0)
        frozen = space.freeze(sched=_cooling_value())
        assert frozen.sample_one(seed=0) == {"sched": _cooling_value()}

    def test_code_freeze_fingerprint_equal_to_hand_written_pin(self):
        sig = ds.Signature({}, "bool")
        value = {"source": "x > 0"}
        space = ds.space(ds.param("p").code(sig))
        frozen = space.freeze(p=value)
        hand_built = ds.space(ds.param("p").code(sig).default(value)).require(
            ds.param("p") == value
        )
        assert frozen.fingerprint("full") == hand_built.fingerprint("full")


class TestSliceUnlikeCustom:
    def test_slice_removes_the_program_param_and_substitutes_at_reference_sites(self):
        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4),
            ds.param("x").real(0.0, 1.0),
        )
        sliced = space.slice(sched=_cooling_value())
        assert "sched" not in sliced.params
        assert sliced.n_params == 1
        sliced.sample_one(seed=0)  # must not raise


# -- 8. Downstream surfaces ----------------------------------------------------


class TestDownstreamSurfaces:
    def test_dataframe_column_is_utf8_json_string(self):
        pl = pytest.importorskip("polars")
        space = ds.space(
            ds.param("sched")
            .symbolic(_cooling_signature(), _cooling_primitives(), 4)
            .default(_cooling_value())
        )
        df = space.sample(5, seed=0)
        assert df.schema["sched"] == pl.Utf8
        import json

        assert json.loads(df["sched"][0]) == _cooling_value()

    def test_flatten_unflatten_round_trip(self):
        space = ds.space(
            ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4),
            ds.param("x").real(0.0, 1.0),
        )
        config = {"sched": _cooling_value(), "x": 0.5}
        flat = ds.flatten(config, space)
        assert flat["sched"] == _cooling_value()
        assert ds.unflatten(flat, space) == config

    def test_apply_defaults_fills_a_program_leaf(self):
        space = ds.space(
            ds.param("sched")
            .symbolic(_cooling_signature(), _cooling_primitives(), 4)
            .default(_cooling_value())
        )
        assert space.apply_defaults({}) == {"sched": _cooling_value()}

    def test_remaining_domain_raises_path_named_type_error(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        with pytest.raises(TypeError, match="'sched'"):
            space.remaining_domain("sched", {})

    def test_cardinality_is_none(self):
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        assert space.cardinality() is None

    def test_is_finite_stays_true_matching_custom_precedent(self):
        # `.is_finite` is a cheap, declaration-only check that is False iff
        # an unquantized real appears anywhere -- it does not (and, for
        # custom, never did) account for an opaque leaf's true enumerability;
        # that is exactly what `.cardinality()` is for. A program-only space
        # is therefore reported "not proven infinite" here, matching custom.
        space = ds.space(ds.param("sched").symbolic(_cooling_signature(), _cooling_primitives(), 4))
        assert space.is_finite is True

    def test_represent_leaves_a_program_param_identical(self):
        space = ds.space(
            ds.param("sched")
            .symbolic(_cooling_signature(), _cooling_primitives(), 4)
            .default(_cooling_value()),
            ds.param("x").real(0.0, 1.0),
        )
        rep = space.represent()
        assert set(rep.target.params) == set(space.params)
        assert rep.target.params["sched"].type_kind == "symbolic"
        result = rep.check()
        assert result.ok

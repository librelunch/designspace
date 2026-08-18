"""The irace translation: placement, names, conditions, forbidden expressions.

`translate(space)` is the one entry point these tests use, and none of them
starts R. The translation is ordinary Python, its conditions and forbidden
entries R expression text, so every rule that decides what irace is handed is
asserted here rather than inside a race.

The text matters more than it does for a binding handing over objects. irace
parses a condition as R and resolves the parameter names it finds, so a name
that is not one R symbol, or a comparison whose operands compare as strings,
fails inside irace rather than here. One assertion per rule keeps the failure
readable when it does.
"""

from __future__ import annotations

from typing import Any

import pytest
from designspace_solvers import UnsupportedSpace
from designspace_solvers.irace import KINDS, translate

import designspace as ds


def _spec(translation: Any, name: str) -> Any:
    """The parameter specification placed under `name`."""
    for spec in translation.params:
        if spec.name == name:
            return spec
    raise AssertionError(f"{name!r} is not among {[s.name for s in translation.params]}")


def _names(translation: Any) -> list[str]:
    return [spec.name for spec in translation.params]


# -- Placement, one case per kind -------------------------------------------


def test_places_a_native_real_parameter() -> None:
    translation = translate(ds.space(ds.param("x").real(0.0, 1.0)))
    spec = _spec(translation, "x")
    assert (spec.type, spec.domain, spec.transf) == ("r", (0.0, 1.0), "")
    assert "x" not in translation.unit_coded


def test_places_a_log_scaled_real_with_iraces_own_transform() -> None:
    translation = translate(ds.space(ds.param("lr").real(1e-4, 1e-1).log_scale()))
    spec = _spec(translation, "lr")
    assert (spec.type, spec.domain, spec.transf) == ("r", (1e-4, 1e-1), "log")
    assert "lr" not in translation.unit_coded


def test_places_a_quantized_real_in_unit_coordinates() -> None:
    space = ds.space(ds.param("wd").real(1e-6, 1e-2).log_scale().quantized(factor=2.0))
    translation = translate(space)
    spec = _spec(translation, "wd")
    assert (spec.type, spec.domain, spec.transf) == ("r", (0.0, 1.0), "")
    assert "wd" in translation.unit_coded


def test_places_a_native_integer_parameter() -> None:
    translation = translate(ds.space(ds.param("n").integer(1, 8)))
    spec = _spec(translation, "n")
    assert (spec.type, spec.domain) == ("i", (1, 8))


def test_places_a_quantized_integer_in_unit_coordinates() -> None:
    space = ds.space(ds.param("n").integer(1, 1024).log_scale().quantized(factor=2.0))
    translation = translate(space)
    spec = _spec(translation, "n")
    assert (spec.type, spec.domain) == ("r", (0.0, 1.0))
    assert "n" in translation.unit_coded


def test_places_a_bool_parameter_as_two_index_strings() -> None:
    translation = translate(ds.space(ds.param("flag").bool()))
    spec = _spec(translation, "flag")
    assert (spec.type, spec.domain) == ("c", ("0", "1"))


def test_places_a_categorical_parameter_by_index() -> None:
    space = ds.space(ds.param("w").categorical("hann", "hamming", "blackman"))
    translation = translate(space)
    spec = _spec(translation, "w")
    assert (spec.type, spec.domain) == ("c", ("0", "1", "2"))
    assert "w" in translation.index_coded


def test_places_an_ordinal_parameter_as_an_integer_over_its_levels() -> None:
    """An index over the levels is the order the levels declare, and irace
    searches an integer the way it searches its own ordinal type. The value is
    a number in R, which is what an order comparison needs and what irace's
    model can fall back to a uniform draw for."""
    space = ds.space(ds.param("level").ordinal("low", "mid", "high"))
    translation = translate(space)
    spec = _spec(translation, "level")
    assert (spec.type, spec.domain) == ("i", (0, 2))
    assert "level" in translation.index_coded


def test_places_a_subset_one_parameter_per_item() -> None:
    space = ds.space(ds.param("s").subset(items=("a", "b", "c")))
    translation = translate(space)
    assert translation.names["s"] == ("s.0", "s.1", "s.2")
    for name in translation.names["s"]:
        assert _spec(translation, name).domain == ("0", "1")


def test_places_a_permutation_by_random_keys() -> None:
    space = ds.space(ds.param("p").permutation(items=("a", "b", "c")))
    translation = translate(space)
    assert translation.names["p"] == ("p.0", "p.1", "p.2")
    for name in translation.names["p"]:
        assert _spec(translation, name).domain == (0.0, 1.0)


def test_places_a_static_scalar_list_one_parameter_per_index() -> None:
    space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(3))
    translation = translate(space)
    assert [n for n in _names(translation) if n.startswith("xs")] == ["xs.0", "xs.1", "xs.2"]


def test_dynamic_length_list_is_refused() -> None:
    space = ds.space(
        ds.param("n").integer(1, 5),
        ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
    )
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    assert "xs" in str(excinfo.value)


def test_kinds_covers_every_generative_kind() -> None:
    assert "custom" not in KINDS
    assert "symbolic" not in KINDS
    assert "code" not in KINDS
    assert {"real", "integer", "bool", "categorical", "ordinal"} <= KINDS


# -- Names ------------------------------------------------------------------


def test_a_bracket_path_mangles_to_one_r_symbol() -> None:
    """A definition path is not an R name. irace resolves the parameters a
    condition names, so every placed name has to parse as a single symbol."""
    space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(2))
    translation = translate(space)
    for name in _names(translation):
        assert "[" not in name and "]" not in name


def test_a_struct_field_path_mangles_to_one_r_symbol() -> None:
    space = ds.space(
        ds.param("workers").space(ds.space(ds.param("timeout_s").real(0.1, 10.0))).repeat(2)
    )
    translation = translate(space)
    assert "workers.0.timeout_s" in _names(translation)


def test_the_name_map_inverts_on_decode() -> None:
    space = ds.space(ds.param("xs").integer(0, 9).repeat(2))
    translation = translate(space)
    decoded = translation.decode({"xs.0": 3, "xs.1": 7})
    assert decoded == {"xs": [3, 7]}


def test_a_path_mangling_to_an_r_reserved_word_is_refused() -> None:
    """`if` is a legal parameter name and an R keyword. A condition naming it
    would not parse, so it is refused where the name is placed."""
    space = ds.space(ds.param("if").real(0.0, 1.0))
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    assert "if" in str(excinfo.value)


@pytest.mark.parametrize("name", ["my-param", "2fast", "x y"], ids=["dash", "digit", "space"])
def test_a_path_that_is_not_an_r_symbol_is_refused(name: str) -> None:
    """Core reserves only `.`, `[` and `]`, so a legal parameter name need not
    be a legal R one. `my-param` parses as a subtraction, `2fast` cannot open
    an identifier, and a space ends one."""
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(ds.space(ds.param(name).real(0.0, 1.0)))
    assert name in str(excinfo.value)


# -- Conditions -------------------------------------------------------------


def test_condition_on_a_bare_bool_parent() -> None:
    space = ds.space(
        ds.param("warmup").bool(),
        ds.param("steps").integer(1, 100).when(ds.param("warmup")),
    )
    assert _spec(translate(space), "steps").condition == 'warmup == "1"'


def test_condition_equals_categorical_parent_compares_the_index() -> None:
    space = ds.space(
        ds.param("algo").categorical("as", "mmas", "acs"),
        ds.param("q0").real(0.0, 1.0).when(ds.param("algo") == "acs"),
    )
    assert _spec(translate(space), "q0").condition == 'algo == "2"'


def test_condition_is_in_becomes_an_r_membership_test() -> None:
    space = ds.space(
        ds.param("algo").categorical("as", "mmas", "acs"),
        ds.param("q0").real(0.0, 1.0).when(ds.param("algo").is_in("as", "acs")),
    )
    assert _spec(translate(space), "q0").condition == 'algo %in% c("0", "2")'


def test_condition_comparing_an_integer_parent_needs_no_coercion() -> None:
    space = ds.space(
        ds.param("n").integer(1, 10),
        ds.param("x").real(0.0, 1.0).when(ds.param("n") > 3),
    )
    assert _spec(translate(space), "x").condition == "n > 3"


def test_condition_ordering_an_ordinal_compares_numbers() -> None:
    """The trap an integer placement avoids: R reads `"10" >= "2"` as FALSE,
    so an order comparison over index strings would silently drop every level
    past nine."""
    space = ds.space(
        ds.param("level").ordinal(*[str(i) for i in range(12)]),
        ds.param("x").real(0.0, 1.0).when(ds.param("level") >= "10"),
    )
    assert _spec(translate(space), "x").condition == "level >= 10"


def test_condition_equality_on_an_ordinal_compares_numbers_too() -> None:
    """One wire form per parameter, whichever comparison reads it."""
    space = ds.space(
        ds.param("level").ordinal("low", "mid", "high"),
        ds.param("x").real(0.0, 1.0).when(ds.param("level") == "mid"),
    )
    assert _spec(translate(space), "x").condition == "level == 1"


def test_a_conditional_ordinal_is_an_integer_irace_can_sample_without_an_elite() -> None:
    """irace draws a new configuration from an elite, and an elite that left
    this parameter inactive supplies no value for the model to centre on. Its
    integer sampler falls back to a uniform draw over the domain where its
    ordinal sampler yields nothing, so the level is placed as an integer."""
    space = ds.space(
        ds.param("use").bool(),
        ds.param("level").ordinal("low", "mid", "high").when(ds.param("use")),
    )
    spec = _spec(translate(space), "level")
    assert (spec.type, spec.domain, spec.condition) == ("i", (0, 2), 'use == "1"')


def test_condition_conjunction_and_disjunction() -> None:
    space = ds.space(
        ds.param("a").bool(),
        ds.param("b").bool(),
        ds.param("x").real(0.0, 1.0).when(ds.param("a") & ds.param("b")),
        ds.param("y").real(0.0, 1.0).when(ds.param("a") | ds.param("b")),
    )
    translation = translate(space)
    assert _spec(translation, "x").condition == '(a == "1") & (b == "1")'
    assert _spec(translation, "y").condition == '(a == "1") | (b == "1")'


def test_condition_negation() -> None:
    space = ds.space(
        ds.param("a").bool(),
        ds.param("x").real(0.0, 1.0).when(~ds.param("a")),
    )
    assert _spec(translate(space), "x").condition == 'a == "0"'


def test_condition_on_a_unit_coded_parent_is_refused() -> None:
    """A literal marks a cell edge in unit coordinates, so the comparison
    would not mean what the space declared."""
    space = ds.space(
        ds.param("wd").real(1e-6, 1e-2).log_scale().quantized(factor=2.0),
        ds.param("x").real(0.0, 1.0).when(ds.param("wd") > 1e-4),
    )
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    assert "wd" in str(excinfo.value)


def test_every_untranslatable_condition_is_reported_at_once() -> None:
    space = ds.space(
        ds.param("wd").real(1e-6, 1e-2).log_scale().quantized(factor=2.0),
        ds.param("x").real(0.0, 1.0).when(ds.param("wd") > 1e-4),
        ds.param("y").real(0.0, 1.0).when(ds.param("wd") < 1e-3),
    )
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    message = str(excinfo.value)
    assert "x" in message and "y" in message


# -- Forbidden expressions --------------------------------------------------


def test_a_hard_constraint_becomes_a_forbidden_expression() -> None:
    space = ds.space(
        ds.param("a").integer(0, 10),
        ds.param("b").integer(0, 10),
    ).forbid((ds.param("a") == 0) & (ds.param("b") == 0))
    assert translate(space).forbidden == ("(a == 0) & (b == 0)",)


def test_a_require_constraint_is_forbidden_as_its_negation() -> None:
    """Negation is pushed into the comparison rather than wrapped around it,
    so what irace logs reads the way the space was declared."""
    space = ds.space(ds.param("a").integer(0, 10)).require(ds.param("a") > 3)
    assert translate(space).forbidden == ("a <= 3",)


def test_an_order_comparison_needs_no_disjunction_workaround() -> None:
    """ConfigSpace has no usable `<=` clause and builds one from two; R has
    the operator."""
    space = ds.space(ds.param("a").integer(0, 10)).forbid(ds.param("a") >= 7)
    assert translate(space).forbidden == ("a >= 7",)


def test_a_comparison_between_two_parameters_translates() -> None:
    space = ds.space(
        ds.param("lo").integer(0, 10),
        ds.param("hi").integer(0, 10),
    ).forbid(ds.param("lo") > ds.param("hi"))
    assert translate(space).forbidden == ("lo > hi",)


def test_an_arithmetic_constraint_translates() -> None:
    """The reach the ConfigSpace binding reports as untranslated instead."""
    space = ds.space(
        ds.param("lr").real(1e-4, 1e-1),
        ds.param("steps").integer(1, 100),
    ).forbid(ds.param("lr") * ds.param("steps") > 1.0)
    translation = translate(space)
    assert translation.forbidden == ("(lr * steps) > 1.0",)
    assert translation.untranslated_constraints == ()


def test_a_subsets_size_bounds_become_forbidden_expressions() -> None:
    """One flag per item loses the size the domain declares, so the sum of the
    flags carries it back. Without this a race returns configurations the
    space calls out of bounds."""
    space = ds.space(ds.param("s").subset(items=("a", "b", "c"), min_size=1, max_size=2))
    total = "as.numeric(s.0) + as.numeric(s.1) + as.numeric(s.2)"
    assert translate(space).forbidden == (f"({total}) < 1", f"({total}) > 2")


def test_an_unbounded_subset_forbids_nothing() -> None:
    """A subset admitting every size states no bound to carry."""
    space = ds.space(ds.param("s").subset(items=("a", "b", "c")))
    assert translate(space).forbidden == ()


def test_an_untranslatable_constraint_is_reported_rather_than_raised() -> None:
    """A subset sits across one parameter per item, so an aggregate over it
    has no operand to name. Reported, never raised: the search may propose a
    configuration the space calls infeasible, and never loses a feasible one."""
    space = ds.space(ds.param("s").subset(items=("a", "b", "c"))).forbid(ds.param("s").size() > 2)
    translation = translate(space)
    assert len(translation.untranslated_constraints) == 1
    assert translation.forbidden == ()


# -- decode and encode ------------------------------------------------------


def test_decode_reads_a_configuration_back_into_domain_units() -> None:
    space = ds.space(
        ds.param("lr").real(1e-4, 1e-1).log_scale(),
        ds.param("w").categorical("hann", "hamming"),
        ds.param("flag").bool(),
    )
    translation = translate(space)
    config = translation.decode({"lr": 0.01, "w": "1", "flag": "0"})
    assert config == {"lr": 0.01, "w": "hamming", "flag": False}
    assert space.is_complete(config)


def test_decode_omits_a_parameter_its_condition_left_inactive() -> None:
    space = ds.space(
        ds.param("warmup").bool(),
        ds.param("steps").integer(1, 100).when(ds.param("warmup")),
    )
    translation = translate(space)
    assert translation.decode({"warmup": "0", "steps": None}) == {"warmup": False}


@pytest.mark.parametrize(
    "space",
    [
        ds.space(ds.param("x").real(0.0, 1.0), ds.param("n").integer(1, 8)),
        ds.space(ds.param("w").categorical("a", "b", "c")),
        ds.space(ds.param("level").ordinal("low", "mid", "high")),
        ds.space(ds.param("s").subset(items=("a", "b", "c"))),
        ds.space(ds.param("p").permutation(items=("a", "b", "c"))),
        ds.space(ds.param("xs").real(0.0, 1.0).repeat(3)),
        ds.space(ds.param("workers").space(ds.space(ds.param("t").integer(1, 60))).repeat(2)),
    ],
    ids=["scalars", "categorical", "ordinal", "subset", "permutation", "list", "struct"],
)
def test_encode_and_decode_round_trip(space: ds.Space) -> None:
    translation = translate(space)
    for seed in range(10):
        config = space.sample_one(seed=seed)
        assert translation.decode(translation.encode(config)) == config


def test_an_rpy2_that_cannot_find_r_says_so_rather_than_reporting_rpy2_absent() -> None:
    """Two prerequisites, reported apart. rpy2 installs without R and locates
    one as it imports, so an interpreter started outside the environment R was
    installed into imports rpy2 and reaches no R. The refusal names what to
    set rather than repeating rpy2's own diagnostic."""
    situation = pytest.importorskip("rpy2.situation")
    from designspace_solvers.irace import _require_rpy2

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(situation, "get_r_home", lambda: None)
        with pytest.raises(RuntimeError) as caught:
            _require_rpy2()

    message = str(caught.value)
    assert "R_HOME" in message
    assert "PATH" in message
    # Not the report for an absent rpy2, which names the extra that installs it.
    assert "designspace-solvers[irace]" not in message

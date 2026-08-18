"""The ConfigSpace translation: placement, conditions, forbidden clauses.

`translate(space)` is the one entry point. These tests exercise it at the
grain `test_backends.py` does not: one assertion per placement rule, one per
recognized condition and forbidden-clause form, and one per refusal, so a
regression here names the exact rule that broke rather than an end-to-end
fixture failing for an unclear reason.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("ConfigSpace")

from designspace_solvers import UnsupportedSpace
from designspace_solvers.configspace import KINDS, translate

import designspace as ds


def _decode_many(translation: Any, n: int, seed: int = 0) -> list[dict[str, Any]]:
    translation.config_space.seed(seed)
    return [translation.decode(translation.config_space.sample_configuration()) for _ in range(n)]


# -- Placement, one case per kind -------------------------------------------


def test_places_a_native_real_parameter() -> None:
    space = ds.space(ds.param("x").real(0.0, 1.0))
    translation = translate(space)
    hp = translation.config_space["x"]
    assert (hp.lower, hp.upper) == (0.0, 1.0)
    assert "x" not in translation.unit_coded


def test_places_a_log_scaled_real_through_its_chart() -> None:
    space = ds.space(ds.param("lr").real(1e-4, 1e-1).log_scale())
    translation = translate(space)
    hp = translation.config_space["lr"]
    assert (hp.lower, hp.upper) == (1e-4, 1e-1)
    assert hp.log is True
    assert "lr" not in translation.unit_coded


def test_places_a_quantized_real_in_unit_coordinates() -> None:
    space = ds.space(ds.param("wd").real(1e-6, 1e-2).log_scale().quantized(factor=2.0))
    translation = translate(space)
    hp = translation.config_space["wd"]
    assert (hp.lower, hp.upper) == (0.0, 1.0)
    assert "wd" in translation.unit_coded
    for config in _decode_many(translation, 30):
        assert space.validate(config).valid


def test_places_a_native_integer_parameter() -> None:
    space = ds.space(ds.param("n").integer(1, 8))
    translation = translate(space)
    hp = translation.config_space["n"]
    assert (hp.lower, hp.upper) == (1, 8)
    assert "n" not in translation.unit_coded


def test_places_a_quantized_integer_in_unit_coordinates() -> None:
    space = ds.space(ds.param("batch").integer(16, 512).quantized(step=16))
    translation = translate(space)
    assert "batch" in translation.unit_coded
    for config in _decode_many(translation, 30):
        assert space.validate(config).valid


def test_places_a_bool_parameter() -> None:
    space = ds.space(ds.param("flag").bool())
    translation = translate(space)
    for config in _decode_many(translation, 20):
        assert isinstance(config["flag"], bool)
        assert space.validate(config).valid


def test_places_a_categorical_parameter_by_index() -> None:
    space = ds.space(ds.param("opt").categorical("sgd", "adam", "rmsprop"))
    translation = translate(space)
    assert "opt" in translation.index_coded
    seen = {c["opt"] for c in _decode_many(translation, 50)}
    assert seen <= {"sgd", "adam", "rmsprop"}
    for config in _decode_many(translation, 20):
        assert type(config["opt"]) is str
        assert space.validate(config).valid


def test_places_an_ordinal_parameter_keeping_order() -> None:
    space = ds.space(ds.param("size").ordinal("small", "medium", "large"))
    translation = translate(space)
    hp = translation.config_space["size"]
    assert list(hp.sequence) == [0, 1, 2]
    for config in _decode_many(translation, 20):
        assert config["size"] in ("small", "medium", "large")
        assert space.validate(config).valid


def test_places_a_choice_parameter_and_its_members() -> None:
    space = ds.space(
        ds.param("algo").choice(
            greedy=ds.space(),
            exact=ds.space(ds.param("depth").integer(1, 10)),
        )
    )
    translation = translate(space)
    for config in _decode_many(translation, 30):
        assert space.is_complete(config)
        assert not space.validate(config).param_errors
        payload = ds.payload(config, "algo") or {}
        assert ("depth" in payload) == (ds.variant(config, "algo") == "exact")


def test_places_a_subset_one_hyperparameter_per_item() -> None:
    space = ds.space(ds.param("s").subset(items=("a", "b", "c"), min_size=1, max_size=2))
    translation = translate(space)
    for name in ("s[0]", "s[1]", "s[2]"):
        assert name in translation.config_space
    for config in _decode_many(translation, 50):
        assert isinstance(config["s"], list)
        assert set(config["s"]) <= {"a", "b", "c"}


def test_places_a_permutation_by_random_keys() -> None:
    space = ds.space(ds.param("order").permutation(items=("a", "b", "c")))
    translation = translate(space)
    for name in ("order[0]", "order[1]", "order[2]"):
        assert name in translation.config_space
    for config in _decode_many(translation, 20):
        assert sorted(config["order"]) == ["a", "b", "c"]


def test_places_a_static_scalar_list_one_hyperparameter_per_index() -> None:
    space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(3))
    translation = translate(space)
    assert sorted(translation.config_space.keys()) == ["xs[0]", "xs[1]", "xs[2]"]
    for config in _decode_many(translation, 30):
        assert len(config["xs"]) == 3
        assert space.validate(config).valid


def test_places_a_static_list_of_each_scalar_element_kind() -> None:
    space = ds.space(
        ds.param("reals").real(1e-4, 1e-1).log_scale().repeat(2),
        ds.param("ints").integer(1, 8).repeat(2),
        ds.param("bools").bool().repeat(2),
        ds.param("cats").categorical("a", "b", "c").repeat(2),
        ds.param("ords").ordinal("small", "large").repeat(2),
        ds.param("subsets").subset(items=("x", "y")).repeat(2),
        ds.param("perms").permutation(items=("p", "q")).repeat(2),
    )
    translation = translate(space)
    for config in _decode_many(translation, 30):
        assert space.is_complete(config)
        assert not space.validate(config).param_errors


def test_places_a_list_of_subsets_with_nested_bracket_paths() -> None:
    space = ds.space(ds.param("ss").subset(items=("a", "b")).repeat(2))
    translation = translate(space)
    assert sorted(translation.config_space.keys()) == [
        "ss[0][0]",
        "ss[0][1]",
        "ss[1][0]",
        "ss[1][1]",
    ]
    for config in _decode_many(translation, 30):
        assert len(config["ss"]) == 2
        for item in config["ss"]:
            assert set(item) <= {"a", "b"}


def test_list_round_trips_encode_and_decode() -> None:
    space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(3))
    translation = translate(space)
    for config in _decode_many(translation, 30):
        again = translation.decode(translation.encode(config))
        assert again == config


def test_dynamic_length_list_is_refused() -> None:
    space = ds.space(
        ds.param("n").integer(1, 5),
        ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
    )
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    assert [r.path for r in excinfo.value.rejections] == ["xs"]
    assert "fixed width" in str(excinfo.value)


@pytest.mark.parametrize("count", [1, 3])
def test_conditional_static_list_gates_every_index(count: int) -> None:
    """A conditional lift gates each index it placed on the same condition,
    so ConfigSpace withholds the whole list together. Width one is the case
    that reads like a scalar and is not one: a lift's own flat key holds a
    length, which no hyperparameter under it represents.
    """
    space = ds.space(
        ds.param("use").bool(),
        ds.param("xs").real(0.0, 1.0).repeat(count).when(ds.param("use")),
    )
    translation = translate(space)
    seen = set()
    for config in _decode_many(translation, 60):
        assert ("xs" in config) == config["use"]
        assert space.is_complete(config)
        assert translation.decode(translation.encode(config)) == config
        seen.add(config["use"])
    assert seen == {False, True}


def test_conditional_struct_gates_each_field() -> None:
    """A struct places no hyperparameter of its own, so its condition reaches
    ConfigSpace through the fields core copied it onto rather than through
    anything this binding gates directly.
    """
    space = ds.space(
        ds.param("on").bool(),
        ds.param("cfg").space(ds.space(ds.param("k").integer(1, 5))).when(ds.param("on")),
    )
    translation = translate(space)
    for config in _decode_many(translation, 60):
        assert ("cfg" in config) == config["on"]
        assert space.is_complete(config)


def test_conditional_subset_gates_every_item() -> None:
    space = ds.space(
        ds.param("on").bool(),
        ds.param("s").subset(items=("a", "b", "c")).when(ds.param("on")),
    )
    translation = translate(space)
    for config in _decode_many(translation, 60):
        assert ("s" in config) == config["on"]
        assert space.is_complete(config)


def test_conditional_choice_lift_combines_both_conditions() -> None:
    """A payload inside a conditional lift of choices is active only where
    the lift is active and that instance chose the variant. That is two
    conditions on one hyperparameter, which ConfigSpace takes as a single
    conjunction rather than as two parent conditions.
    """
    space = ds.space(
        ds.param("on").bool(),
        ds.param("choices")
        .choice(a=ds.space(), b=ds.space(ds.param("v").integer(1, 5)))
        .repeat(2)
        .when(ds.param("on")),
    )
    translation = translate(space)
    assert len(translation.config_space.parent_conditions_of["choices[0].b.v"]) == 1
    for config in _decode_many(translation, 80):
        assert ("choices" in config) == config["on"]
        assert space.is_complete(config)
        assert not space.validate(config).param_errors
        assert translation.decode(translation.encode(config)) == config


def test_places_a_struct_lift_field() -> None:
    space = ds.space(
        ds.param("workers").space(ds.space(ds.param("timeout_s").integer(1, 3600))).repeat(3)
    )
    translation = translate(space)
    assert sorted(translation.config_space.keys()) == [
        "workers[0].timeout_s",
        "workers[1].timeout_s",
        "workers[2].timeout_s",
    ]
    for config in _decode_many(translation, 30):
        assert space.is_complete(config)
        assert not space.validate(config).param_errors
        again = translation.decode(translation.encode(config))
        assert again == config


def test_places_a_choice_lift_with_an_instance_scoped_discriminator() -> None:
    """The relocated discriminator-equality condition, `choices[] == 'b'`,
    is rewritten per instance rather than left referencing the template."""
    space = ds.space(
        ds.param("choices").choice(a=ds.space(), b=ds.space(ds.param("v").integer(1, 5))).repeat(2)
    )
    translation = translate(space)
    assert sorted(translation.config_space.keys()) == [
        "choices[0]",
        "choices[0].b.v",
        "choices[1]",
        "choices[1].b.v",
    ]
    for config in _decode_many(translation, 40):
        assert space.is_complete(config)
        assert not space.validate(config).param_errors
        for element in config["choices"]:
            assert ("v" in element.get("b", {})) == ("b" in element)
        again = translation.decode(translation.encode(config))
        assert again == config


def test_places_a_nested_choice_within_a_struct_lift_element() -> None:
    space = ds.space(
        ds.param("workers")
        .space(
            ds.space(
                ds.param("mode").choice(
                    fast=ds.space(), careful=ds.space(ds.param("retries").integer(1, 5))
                )
            )
        )
        .repeat(2)
    )
    translation = translate(space)
    for config in _decode_many(translation, 30):
        assert space.is_complete(config)
        assert not space.validate(config).param_errors


def test_places_a_nested_static_list_within_a_struct_lift_field() -> None:
    space = ds.space(
        ds.param("workers").space(ds.space(ds.param("items").real(0.0, 1.0).repeat(2))).repeat(2)
    )
    translation = translate(space)
    assert sorted(translation.config_space.keys()) == [
        "workers[0].items[0]",
        "workers[0].items[1]",
        "workers[1].items[0]",
        "workers[1].items[1]",
    ]
    for config in _decode_many(translation, 20):
        assert space.is_complete(config)
        assert not space.validate(config).param_errors


def test_places_a_nested_list_of_scalar_lists() -> None:
    space = ds.space(ds.param("m").real(0.0, 1.0).repeat(2).repeat(3))
    translation = translate(space)
    assert sorted(translation.config_space.keys()) == [
        f"m[{i}][{j}]" for i in range(3) for j in range(2)
    ]
    for config in _decode_many(translation, 20):
        assert space.is_complete(config)
        assert len(config["m"]) == 3
        assert all(len(row) == 2 for row in config["m"])


def test_struct_lift_element_constraints_translate_to_forbidden_clauses() -> None:
    """A hard constraint declared inside a struct element's own space is
    realized once per instance, `element_constraints` never appearing on
    `space.constraints` itself for `_apply_forbidden` to find directly."""
    space = ds.space(
        ds.param("rows")
        .space(
            ds.space(ds.param("a").integer(0, 10), ds.param("b").integer(0, 10)).forbid(
                ds.param("a") > ds.param("b")
            )
        )
        .repeat(2)
    )
    translation = translate(space)
    assert not translation.untranslated_constraints
    for config in _decode_many(translation, 50):
        for row in config["rows"]:
            assert row["a"] <= row["b"]


def test_list_of_struct_or_choice_default_seeds_the_instance() -> None:
    space = ds.space(
        ds.param("choices").choice(a=ds.space(), b=ds.space(ds.param("v").integer(1, 5))).repeat(2)
    )
    translation = translate(space, default={"choices": [{"b": {"v": 4}}, {"a": {}}]})
    default_config = translation.decode(translation.config_space.get_default_configuration())
    assert default_config == {"choices": [{"b": {"v": 4}}, {"a": {}}]}


def test_list_default_seeds_each_index() -> None:
    space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(3).default([0.1, 0.2, 0.9]))
    translation = translate(space)
    default_config = translation.decode(translation.config_space.get_default_configuration())
    assert default_config["xs"] == pytest.approx([0.1, 0.2, 0.9])


def test_kinds_includes_list_but_not_program_or_custom_kinds() -> None:
    assert "list" in KINDS
    assert "symbolic" not in KINDS
    assert "code" not in KINDS
    assert "custom" not in KINDS


# -- Conditions ---------------------------------------------------------


def test_condition_bare_bool_parent() -> None:
    space = ds.space(
        ds.param("use_warmup").bool(),
        ds.param("warmup_steps").integer(1, 100).when(ds.param("use_warmup")),
    )
    translation = translate(space)
    for config in _decode_many(translation, 40):
        assert ("warmup_steps" in config) == config["use_warmup"]


def test_condition_equals_categorical_parent() -> None:
    space = ds.space(
        ds.param("optimizer").categorical("sgd", "adam"),
        ds.param("nesterov").bool().when(ds.param("optimizer") == "sgd"),
    )
    translation = translate(space)
    for config in _decode_many(translation, 40):
        assert ("nesterov" in config) == (config["optimizer"] == "sgd")


def test_condition_not_equals() -> None:
    space = ds.space(
        ds.param("optimizer").categorical("sgd", "adam", "rmsprop"),
        ds.param("extra").bool().when(ds.param("optimizer") != "sgd"),
    )
    translation = translate(space)
    for config in _decode_many(translation, 40):
        assert ("extra" in config) == (config["optimizer"] != "sgd")


def test_condition_is_in() -> None:
    space = ds.space(
        ds.param("optimizer").categorical("sgd", "adam", "rmsprop"),
        ds.param("extra").bool().when(ds.param("optimizer").is_in("adam", "rmsprop")),
    )
    translation = translate(space)
    for config in _decode_many(translation, 40):
        assert ("extra" in config) == (config["optimizer"] in ("adam", "rmsprop"))


def test_condition_comparison_on_integer_parent() -> None:
    space = ds.space(
        ds.param("depth").integer(1, 10),
        ds.param("prune").bool().when(ds.param("depth") > 5),
    )
    translation = translate(space)
    for config in _decode_many(translation, 60):
        assert ("prune" in config) == (config["depth"] > 5)


def test_condition_and_conjunction() -> None:
    space = ds.space(
        ds.param("a").bool(),
        ds.param("b").bool(),
        ds.param("both").integer(0, 1).when(ds.param("a") & ds.param("b")),
    )
    translation = translate(space)
    for config in _decode_many(translation, 60):
        assert ("both" in config) == (config["a"] and config["b"])


def test_condition_or_conjunction() -> None:
    space = ds.space(
        ds.param("a").bool(),
        ds.param("b").bool(),
        ds.param("either").integer(0, 1).when(ds.param("a") | ds.param("b")),
    )
    translation = translate(space)
    for config in _decode_many(translation, 60):
        assert ("either" in config) == (config["a"] or config["b"])


def test_condition_implies_desugars() -> None:
    space = ds.space(
        ds.param("a").bool(),
        ds.param("b").bool(),
        ds.param("c").integer(0, 1).when(ds.param("a").implies(ds.param("b"))),
    )
    translation = translate(space)
    for config in _decode_many(translation, 60):
        assert ("c" in config) == ((not config["a"]) or config["b"])


def test_choice_discriminator_condition_translates() -> None:
    space = ds.space(
        ds.param("algo").choice(
            greedy=ds.space(),
            exact=ds.space(ds.param("depth").integer(1, 10)),
        )
    )
    translation = translate(space)
    cond = translation.config_space.parent_conditions_of["algo.exact.depth"]
    assert len(cond) == 1


def test_condition_referencing_two_params_is_refused() -> None:
    space = ds.space(
        ds.param("a").integer(0, 10),
        ds.param("b").integer(0, 10),
        ds.param("c").integer(0, 1).when(ds.param("a") < ds.param("b")),
    )
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    assert "c" in str(excinfo.value)


def test_condition_on_a_unit_coded_parent_is_refused() -> None:
    """A quantized parent sits in unit coordinates, where a literal marks a
    cell edge rather than the value itself, so gating on it would put the
    boundary cell on the wrong side of the condition."""
    space = ds.space(
        ds.param("batch").integer(16, 512).quantized(step=16),
        ds.param("extra").bool().when(ds.param("batch") > 256),
    )
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    assert [r.path for r in excinfo.value.rejections] == ["extra"]


def test_every_untranslatable_condition_is_reported_at_once() -> None:
    """A space is not fixed one parameter per run, so both offending paths
    come back from one call rather than the first alone."""
    space = ds.space(
        ds.param("a").integer(0, 10),
        ds.param("b").integer(0, 10),
        ds.param("c").integer(0, 1).when(ds.param("a") < ds.param("b")),
        ds.param("d").integer(0, 1).when(ds.param("a") >= 5),
    )
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    assert [r.path for r in excinfo.value.rejections] == ["c", "d"]


def test_condition_on_ds_value_is_refused() -> None:
    space = ds.space(
        ds.param("a").integer(0, 10),
        ds.param("b")
        .integer(0, 1)
        .when(ds.value(lambda x: x % 2 == 0, ds.param("a"), returns=bool)),
    )
    with pytest.raises(UnsupportedSpace) as excinfo:
        translate(space)
    assert "b" in str(excinfo.value)


# -- Subset size bounds -----------------------------------------------------


def test_a_bounded_subset_never_samples_outside_its_size() -> None:
    """A subset sits across one hyperparameter per item, which on its own
    admits every combination. The declared size has to survive that."""
    space = ds.space(ds.param("s").subset(items=("a", "b", "c", "d", "e"), min_size=1, max_size=3))
    translation = translate(space)
    for config in _decode_many(translation, 200):
        assert 1 <= len(config["s"]) <= 3, config
        assert not space.validate(config).param_errors


def test_a_bounded_subset_still_reaches_every_admissible_size() -> None:
    """Excluding the sizes outside the bounds excludes nothing inside them."""
    space = ds.space(ds.param("s").subset(items=("a", "b", "c", "d", "e"), min_size=1, max_size=3))
    translation = translate(space)
    sizes = {len(config["s"]) for config in _decode_many(translation, 200)}
    assert sizes == {1, 2, 3}


def test_a_bounded_subset_inside_a_static_lift_bounds_each_instance() -> None:
    """Each unrolled instance carries the bound its element declares."""
    space = ds.space(ds.param("ss").subset(items=("a", "b", "c"), min_size=2).repeat(2))
    translation = translate(space)
    for config in _decode_many(translation, 100):
        for item in config["ss"]:
            assert len(item) >= 2, config


def test_an_unbounded_subset_adds_no_clause() -> None:
    """A subset admitting every size states nothing to exclude."""
    space = ds.space(ds.param("s").subset(items=("a", "b", "c")))
    translation = translate(space)
    assert not list(translation.config_space.forbidden_clauses)


def test_a_subset_whose_bounds_need_too_many_clauses_is_refused() -> None:
    """ConfigSpace states a forbidden combination one at a time, so a bound
    over many items costs combinatorially many. Past the cap the parameter is
    refused rather than translated with the bound dropped."""
    items = tuple(f"i{n}" for n in range(40))
    space = ds.space(ds.param("s").subset(items=items, min_size=8, max_size=20))
    with pytest.raises(UnsupportedSpace) as caught:
        translate(space)
    assert "s" in {r.path for r in caught.value.rejections}


# -- Forbidden clauses ----------------------------------------------------


def test_forbid_translates_to_a_forbidden_clause() -> None:
    space = ds.space(ds.param("a").integer(0, 10)).forbid(ds.param("a") > 5)
    translation = translate(space)
    assert not translation.untranslated_constraints
    for config in _decode_many(translation, 60):
        assert config["a"] <= 5


def test_require_negates_into_a_forbidden_clause() -> None:
    space = ds.space(ds.param("a").integer(0, 10), ds.param("b").integer(0, 10)).require(
        ds.param("a") < ds.param("b")
    )
    # Both params default to their range's midpoint, 5, which the constraint
    # itself forbids (5 < 5 is False); ConfigurationSpace validates its own
    # default eagerly, so a caller in this situation supplies one that fits.
    translation = translate(space, default={"a": 2, "b": 8})
    assert not translation.untranslated_constraints
    for config in _decode_many(translation, 60):
        assert config["a"] < config["b"]


def test_forbid_between_two_parameters() -> None:
    space = ds.space(ds.param("a").integer(0, 10), ds.param("b").integer(0, 10)).forbid(
        ds.param("a") > ds.param("b"), tags=("ordering",)
    )
    translation = translate(space)
    assert not translation.untranslated_constraints
    for config in _decode_many(translation, 60):
        assert config["a"] <= config["b"]


def test_native_log_scaled_literal_stays_in_domain_units() -> None:
    """A log-scaled real with no grid is placed as ConfigSpace's own
    log-distributed `Float`, so a clause over it carries the declared value
    rather than a unit coordinate."""
    space = ds.space(ds.param("lr").real(1e-5, 1.0).log_scale()).forbid(ds.param("lr") > 0.5)
    translation = translate(space)
    assert not translation.unit_coded
    assert not translation.untranslated_constraints
    for config in _decode_many(translation, 60):
        assert config["lr"] <= 0.5 + 1e-9


@pytest.mark.parametrize(
    ("build", "feasible"),
    [
        (lambda: ds.space(ds.param("x").integer(0, 10)).require(ds.param("x") > 5), (6, 11)),
        (lambda: ds.space(ds.param("x").integer(0, 10)).forbid(ds.param("x") <= 5), (6, 11)),
        (lambda: ds.space(ds.param("x").integer(0, 10)).require(ds.param("x") < 5), (0, 5)),
        (lambda: ds.space(ds.param("x").integer(0, 10)).forbid(ds.param("x") >= 5), (0, 5)),
    ],
    ids=["require_gt", "forbid_le", "require_lt", "forbid_ge"],
)
def test_non_strict_comparison_forbids_exactly_the_region_it_names(
    build: Any, feasible: tuple[int, int]
) -> None:
    """`>=` and `<=` are built from the strict clause and the equality clause
    rather than from ConfigSpace's own non-strict pair, which compares one
    way where it samples and the other way where it validates. The boundary
    value is what tells the two apart, so the whole feasible set is asserted
    rather than a bound on it.
    """
    space = build()
    lo, hi = feasible
    translation = translate(space, default={"x": lo})
    assert not translation.untranslated_constraints
    assert {c["x"] for c in _decode_many(translation, 200)} == set(range(lo, hi))


def test_unit_coded_comparison_is_reported_rather_than_narrowing_the_search() -> None:
    """A quantized parameter sits in unit coordinates, where a literal marks
    the edge of the cell that decodes to it. A clause there would drop that
    whole cell, hiding a feasible value from the search instead of relaxing
    anything, so the constraint is reported and the boundary stays reachable.
    """
    space = ds.space(ds.param("batch").integer(16, 512).quantized(step=16)).forbid(
        ds.param("batch") > 256
    )
    translation = translate(space)
    assert "batch" in translation.unit_coded
    assert [c.kind for c in translation.untranslated_constraints] == ["forbid"]
    assert not translation.config_space.forbidden_clauses
    assert 256 in {c["batch"] for c in _decode_many(translation, 200)}


def test_translation_writes_nothing_to_a_caller_s_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ConfigSpace's own non-strict clauses print as they validate. Nothing
    this binding builds may put a line on a caller's stdout."""
    space = ds.space(ds.param("x").integer(0, 10)).forbid(ds.param("x") >= 5)
    translation = translate(space, default={"x": 2})
    translation.encode({"x": 3})
    assert capsys.readouterr().out == ""


def test_soft_constraints_are_never_translated_or_reported() -> None:
    space = ds.space(ds.param("a").real(0.0, 1.0)).encourage(ds.param("a") < 0.5)
    translation = translate(space)
    assert not translation.untranslated_constraints


def test_untranslatable_constraint_is_reported_not_raised() -> None:
    space = ds.space(ds.param("s").subset(items=("a", "b", "c"))).forbid(ds.param("s").size() > 2)
    translation = translate(space)
    assert len(translation.untranslated_constraints) == 1


def test_compiler_pipeline_constraints_mostly_translate() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
    from corpus.compiler_pipeline import build_space

    space = build_space()
    translation = translate(space)
    # The two prerequisite-free passes desugar to an always-satisfied
    # implication, which carries no forbidden state to translate.
    assert len(translation.untranslated_constraints) == 2
    for config in _decode_many(translation, 100):
        assert not space.validate(config).param_errors


# -- decode / encode round trip -------------------------------------------


def test_round_trips_flat_hpo() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
    from corpus.flat_hpo import build_space

    space = build_space()
    translation = translate(space)
    for config in _decode_many(translation, 100):
        assert space.is_complete(config)
        assert not space.validate(config).param_errors
        again = translation.decode(translation.encode(config))
        assert again == config


def test_activity_agrees_with_the_space() -> None:
    """ConfigSpace omits an inactive hyperparameter from a `Configuration`
    exactly where designspace omits an inactive parameter from a config, so
    the decoded result is always complete rather than needing repair."""
    space = ds.space(
        ds.param("optimizer").categorical("sgd", "adam"),
        ds.param("nesterov").bool().when(ds.param("optimizer") == "sgd"),
    )
    translation = translate(space)
    for config in _decode_many(translation, 60):
        assert space.is_complete(config)
        assert not space.validate(config).param_errors


def test_encode_raises_nothing_for_a_feasible_config() -> None:
    space = ds.space(
        ds.param("optimizer").categorical("sgd", "adam"),
        ds.param("nesterov").bool().when(ds.param("optimizer") == "sgd"),
    )
    translation = translate(space)
    config = {"optimizer": "sgd", "nesterov": True}
    configuration = translation.encode(config)
    assert dict(translation.decode(configuration)) == config


def test_observation_key_is_stable_across_decodes() -> None:
    space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("n").integer(0, 10))
    translation = translate(space)
    translation.config_space.seed(0)
    configuration = translation.config_space.sample_configuration()
    config_a = translation.decode(configuration)
    config_b = translation.decode(configuration)
    key_a = (space.fingerprint(), ds.config_hash(config_a, space))
    key_b = (space.fingerprint(), ds.config_hash(config_b, space))
    assert key_a == key_b

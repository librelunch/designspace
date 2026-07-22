"""Conformance laws: Defaults (API.md, "Defaults"; "Conformance Laws" >
"Defaults").

- `apply_defaults` is idempotent and monotone (never overwrites, never
  removes) — hypothesis over partial slices of sampled configs.
- Completeness postcondition: `is_complete(apply_defaults(c))` iff every
  active param under the filled config has a default or was supplied.
- Activity-respecting fill: an inactive param's default is never filled
  (the spec's own `turbo`/`chassis` history — reproduced verbatim here).
- Element/list default exclusivity (row 21).
- The defaulted-count-param cascade under fill-only output.
- Field-wise choice/struct fill.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

import designspace as ds
from designspace.build._space import Space
from designspace.config import flatten, unflatten
from designspace.errors import ResolutionError


def _greenhouse() -> Space:
    return ds.space(
        ds.param("heating").choice(
            "electric",
            gas=ds.space(
                ds.param("burner_power_kw").real(5.0, 50.0),
                ds.param("pilot_light").bool().default(True),
            ),
        ),
        ds.param("target_temp_c").real(10.0, 35.0).default(21.0),
        ds.param("humidity_control").choice(
            "off",
            active=ds.space(ds.param("target_humidity_pct").real(30.0, 90.0)),
        ),
        ds.param("zone").space(
            ds.param("area_m2").real(1.0, 1000.0),
            ds.param("shade_cloth").bool(),
        ),
    )


@given(st.data())
def test_idempotent_and_monotone(data):
    space = _greenhouse()
    seed = data.draw(st.integers(min_value=0, max_value=10_000))
    full = space.sample_dicts(1, seed=seed)[0]
    flat_full = flatten(full, space)
    keys = list(flat_full)
    keep = data.draw(st.lists(st.sampled_from(keys), unique=True, max_size=len(keys)))
    partial = unflatten({k: flat_full[k] for k in keep}, space)

    once = space.apply_defaults(partial)
    twice = space.apply_defaults(once)
    assert once == twice  # idempotent

    # `partial` itself (not the raw `keep` list) is the ground truth for
    # monotonicity: a dropped discriminator can silently strip a surviving
    # payload key during the unflatten round-trip (choice values are
    # self-contained), so what actually reaches `apply_defaults` can be a
    # strict subset of `keep`.
    partial_flat = flatten(partial, space)
    once_flat = flatten(once, space)
    for k, v in partial_flat.items():
        assert once_flat.get(k) == v  # monotone: never overwrites, never removes


class TestCompletenessPostcondition:
    def test_incomplete_when_some_active_param_has_no_default(self):
        space = _greenhouse()
        filled = space.apply_defaults({})
        # burner_power_kw/target_humidity_pct/zone.* have no defaults, and
        # heating/humidity_control themselves have no default either, so
        # nothing downstream of them ever gets filled or supplied.
        assert not space.is_complete(filled)
        assert not space.has_complete_defaults

    def test_complete_when_every_active_param_is_defaulted_or_supplied(self):
        space = _greenhouse()
        filled = space.apply_defaults(
            {
                "heating": "electric",
                "humidity_control": "off",
                "zone": {"area_m2": 10.0, "shade_cloth": False},
            }
        )
        assert space.is_complete(filled)

    def test_has_complete_defaults_true_when_every_param_defaults(self):
        space = ds.space(
            ds.param("x").real(0.0, 1.0).default(0.5),
            ds.param("y").bool().default(False),
        )
        assert space.has_complete_defaults


class TestActivityRespectingFill:
    """The spec's own worked example: an inactive param's default is left
    untouched, not silently filled."""

    def test_turbo_off_leaves_boost_unfilled(self):
        space = ds.space(
            ds.param("turbo").bool().default(False),
            ds.param("boost_psi").real(0.0, 30.0).default(10.0).when(ds.param("turbo")),
        )
        assert space.apply_defaults({}) == {"turbo": False}

    def test_turbo_on_fills_boost(self):
        space = ds.space(
            ds.param("turbo").bool().default(False),
            ds.param("boost_psi").real(0.0, 30.0).default(10.0).when(ds.param("turbo")),
        )
        assert space.apply_defaults({"turbo": True}) == {"turbo": True, "boost_psi": 10.0}

    def test_unknown_activity_leaves_dependent_unfilled(self):
        """`turbo` itself undetermined (no default, not supplied) -> its own
        activity is unresolved, so `boost_psi`'s activity is "unknown", not
        "active" -- fill must leave it alone, same as the inactive case."""
        space = ds.space(
            ds.param("turbo").bool(),
            ds.param("boost_psi").real(0.0, 30.0).default(10.0).when(ds.param("turbo")),
        )
        assert space.apply_defaults({}) == {}


class TestElementListDefaultExclusivity:
    def test_element_and_list_default_together_rejected(self):
        with pytest.raises(ResolutionError, match=r"mutually exclusive"):
            ds.space(
                ds.param("dropout").real(0.0, 0.6).default(0.1).repeat(4).default([0.1] * 4),
            )


class TestDefaultedCountParamCascade:
    def test_count_default_determines_materialized_length(self):
        space = ds.space(
            ds.param("n_layers").integer(0, 8).default(2),
            ds.param("layers").space(
                ds.param("width").integer(16, 1024).default(64),
            ).repeat(ds.param("n_layers")),
        )
        assert space.apply_defaults({}) == {
            "n_layers": 2,
            "layers": [{"width": 64}, {"width": 64}],
        }

    def test_zero_count_materializes_empty_list(self):
        space = ds.space(
            ds.param("n_layers").integer(0, 8).default(0),
            ds.param("layers").space(
                ds.param("width").integer(16, 1024).default(64),
            ).repeat(ds.param("n_layers")),
        )
        assert space.apply_defaults({}) == {"n_layers": 0, "layers": []}

    def test_no_element_defaults_leaves_lift_implicit(self):
        space = ds.space(
            ds.param("n_layers").integer(0, 8).default(2),
            ds.param("layers").space(
                ds.param("width").integer(16, 1024),  # no default anywhere
            ).repeat(ds.param("n_layers")),
        )
        assert space.apply_defaults({}) == {"n_layers": 2}


class TestFieldWiseFill:
    def test_choice_default_fills_named_variant_field_wise(self):
        space = ds.space(
            ds.param("heating").choice(
                "electric",
                gas=ds.space(ds.param("pilot_light").bool().default(True)),
            ).default("gas"),
        )
        assert space.apply_defaults({}) == {"heating": {"gas": {"pilot_light": True}}}

    def test_supplied_variant_wins_and_is_filled_field_wise(self):
        """"If a config already supplies a choice's variant, partial input
        wins — that variant's payload is filled from its own members'
        defaults."" (API.md, "Defaults")."""
        space = ds.space(
            ds.param("heating").choice(
                "electric",
                gas=ds.space(ds.param("pilot_light").bool().default(True)),
            ).default("electric"),
        )
        assert space.apply_defaults({"heating": "gas"}) == {
            "heating": {"gas": {"pilot_light": True}}
        }

    def test_struct_fills_field_wise(self):
        space = ds.space(
            ds.param("zone").space(
                ds.param("area_m2").real(1.0, 1000.0).default(10.0),
                ds.param("shade_cloth").bool(),  # no default
            ),
        )
        assert space.apply_defaults({}) == {"zone": {"area_m2": 10.0}}

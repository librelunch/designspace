"""Corpus: `greenhouse` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from greenhouse import build_space

from designspace.build._space import Space


def test_resolves():
    space = build_space()
    # heating, heating.gas.burner_power_kw, heating.gas.pilot_light,
    # target_temp_c, humidity_control, humidity_control.active.target_humidity_pct,
    # zone, zone.area_m2, zone.shade_cloth
    assert space.n_params == 9


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_choice_values_are_self_contained():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        heating = cfg["heating"]
        if heating == "electric":
            continue
        assert set(heating.keys()) == {"gas"}
        assert set(heating["gas"].keys()) <= {"burner_power_kw", "pilot_light"}


def test_zone_struct_always_present():
    space = build_space()
    for cfg in space.sample_dicts(50, seed=2):
        assert "zone" in cfg
        assert set(cfg["zone"].keys()) == {"area_m2", "shade_cloth"}


def test_defaults_cascade():
    """M6: `.default()` was accepted and resolution-validated since M1
    (see this fixture's own module docstring); `apply_defaults` itself is
    M6's cascade over it."""
    space = build_space()

    # Neither choice names its own default variant, and struct/variant
    # fields without a `.default()` (burner_power_kw, target_humidity_pct,
    # zone's own fields) are left unfilled -- only target_temp_c's default
    # is emitted.
    assert space.apply_defaults({}) == {"target_temp_c": 21.0}
    assert not space.has_complete_defaults

    # Partial input wins: supplying "gas" fills its payload field-wise
    # (pilot_light's own default), without requiring burner_power_kw.
    assert space.apply_defaults({"heating": "gas"}) == {
        "heating": {"gas": {"pilot_light": True}},
        "target_temp_c": 21.0,
    }

    # A complete config is a fixed point (idempotence) and is reported
    # complete once every active param is supplied or defaulted.
    full = {
        "heating": "electric",
        "target_temp_c": 5.0,
        "humidity_control": "off",
        "zone": {"area_m2": 1.0, "shade_cloth": True},
    }
    assert space.is_complete(full)
    assert space.apply_defaults(full) == full
    assert space.next_assignable(full) == []


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=3):
        assert restored.validate(cfg).valid

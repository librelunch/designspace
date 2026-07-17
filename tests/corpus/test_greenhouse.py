"""Corpus: `greenhouse` end-to-end (resolve -> sample 200 -> validate all)."""

from __future__ import annotations

from greenhouse import build_space


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

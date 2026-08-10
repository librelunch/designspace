"""config/ unit tests: `flatten`/`unflatten`/`variant`/`payload`/
`destructure` (API.md, "Config Utilities")."""

from __future__ import annotations

import pytest

import designspace as ds


class TestFlattenUnflatten:
    def _space(self):
        return ds.space(
            ds.param("algo").choice(
                "linear",
                svm=ds.space(ds.param("gamma").real(0.0, 1.0)),
            ),
            ds.param("layers").space(ds.param("width").integer(0, 100)),
        )

    def test_flatten_bare_variant(self):
        space = self._space()
        flat = ds.flatten({"algo": "linear", "layers": {"width": 5}}, space)
        assert flat == {"algo": "linear", "layers.width": 5}

    def test_flatten_parameterized_variant(self):
        space = self._space()
        flat = ds.flatten({"algo": {"svm": {"gamma": 0.5}}, "layers": {"width": 5}}, space)
        assert flat == {"algo": "svm", "algo.svm.gamma": 0.5, "layers.width": 5}

    def test_unflatten_is_flatten_inverse(self):
        space = self._space()
        nested = {"algo": {"svm": {"gamma": 0.25}}, "layers": {"width": 9}}
        assert ds.unflatten(ds.flatten(nested, space), space) == nested

    def test_flatten_is_non_validating(self):
        # flatten does its best with malformed input rather than raising --
        # validate() is what catches shape errors (see DECISIONS.md).
        space = self._space()
        flat = ds.flatten({"algo": 123}, space)
        assert "algo" not in flat

    def test_flatten_skips_absent_container(self):
        space = self._space()
        flat = ds.flatten({"algo": "linear"}, space)
        assert flat == {"algo": "linear"}


class TestUnflattenStaticCountFallback:
    """`unflatten`'s static-count fallback.

    API.md, "The fixed leaf layout" says that "for a static count
    [unflatten] recovers the length from the ListDomain rather than
    requiring the bookkeeping key." A present key still wins. A dynamic
    count that is absent stays unrecoverable: the outer level omits the
    list, and a nested level raises `KeyError`.
    """

    def _static_space(self):
        return ds.space(
            ds.param("dropout").real(0.0, 1.0).repeat(3),
            ds.param("grid").real(0.0, 1.0).repeat(2, 3),
        )

    def test_outer_static_count_recovered_when_bookkeeping_key_absent(self):
        space = self._static_space()
        flat = {"dropout[0]": 0.1, "dropout[1]": 0.2, "dropout[2]": 0.3, "grid": 0}
        assert ds.unflatten(flat, space)["dropout"] == [0.1, 0.2, 0.3]

    def test_nested_static_count_recovered_when_bookkeeping_key_absent(self):
        space = self._static_space()
        flat = {
            "dropout": 0,
            "grid[0][0]": 0.1,
            "grid[0][1]": 0.2,
            "grid[0][2]": 0.3,
            "grid[1][0]": 0.4,
            "grid[1][1]": 0.5,
            "grid[1][2]": 0.6,
        }
        result = ds.unflatten(flat, space)
        assert result["grid"] == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    def test_full_static_round_trip_with_no_bookkeeping_keys_at_all(self):
        space = self._static_space()
        config = {"dropout": [0.1, 0.2, 0.3], "grid": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}
        coordinates = space.coordinate_paths()
        flat = ds.flatten(config, space)
        no_bookkeeping = {p: flat[p] for p in coordinates}
        assert ds.unflatten(no_bookkeeping, space) == config

    def test_present_bookkeeping_key_still_wins(self):
        # flatten's own realized length takes priority over the domain's
        # declared static count -- the fallback only ever fires on absence.
        space = ds.space(ds.param("dropout").real(0.0, 1.0).repeat(3))
        flat = {"dropout": 2, "dropout[0]": 0.1, "dropout[1]": 0.2}
        assert ds.unflatten(flat, space)["dropout"] == [0.1, 0.2]

    def test_dynamic_and_absent_count_is_unchanged(self):
        space = ds.space(
            ds.param("n").integer(0, 5),
            ds.param("dropout").real(0.0, 1.0).repeat(ds.param("n")),
        )
        # Outer level: silently omitted, exactly as before this milestone.
        assert "dropout" not in ds.unflatten({"n": 2}, space)

    def test_nested_dynamic_and_absent_count_still_raises_key_error(self):
        space = ds.space(
            ds.param("n").integer(0, 5),
            ds.param("grid").real(0.0, 1.0).repeat(ds.param("n")).repeat(2),
        )
        with pytest.raises(KeyError):
            ds.unflatten({"n": 2}, space)


class TestVariantPayloadDestructure:
    def test_bare_variant(self):
        cfg = {"algo": "linear"}
        assert ds.variant(cfg, "algo") == "linear"
        assert ds.payload(cfg, "algo") is None
        assert ds.destructure(cfg, "algo") == ("linear", None)

    def test_parameterized_variant(self):
        cfg = {"algo": {"svm": {"gamma": 0.5}}}
        assert ds.variant(cfg, "algo") == "svm"
        assert ds.payload(cfg, "algo") == {"gamma": 0.5}
        assert ds.destructure(cfg, "algo") == ("svm", {"gamma": 0.5})

    def test_nested_choice_path(self):
        cfg = {"outer": {"a": {"inner": "linear"}}}
        assert ds.variant(cfg, "outer.a.inner") == "linear"

    def test_malformed_value_raises(self):
        with pytest.raises(ValueError):
            ds.variant({"algo": 123}, "algo")

    def test_missing_path_raises(self):
        with pytest.raises(KeyError):
            ds.variant({}, "algo")


class TestInstancePathVariantPayloadDestructure:
    """API.md, "Config Utilities": `variant`/`payload`/`destructure` accept
    instance paths such as `pipeline[1]` into a lifted choice. The bare list
    path is a misuse error whose message names the indexed form.
    """

    def _cfg(self) -> dict:
        # A lifted-choice config: bare variants alongside parameterized ones.
        return {
            "n_ops": 3,
            "pipeline": ["shuffle", {"mutation": {"rate": 0.1}}, "crossover"],
        }

    def test_index_into_bare_variant_element(self):
        cfg = self._cfg()
        assert ds.variant(cfg, "pipeline[0]") == "shuffle"
        assert ds.payload(cfg, "pipeline[0]") is None
        assert ds.destructure(cfg, "pipeline[0]") == ("shuffle", None)

    def test_index_into_parameterized_element(self):
        cfg = self._cfg()
        assert ds.variant(cfg, "pipeline[1]") == "mutation"
        assert ds.payload(cfg, "pipeline[1]") == {"rate": 0.1}
        assert ds.destructure(cfg, "pipeline[1]") == ("mutation", {"rate": 0.1})

    def test_nested_index_then_field(self):
        # A lifted struct whose element carries a choice field: index into the
        # element, then walk the dotted field name.
        cfg = {"stages": [{"algo": "linear"}, {"algo": {"svm": {"gamma": 0.5}}}]}
        assert ds.variant(cfg, "stages[0].algo") == "linear"
        assert ds.variant(cfg, "stages[1].algo") == "svm"
        assert ds.payload(cfg, "stages[1].algo") == {"gamma": 0.5}

    def test_bare_list_path_is_misuse_error_naming_indexed_form(self):
        cfg = self._cfg()
        with pytest.raises(TypeError, match=r"pipeline\[.*\]"):
            ds.variant(cfg, "pipeline")

    def test_out_of_range_index_raises_lookup_error(self):
        cfg = self._cfg()
        with pytest.raises(KeyError):
            ds.variant(cfg, "pipeline[9]")


class TestFlattenRejectsAnAlreadyFlatConfig:
    """Flattening twice dropped every lift key. It now says so.

    A lift's value is a list in nested form and its length in flat form,
    so a second pass met an `int` where it wanted a list and skipped the
    parameter, taking the element keys with it. Nothing was raised, so a
    caller who flattened twice lost the lift and read a complete config
    as incomplete.
    """

    @staticmethod
    def _space():
        return ds.space(
            ds.param("n").integer(0, 3),
            ds.param("workers")
            .space(ds.space(ds.param("timeout_s").integer(1, 3600)))
            .repeat(ds.param("n")),
        )

    def test_flattening_twice_raises_naming_the_parameter(self):
        space = self._space()
        flat = ds.flatten({"n": 1, "workers": [{"timeout_s": 30}]}, space)
        with pytest.raises(TypeError) as caught:
            ds.flatten(flat, space)
        assert "workers" in str(caught.value)

    def test_a_struct_config_flattened_twice_raises(self):
        space = ds.space(ds.param("s").space(ds.space(ds.param("a").integer(0, 4))))
        flat = ds.flatten({"s": {"a": 1}}, space)
        with pytest.raises(TypeError):
            ds.flatten(flat, space)

    def test_a_space_whose_two_forms_coincide_is_unaffected(self):
        """With no lift and no struct, flat and nested are the same dict."""
        space = ds.space(ds.param("a").integer(0, 4), ds.param("b").real(0.0, 1.0))
        config = {"a": 1, "b": 0.5}
        assert ds.flatten(config, space) == config
        assert ds.flatten(ds.flatten(config, space), space) == config


class TestUnflattenReadsLengthFromElementKeys:
    """A lift's element keys establish its length, with no count entry.

    `flatten` writes a bookkeeping entry holding the realized length, but
    `next_assignable` never reports it: a driver loop assigns the count
    param and the instance leaves. The flat dict such a loop builds
    therefore has every element key and no entry, and unflattening it
    dropped the whole lift.

    The entry stays required where it is the only evidence there is. With
    no element key present, absence means the lift is inactive, and an
    entry of `0` is what distinguishes an active empty one.
    """

    @staticmethod
    def _space():
        return ds.space(
            ds.param("on").bool(),
            ds.param("n").integer(0, 3),
            ds.param("workers")
            .space(ds.space(ds.param("timeout_s").integer(1, 3600)))
            .repeat(ds.param("n"))
            .when(ds.param("on")),
        )

    def test_element_keys_alone_rebuild_the_list(self):
        space = self._space()
        flat = {
            "on": True,
            "n": 2,
            "workers[0].timeout_s": 30,
            "workers[1].timeout_s": 900,
        }
        assert ds.unflatten(flat, space) == {
            "on": True,
            "n": 2,
            "workers": [{"timeout_s": 30}, {"timeout_s": 900}],
        }

    def test_a_present_entry_still_wins(self):
        space = self._space()
        flat = {"on": True, "n": 2, "workers": 2, "workers[0].timeout_s": 30}
        rebuilt = ds.unflatten(flat, space)
        assert len(rebuilt["workers"]) == 2

    def test_an_active_empty_lift_needs_its_entry(self):
        space = self._space()
        assert ds.unflatten({"on": True, "n": 0, "workers": 0}, space)["workers"] == []

    def test_an_inactive_lift_stays_absent(self):
        space = self._space()
        assert "workers" not in ds.unflatten({"on": False, "n": 0}, space)

    def test_it_round_trips_what_a_driver_loop_builds(self):
        space = self._space()
        flat: dict = {}
        for _ in range(10):
            assignable = space.next_assignable(flat)
            if not assignable:
                break
            for path in assignable:
                flat[path] = 30 if path.endswith("timeout_s") else (True if path == "on" else 2)
        else:
            raise AssertionError("the loop did not terminate")
        assert space.validate(ds.unflatten(flat, space)).valid


class TestIsFlat:
    """`is_flat` answers what `flatten` refuses on, before it refuses.

    A function that raises on a condition has to let a caller test that
    condition. `flatten` rejects a config already keyed by path, so the
    same question it asks is available to ask first.
    """

    @staticmethod
    def _space():
        return ds.space(
            ds.param("n").integer(0, 3),
            ds.param("workers")
            .space(ds.space(ds.param("timeout_s").integer(1, 3600)))
            .repeat(ds.param("n")),
        )

    def test_it_agrees_with_what_flatten_refuses(self):
        """The law: flat exactly when flatten will not take it."""
        space = self._space()
        configs = [
            {"n": 0, "workers": []},
            {"n": 1, "workers": [{"timeout_s": 30}]},
            {"n": 2, "workers": [{"timeout_s": 30}, {"timeout_s": 900}]},
            {"n": 2},
            {},
        ]
        for nested in configs:
            assert not ds.is_flat(nested, space)
            flat = ds.flatten(nested, space)
            assert ds.is_flat(flat, space) == (flat != nested)
            if ds.is_flat(flat, space):
                with pytest.raises(TypeError):
                    ds.flatten(flat, space)
            else:
                ds.flatten(flat, space)

    def test_a_lift_is_told_by_its_own_entry(self):
        """Zero elements leave no path key, so the entry settles it."""
        space = self._space()
        assert ds.is_flat({"n": 0, "workers": 0}, space)
        assert not ds.is_flat({"n": 0, "workers": []}, space)

    def test_a_struct_is_told_by_its_dotted_key(self):
        space = ds.space(ds.param("s").space(ds.space(ds.param("a").integer(0, 4))))
        assert ds.is_flat({"s.a": 1}, space)
        assert not ds.is_flat({"s": {"a": 1}}, space)

    def test_a_space_whose_two_forms_coincide_is_never_flat(self):
        """With no lift and no nesting there is nothing to tell apart."""
        space = ds.space(ds.param("a").integer(0, 4), ds.param("b").real(0.0, 1.0))
        config = {"a": 1, "b": 0.5}
        assert not ds.is_flat(config, space)
        assert ds.flatten(config, space) == config

    def test_an_empty_config_is_not_flat(self):
        assert not ds.is_flat({}, self._space())

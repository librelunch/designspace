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

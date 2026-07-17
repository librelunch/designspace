"""config/ unit tests: `flatten`/`unflatten`/`variant`/`payload`/
`destructure` (API_v3.md, "Config Utilities")."""

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

"""Conformance laws: `Space.coordinate_paths()` (API.md, "Config Utilities" >
"The fixed leaf layout"; error-table row 33; M10.7).

- A fixed layout requires every `.repeat()` count to be a literal integer and
  no param to carry a condition; either makes the key set config-dependent,
  so `coordinate_paths()` raises a path-named `ResolutionError` (row 33)
  rather than returning a config-specific answer.
- `unflatten(dict(zip(space.coordinate_paths(), values)), space)` is the
  inverse of reading those same paths out of `flatten` — the round trip the
  fixed layout exists to support.
- Lift-length bookkeeping entries are excluded at every nesting depth; struct
  params never appear (they hold no value of their own); `subset`/
  `permutation`/`categorical`/`ordinal` leaves *do* appear (a fixed layout is
  not the same as numeric packability).
- Order matches `flatten`'s (and therefore the DataFrame's) leaf order.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import designspace as ds
from designspace.config import flatten, unflatten
from designspace.errors import ResolutionError

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))

# Fixed layout: every `.repeat()` count is a literal integer and no param
# carries a condition. Measured directly against each fixture's own
# `build_space()` (not any other builder the module happens to also export —
# `vi_family` exports `build_finite_space()` too, whose count *is* static;
# `build_space()`, the one every other corpus-driven suite exercises, has a
# `.prop()`-driven dynamic lift and belongs in the "not fixed" set below).
FIXED_FIXTURES = [
    "flow_chemistry",
    "job_shop",
    "wind_farm_grid",
    "firmware_buffers",
    "pump_configurator",
    "compiler_pipeline",
]

# name -> the set of paths whose own condition or dynamic count could be the
# one named in the row-33 message. Declaration-order traversal picks exactly
# one; which one is an implementation choice, not part of the law, so the
# test only checks membership.
NOT_FIXED_FIXTURES: dict[str, set[str]] = {
    "flat_hpo": {"nesterov"},
    "greenhouse": {
        "heating.gas.burner_power_kw",
        "heating.gas.pilot_light",
        "humidity_control.active.target_humidity_pct",
    },
    "sat_solver": {"solver.cdcl.restart_strategy"},
    "delivery_routes": {"stops"},
    "solver_portfolio": {"workers"},
    "memetic_pipeline": {"pipeline", "pipeline[].mutation.rate", "pipeline[].local_search.iters"},
    "vi_family": {"edge_weight"},
}


def _build(name: str):
    import importlib

    return importlib.import_module(name).build_space()


class TestFixedLayoutRoundTrip:
    """ "`unflatten` completes the round trip: for a static count it recovers
    the length from the `ListDomain`... so `ds.unflatten(dict(zip(
    space.coordinate_paths(), values)), space)` is the inverse of reading
    those paths out of `flatten`."""

    @pytest.mark.parametrize("name", FIXED_FIXTURES)
    def test_round_trips_through_unflatten(self, name):
        space = _build(name)
        paths = space.coordinate_paths()
        assert paths  # every fixed fixture has at least one leaf
        for seed in range(20):
            config = space.sample_one(seed=seed)
            flat = flatten(config, space)
            values = [flat[p] for p in paths]
            rebuilt = unflatten(dict(zip(paths, values, strict=True)), space)
            assert rebuilt == config


class TestNoFixedLayoutRaisesRow33:
    @pytest.mark.parametrize("name", sorted(NOT_FIXED_FIXTURES))
    def test_raises_naming_an_offending_path(self, name):
        space = _build(name)
        with pytest.raises(ResolutionError) as excinfo:
            space.coordinate_paths()
        message = str(excinfo.value)
        assert "row 33" in message
        assert any(path in message for path in NOT_FIXED_FIXTURES[name])


class TestCoordinatePathsStructure:
    """Structural laws exercised on a hand-built space, independent of the
    corpus: lift-length exclusion at every depth, struct exclusion, bare vs.
    payload-bearing choice, and non-numeric/variable-length leaves."""

    def _space(self):
        return ds.space(
            ds.param("grid").real(0.0, 1.0).repeat(2, 3),
            ds.param("mode").choice("a", "b"),
            ds.param("st").space(ds.param("w").integer(1, 4)).repeat(2),
            ds.param("items").subset(("x", "y", "z")),
            ds.param("order").permutation(("p", "q", "r")),
            ds.param("cat").categorical("x", "y"),
            ds.param("wrap").space(ds.param("v").real(0.0, 1.0)),
        )

    def test_excludes_lift_length_bookkeeping_at_every_depth(self):
        space = self._space()
        paths = space.coordinate_paths()
        assert "grid" not in paths
        assert "grid[0]" not in paths
        assert "grid[1]" not in paths
        for i in range(2):
            for j in range(3):
                assert f"grid[{i}][{j}]" in paths
        assert "st" not in paths
        for i in range(2):
            assert f"st[{i}].w" in paths

    def test_struct_params_never_appear(self):
        space = self._space()
        paths = space.coordinate_paths()
        assert "wrap" not in paths
        assert "wrap.v" in paths

    def test_bare_variant_choice_is_one_coordinate(self):
        space = self._space()
        assert "mode" in space.coordinate_paths()

    def test_non_numeric_and_variable_length_leaves_are_coordinates(self):
        """ "A fixed layout is not the same as numeric packability... subset
        and permutation leaves have a stable key but a variable-length list
        value; categorical and ordinal leaves are scalar but not numeric.
        Both appear in coordinate_paths()." """
        space = self._space()
        paths = space.coordinate_paths()
        assert "items" in paths
        assert "order" in paths
        assert "cat" in paths

    def test_round_trips_through_unflatten_without_bookkeeping_keys(self):
        """The general form of `TestFixedLayoutRoundTrip`, but on a space
        that actually has lifts (none of the fixed corpus fixtures do) --
        this is what exercises `unflatten`'s static-count fallback: `paths`
        excludes `grid`/`grid[0]`/`grid[1]`/`st` by construction, so the flat
        dict handed to `unflatten` never carries their bookkeeping counts."""
        space = self._space()
        paths = space.coordinate_paths()
        for seed in range(20):
            config = space.sample_one(seed=seed)
            flat = flatten(config, space)
            values = [flat[p] for p in paths]
            rebuilt = unflatten(dict(zip(paths, values, strict=True)), space)
            assert rebuilt == config

    def test_order_matches_flatten_for_a_lift_free_space(self):
        space = ds.space(
            ds.param("wrap").space(
                ds.param("a").real(0.0, 1.0),
                ds.param("b").integer(0, 10),
            ),
            ds.param("mode").choice("x", "y"),
            ds.param("cat").categorical("p", "q"),
        )
        config = space.sample_one(seed=0)
        flat = flatten(config, space)
        # No lifts here, so flatten's keys are exactly the leaf coordinates
        # with no bookkeeping entries to filter out -- a clean order check.
        assert list(space.coordinate_paths()) == list(flat.keys())

    def test_payload_bearing_choice_raises_row_33(self):
        space = ds.space(
            ds.param("algo").choice("linear", svm=ds.space(ds.param("gamma").real(0.0, 1.0))),
        )
        with pytest.raises(ResolutionError, match="row 33"):
            space.coordinate_paths()

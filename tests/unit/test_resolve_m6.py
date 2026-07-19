"""M6 gate: completed row-21 default validation (API_v3.md, "Defaults";
error table row 21).

The milestone's *laws* (idempotence/monotonicity, completeness postcondition,
activity-respecting fill, the driver-loop coincidence, reducer sound/negative)
live in tests/conformance/test_defaults.py and tests/conformance/test_partial.py.
This file covers the mechanics: message-content tests for the row-21 cases
M6 completed in code (choice/subset/permutation default validation; struct
defaults rejected regardless of `.repeat()` position; a quantized real/
integer's *domain* is its grid, not the raw `[lo, hi]` interval, and a
periodic real's is the half-open `[lo, hi)` — a default outside either was
previously accepted silently at resolution and only surfaced later as a
`validate()` failure on `apply_defaults`'s own output); and a *list*
default's per-item domain validity (previously not checked at all — an
out-of-bounds, off-grid, or malformed struct/choice item in a
`.repeat(n).default([...])` resolved silently).
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError


class TestStructDefaultRejected:
    def test_top_level_struct_default_rejected(self):
        with pytest.raises(ResolutionError, match=r"'zone'.*struct"):
            ds.space(
                ds.param("zone").space(ds.param("area").real(0.0, 1.0)).default({"area": 0.5}),
            )

    def test_lifted_struct_element_default_rejected(self):
        with pytest.raises(ResolutionError, match=r"'layers\[\]'.*struct"):
            ds.space(
                ds.param("layers")
                .space(ds.param("width").integer(1, 10))
                .default({"width": 5})
                .repeat(3),
            )


class TestChoiceDefaultValidation:
    def test_valid_variant_name_accepted(self):
        space = ds.space(
            ds.param("algo").choice("sgd", adam=ds.space(ds.param("lr").real(0.0, 1.0))).default(
                "adam"
            ),
        )
        assert space.params["algo"].default == "adam"

    def test_undeclared_variant_name_rejected(self):
        with pytest.raises(ResolutionError, match=r"'algo'.*outside its domain"):
            ds.space(
                ds.param("algo").choice("sgd", "adam").default("rmsprop"),
            )


class TestSubsetDefaultValidation:
    def test_valid_subset_accepted(self):
        space = ds.space(
            ds.param("ops").subset(["a", "b", "c"], min_size=1).default(["a", "c"]),
        )
        assert space.params["ops"].default == ["a", "c"]

    def test_default_with_undeclared_item_rejected(self):
        with pytest.raises(ResolutionError, match=r"'ops'.*outside its domain"):
            ds.space(
                ds.param("ops").subset(["a", "b", "c"]).default(["a", "z"]),
            )

    def test_default_violating_size_bounds_rejected(self):
        with pytest.raises(ResolutionError, match=r"'ops'.*outside its domain"):
            ds.space(
                ds.param("ops").subset(["a", "b", "c"], min_size=2).default(["a"]),
            )

    def test_default_with_duplicate_rejected(self):
        with pytest.raises(ResolutionError, match=r"'ops'.*outside its domain"):
            ds.space(
                ds.param("ops").subset(["a", "b", "c"]).default(["a", "a"]),
            )


class TestPermutationDefaultValidation:
    def test_valid_permutation_accepted(self):
        space = ds.space(
            ds.param("order").permutation(["a", "b", "c"]).default(["c", "a", "b"]),
        )
        assert space.params["order"].default == ["c", "a", "b"]

    def test_partial_permutation_rejected(self):
        with pytest.raises(ResolutionError, match=r"'order'.*outside its domain"):
            ds.space(
                ds.param("order").permutation(["a", "b", "c"]).default(["a", "b"]),
            )

    def test_permutation_with_foreign_item_rejected(self):
        with pytest.raises(ResolutionError, match=r"'order'.*outside its domain"):
            ds.space(
                ds.param("order").permutation(["a", "b", "c"]).default(["a", "b", "z"]),
            )


class TestQuantizedDefaultValidation:
    def test_off_grid_integer_default_rejected(self):
        with pytest.raises(ResolutionError, match=r"'x'.*outside its domain"):
            ds.space(ds.param("x").integer(10, 100).quantized(step=10).default(11))

    def test_on_grid_integer_default_accepted(self):
        space = ds.space(ds.param("x").integer(10, 100).quantized(step=10).default(20))
        assert space.params["x"].default == 20

    def test_off_grid_real_default_rejected(self):
        with pytest.raises(ResolutionError, match=r"'y'.*outside its domain"):
            ds.space(ds.param("y").real(0.0, 1.0).quantized(step=0.1).default(0.15))

    def test_on_grid_real_default_accepted(self):
        space = ds.space(ds.param("y").real(0.0, 1.0).quantized(step=0.1).default(0.3))
        assert space.params["y"].default == 0.3

    def test_off_grid_lift_element_default_rejected(self):
        """The same check applies to a pre-`.repeat()` element default,
        reused via `_validate_lift`'s reconstructed element view."""
        with pytest.raises(ResolutionError, match=r"'grid\[\]'.*outside its domain"):
            ds.space(
                ds.param("grid").real(0.0, 1.0).quantized(step=0.25).default(0.1).repeat(3),
            )

    def test_apply_defaults_output_now_validates(self):
        """The motivating bug: a filled default must itself be a legal
        (on-grid) value, so `validate()` on `apply_defaults`'s own output
        never fails."""
        space = ds.space(ds.param("x").integer(10, 100).quantized(step=10).default(20))
        filled = space.apply_defaults({})
        assert space.validate(filled).valid


class TestPeriodicDefaultValidation:
    def test_default_at_hi_rejected(self):
        with pytest.raises(ResolutionError, match=r"'theta'.*outside its domain"):
            ds.space(ds.param("theta").real(0.0, 360.0, periodic=True).default(360.0))

    def test_default_within_half_open_range_accepted(self):
        space = ds.space(ds.param("theta").real(0.0, 360.0, periodic=True).default(90.0))
        assert space.params["theta"].default == 90.0


class TestListDefaultItemValidation:
    """A `.repeat(n).default([...])` list default is a literal phenotype
    value per index — previously only its *length* was checked (row 21's
    "list default length must match"); no item was ever validated against
    the element's own domain, so an out-of-bounds/off-grid/malformed item
    resolved silently and only surfaced later as a `validate()` failure on
    `apply_defaults`'s own output (the same shape of bug as the scalar
    default gap above, one level up through `.repeat()`)."""

    def test_out_of_bounds_item_rejected(self):
        with pytest.raises(ResolutionError, match=r"'x'.*list default.*outside its domain"):
            ds.space(ds.param("x").integer(10, 100).repeat(2).default([20, 200]))

    def test_off_grid_item_rejected(self):
        with pytest.raises(ResolutionError, match=r"'x'.*list default.*outside its domain"):
            ds.space(
                ds.param("x").integer(10, 100).quantized(step=10).repeat(2).default([20, 25])
            )

    def test_valid_scalar_list_default_accepted(self):
        space = ds.space(
            ds.param("dropout").real(0.0, 0.6).repeat(4).default([0.1, 0.2, 0.3, 0.4]),
        )
        assert space.apply_defaults({}) == {"dropout": [0.1, 0.2, 0.3, 0.4]}

    def test_struct_list_default_with_invalid_field_rejected(self):
        with pytest.raises(ResolutionError, match=r"'layers'.*list default.*outside its domain"):
            ds.space(
                ds.param("layers")
                .space(ds.param("width").integer(16, 1024))
                .repeat(2)
                .default([{"width": 128}, {"width": 9999}]),
            )

    def test_valid_struct_list_default_accepted(self):
        space = ds.space(
            ds.param("layers")
            .space(ds.param("width").integer(16, 1024))
            .repeat(2)
            .default([{"width": 128}, {"width": 256}]),
        )
        assert space.apply_defaults({}) == {"layers": [{"width": 128}, {"width": 256}]}

    def test_lifted_choice_list_default_with_undeclared_variant_rejected(self):
        with pytest.raises(ResolutionError, match=r"'pipeline'.*list default.*outside its domain"):
            ds.space(
                ds.param("pipeline")
                .choice("shuffle", pmx=ds.space(ds.param("swap_p").real(0.0, 1.0)))
                .repeat(2)
                .default(["shuffle", "nonexistent"]),
            )

    def test_valid_lifted_choice_list_default_accepted(self):
        space = ds.space(
            ds.param("pipeline")
            .choice("shuffle", pmx=ds.space(ds.param("swap_p").real(0.0, 1.0)))
            .repeat(2)
            .default(["shuffle", {"pmx": {"swap_p": 0.2}}]),
        )
        assert space.apply_defaults({}) == {
            "pipeline": ["shuffle", {"pmx": {"swap_p": 0.2}}]
        }

    def test_apply_defaults_output_now_validates(self):
        space = ds.space(
            ds.param("layers")
            .space(ds.param("width").integer(16, 1024))
            .repeat(2)
            .default([{"width": 128}, {"width": 256}]),
        )
        filled = space.apply_defaults({})
        assert space.validate(filled).valid

"""Unit tests for row-21 default validation (API.md, "Defaults").

The laws, meaning idempotence and monotonicity, the completeness
postcondition, activity-respecting fill, the driver-loop coincidence, and
the reducer's sound and negative cases, live in
`tests/conformance/test_defaults.py` and
`tests/conformance/test_partial.py`.

This file covers the mechanics, as message-content tests over the row-21
cases: choice, subset and permutation default validation; struct defaults
rejected whatever the `.repeat()` position; a quantized real's or integer's
domain being its grid rather than the raw `[lo, hi]` interval, and a
periodic real's the half-open `[lo, hi)`; and a list default's per-item
domain validity.
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
            ds.param("algo")
            .choice("sgd", adam=ds.space(ds.param("lr").real(0.0, 1.0)))
            .default("adam"),
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
    """Each item of a `.repeat(n).default([...])` is validated.

    The list default is a literal phenotype value per index. Row 21's "list
    default length must match" governs the length; each item must
    additionally be a member of the element's own domain, or an
    out-of-bounds, off-grid or malformed item resolves silently and surfaces
    only later, as a `validate()` failure on `apply_defaults`'s own output.
    """

    def test_out_of_bounds_item_rejected(self):
        with pytest.raises(ResolutionError, match=r"'x'.*list default.*outside its domain"):
            ds.space(ds.param("x").integer(10, 100).repeat(2).default([20, 200]))

    def test_off_grid_item_rejected(self):
        with pytest.raises(ResolutionError, match=r"'x'.*list default.*outside its domain"):
            ds.space(ds.param("x").integer(10, 100).quantized(step=10).repeat(2).default([20, 25]))

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
        assert space.apply_defaults({}) == {"pipeline": ["shuffle", {"pmx": {"swap_p": 0.2}}]}

    def test_apply_defaults_output_now_validates(self):
        space = ds.space(
            ds.param("layers")
            .space(ds.param("width").integer(16, 1024))
            .repeat(2)
            .default([{"width": 128}, {"width": 256}]),
        )
        filled = space.apply_defaults({})
        assert space.validate(filled).valid


class TestIntermediateListDefaultItemValidation:
    """A `list_default` at an intermediate nesting level is item-validated too.

    An intermediate level of a chained lift, as in
    `.repeat(a).default([...]).repeat(b)`, has no `list_default[i]`
    corresponding one-to-one to a real instance path: the same literal
    default applies identically to every outer instance.

    A chained lift only ever wraps a scalar, subset or permutation element,
    a struct or choice element being rejected under more than one
    `.repeat()`, so no descendant-template plumbing is needed. Recursion
    through `ListDomain.element_domain` under a synthesized placeholder
    outer index suffices.
    """

    def test_documented_repro_rejected(self):
        with pytest.raises(ResolutionError, match=r"'x'.*list default.*outside its domain"):
            ds.space(
                ds.param("x").integer(0, 10).repeat(3).default([5, 999, 2]).repeat(2),
            )

    def test_valid_intermediate_default_accepted_and_output_validates(self):
        """The actual invariant being restored: the completeness
        postcondition `validate(apply_defaults({})).valid` must hold."""
        space = ds.space(
            ds.param("x").integer(0, 10).repeat(3).default([5, 7, 2]).repeat(2),
        )
        filled = space.apply_defaults({})
        assert filled == {"x": [[5, 7, 2], [5, 7, 2]]}
        assert space.validate(filled).valid

    def test_multi_level_simultaneous_defaults_inner_invalid_rejected(self):
        """Independent `list_default` values at the inner and outer levels.

        Each level is checked against its own `flat` dict, with no collision
        between the synthetic outer-index prefixes.
        """
        with pytest.raises(ResolutionError, match=r"'x'.*list default.*outside its domain"):
            ds.space(
                ds.param("x")
                .integer(0, 10)
                .repeat(2)
                .default([1, 999])  # inner: 999 out of bounds
                .repeat(2)
                .default([[1, 2], [3, 4]]),  # outer: shape-valid
            )

    def test_three_level_chain_default_at_middle_level_rejected(self):
        """Exercises the recursion tail through `element_kind == 'list'`
        past the outermost level (outermost C wraps middle B, which carries
        the invalid `list_default`, which wraps innermost A)."""
        with pytest.raises(ResolutionError, match=r"'x'.*list default.*outside its domain"):
            ds.space(
                ds.param("x")
                .integer(0, 10)
                .repeat(2)  # A: innermost, no default
                .repeat(2)
                .default([[1, 2], [300, 4]])  # B: middle, invalid nested item 300
                .repeat(2),  # C: outermost, no default
            )

    def test_off_grid_quantized_intermediate_item_rejected(self):
        with pytest.raises(ResolutionError, match=r"'x'.*list default.*outside its domain"):
            ds.space(
                ds.param("x")
                .integer(0, 100)
                .quantized(step=10)
                .repeat(2)
                .default([20, 25])  # inner: 25 off-grid
                .repeat(2),
            )

    def test_struct_nested_chained_lift_invalid_default_rejected(self):
        """A chained lift inside a lifted struct's `.space(...)`.

        The struct's own `resolve_space` call runs this same check over its
        contents, so the behaviour reaches here with no extra plumbing.
        """
        with pytest.raises(ResolutionError, match=r"'sizes'.*list default.*outside its domain"):
            ds.space(
                ds.param("g")
                .space(
                    ds.param("sizes").integer(0, 10).repeat(2).default([5, 999]).repeat(2),
                )
                .repeat(2),
            )

    def test_struct_nested_chained_lift_valid_default_accepted(self):
        space = ds.space(
            ds.param("g")
            .space(
                ds.param("sizes").integer(0, 10).repeat(2).default([5, 7]).repeat(2),
            )
            .repeat(2),
        )
        filled = space.apply_defaults({})
        assert filled == {
            "g": [
                {"sizes": [[5, 7], [5, 7]]},
                {"sizes": [[5, 7], [5, 7]]},
            ]
        }
        assert space.validate(filled).valid

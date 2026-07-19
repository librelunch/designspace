"""M6 gate: completed row-21 default validation (API_v3.md, "Defaults";
error table row 21).

The milestone's *laws* (idempotence/monotonicity, completeness postcondition,
activity-respecting fill, the driver-loop coincidence, reducer sound/negative)
live in tests/conformance/test_defaults.py and tests/conformance/test_partial.py.
This file covers the mechanics: message-content tests for the row-21 cases
M6 completed in code (choice/subset/permutation default validation; struct
defaults rejected regardless of `.repeat()` position).
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

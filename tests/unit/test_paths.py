"""paths/ grammar unit tests (API.md, "Paths and Scoping").

Segment := name ("[" i "]")* (instance) | name ("[]")* (definition). No
lift lands until M4, so brackets are never produced by resolution yet —
this exercises the parser directly, "multi-index ready" ahead of need.
"""

from __future__ import annotations

import pytest

from designspace.errors import ResolutionError
from designspace.paths import (
    Segment,
    definition_form,
    element_prefix,
    instance_prefix,
    is_definition_path,
    join_path,
    parse_path,
    strip_last_index,
)


class TestParsePlainNames:
    def test_single_segment(self):
        assert parse_path("x") == (Segment("x", ()),)

    def test_multi_segment(self):
        assert parse_path("algo.svm.gamma") == (
            Segment("algo", ()),
            Segment("svm", ()),
            Segment("gamma", ()),
        )

    def test_empty_path_raises(self):
        with pytest.raises(ResolutionError):
            parse_path("")


class TestParseInstanceBrackets:
    def test_single_index(self):
        assert parse_path("mask[2]") == (Segment("mask", (2,)),)

    def test_nested_indices(self):
        assert parse_path("mask[2][3]") == (Segment("mask", (2, 3)),)

    def test_index_across_segments(self):
        segs = parse_path("stops[0].dwell_min")
        assert segs == (Segment("stops", (0,)), Segment("dwell_min", ()))


class TestParseDefinitionBrackets:
    def test_single_definition_marker(self):
        assert parse_path("mask[]") == (Segment("mask", (None,)),)

    def test_nested_definition_markers(self):
        assert parse_path("mask[][]") == (Segment("mask", (None, None)),)


class TestParseErrors:
    def test_mixed_instance_and_definition_brackets_raises(self):
        with pytest.raises(ResolutionError):
            parse_path("mask[0][]")

    def test_non_integer_index_raises(self):
        with pytest.raises(ResolutionError):
            parse_path("mask[x]")


class TestJoinPath:
    def test_round_trips_plain(self):
        segs = parse_path("algo.svm.gamma")
        assert join_path(segs) == "algo.svm.gamma"

    def test_round_trips_instance_brackets(self):
        segs = parse_path("mask[2][3]")
        assert join_path(segs) == "mask[2][3]"

    def test_round_trips_definition_brackets(self):
        segs = parse_path("mask[][]")
        assert join_path(segs) == "mask[][]"


class TestIsDefinitionPath:
    def test_plain_name_is_not_definition(self):
        assert is_definition_path("algo.svm.gamma") is False

    def test_bracket_marker_is_definition(self):
        assert is_definition_path("mask[]") is True

    def test_instance_index_is_not_definition(self):
        assert is_definition_path("mask[2]") is False


class TestDefinitionForm:
    """`definition_form` (M10.6): blank every concrete index to `"[]"` —
    the inverse of `split_instance_path`'s peel."""

    def test_plain_name_is_its_own_definition_form(self):
        assert definition_form("algo.svm.gamma") == "algo.svm.gamma"

    def test_single_index(self):
        assert definition_form("workers[0].timeout_s") == "workers[].timeout_s"

    def test_nested_indices(self):
        assert definition_form("g[0][1]") == "g[][]"

    def test_index_across_segments(self):
        assert definition_form("layers[2].act[1]") == "layers[].act[]"

    def test_already_definition_form_is_idempotent(self):
        assert definition_form("workers[].timeout_s") == "workers[].timeout_s"

    def test_empty_path_raises(self):
        with pytest.raises(ResolutionError):
            definition_form("")


class TestStripLastIndex:
    """`strip_last_index` (M10.7): peel one trailing `"[i]"` bracket group,
    the "which lift does this concrete sibling belong to" step re-derived
    by hand (`path[: path.rindex("[")]`) in half a dozen modules before
    M10.7's traversal-extraction milestone."""

    def test_single_index(self):
        assert strip_last_index("stops[3]") == "stops"

    def test_nested_indices_peels_only_the_last(self):
        assert strip_last_index("stops[3][1]") == "stops[3]"

    def test_index_after_a_dotted_field(self):
        assert strip_last_index("layers.act[1]") == "layers.act"


class TestElementPrefix:
    """`element_prefix` (M10.7): the lift's element-template prefix, unifying
    the two idioms every space-guided walker rederived: a bare definition
    path gets `"[]."` appended; an existing `"[]."`/`"[i]."`-terminated
    prefix gets its trailing dot dropped before another bracket group is
    appended (one level deeper, for a chained `.repeat().repeat()`)."""

    def test_bare_path(self):
        assert element_prefix("edges") == "edges[]."

    def test_existing_template_prefix_nests_one_level_deeper(self):
        assert element_prefix("grid[].") == "grid[][]."

    def test_composes_with_strip_last_index_from_a_concrete_instance(self):
        # The "which lift template does this concrete sibling belong to"
        # composition every walker needs to go from an instance path
        # (`"stops[3]"`) back to that lift's own element template.
        assert element_prefix(strip_last_index("stops[3]")) == "stops[]."


class TestInstancePrefix:
    def test_builds_the_concrete_per_instance_prefix(self):
        assert instance_prefix("stops", 3) == "stops[3]."

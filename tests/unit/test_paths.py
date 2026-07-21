"""paths/ grammar unit tests (API.md, "Paths and Scoping").

Segment := name ("[" i "]")* (instance) | name ("[]")* (definition). No
lift lands until M4, so brackets are never produced by resolution yet —
this exercises the parser directly, "multi-index ready" ahead of need.
"""

from __future__ import annotations

import pytest

from designspace.errors import ResolutionError
from designspace.paths import Segment, is_definition_path, join_path, parse_path


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

"""Conformance laws: charts (API.md, "Charts").

Laws enforced here: `chart_known_answers`, `integer_floor_uniformity`,
`quantized_cell_measure`, `grid_canonicalization_invariance`.

Also asserted, from row 9's "Requires" column: a valid `Power` chart is a
monotone bijection onto `[lo, hi]`, and every domain the column rejects
raises `ResolutionError`.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from designspace.charts._build import build_chart
from designspace.charts._grid import build_grid_shape, grid_membership
from designspace.ir import IntegerDomain, Log, Logit, Power, QuantizedSpec, RealDomain


def _chart(type_kind, domain, prior=None, quantized=None):
    return build_chart("x", type_kind, domain, prior, quantized)


class TestUniformKnownAnswer:
    def test_from_unit(self):
        c = _chart("real", RealDomain(0.0, 10.0))
        assert c.from_unit(0.0) == pytest.approx(0.0)
        assert c.from_unit(0.5) == pytest.approx(5.0)
        assert c.from_unit(1.0) == pytest.approx(10.0)

    def test_to_unit_inverts(self):
        c = _chart("real", RealDomain(-5.0, 5.0))
        for u in (0.0, 0.25, 0.5, 0.75, 1.0):
            v = c.from_unit(u)
            assert c.to_unit(v) == pytest.approx(u)

    def test_degenerate_constant_chart(self):
        c = _chart("real", RealDomain(3.0, 3.0))
        assert c.from_unit(0.0) == 3.0
        assert c.from_unit(0.7) == 3.0
        assert c.from_unit(1.0) == 3.0


class TestLogKnownAnswer:
    def test_from_unit_endpoints(self):
        c = _chart("real", RealDomain(1e-5, 1.0), Log())
        assert c.from_unit(0.0) == pytest.approx(1e-5)
        assert c.from_unit(1.0) == pytest.approx(1.0)

    def test_from_unit_midpoint_is_geometric_mean(self):
        c = _chart("real", RealDomain(1.0, 100.0), Log())
        assert c.from_unit(0.5) == pytest.approx(10.0)

    def test_subnormal_range(self):
        # lo well inside float64's subnormal range (< ~2.225e-308).
        lo, hi = 1e-310, 1e-300
        c = _chart("real", RealDomain(lo, hi), Log())
        assert c.from_unit(0.0) == pytest.approx(lo, rel=1e-9)
        assert c.from_unit(1.0) == pytest.approx(hi, rel=1e-9)
        # monotone increasing
        prev = c.from_unit(0.0)
        for u in (0.1, 0.3, 0.5, 0.7, 0.9, 1.0):
            cur = c.from_unit(u)
            assert cur > prev
            prev = cur

    def test_requires_positive_lo(self):
        from designspace.errors import ResolutionError

        with pytest.raises(ResolutionError):
            _chart("real", RealDomain(-1.0, 1.0), Log())


class TestLogitKnownAnswer:
    def test_symmetric_midpoint_is_half(self):
        c = _chart("real", RealDomain(0.1, 0.9), Logit())
        assert c.from_unit(0.5) == pytest.approx(0.5)

    def test_endpoints(self):
        c = _chart("real", RealDomain(0.1, 0.9), Logit())
        assert c.from_unit(0.0) == pytest.approx(0.1)
        assert c.from_unit(1.0) == pytest.approx(0.9)

    def test_requires_domain_in_unit_interval(self):
        from designspace.errors import ResolutionError

        with pytest.raises(ResolutionError):
            _chart("real", RealDomain(0.0, 0.5), Logit())
        with pytest.raises(ResolutionError):
            _chart("real", RealDomain(0.5, 1.0), Logit())


class TestPowerKnownAnswer:
    def test_p1_reduces_to_uniform(self):
        c = _chart("real", RealDomain(0.0, 10.0), Power(1))
        assert c.from_unit(0.5) == pytest.approx(5.0)

    def test_p2_known_value(self):
        c = _chart("real", RealDomain(1.0, 4.0), Power(2))
        expected = (1.0 + 0.5 * (16.0 - 1.0)) ** 0.5
        assert c.from_unit(0.5) == pytest.approx(expected)

    def test_endpoints(self):
        c = _chart("real", RealDomain(2.0, 8.0), Power(3))
        assert c.from_unit(0.0) == pytest.approx(2.0)
        assert c.from_unit(1.0) == pytest.approx(8.0)

    def test_rejects_p_zero(self):
        from designspace.errors import ResolutionError

        with pytest.raises(ResolutionError):
            _chart("real", RealDomain(1.0, 4.0), Power(0))

    def test_rejects_negative_p_at_zero_lo(self):
        from designspace.errors import ResolutionError

        with pytest.raises(ResolutionError):
            _chart("real", RealDomain(0.0, 4.0), Power(-1))


class TestPowerMonotoneBijectionLaw:
    """Row 9: every valid `Power` chart is a monotone bijection onto `[lo, hi]`.

    Every domain the "Requires" column rejects raises `ResolutionError`.
    See API.md, "Charts" > "Built-in prior families".
    """

    @pytest.mark.parametrize(
        ("lo", "hi", "p"),
        [
            (1.0, 4.0, 2),
            (2.0, 8.0, 3),
            (0.0, 10.0, 1),
            (-4.0, -2.0, 3),  # odd p: fully general, even over a negative domain
            (-2.0, 5.0, 3),  # odd p: fully general, even straddling zero
        ],
    )
    def test_valid_domain_is_a_monotone_bijection(self, lo, hi, p):
        c = _chart("real", RealDomain(lo, hi), Power(p))
        assert c.from_unit(0.0) == pytest.approx(lo)
        assert c.from_unit(1.0) == pytest.approx(hi)
        us = [i / 20 for i in range(21)]
        values = [c.from_unit(u) for u in us]
        assert all(a < b for a, b in pairwise(values))

    @pytest.mark.parametrize(
        ("lo", "hi", "p"),
        [
            (-2.0, 3.0, 2),  # straddles zero, domain-incomplete
            (-1.0, 1.0, 2),  # straddles zero, degenerate lo**p == hi**p
            (-4.0, -2.0, 2),  # all-negative, even p: monotone yet unrecoverable
            (-3.0, -1.0, 4),  # all-negative, even p (another exponent)
        ],
    )
    def test_row_9_violation_raises(self, lo, hi, p):
        from designspace.errors import ResolutionError

        with pytest.raises(ResolutionError, match="'x'"):
            _chart("real", RealDomain(lo, hi), Power(p))


class TestFloorIntegerUniformity:
    def test_chi_square_uniform(self):
        lo, hi = 1, 20
        n_bins = hi - lo + 1
        c = _chart("integer", IntegerDomain(lo, hi))
        rng = np.random.default_rng(12345)
        n_draws = 20_000
        counts = np.zeros(n_bins)
        for _ in range(n_draws):
            v = c.from_unit(float(rng.random()))
            counts[v - lo] += 1
        expected = n_draws / n_bins
        chi_sq = float(np.sum((counts - expected) ** 2 / expected))
        # df = n_bins - 1 = 19; critical value at alpha=0.01 is ~36.19.
        # Fixed seed makes this deterministic, not flaky.
        assert chi_sq < 36.19, f"chi-square {chi_sq} exceeds critical value (counts={counts})"

    def test_endpoint_bias_free(self):
        # No endpoint bias: floor(chart(u)) over [lo, hi+1) hits lo and hi
        # each with weight 1 like every other integer.
        c = _chart("integer", IntegerDomain(0, 3))
        rng = np.random.default_rng(7)
        counts = {0: 0, 1: 0, 2: 0, 3: 0}
        for _ in range(40_000):
            counts[c.from_unit(float(rng.random()))] += 1
        total = sum(counts.values())
        for n in counts.values():
            assert abs(n / total - 0.25) < 0.01, counts


class TestQuantizedCellMeasure:
    def test_uniform_prior_equiprobable_grid(self):
        lo, hi, step = 0.0, 1.0, 0.25
        shape = build_grid_shape(lo, hi, step, None, False)
        c = _chart("real", RealDomain(lo, hi), None, QuantizedSpec(step=step, factor=None))
        rng = np.random.default_rng(99)
        n_draws = 20_000
        grid_points = [round(lo + k * step, 10) for k in range(shape.K + 1)]
        counts = dict.fromkeys(grid_points, 0)
        for _ in range(n_draws):
            v = round(c.from_unit(float(rng.random())), 10)
            counts[v] += 1
        expected = n_draws / len(grid_points)
        chi_sq = sum((n - expected) ** 2 / expected for n in counts.values())
        # df=4, alpha=0.01 critical value.
        assert chi_sq < 16.9, f"chi-square {chi_sq} exceeds critical value (counts={counts})"


class TestGridCanonicalizationInvariance:
    def test_bit_different_representations_canonicalize_equal(self):
        shape = build_grid_shape(0.0, 1.0, 0.1, None, False)
        computed = 0.1 + 0.2  # 0.30000000000000004, not bit-identical to 0.3
        literal = 0.3
        assert computed != literal  # sanity: genuinely bit-different
        canon_computed = grid_membership(shape, computed)
        canon_literal = grid_membership(shape, literal)
        assert canon_computed is not None
        assert canon_computed == canon_literal

    def test_off_grid_value_rejected(self):
        shape = build_grid_shape(0.0, 1.0, 0.25, None, False)
        assert grid_membership(shape, 0.1) is None

    def test_degenerate_single_point_grid(self):
        shape = build_grid_shape(0.0, 0.1, 1.0, None, False)
        assert shape.K == 0
        assert grid_membership(shape, 0.0) == 0.0
        assert grid_membership(shape, 0.1) is None

    def test_include_hi_appends_endpoint(self):
        shape = build_grid_shape(0.0, 1.0, 0.3, None, True)
        # 0.3 doesn't evenly divide 1.0: grid is 0.0, 0.3, 0.6, 0.9, plus hi=1.0
        assert grid_membership(shape, 1.0) == 1.0
        assert grid_membership(shape, 0.9) == pytest.approx(0.9)

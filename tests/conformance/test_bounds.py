"""Conformance laws: expression bounds.

See API.md, "Constraints and Feasibility" > "Expression bounds are sugar".

Laws enforced here: `polarity_tracks_feasibility`, `tighten_equals_reject`.

Also asserted: the bound-origin coupling yields the `y - x` margin the spec
states, computed through the ordinary margin machinery on the constraint's
stored, desired-state predicate; and the sugared param's envelope equals a
hand-written literal-bound param's domain, the two spaces agreeing on
feasibility for every sampled config.

Expression equality against a hand-written `.forbid()` is deliberately not
asserted. A bound-origin constraint stores the desired predicate `x <= y`,
which the margin sign above and fingerprint equality with the manual
expansion both require. A hand-built equivalent stores the opposite shape,
`.forbid(x > y)`, `.forbid()`'s convention being that its argument names the
forbidden state. The two differ in stored shape and margin sign by design.

`tighten_equals_reject` is checked both ways: a white-box check that the
shipped sampler narrows a tightenable param's chart in place, and a
two-sample KS test against a reference sampler that always draws from the
full envelope and rejects.
"""

from __future__ import annotations

import numpy as np

import designspace as ds
from designspace.eval import compute_activity, evaluate_constraint
from designspace.ir import RealDomain
from designspace.resolve._bounds import bound_origin_targets
from designspace.sample._sample import _tighten, _tightenable


class TestBoundOriginMargin:
    def test_margin_is_y_minus_x(self):
        space = ds.space(
            ds.param("y").real(0.0, 100.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        constraint = space.constraints[0]
        config = {"x": 30.0, "y": 80.0}
        activity = compute_activity(space, config)
        ce = evaluate_constraint(constraint, config, activity, space)
        assert ce.margin == 50.0  # y - x

    def test_negative_margin_when_x_exceeds_y(self):
        space = ds.space(
            ds.param("y").real(0.0, 100.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        constraint = space.constraints[0]
        config = {"x": 90.0, "y": 10.0}
        activity = compute_activity(space, config)
        ce = evaluate_constraint(constraint, config, activity, space)
        assert ce.margin == -80.0

    def test_violation_makes_the_space_infeasible(self):
        space = ds.space(
            ds.param("y").real(0.0, 100.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        assert space.validate({"x": 90.0, "y": 10.0}).valid is False
        assert space.validate({"x": 10.0, "y": 90.0}).valid is True


class TestStructuralEquivalenceToHandWrittenExpansion:
    def test_envelope_matches_manual_literal_bound(self):
        sugared = ds.space(
            ds.param("y").real(0.0, 100.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        manual = ds.space(
            ds.param("y").real(0.0, 100.0),
            ds.param("x").real(0.0, 100.0),
        ).forbid(ds.param("x") > ds.param("y"))
        assert sugared.params["x"].domain == manual.params["x"].domain == RealDomain(0.0, 100.0)

    def test_feasibility_agrees_across_sampled_configs(self):
        sugared = ds.space(
            ds.param("y").real(0.0, 100.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        manual = ds.space(
            ds.param("y").real(0.0, 100.0),
            ds.param("x").real(0.0, 100.0),
        ).forbid(ds.param("x") > ds.param("y"))
        for cfg in sugared.sample_dicts(200, seed=0):
            assert sugared.validate(cfg).valid
            assert manual.validate(cfg).valid  # same param shapes, same predicate


class TestTightenNotReject:
    def test_tighten_narrows_domain_and_chart_in_place(self):
        """A white-box check that the tightening mechanism itself fires.

        The KS test below checks only that the result is distributionally
        equivalent to rejection, and cannot distinguish a tightened sampler
        from one that is still rejecting and got lucky, both being draws
        from the same theoretical law.
        """
        space = ds.space(
            ds.param("y").real(10.0, 20.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        pd = space.params["x"]
        assert _tightenable(pd)
        bounds = bound_origin_targets(space)["x"]
        config = {"y": 12.0}
        activity = {"y": True}
        tightened = _tighten(pd, bounds, config, activity, space)
        assert tightened.domain == RealDomain(0.0, 12.0)
        assert tightened.chart is not None
        assert tightened.chart.from_unit(1.0) <= 12.0

    def test_quantized_param_is_not_tightenable(self):
        space = ds.space(
            ds.param("y").real(10.0, 20.0),
            ds.param("x").real(0.0, ds.param("y")).quantized(step=0.5),
        )
        assert not _tightenable(space.params["x"])

    def test_log_scaled_bound_expression_samples_feasibly(self):
        """A log-scaled bound expression samples feasibly.

        `_tightenable` admits `Log`, `Logit` and `Power` as well as the
        default uniform prior exercised elsewhere in this file. Exercising
        one end-to-end checks empirically that a sub-interval preserves the
        family's own requirement. `Log` needs `lo > 0`, and a tightened
        `[1, y]` for `y` in `[1, 100]` always satisfies that.
        """
        space = ds.space(
            ds.param("y").real(1.0, 100.0),
            ds.param("x").real(1.0, ds.param("y")).log_scale(),
        )
        assert space.params["x"].prior is not None
        for cfg in space.sample_dicts(200, seed=2):
            assert 1.0 <= cfg["x"] <= cfg["y"]

    def test_sampling_succeeds_even_when_the_coupling_dominates_the_envelope(self):
        """`x`'s envelope is pinned to `y`'s declared hi (20.0), but every
        draw of `y` is confined to a narrow window near the envelope's low
        end. Confirms tightening (not luck) is what keeps this cheap and
        reliable across many draws. The white-box test above checks the
        mechanism directly.
        """
        space = ds.space(
            ds.param("y").real(10.0, 10.01),
            ds.param("x").real(0.0, ds.param("y")),
        )
        for cfg in space.sample_dicts(200, seed=1):
            assert 0.0 <= cfg["x"] <= cfg["y"]

    @staticmethod
    def _ks_statistic(a: np.ndarray, b: np.ndarray) -> float:
        a_sorted, b_sorted = np.sort(a), np.sort(b)
        all_vals = np.concatenate([a_sorted, b_sorted])
        cdf_a = np.searchsorted(a_sorted, all_vals, side="right") / len(a_sorted)
        cdf_b = np.searchsorted(b_sorted, all_vals, side="right") / len(b_sorted)
        return float(np.max(np.abs(cdf_a - cdf_b)))

    def test_tighten_vs_reject_distributional_equivalence(self):
        """Truncation equals conditioning (API.md, "All charts are static").

        The shipped, tightening sampler and a reference sampler that always
        draws `x` from the full envelope and rejects `x > y` are two Monte
        Carlo estimates of the same theoretical law, so a two-sample KS test
        finds no significant difference. Fixed seeds make this deterministic
        rather than flaky. The critical value is the standard two-sample
        asymptotic KS formula at alpha=0.01
        (`D_crit = 1.63 * sqrt((n1+n2)/(n1*n2))`).
        """
        space = ds.space(
            ds.param("y").real(10.0, 20.0),
            ds.param("x").real(0.0, ds.param("y")),
        )
        n = 3000
        prod_configs = space.sample_dicts(n, seed=123)
        xs_prod = np.array([c["x"] for c in prod_configs])

        y_chart = space.params["y"].chart
        x_chart = space.params["x"].chart  # the envelope chart, [0, 20]
        assert y_chart is not None and x_chart is not None
        rng = np.random.default_rng(456)
        xs_naive = np.empty(n)
        for i in range(n):
            y_val = y_chart.from_unit(float(rng.random()))
            while True:
                x_val = x_chart.from_unit(float(rng.random()))
                if x_val <= y_val:
                    break
            xs_naive[i] = x_val

        d_stat = self._ks_statistic(xs_prod, xs_naive)
        d_crit = 1.63 * (2 * n / n**2) ** 0.5
        assert d_stat < d_crit, f"KS statistic {d_stat} exceeds critical value {d_crit}"

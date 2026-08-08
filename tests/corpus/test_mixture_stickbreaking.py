"""Corpus: `mixture_stickbreaking`, end-to-end.

Resolve, sample 200, validate all, round-trip, plus the representation
surface this fixture was built for.
"""

from __future__ import annotations

from mixture_stickbreaking import (
    CUSTOM_TYPES,
    K_COMPONENTS,
    MixtureWeights,
    build_space,
    stickbreaking_rule,
)

from designspace import Space
from designspace.ir import ListDomain, RealDomain


def test_resolves():
    space = build_space()
    assert space.n_params == 3


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)
        assert len(cfg["weights"]) == K_COMPONENTS
        assert abs(sum(cfg["weights"]) - 1.0) < 1e-9


def test_round_trips():
    space = build_space()
    doc = space.to_json()
    restored = Space.from_json(doc, custom_types=CUSTOM_TYPES)
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=1):
        assert restored.validate(cfg).valid


def test_describe_round_trip_law():
    pt = MixtureWeights(k=5)
    rebuilt = MixtureWeights(**pt.describe())
    assert rebuilt.k == pt.k


class TestRepresentationMorphism:
    """A chosen morphism, mixed genotypes, and the custom-to-u-space bridge.

    Core ships none of the three.
    """

    def test_only_weights_is_encoded(self):
        space = build_space()
        rep = space.represent(stickbreaking_rule)
        assert rep.encoded == ("weights",)

    def test_mixed_genotypes_means_and_scale_pass_through_unconverted(self):
        # No rule matches "means"/"scale" -- represent() given an explicit
        # rule never falls back to the induced rule for what it misses, so
        # these stay in their *original* phenotype units in the target,
        # unlike the induced representation's own unit-interval conversion.
        space = build_space()
        rep = space.represent(stickbreaking_rule)
        means_domain = rep.target.params["means"].domain
        assert isinstance(means_domain, ListDomain)
        assert means_domain.element_domain == RealDomain(-5.0, 5.0)
        assert rep.target.params["scale"].domain == RealDomain(0.1, 2.0)
        assert rep.target.params["scale"].prior is not None  # log_scale preserved untouched

    def test_weights_targets_k_minus_1_unit_reals(self):
        space = build_space()
        rep = space.represent(stickbreaking_rule)
        domain = rep.target.params["weights"].domain
        assert isinstance(domain, ListDomain)
        assert domain.count == K_COMPONENTS - 1
        assert domain.element_domain == RealDomain(0.0, 1.0)

    def test_decode_totality_and_feasibility_agreement(self):
        space = build_space()
        rep = space.represent(stickbreaking_rule)
        for g in rep.target.sample_dicts(200, seed=2):
            p = rep.decode(g)
            assert space.validate(p).param_errors == ()
            assert rep.target.is_feasible(g) == space.is_feasible(p)

    def test_round_trip_via_check(self):
        space = build_space()
        rep = space.represent(stickbreaking_rule)
        result = rep.check(n=200, seed=3)
        assert result.ok, result.failures

    def test_encode_decode_recovers_the_stick_breaking_fractions(self):
        space = build_space()
        rep = space.represent(stickbreaking_rule)
        assert rep.invertible is True
        for g in rep.target.sample_dicts(50, seed=4):
            p = rep.decode(g)
            back = rep.encode(p)
            for a, b in zip(g["weights"], back["weights"], strict=True):
                assert abs(a - b) < 1e-9

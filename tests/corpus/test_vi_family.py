"""Corpus: `vi_family` end-to-end (resolve -> sample 200 -> validate all ->
round-trip); also exercises the M9 gate items this fixture was built for.
"""

from __future__ import annotations

from vi_family import CUSTOM_TYPES, FixedTopology, GraphTopology, build_finite_space, build_space

import designspace as ds
from designspace.build._space import Space


def test_resolves():
    space = build_space()
    assert space.n_params == 2


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_canonical_ordering_law():
    # A prop-driven lift count: the number of edge_weight elements always
    # matches the topology's realized edge count.
    space = build_space()
    for cfg in space.sample_dicts(50, seed=1):
        assert len(cfg["edge_weight"]) == len(cfg["topology"])


def test_connectivity_constraint_holds():
    from vi_family import _is_connected

    space = build_space()
    for cfg in space.sample_dicts(50, seed=2):
        edges = [(i, j) for i, j in cfg["topology"]]
        assert _is_connected(5, edges)


def test_round_trips():
    space = build_space()
    doc = space.to_json()
    restored = Space.from_json(doc, custom_types=CUSTOM_TYPES)
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=3):
        assert restored.validate(cfg).valid


def test_describe_round_trip_law():
    # factory(x.describe()) ≡ x
    pt = GraphTopology(n_nodes=6, max_degree=4, connected=False)
    rebuilt = GraphTopology(**pt.describe())
    assert rebuilt == pt


def test_non_generative_custom_needs_default_or_freeze():
    space = ds.space(ds.param("fixed").custom(FixedTopology(n_nodes=3)))
    assert space.has_nongenerative_params
    import pytest

    from designspace.errors import SamplingError

    with pytest.raises(SamplingError):
        space.sample_one(seed=0)

    defaulted = ds.space(ds.param("fixed").custom(FixedTopology(n_nodes=3)).default([[0, 1]]))
    assert defaulted.sample_one(seed=0) == {"fixed": [[0, 1]]}


def test_cardinality_exact_on_finite_fixture():
    space = build_finite_space()
    # FixedFamily(n_nodes=3): 2**3 = 8 possible edge subsets; depth: 1..3 (3).
    assert space.cardinality() == 8 * 3


def test_cardinality_none_on_unquantized_custom_without_declared_cardinality():
    space = build_space()  # GraphTopology declares no cardinality()
    assert space.cardinality() is None

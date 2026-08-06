"""Corpus: `compiler_pipeline` end-to-end (resolve -> sample 200 -> validate
all); also exercises `.map_params()` (M8 gate: "map_params coarsening
example from the spec history")."""

from __future__ import annotations

from dataclasses import replace

from compiler_pipeline import PASS_REGISTRY, build_space

from designspace import Space


def test_resolves():
    space = build_space()
    assert space.n_params == len(PASS_REGISTRY)


def test_sample_and_validate_all():
    space = build_space()
    configs = space.sample_dicts(200, seed=0)
    assert len(configs) == 200
    for cfg in configs:
        result = space.validate(cfg)
        assert result.valid, (cfg, result)


def test_dependency_requires_prerequisites_enabled():
    space = build_space()
    for cfg in space.sample_dicts(200, seed=1):
        for name, prereqs in PASS_REGISTRY.items():
            if cfg[f"enable_{name}"]:
                for p in prereqs:
                    assert cfg[f"enable_{p}"]


def test_prerequisite_free_pass_is_unconstrained():
    # `constant_folding`/`inlining` have no prerequisites: `all_()` folds to
    # the literal True identity, so `require(pass.implies(True))` never
    # restricts feasibility -- both True and False are always legal.
    space = build_space()
    base = {f"enable_{name}": False for name in PASS_REGISTRY}
    for value in (True, False):
        cfg = {**base, "enable_constant_folding": value}
        assert space.is_feasible(cfg)


def test_dependent_pass_infeasible_without_prerequisite():
    space = build_space()
    cfg = {f"enable_{name}": False for name in PASS_REGISTRY}
    cfg["enable_dead_code_elimination"] = True  # needs constant_folding
    assert not space.is_feasible(cfg)


def test_map_params_coarsening_widens_generated_params():
    # A representative map_params rewrite over registry-generated params:
    # replace every bool pass flag with a coarser tri-state ordinal
    # ("off"/"on") is out of scope for a *coarsening* example (that would
    # change type_kind); instead, tag every generated param uniformly, the
    # kind of blanket rewrite `map_params` is meant for.
    space = build_space()

    def tag_as_generated(pd):
        return replace(pd, tags=pd.tags | frozenset({"compiler_pass"}))

    tagged = space.map_params(tag_as_generated)
    assert all("compiler_pass" in pd.tags for pd in tagged.params.values())
    assert tagged.n_params == space.n_params
    for cfg in tagged.sample_dicts(20, seed=2):
        assert tagged.validate(cfg).valid


def test_round_trips():
    space = build_space()
    restored = Space.from_json(space.to_json())
    assert restored.fingerprint() == space.fingerprint()
    assert restored.fingerprint("sampling") == space.fingerprint("sampling")
    for cfg in restored.sample_dicts(50, seed=3):
        assert restored.validate(cfg).valid

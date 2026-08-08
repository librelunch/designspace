"""Known-answer digest vectors, one per corpus fixture.

Laws enforced here: `digest_known_answers`.

This module reads and asserts, and never regenerates. A missing vector file
is a hard failure, `FileNotFoundError` propagating rather than a silent
compute-and-write fallback, which would make the vectors detect nothing. To
add or update a vector deliberately, under the version-bump protocol, run
`tests/conformance/vectors/_generate.py` by hand.

The `to_json` vector is compared as a parsed dict rather than as a string.
JCS, and therefore byte-stability, governs the digest preimage rather than
this file's own JSON formatting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
VECTORS_DIR = Path(__file__).resolve().parent / "vectors"

if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))

FIXTURES = [
    "flat_hpo",
    "greenhouse",
    "flow_chemistry",
    "job_shop",
    "sat_solver",
    "wind_farm_grid",
    "delivery_routes",
    "solver_portfolio",
    "memetic_pipeline",
    "firmware_buffers",
    "pump_configurator",
    "compiler_pipeline",
    "vi_family",
    "mixture_stickbreaking",
    "annealing_schedule",
]


def _load_vector(name: str) -> dict:
    path = VECTORS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"missing known-answer vector {path}; generate it with "
            "`uv run python tests/conformance/vectors/_generate.py` "
            "(deliberately, per the version-bump protocol; never auto-generated)"
        )
    return json.loads(path.read_text())


@pytest.mark.parametrize("name", FIXTURES)
def test_fingerprint_matches_known_answer(name):
    import importlib

    space = importlib.import_module(name).build_space()
    vector = _load_vector(name)
    assert space.fingerprint("full") == vector["fingerprint_full"]
    assert space.fingerprint("sampling") == vector["fingerprint_sampling"]


@pytest.mark.parametrize("name", FIXTURES)
def test_to_json_matches_known_answer(name):
    import importlib

    space = importlib.import_module(name).build_space()
    vector = _load_vector(name)
    assert space.to_json() == vector["to_json"]

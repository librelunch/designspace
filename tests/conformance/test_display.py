"""Conformance laws: human-readable rendering.

See API.md, "Human-Readable Rendering".

Laws enforced here: `display_totality`, `display_accounts_for_every_param`,
`display_paths_use_the_grammar`, `display_respects_the_width_budget`,
`display_elides_without_truncating`, `repr_is_unchanged`,
`expression_render_distinguishes`, `display_escapes_html`,
`symbolic_ast_is_not_rendered_as_source`.

The corpus fixtures drive most of these: `str()` and the notebook display
hooks are exercised on every displayable type that appears in a real space,
rather than on hand-built dataclass instances whose field combinations might
not occur in practice. A per-kind matrix, mirroring
`tests/conformance/test_kind_surface_matrix.py`'s but kept local since
conformance modules do not import each other, fills in the kinds no corpus
fixture exercises directly (bare custom, quantized, periodic, every lift
shape).
"""

from __future__ import annotations

import importlib
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pytest

import designspace as ds
from designspace.display._space import _walk
from designspace.paths._grammar import definition_form, parse_path

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))

FIXTURES = [
    "annealing_schedule",
    "compiler_pipeline",
    "delivery_routes",
    "firmware_buffers",
    "flat_hpo",
    "flow_chemistry",
    "greenhouse",
    "job_shop",
    "memetic_pipeline",
    "mixture_stickbreaking",
    "nested_survey",
    "pump_configurator",
    "sat_solver",
    "solver_portfolio",
    "vi_family",
    "wind_farm_grid",
]

WIDTH_BUDGET = 88


def _build(name: str) -> ds.Space:
    return importlib.import_module(name).build_space()


SPACES = {name: _build(name) for name in FIXTURES}


class _Printer:
    """A minimal stand-in for IPython's `PrettyPrinter`, capturing `.text()`."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def text(self, s: str) -> None:
        self.parts.append(s)


def _pretty(obj: Any) -> str:
    p = _Printer()
    obj._repr_pretty_(p, False)
    return "".join(p.parts)


def _iter_domains(domain: Any):
    yield domain
    if isinstance(domain, ds.ListDomain):
        yield from _iter_domains(domain.element_domain)


def _iter_displayables(space: ds.Space):
    """Every displayable object a real space carries."""
    yield space
    for pd in space.params.values():
        yield pd
        yield from _iter_domains(pd.domain)
        if pd.prior is not None:
            yield pd.prior
        if pd.condition is not None:
            yield pd.condition
    yield from space.conditions
    yield from space.constraints
    yield from space.subspaces.values()


def _assert_renders(obj: Any) -> str:
    """`display_totality`: `str()` and the display hooks never raise."""
    text = str(obj)
    assert isinstance(text, str) and text
    assert _pretty(obj) == text
    html = obj._repr_html_()
    assert isinstance(html, str) and html
    return text


class TestDisplayTotality:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_object_a_space_carries_renders(self, name):
        space = SPACES[name]
        for obj in _iter_displayables(space):
            _assert_renders(obj)

    @pytest.mark.parametrize("name", FIXTURES)
    def test_derived_results_render(self, name):
        space = SPACES[name]
        config = space.sample_one(seed=0)
        _assert_renders(space.validate(config))
        _assert_renders(space.evaluate_partial({}))
        _assert_renders(space.represent())
        report = space.sampling_report(n=20, seed=0)
        _assert_renders(report)
        for row in report.constraints:
            _assert_renders(row)


_SIG = ds.Signature(args={"x": float}, returns=float)


@dataclass(frozen=True)
class _Widget:
    """A minimal full-protocol `ParamType`, for the bare-custom kind."""

    size: int = 3

    @property
    def type_key(self) -> str:
        return "widget"

    def sample(self, rng: Any) -> dict[str, Any]:
        return {"n": int(rng.integers(0, self.size))}

    def validate(self, value: Any) -> bool:
        return isinstance(value, dict) and isinstance(value.get("n"), int)

    def to_json(self, value: Any) -> Any:
        return dict(value)

    def from_json(self, data: Any) -> Any:
        return dict(data)

    def describe(self) -> dict[str, Any]:
        return asdict(self)


# kind -> builder, covering the shapes no corpus fixture happens to use.
EXTRA_KINDS: dict[str, Any] = {
    "real_periodic": lambda: ds.param("p").real(0.0, 6.28, periodic=True),
    "real_quantized": lambda: ds.param("p").real(0.0, 1.0).quantized(step=0.25),
    "integer_quantized": lambda: ds.param("p").integer(0, 8).quantized(step=2),
    "custom_bare": lambda: ds.param("p").custom(_Widget()),
    "scalar_lift": lambda: ds.param("p").real(0.0, 1.0).repeat(3),
    "nested_lift": lambda: ds.param("p").real(0.0, 1.0).repeat(2).repeat(3),
    "struct_lift": lambda: ds.param("p").space(ds.param("w").real(0.0, 1.0)).repeat(3),
    "choice_lift": lambda: (
        ds.param("p").choice("a", b=ds.space(ds.param("w").real(0.0, 1.0))).repeat(2)
    ),
    "subset_lift": lambda: ds.param("p").subset(["a", "b"], min_size=1).repeat(2),
    "code": lambda: ds.param("p").code(_SIG),
    "symbolic": lambda: ds.param("p").symbolic(_SIG, primitives=["add", "x"], max_depth=3),
}


class TestDisplayTotalityByKind:
    @pytest.mark.parametrize("kind", sorted(EXTRA_KINDS))
    def test_kind_renders(self, kind):
        space = ds.space(EXTRA_KINDS[kind]())
        for obj in _iter_displayables(space):
            _assert_renders(obj)


class TestDisplayAccountsForEveryParam:
    """`space.params`, not the table's own traversal, is the enumeration a
    declared path is checked against: a path the table's walk never visits is
    a failure here even though nothing downstream of the walk could ever see
    it. A row-count cap is the only legitimate reason a declared path's label
    would be absent from the text, hence the `"more"` escape stays; a path the
    walk never reaches at all is not that, and gets no escape.
    """

    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_declared_path_is_named_or_elided(self, name):
        space = SPACES[name]
        text = str(space)
        labels = {
            path: label for path, _pd, _depth, label, _suppress in _walk(space, "", 0, "", None)
        }
        for path in space.params:
            assert path in labels, (name, path, "not reached by the table's own traversal")
            assert labels[path] in text or "more" in text, (name, path, labels[path], text)


# Any run of identifier characters, optionally bracket- and dot-chained, not
# immediately followed by "(" (which would make it an operator or method
# name such as `sum(` or `.prop(`).
_PATH_TOKEN_RE = re.compile(r"\b[A-Za-z_]\w*(?:\[\d*\])*(?:\.[A-Za-z_]\w*(?:\[\d*\])*)*\b(?!\s*\()")


class TestDisplayPathsUseTheGrammar:
    """`str(space)`'s row *labels* are deliberately tree-relative (a choice
    payload field shows as `gas.burner_power_kw`, not the real
    `heating.gas.burner_power_kw`), exactly as `nested_survey`'s `[].minutes`
    is relative to the `items` row above it: that is what a tree layout is
    for, and no more a free-floating path than a file tree's `bar.py` is a
    full filesystem path. What must be a genuine, resolvable path is a
    *reference inside an expression*: a condition, a constraint, or a lift's
    declared count. `str(ParamDef)` always prefixes with the real full path
    (`render_param_def`, unlike a table row, has no ancestor row to omit it
    for), so scanning it and every condition and constraint catches the bug
    this law exists for, `sum(stops.dwell_min)` missing its `[]` marker,
    without also flagging the table's intentionally relative labels.
    """

    @pytest.mark.parametrize("name", FIXTURES)
    def test_compound_tokens_are_declared_paths(self, name):
        space = SPACES[name]
        texts = [str(pd) for pd in space.params.values()]
        texts += [str(c) for c in space.conditions]
        texts += [str(c) for c in space.constraints]
        for text in texts:
            for token in _PATH_TOKEN_RE.findall(text):
                if "." not in token and "[" not in token:
                    continue  # a bare word; not the shape the bug under test takes
                segments = parse_path(token)  # raises ResolutionError if malformed
                assert segments
                key = definition_form(token)
                assert key in space.params, (name, token, key, text)


class TestDisplayRespectsTheWidthBudget:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_no_line_exceeds_the_budget(self, name):
        text = str(SPACES[name])
        for line in text.splitlines():
            assert len(line) <= WIDTH_BUDGET, (name, len(line), line)


class TestDisplayElidesWithoutTruncating:
    def test_a_long_categorical_elides_with_a_count(self):
        values = tuple(f"opt_{i}" for i in range(40))
        space = ds.space(ds.param("p").categorical(*values))
        text = str(space)
        assert "opt_0" in text
        assert "more" in text
        assert not text.rstrip().endswith("...")
        assert "opt_39" not in text or "more" not in text

    def test_a_long_choice_elides_with_a_count(self):
        variants = {f"v{i}": ds.space(ds.param("w").real(0.0, 1.0)) for i in range(30)}
        space = ds.space(ds.param("p").choice("base", **variants))
        text = str(space)
        assert "more" in text


class TestReprIsUnchanged:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_repr_stays_the_dataclass_form(self, name):
        space = SPACES[name]
        assert repr(space).startswith("Space(")
        for pd in space.params.values():
            assert repr(pd).startswith("ParamDef(")
            assert str(pd) != repr(pd)
        assert str(space) != repr(space)

    def test_domain_repr_is_the_constructor_form(self):
        d = ds.RealDomain(0.0, 1.0)
        assert repr(d) == "RealDomain(lo=0.0, hi=1.0)"


class TestExpressionRenderDistinguishes:
    def test_operators_render_their_own_spelling(self):
        x = ds.param("x").real(0.0, 1.0)
        y = ds.param("y").real(0.0, 1.0)
        cases = {
            (x < y): "<",
            (x <= y): "<=",
            (x > y): ">",
            (x >= y): ">=",
            (x == y): "==",
            (x != y): "!=",
        }
        seen = set()
        for expr, op in cases.items():
            text = str(expr)
            assert op in text
            assert text not in seen
            seen.add(text)

    def test_distinct_expressions_render_distinctly(self):
        x = ds.param("x").real(0.0, 1.0)
        y = ds.param("y").real(0.0, 1.0)
        renders = {str(x < y), str(x > y), str((x < y) & (x > y)), str((x < y) | (x > y))}
        assert len(renders) == 4

    def test_a_fallback_expression_renders_not_its_repr(self):
        space = ds.space(
            ds.param("n").integer(0, 3),
            ds.param("vals").real(0.0, 1.0).repeat(ds.param("n")),
        )
        total = ds.value(sum, ds.param("vals"), returns=float).if_inactive(0)
        space = space.forbid(total > 10)
        text = str(space.constraints[0].expr)
        assert "Literal(" not in text
        assert "value(" in text


class TestDisplayEscapesHtml:
    def test_a_dangerous_categorical_value_is_escaped_in_html(self):
        space = ds.space(ds.param("p").categorical("<script>", "b&b", "ok"))
        html = space._repr_html_()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "&amp;lt;" in html

    def test_a_dangerous_path_name_is_escaped_in_html(self):
        space = ds.space(ds.param("<bad>").real(0.0, 1.0))
        html = space._repr_html_()
        assert "<bad>" not in html


class TestSymbolicAstIsNotRenderedAsSource:
    def test_symbolic_domain_shows_declaration_not_a_value(self):
        sig = ds.Signature(args={"x": float}, returns=float)
        space = ds.space(
            ds.param("expr").symbolic(sig, primitives=["add", "mul", "x"], max_depth=3)
        )
        text = str(space)
        assert "x: float" in text or "x:float" in text
        assert "'op'" not in text and '"op"' not in text

    def test_a_symbolic_value_default_does_not_dump_the_ast(self):
        sig = ds.Signature(args={"x": float}, returns=float)
        value = {"ast": {"var": "x"}, "source": "x"}
        space = ds.space(
            ds.param("expr").symbolic(sig, primitives=["x"], max_depth=2).default(value)
        )
        text = str(space)
        assert "'var': 'x'" not in text
        assert len(max(text.splitlines(), key=len)) <= WIDTH_BUDGET

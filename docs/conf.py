"""Sphinx configuration for the designspace documentation site (PLAN.md, M13.5).

The API reference is generated from the docstrings M13 wrote; this file adds no
prose of its own. Two things here are load-bearing and should not be relaxed
without reading M13.5 in `PLAN.md`:

- `nitpicky` is on and the build runs under `-W`. Measured at M13.5's open: a
  default-level build was already clean over all 90 exports, so it could never
  have caught anything. Nitpicky found a docstring that napoleon renders with
  the wrong type, which griffe's gate structurally cannot see.
- every `nitpick_ignore` entry carries the reason it is there. An unexplained
  ignore is indistinguishable from a bug someone silenced.
"""

from __future__ import annotations

project = "designspace"
author = "Jonathan Wurth"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "myst_parser",
    "sphinx_copybutton",
]

templates_path = ["_templates"]
exclude_patterns = ["_build"]

# M13 chose NumPy-style sections; Google style is off so a malformed NumPy
# block cannot be silently reinterpreted as a valid Google one.
napoleon_numpy_docstring = True
napoleon_google_docstring = False

# Cross-document links to a heading (`structured-values.md#tier-3-a-custom-type`)
# need MyST to emit anchor targets. docutils gives the rendered HTML an `id`
# either way, so without this a link silently points at nothing.
myst_heading_anchors = 3

autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "signature"

html_theme = "pydata_sphinx_theme"
html_title = "designspace"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "polars": ("https://docs.pola.rs/api/python/stable", None),
}

nitpicky = True

nitpick_ignore = [
    # The read-only mapping views' annotation renders unqualified, so it cannot
    # resolve to `types.MappingProxyType` through intersphinx.
    ("py:class", "MappingProxyType"),
    # polars publishes 143 `polars.DataFrame.*` method entries in its inventory
    # and no `polars.DataFrame` class entry, so there is no upstream target to
    # link to. Verified against the published objects.inv, not assumed.
    ("py:class", "polars.DataFrame"),
    ("py:class", "pl.DataFrame"),
]

nitpick_ignore_regex = [
    # Private types reachable from a public annotation. `_ElementSnapshot` is
    # the one M13 deliberately left private (builder state behind
    # `ParamExpr.lift`); `_NumericParamExpr` is a shared base of the real and
    # integer view types, surfaced by `:show-inheritance:`.
    (r"py:.*", r"designspace\..*\._.*"),
    # `{"raise", "mark", "drop"}` is the canonical NumPy "one of" spelling and
    # the docstrings using it are correct. Napoleon splits it per token and
    # tries to resolve each fragment as a class; these two patterns match the
    # opening and closing fragments. Degrading the docstrings to a bare `str`
    # to satisfy the checker would be the wrong trade.
    (r"py:.*", r'^[{"].*'),
    (r"py:.*", r'.*[}"]$'),
]

"""Sphinx configuration for the designspace documentation site.

The API reference is generated from the docstrings, and this file adds no
prose of its own. Two things here are load-bearing and should not be
relaxed:

- `nitpicky` is on and the build runs under `-W`. A default-level build was
  already clean over every export when this was set, so it could never have
  caught anything. Nitpicky found a docstring that napoleon renders with the
  wrong type, which griffe's gate structurally cannot see.
- Every `nitpick_ignore` entry carries the reason it is there. An
  unexplained ignore is indistinguishable from a bug someone silenced.
"""

from __future__ import annotations

from importlib.metadata import version as _distribution_version

project = "designspace"
author = "Jonathan Wurth"
# Read from the installed distribution rather than written here, so the release
# the site reports cannot disagree with the one it documents.
release = _distribution_version("designspace")
version = release

# The deployed host. Canonical link tags resolve against it, so a page served
# from the site does not advertise a relative address.
html_baseurl = "https://librelunch.github.io/designspace/"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    # `myst_nb`, NOT `myst_parser`. myst-nb registers itself as the `.md` parser
    # with `override=True` and calls myst-parser's own setup internally; listing
    # both raises a bare `ExtensionError` at startup with no indication of the
    # cause (myst-nb #421, #653). Every MyST setting below still applies.
    "myst_nb",
    "sphinx_copybutton",
    "sphinx_design",
]

templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    # myst-nb writes each executed page here, inside the source directory. Left
    # unexcluded, Sphinx reads those notebooks back as source documents on the
    # *next* build and reports every one as an orphan plus a broken xref, so a
    # first build passes and every later one fails. The cache is excluded for
    # the same reason.
    "jupyter_execute",
    ".jupyter_cache",
]

# The docstrings use NumPy-style sections. Google style is off, so that a
# malformed NumPy block cannot be silently reinterpreted as a valid Google
# one.
napoleon_numpy_docstring = True
napoleon_google_docstring = False

# Cross-document links to a heading (`structured-values.md#a-custom-type`)
# need MyST to emit anchor targets. docutils gives the rendered HTML an `id`
# either way, so without this a link silently points at nothing.
myst_heading_anchors = 3

# MyST ships with no optional extensions enabled. `colon_fence` is the one the
# site needs: sphinx-design's directives nest, and `:::` delimiters let an outer
# `{tab-set}` contain inner ```` ``` ```` code fences without either closing the
# other.
myst_enable_extensions = ["colon_fence"]

# Execution of the user-guide pages. myst-nb treats a `.md` file as a notebook
# only when its front matter says `file_format: mystnb`, so the design notes and
# the reference are parsed as plain MyST and never execute.
nb_execution_mode = "auto"
# A failed cell defaults to a warning, which `-W` already promotes to an error.
# Raising instead aborts at the failing cell and names it, rather than rendering
# the whole page with a traceback cell and reporting the failure at the end.
nb_execution_raise_on_error = True
# Without this the failure message carries the exception class name and nothing
# else, which is not enough to find the offending cell.
nb_execution_show_tb = True
# The default 30s is tight: the diagnostics page draws several hundred configs
# and the constraint pages evaluate every draw.
nb_execution_timeout = 120

autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "signature"

html_theme = "pydata_sphinx_theme"
html_title = "designspace"
html_static_path = ["_static"]
# Carries the navbar release label's color. It states the color in the theme's
# own tokens, which are the ones the light and dark switch redefines.
html_css_files = ["custom.css"]

# The wordmark carries the project name, so the theme renders the image alone
# and omits the text title beside it. Without `alt_text` the images would carry
# the theme's default, which reads "designspace - Home".
html_theme_options = {
    "logo": {
        "image_light": "_static/navbar-light.svg",
        "image_dark": "_static/navbar-dark.svg",
        "alt_text": "designspace",
    },
    # `version.html` is ours. The theme reports the versions of Sphinx and of
    # itself in the footer and has no component for the project's own, which
    # left the release a page describes as the one version the page omitted.
    # The two names after it are the theme's defaults for this slot, repeated
    # because assigning the key replaces the list rather than adding to it.
    "navbar_end": ["version", "theme-switcher", "navbar-icon-links"],
    # What fills the last of those. Without these the component renders an empty
    # list, which is what left a reader of the site no route to the source or to
    # the package.
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/librelunch/designspace",
            "icon": "fa-brands fa-github",
        },
        {
            "name": "PyPI",
            "url": "https://pypi.org/project/designspace/",
            "icon": "fa-brands fa-python",
        },
    ],
}

# One file for both color schemes. The icon selects between them with a
# `prefers-color-scheme` rule it carries internally, which applies because a
# browser loads a favicon as a document rather than as an image.
html_favicon = "_static/favicon.svg"

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
    # deliberately private, being builder state behind `ParamExpr.lift`,
    # and `_NumericParamExpr` is a shared base of the real and
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

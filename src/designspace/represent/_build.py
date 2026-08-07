"""`space.represent(*rules)` (API.md, "The Representation Layer").

Error rows 31 and 32 govern eligibility. The pipeline runs in order:

1. Dispatch the rules over every param, the first non-`None` result winning
   per param. When the caller gives no rules, the induced chart rule is the
   whole set, never a fallback behind user rules, which would break the
   identity law.
2. Check row 31 and row 32 eligibility.
3. Build each param's `target()`.
4. Transport all four expression stores, in `represent/_transport.py`.
5. Settle defaults, by encoding and validating, or by dropping.
6. Assemble the target `Space`.
7. Settle anchors the same way.
8. Build the whole-config `decode` and `encode` closures, and return a
   `Representation`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from designspace.builder._space import Space
from designspace.errors import ResolutionError
from designspace.ir import ListDomain, ParamDef
from designspace.meta._meta import _build_space_from_ir, space_from_ir
from designspace.paths import element_prefix
from designspace.represent._charts import induced_rule
from designspace.represent._protocol import (
    Encoding,
    EncodingRule,
    can_encode,
    has_prop_expr,
    is_measure_preserving,
)
from designspace.represent._representation import Config, Representation
from designspace.represent._transport import count_read_paths, prop_read_paths, transport_space
from designspace.resolve._relocate import element_paramdef
from designspace.validate._validate import _domain_error_reason

# -- dispatch + row 31/32 eligibility ----------------------------------------


def _dispatch(
    source: Space,
    rules: tuple[EncodingRule, ...],
    count_read: frozenset[str],
    prop_read: frozenset[str],
) -> dict[str, Encoding]:
    """Dispatch the rules over one param; the first non-`None` result wins.

    The induced chart rule, used only when the caller passes no rules,
    silently declines a count-read or prop-excluded param rather than
    matching it, exactly as if it had returned `None` for that path. Its own
    matching criterion already excludes those params, and nobody explicitly
    asked for them, so declining is the right default.

    A user-supplied rule matching such a path is a different case. The user
    did ask, so `_build_targets`' eligibility check raises row 32 rather
    than dropping the match silently.
    """
    using_induced_fallback = not rules
    effective_rules = rules if rules else (induced_rule,)
    matched: dict[str, Encoding] = {}
    for path, pd in source.params.items():
        for rule in effective_rules:
            candidate = rule(pd)
            if candidate is None:
                continue
            if using_induced_fallback and path in count_read:
                break  # decline silently: the rule's own exclusion criterion
            if using_induced_fallback and path in prop_read and not has_prop_expr(candidate):
                break  # likewise; the induced chart encoding has no prop_expr
            matched[path] = candidate
            break
    return matched


def _is_encodable_path(path: str, source: Space) -> bool:
    """Row 32: whether `p` owns its whole subtree.

    No other key of `source.params` may begin `f"{p}."` or `f"{p}[]."`,
    because an encoding owns its whole subtree. A struct, a payload-bearing
    choice discriminator and a struct or choice lift each have descendants
    relocated elsewhere that nothing reconnects. A bare choice has no
    descendants and is encodable.
    """
    dotted, bracketed = f"{path}.", f"{path}[]."
    return not any(
        other != path and (other.startswith(dotted) or other.startswith(bracketed))
        for other in source.params
    )


def _check_eligibility(
    path: str,
    encoding: Encoding,
    source: Space,
    count_read: frozenset[str],
    prop_read: frozenset[str],
) -> None:
    if not _is_encodable_path(path, source):
        raise ResolutionError(
            f"represent(): {path!r} has relocated descendants (a struct, "
            "payload-bearing choice discriminator, or struct/choice lift) "
            "and cannot be encoded (row 32)"
        )
    if path in count_read:
        raise ResolutionError(
            f"represent(): {path!r} is read by a .repeat() count and cannot "
            "be encoded (row 32); transport rewrites conditions, ParamDef."
            "condition, constraints, and element_constraints, but never a "
            "count expression, so encoding it would silently change what "
            "the count means"
        )
    if path in prop_read and not has_prop_expr(encoding):
        raise ResolutionError(
            f"represent(): {path!r} is read by .prop() and its Encoding "
            "supplies no prop_expr() to repair the reference; either "
            "supply one, or the param cannot be encoded (row 32)"
        )


def _build_targets(
    source: Space,
    matched: Mapping[str, Encoding],
    count_read: frozenset[str],
    prop_read: frozenset[str],
) -> dict[str, ParamDef]:
    targets: dict[str, ParamDef] = {}
    for path, pd in source.params.items():
        encoding = matched.get(path)
        if encoding is None:
            targets[path] = pd
            continue
        _check_eligibility(path, encoding, source, count_read, prop_read)
        target_pd = encoding.target(pd)
        if target_pd.path != path:
            raise ResolutionError(
                f"represent(): Encoding.target() for {path!r} returned a "
                f"different path {target_pd.path!r} (row 31)"
            )
        targets[path] = target_pd
    return targets


# -- defaults: encode-and-validate, or drop ----------------------------------


def _bottom_probe_paramdef(target_pd: ParamDef) -> ParamDef:
    """A `ParamDef` shaped like `target_pd`'s own scalar domain.

    That is `target_pd` itself for a plain scalar, or `element_paramdef` at
    the bottom `ListDomain` level for a lift. It is used only to probe a
    candidate default or anchor value for domain membership through
    `_domain_error_reason`, and is never stored.
    """
    if target_pd.type_kind != "list":
        return target_pd
    domain = target_pd.domain
    assert isinstance(domain, ListDomain)
    while domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        domain = domain.element_domain
    return element_paramdef(f"{target_pd.path}[]", domain)


def _encoded_value_is_domain_valid(value: Any, domain: Any, probe_pd: ParamDef) -> bool:
    """Recurse through a `ListDomain` chain down to `probe_pd`'s scalar shape.

    A list default is a list of element values rather than a count.
    """
    if isinstance(domain, ListDomain):
        if not isinstance(value, list):
            return False
        return all(
            _encoded_value_is_domain_valid(v, domain.element_domain, probe_pd) for v in value
        )
    return _domain_error_reason(probe_pd, value) is None


def _try_encode(encoding: Encoding, source_pd: ParamDef, value: Any) -> tuple[bool, Any]:
    """`(ok, encoded)` for one candidate value.

    `ok` is `False` when the encoding cannot encode at all, or when its own
    `encode()` raises. Callers still owe the domain-membership check
    afterward, an encoding never being trusted blindly: API.md says
    "`represent()` ... validates the result itself rather than trusting the
    assembler".
    """
    if not can_encode(encoding):
        return False, None
    try:
        return True, getattr(encoding, "encode")(source_pd, value)  # noqa: B009
    except Exception:
        return False, None


def _settle_defaults(
    source: Space, target_params: dict[str, ParamDef], matched: Mapping[str, Encoding]
) -> list[str]:
    dropped: list[str] = []
    for path, encoding in matched.items():
        source_pd = source.params[path]
        target_pd = target_params[path]
        if source_pd.type_kind == "list":
            assert isinstance(source_pd.domain, ListDomain)
            assert isinstance(target_pd.domain, ListDomain)
            new_domain, was_dropped = _settle_list_defaults(source_pd, target_pd.domain, encoding)
            target_params[path] = replace(target_pd, domain=new_domain)
            if was_dropped:
                dropped.append(path)
            continue
        if source_pd.default is None:
            continue
        ok, encoded = _try_encode(encoding, source_pd, source_pd.default)
        if ok and _encoded_value_is_domain_valid(encoded, target_pd.domain, target_pd):
            target_params[path] = replace(target_pd, default=encoded)
        else:
            dropped.append(path)
    return dropped


def _settle_list_defaults(
    source_pd: ParamDef, target_domain: ListDomain, encoding: Encoding
) -> tuple[ListDomain, bool]:
    dropped = False
    probe = _bottom_probe_paramdef(replace(source_pd, domain=target_domain))
    new_list_default = None
    if target_domain.list_default is not None:
        ok, encoded = _try_encode(encoding, source_pd, target_domain.list_default)
        if ok and _encoded_value_is_domain_valid(encoded, target_domain, probe):
            new_list_default = encoded
        else:
            dropped = True
    new_element_default = None
    if target_domain.element_default is not None:
        ok, encoded = _try_encode(encoding, source_pd, target_domain.element_default)
        if ok and _encoded_value_is_domain_valid(encoded, target_domain.element_domain, probe):
            new_element_default = encoded
        else:
            dropped = True
    return (
        replace(target_domain, list_default=new_list_default, element_default=new_element_default),
        dropped,
    )


# -- anchors: encode-and-validate against the assembled target, or drop whole


def _transcode_level(
    nested: dict[str, Any],
    space: Space,
    matched: Mapping[str, Encoding],
    direction: str,
    template_prefix: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for template_path in space._direct_children(template_prefix):
        pd = space.params[template_path]
        local_name = template_path[len(template_prefix) :]
        if local_name not in nested:
            continue
        value = nested[local_name]
        encoding = matched.get(template_path)
        if encoding is not None:
            # `encode` is an optional capability, never part of
            # `Encoding`'s static Protocol shape, so it is reached through
            # `getattr` rather than the direct attribute access
            # mypy --strict would reject. `build_encode`, the only caller of
            # this direction, already gates on every matched encoding
            # supplying it.
            fn = encoding.decode if direction == "decode" else getattr(encoding, "encode")  # noqa: B009
            out[local_name] = fn(pd, value)
            continue
        if pd.type_kind == "space":
            out[local_name] = (
                _transcode_level(value, space, matched, direction, f"{template_path}.")
                if isinstance(value, dict)
                else value
            )
        elif pd.type_kind == "choice":
            out[local_name] = _transcode_choice_value(
                value, space, matched, direction, template_path
            )
        elif pd.type_kind == "list":
            assert isinstance(pd.domain, ListDomain)
            out[local_name] = _transcode_list_value(
                value, pd.domain, space, matched, direction, template_path
            )
        else:
            out[local_name] = value
    return out


def _transcode_choice_value(
    value: Any, space: Space, matched: Mapping[str, Encoding], direction: str, template_path: str
) -> Any:
    if isinstance(value, str):
        return value  # bare variant, no payload
    if not (isinstance(value, dict) and len(value) == 1):
        return value  # malformed; validate() catches this, not the transcoder
    ((variant_name, payload),) = value.items()
    if not isinstance(payload, dict):
        return value
    new_payload = _transcode_level(
        payload, space, matched, direction, f"{template_path}.{variant_name}."
    )
    return {variant_name: new_payload}


def _transcode_list_value(
    value: Any,
    domain: ListDomain,
    space: Space,
    matched: Mapping[str, Encoding],
    direction: str,
    template_path: str,
) -> Any:
    if not isinstance(value, list):
        return value
    elem_prefix = element_prefix(template_path)
    return [
        _transcode_list_element(item, domain, space, matched, direction, elem_prefix)
        for item in value
    ]


def _transcode_list_element(
    item: Any,
    domain: ListDomain,
    space: Space,
    matched: Mapping[str, Encoding],
    direction: str,
    template_prefix: str,
) -> Any:
    if domain.element_kind == "space":
        return (
            _transcode_level(item, space, matched, direction, template_prefix)
            if isinstance(item, dict)
            else item
        )
    if domain.element_kind == "choice":
        return _transcode_choice_value(item, space, matched, direction, template_prefix[:-1])
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _transcode_list_value(
            item, domain.element_domain, space, matched, direction, template_prefix[:-1]
        )
    # A direct scalar, subset, permutation, bool, categorical or custom
    # element. It is reached only when the enclosing list param is itself
    # unmatched; _transcode_level above handles a matched direct lift
    # wholesale, its governing key being the enclosing list's path. There is
    # nothing further to recurse into.
    return item


def build_decode(source: Space, matched: Mapping[str, Encoding]) -> Callable[[Config], Config]:
    def decode(genotype: Config) -> Config:
        return _transcode_level(genotype, source, matched, "decode", "")

    return decode


def build_encode(
    source: Space, matched: Mapping[str, Encoding]
) -> Callable[[Config], Config] | None:
    if not all(can_encode(e) for e in matched.values()):
        return None

    def encode(phenotype: Config) -> Config:
        return _transcode_level(phenotype, source, matched, "encode", "")

    return encode


def _settle_anchors(
    source: Space, matched: Mapping[str, Encoding], target_probe: Space
) -> tuple[dict[str, Config], list[str]]:
    """Whether this anchor survives; an anchor drops whole, never field-wise.

    A config missing an active param is not a valid anchor (API.md,
    "Obligations").
    """
    surviving: dict[str, Config] = {}
    dropped: list[str] = []
    for name, config in source.anchors.items():
        try:
            encoded = _transcode_level(dict(config), source, matched, "encode", "")
        except Exception:
            dropped.append(name)
            continue
        if target_probe.validate(encoded).valid:
            surviving[name] = encoded
        else:
            dropped.append(name)
    return surviving, dropped


# -- entry point --------------------------------------------------------------


def represent(source: Space, *rules: EncodingRule) -> Representation:
    count_read = count_read_paths(source)
    prop_read = prop_read_paths(source)
    matched = _dispatch(source, rules, count_read, prop_read)
    target_params = _build_targets(source, matched, count_read, prop_read)

    transported = transport_space(source, matched, target_params)
    target_params = transported.target_params

    dropped_defaults = _settle_defaults(source, target_params, matched)

    # A probe build, without anchors, so that surviving anchors can be
    # validated against the real target structure before the final,
    # anchor-bearing build below. `space_from_ir`'s own anchor pass would
    # otherwise raise row 22 on exactly the anchors this function means to
    # drop softly.
    target_probe = _build_space_from_ir(
        target_params, transported.target_conditions, transported.target_constraints
    )
    surviving_anchors, dropped_anchors = _settle_anchors(source, matched, target_probe)

    target = space_from_ir(
        target_params,
        transported.target_conditions,
        transported.target_constraints,
        anchors=surviving_anchors,
        meta=dict(source.meta_map),
    )

    decode = build_decode(source, matched)
    encode = build_encode(source, matched)
    encoded = tuple(sorted(matched.keys()))
    excluded_by_prop = tuple(sorted((count_read | prop_read) - matched.keys()))

    return Representation(
        source=source,
        target=target,
        decode=decode,
        encoded=encoded,
        excluded_by_prop=excluded_by_prop,
        opaque_conditions=transported.opaque_conditions,
        opaque_constraints=transported.opaque_constraints,
        dropped_defaults=tuple(sorted(dropped_defaults)),
        dropped_anchors=tuple(sorted(dropped_anchors)),
        encode=encode,
        measure_preserving=all(is_measure_preserving(e) for e in matched.values()),
    )

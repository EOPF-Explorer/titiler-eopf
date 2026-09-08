"""LoadCollection.load_collection's spatial_extent/temporal_extent must stay
`Optional[X]`, not `X | None`.

titiler.openeo's process-graph parameter resolution
(`titiler.openeo.processes.implementations.core._is_optional_type`) detects
an optional parameter via `typing.get_origin(t) is typing.Union`. PEP 604's
`X | None` syntax produces a `types.UnionType` object instead, which is not
`typing.Union`, so the check silently fails and the BoundingBox/
TemporalInterval coercion (`_resolve_special_parameter`) is skipped. A raw
dict/list from a UDP parameter's default then reaches `load_collection`
unconverted, and fails later -- e.g. `temporal_extent.start` in
`LoadCollection._get_items` raises `AttributeError: 'list' object has no
attribute 'start'`.

Everything else in this repo uses `X | None`; these two parameters are the
deliberate exception, so this regression test exists to make that exception
loud rather than silent.
"""

import inspect

from openeo_pg_parser_networkx.pg_schema import (
    BoundingBox,
    ParameterReference,
    TemporalInterval,
)

from titiler.eopf.openeo.stacapi import LoadCollection
from titiler.openeo.processes.implementations import core


def test_spatial_and_temporal_extent_are_coerced_from_udp_defaults():
    """Simulates a UDP parameter reference resolving to its raw JSON default
    (exactly what the openEO Python client sends for a `Parameter` with a
    plain dict/list `default`), and asserts both come out correctly typed.
    """
    sig = inspect.signature(LoadCollection.load_collection)
    param_types = {name: p.annotation for name, p in sig.parameters.items()}

    kwargs = {
        "id": "sentinel-2-l2a",
        "spatial_extent": ParameterReference(from_parameter="bounding_box"),
        "temporal_extent": ParameterReference(from_parameter="time"),
    }
    named_parameters = {
        "bounding_box": {"west": -5.0, "south": 40.0, "east": 5.0, "north": 50.0},
        "time": ["2026-01-10", "2026-01-20"],
    }

    resolved = core._resolve_kwargs(
        kwargs, named_parameters, param_types, "load_collection"
    )

    assert isinstance(resolved["spatial_extent"], BoundingBox)
    assert resolved["spatial_extent"].west == -5.0

    assert isinstance(resolved["temporal_extent"], TemporalInterval)

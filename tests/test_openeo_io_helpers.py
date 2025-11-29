"""Unit tests for openEO I/O helper utilities."""

import pytest
from rio_tiler.types import AssetInfo

from titiler.eopf.openeo.processes.implementations.io import (
    _preferred_asset_href,
    _split_asset_identifier,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("B01", ("B01", None, None)),
        ("B01|group:band", ("B01", "group:band", None)),
        ("B01|bidx=1,2,3", ("B01", None, (1, 2, 3))),
        ("B02|bidx=5", ("B02", None, (5,))),
    ],
)
def test_split_asset_identifier(
    raw: str, expected: tuple[str, str | None, tuple[int, ...] | None]
) -> None:
    """Return (asset, suffix, indexes) tuple for raw identifiers."""
    assert _split_asset_identifier(raw) == expected


@pytest.mark.parametrize(
    "asset_info, expected",
    [
        (
            {
                "url": "https://example.com/data.tif",
                "metadata": {
                    "alternate": {
                        "http": {"href": "https://example.com/data.tif"},
                        "s3": {"href": "s3://bucket/data.tif"},
                    }
                },
            },
            "s3://bucket/data.tif",
        ),
        (
            {
                "url": "https://example.com/data.tif",
                "metadata": {
                    "alternate": {
                        "mirror": {"href": "https://mirror/data.tif"},
                    }
                },
            },
            "https://mirror/data.tif",
        ),
        ({"url": "https://example.com/data.tif"}, "https://example.com/data.tif"),
    ],
)
def test_preferred_asset_href(asset_info: AssetInfo, expected: str) -> None:
    """Prefer alternate hrefs (s3/http) over reader default URLs."""
    assert _preferred_asset_href(asset_info) == expected

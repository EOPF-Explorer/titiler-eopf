"""`get_all_band_names` band-vocabulary deduplication.

EOPF's Sentinel-2 catalogue publishes the same physical band several ways at
once: as its own single-band asset (e.g. ``B02_10m``, one band named
``B02``), and again inside multi-band composites covering the same or other
resolutions (``SR_10m``, ``SR_20m``, ``SR_60m``, and the true-colour
``TCI_10m``, none of which carry a rendering role in this catalogue's
metadata). Left unfiltered that produces up to four names for one band.
`get_all_band_names` prefers the single-band asset when one exists, and only
falls back to advertising every composite copy when no single-band
alternative is published at all (Sentinel-3 OLCI's ``radianceData`` is the
real collection shaped that way).
"""

import pystac

from titiler.eopf.openeo.stacapi import get_all_band_names


def _asset(roles: list[str], bands: list[dict] | None = None) -> dict:
    asset: dict = {"type": "application/vnd+zarr", "roles": roles}
    if bands is not None:
        asset["bands"] = bands
    return asset


def _collection(item_assets: dict) -> pystac.Collection:
    return pystac.Collection.from_dict(
        {
            "type": "Collection",
            "id": "test-collection",
            "stac_version": "1.0.0",
            "description": "test",
            "license": "proprietary",
            "extent": {
                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                "temporal": {"interval": [[None, None]]},
            },
            "links": [],
            "item_assets": item_assets,
        }
    )


def test_single_band_asset_wins_over_composite_duplicate():
    """A band available from its own single-band asset drops the composite's copy."""
    collection = _collection(
        {
            "B02_10m": _asset(["data", "reflectance"], [{"name": "B02"}]),
            "SR_10m": _asset(
                ["data", "reflectance", "dataset"],
                [{"name": "B02"}, {"name": "B03"}],
            ),
            "B03_10m": _asset(["data", "reflectance"], [{"name": "B03"}]),
        }
    )

    names = get_all_band_names(collection)

    assert names == ["B02_10m|bands=B02", "B03_10m|bands=B03"]


def test_composite_only_band_is_kept():
    """A band with no single-band alternative is never dropped."""
    collection = _collection(
        {
            "radianceData": _asset(
                ["data", "dataset"],
                [{"name": "Oa01"}, {"name": "Oa02"}],
            ),
        }
    )

    names = get_all_band_names(collection)

    assert names == ["radianceData|bands=Oa01", "radianceData|bands=Oa02"]


def test_mixed_collection_dedupes_only_what_has_an_alternative():
    """One collection can mix both cases; each is resolved independently."""
    collection = _collection(
        {
            "B02_10m": _asset(["data", "reflectance"], [{"name": "B02"}]),
            "SR_10m": _asset(
                ["data", "reflectance", "dataset"],
                [{"name": "B02"}, {"name": "B09"}],
            ),
            "AOT_10m": _asset(["data"]),
        }
    )

    names = get_all_band_names(collection)

    # B02: single-band alternative exists -> composite copy dropped.
    # B09: no single-band alternative -> composite copy kept.
    # AOT_10m: no bands array -> bare asset name, unaffected.
    assert names == ["AOT_10m", "B02_10m|bands=B02", "SR_10m|bands=B09"]


def test_asset_flagged_metadata_is_not_advertised_as_a_band():
    """An asset that is both 'data' and 'metadata' (the whole product store,
    e.g. EOPF's `product`) has no bands to select and must not be advertised."""
    collection = _collection(
        {
            "B02_10m": _asset(["data", "reflectance"], [{"name": "B02"}]),
            "product": _asset(["data", "metadata"]),
            "product_metadata": _asset(["metadata"]),
        }
    )

    names = get_all_band_names(collection)

    assert names == ["B02_10m|bands=B02"]

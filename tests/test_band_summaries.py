"""`replace_bands_in_summaries_dict` restores rich metadata per band.

`get_all_band_names` produces qualified band names in the current
`<asset>|bands=<band>` form (e.g. `B01_20m|bands=B01`) -- the notation moved
from the pre-0.8.0 `<asset>|<band>` shape, but `replace_bands_in_summaries_dict`
kept hand-splitting on `"|"` and taking everything after it as the band name
literally (`"bands=B01"`), which never matches an entry in the catalogue's
original `summaries.bands` (named plain `"B01"`). Every qualified band
therefore lost its description/`eo:common_name`/wavelength, silently
degrading to a bare `{"name": "B01_20m|bands=B01"}` -- this is exactly the
metadata openEO Studio's band picker (developmentseed/openeo-studio#103)
reads from `summaries.bands` as its first-choice source.

The asset-only branch (bands with no asset qualifier, e.g. `AOT_10m`) had a
second, independent bug: it read descriptions from the collection's
top-level `assets` dict, which only ever holds collection-level assets like
a thumbnail -- never a per-band one -- so it always fell through to the
generic "Data from X asset" filler. Per-band descriptions live in
`item_assets`, under `title` (occasionally `description`).
"""

from titiler.eopf.openeo.stacapi import stacApiBackend


def _backend() -> stacApiBackend:
    return stacApiBackend(url="https://stac.example.test")


def test_qualified_band_gets_its_rich_metadata_back():
    """`B01_20m|bands=B01` must resolve against the original `B01` entry."""
    collection = {
        "summaries": {
            "bands": [
                {
                    "name": "B01",
                    "description": "Coastal aerosol (band 1)",
                    "eo:common_name": "coastal",
                    "eo:center_wavelength": 0.443,
                },
            ]
        },
        "cube:dimensions": {
            "bands": {"type": "bands", "values": ["B01_20m|bands=B01"]}
        },
        "item_assets": {},
        "assets": {},
    }

    _backend().replace_bands_in_summaries_dict(collection)

    assert collection["summaries"]["bands"] == [
        {
            "name": "B01_20m|bands=B01",
            "description": "Coastal aerosol (band 1)",
            "eo:common_name": "coastal",
            "eo:center_wavelength": 0.443,
        }
    ]


def test_asset_only_band_reads_title_from_item_assets_not_assets():
    """A bare asset name (no `|bands=`) must not read the collection-level
    `assets` dict (thumbnails etc.) -- its description lives in
    `item_assets[<name>]["title"]`."""
    collection = {
        "summaries": {"bands": []},
        "cube:dimensions": {"bands": {"type": "bands", "values": ["AOT_10m"]}},
        "item_assets": {
            "AOT_10m": {"title": "Aerosol optical thickness (AOT)"},
        },
        # A collection-level asset that happens to share no name with any
        # band -- proves the fix isn't reading from here.
        "assets": {"thumbnail": {"description": "wrong source"}},
    }

    _backend().replace_bands_in_summaries_dict(collection)

    assert collection["summaries"]["bands"] == [
        {"name": "AOT_10m", "description": "Aerosol optical thickness (AOT)"}
    ]


def test_asset_only_band_falls_back_when_no_title_available():
    """No item_assets entry at all -- falls back to the generic filler,
    rather than raising."""
    collection = {
        "summaries": {"bands": []},
        "cube:dimensions": {"bands": {"type": "bands", "values": ["WVP_10m"]}},
        "item_assets": {},
        "assets": {},
    }

    _backend().replace_bands_in_summaries_dict(collection)

    assert collection["summaries"]["bands"] == [
        {"name": "WVP_10m", "description": "Data from WVP_10m asset"}
    ]


def test_qualified_band_not_in_original_summaries_falls_back_to_bare_name():
    """A qualified band with no matching entry in the original
    `summaries.bands` gets a bare `{"name": ...}` rather than raising --
    matches the asset-only fallback shape, just without a description."""
    collection = {
        "summaries": {"bands": []},
        "cube:dimensions": {
            "bands": {"type": "bands", "values": ["B99_10m|bands=B99"]}
        },
        "item_assets": {},
        "assets": {},
    }

    _backend().replace_bands_in_summaries_dict(collection)

    assert collection["summaries"]["bands"] == [{"name": "B99_10m|bands=B99"}]

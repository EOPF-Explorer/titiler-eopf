"""titiler-eopf openeo test processes"""

import datetime
import os

from openeo_pg_parser_networkx.pg_schema import BoundingBox
from rio_tiler.errors import TileOutsideBounds
from rio_tiler.models import ImageData

from titiler.eopf.openeo.processes import PROCESS_IMPLEMENTATIONS, process_registry
from titiler.eopf.openeo.processes.implementations import load_zarr
from titiler.eopf.openeo.reader import STACReader
from titiler.eopf.openeo.stacapi import LoadCollection

FIXTURES_DIRECTORY = os.path.join(os.path.dirname(__file__), "fixtures")

collection_json = os.path.join(FIXTURES_DIRECTORY, "collection.json")


def test_custom_processes():
    """make sure custom processes are registered"""
    assert len(PROCESS_IMPLEMENTATIONS) == 1
    assert PROCESS_IMPLEMENTATIONS[0].__name__ == "load_zarr"


def test_registery():
    """Check load_zarr is in the registery"""
    _, names = zip(*process_registry)
    assert "load_zarr" in names
    assert process_registry.get("load_zarr")


def test_load_zarr(geozarr_dataset):
    """Test Load Zarr function."""
    zarr = load_zarr(geozarr_dataset)

    # Check that we have at least one key (time slice)
    assert len(zarr) > 0

    # Check that we can access keys
    keys = list(zarr.keys())
    assert len(keys) == 1  # we only have one time slice

    # Check that without variable filtering, we get all available bands
    img_stack = list(zarr.values())
    assert len(img_stack) == 1
    assert isinstance(img_stack[0], ImageData)
    # Should contain all bands from the default level: b02, b03, b04, b05, b06, b07, b08, b11, b12, b8a
    expected_bands = [
        "/measurements/reflectance:b02",
        "/measurements/reflectance:b03",
        "/measurements/reflectance:b04",
        "/measurements/reflectance:b05",
        "/measurements/reflectance:b06",
        "/measurements/reflectance:b07",
        "/measurements/reflectance:b08",
        "/measurements/reflectance:b11",
        "/measurements/reflectance:b12",
        "/measurements/reflectance:b8a",
    ]
    assert sorted(img_stack[0].band_descriptions) == sorted(
        expected_bands
    ), f"Expected {expected_bands} but got {img_stack[0].band_names}"

    # Test with specific variables
    zarr = load_zarr(
        geozarr_dataset,
        options={
            "variables": ["/measurements/reflectance:b02"],
        },
    )

    # Check we can get values (ImageData objects)
    img_stack = list(zarr.values())
    assert len(img_stack) == 1
    assert isinstance(img_stack[0], ImageData)
    assert img_stack[0].band_descriptions == ["/measurements/reflectance:b02"]


def test_load_collection(geozarr_stac):
    """Test load collection process."""

    class FakeBackend:
        url: str

        def __init__(self, url: str):
            self.url = url

        def get_items(self, *args, **kwargs):
            return [geozarr_stac]

    loaders = LoadCollection(FakeBackend("https://fake.api.io/stac"))

    bbox = BoundingBox(
        west=14.941406249999993,
        south=37.857507156252034,
        east=15.11718749999999,
        north=37.99616267972812,
    )

    collection = loaders.load_collection(
        "sentinel-2-l2a",
        spatial_extent=bbox,
        width=512,
        height=512,
        bands=[
            "reflectance|bands=b04",
            "reflectance|bands=b03",
            "reflectance|bands=b02",
        ],
    )
    assert collection.band_names == [
        "reflectance|bands=b04",
        "reflectance|bands=b03",
        "reflectance|bands=b02",
    ]
    assert collection.width == 512
    assert collection.height == 512

    # Check we can get values (ImageData objects)
    img_stack = list(collection.values())
    assert len(img_stack) == 1
    assert isinstance(img_stack[0], ImageData)
    # titiler-openeo>=0.20 (#460) labels each image with the stack's
    # band names, so the band dimension keeps the requested labels.
    assert img_stack[0].band_descriptions == collection.band_names


class _FakeBackend:
    """STAC backend stand-in that returns fixed items."""

    url = "https://fake.api.io/stac"

    def __init__(self, items):
        self.items = items

    def get_items(self, *args, **kwargs):
        return self.items


_BBOX = BoundingBox(
    west=14.941406249999993,
    south=37.857507156252034,
    east=15.11718749999999,
    north=37.99616267972812,
)


def _valid_pixels(collection) -> int:
    img = list(collection.values())[0]
    return int((~img.array.mask).sum())


def test_load_collection_geojson_extent(geozarr_stac):
    """A GeoJSON polygon extent masks the pixels outside the polygon."""
    loaders = LoadCollection(_FakeBackend([geozarr_stac]))
    kwargs = {"width": 64, "height": 64, "bands": ["reflectance|bands=b04"]}

    # Triangle over the item (14.99..15.12, 37.85..37.95), and its bounding box:
    # the same output grid, the triangle masks about half of it.
    west, south, east, north = 15.0, 37.86, 15.11, 37.94
    triangle = {
        "type": "Polygon",
        "coordinates": [[[west, south], [east, south], [east, north], [west, south]]],
    }
    box = BoundingBox(west=west, south=south, east=east, north=north)

    full = loaders.load_collection("sentinel-2-l2a", spatial_extent=box, **kwargs)
    half = loaders.load_collection("sentinel-2-l2a", spatial_extent=triangle, **kwargs)

    assert 0 < _valid_pixels(half) < 0.75 * _valid_pixels(full)


def test_load_collection_skips_empty_date(geozarr_stac, monkeypatch):
    """A date with no pixels in the bbox is skipped; the other date keeps its label."""
    empty = geozarr_stac.clone()
    empty.id = "empty"
    empty.datetime = datetime.datetime(2026, 3, 17, tzinfo=datetime.timezone.utc)

    part = STACReader.part

    def part_or_outside(self, *args, **kwargs):
        if self.input.id == "empty":
            raise TileOutsideBounds("no data in bbox")
        return part(self, *args, **kwargs)

    monkeypatch.setattr(STACReader, "part", part_or_outside)

    loaders = LoadCollection(_FakeBackend([geozarr_stac, empty]))
    collection = loaders.load_collection(
        "sentinel-2-l2a",
        spatial_extent=_BBOX,
        width=64,
        height=64,
        bands=["reflectance|bands=b04"],
    )

    images = dict(collection.items())
    assert list(images) == [geozarr_stac.datetime.replace(tzinfo=None)]


def test_load_collection_null_datetime(geozarr_stac):
    """An item with only `start_datetime`/`end_datetime` is read."""
    item = geozarr_stac.clone()
    item.datetime = None
    item.properties["datetime"] = None

    loaders = LoadCollection(_FakeBackend([item]))
    collection = loaders.load_collection(
        "sentinel-2-l2a",
        spatial_extent=_BBOX,
        width=64,
        height=64,
        bands=["reflectance|bands=b04"],
    )

    images = list(collection.values())
    assert len(images) == 1
    assert _valid_pixels(collection) > 0

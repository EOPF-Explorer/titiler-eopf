"""titiler-eopf openeo test processes"""

import json
import os

import pystac
from openeo_pg_parser_networkx.pg_schema import BoundingBox
from rio_tiler.models import ImageData

from titiler.eopf.openeo.processes import PROCESS_IMPLEMENTATIONS, process_registry
from titiler.eopf.openeo.processes.implementations import load_zarr
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
            return [pystac.Item.from_dict(json.loads(geozarr_stac))]

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
    assert img_stack[0].band_descriptions == [
        "reflectance_b04",
        "reflectance_b03",
        "reflectance_b02",
    ]

"""titiler-eopf openeo test processes"""

import os

from rio_tiler.models import ImageData

from titiler.eopf.openeo.processes import PROCESS_IMPLEMENTATIONS, process_registry
from titiler.eopf.openeo.processes.implementations import load_zarr

DATA_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
OPTIMIZED_PYRAMID = os.path.join(
    DATA_DIR,
    "eopf_geozarr",
    "optimized_pyramid.zarr",
)


def test_custom_processes():
    """make sure custom processes are registered"""
    assert len(PROCESS_IMPLEMENTATIONS) == 1
    assert PROCESS_IMPLEMENTATIONS[0].__name__ == "load_zarr"


def test_registery():
    """Check load_zarr is in the registery"""
    _, last_registered = list(process_registry)[-1]
    assert last_registered == "load_zarr"
    assert process_registry.get("load_zarr")


def test_load_zarr():
    """Test Load Zarr function."""
    zarr = load_zarr(OPTIMIZED_PYRAMID)

    # Check that we have at least one key (time slice)
    assert len(zarr) > 0

    # Check that we can access keys
    keys = list(zarr.keys())
    assert len(keys) == 1  # we only have one time slice

    # Test with specific variables
    zarr = load_zarr(
        OPTIMIZED_PYRAMID,
        options={
            "variables": ["/measurements/reflectance:b02"],
        },
    )

    # Check we can get values (ImageData objects)
    img_stack = list(zarr.values())
    assert len(img_stack) == 1
    assert isinstance(img_stack[0], ImageData)

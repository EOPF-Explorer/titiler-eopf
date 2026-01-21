#!/usr/bin/env python3
"""
Script to create a optimized pyramid test fixture that mimics the new S2 optimization structure.
"""

import os

import numpy as np
import rioxarray  # noqa: F401
import xarray as xr
import zarr
from pyproj import CRS
from zarr.codecs import BloscCodec


def create_optimized_pyramid_fixture():  # noqa: C901
    """Create a optimized pyramid fixture with different variables at different scales."""

    fixture_path = "tests/fixtures/eopf_geozarr/optimized_pyramid.zarr"

    # Remove existing fixture if it exists
    if os.path.exists(fixture_path):
        import shutil

        shutil.rmtree(fixture_path)

    # Create zarr store
    store = zarr.open(fixture_path, mode="w")

    # Define CRS and transform (similar to existing fixture)
    crs = CRS.from_epsg(32633)  # WGS 84 / UTM zone 33N

    # Create compressor for encoding
    compressor = BloscCodec(cname="zstd", clevel=3, shuffle="shuffle", blocksize=0)

    def create_encoding(ds, spatial_chunk=64):
        """Create encoding for dataset variables."""
        encoding = {}
        for var in ds.data_vars:
            data_shape = ds[var].shape
            if len(data_shape) >= 2:
                chunk_y = min(spatial_chunk, data_shape[-2])
                chunk_x = min(spatial_chunk, data_shape[-1])
                chunks = (chunk_y, chunk_x)
            else:
                chunks = (min(spatial_chunk, data_shape[-1]),)

            encoding[var] = {"compressors": [compressor], "chunks": chunks}

        # Add coordinate encoding
        for coord in ds.coords:
            encoding[coord] = {"compressors": None}

        return encoding

    # Base spatial parameters
    base_x_10m = np.arange(500000, 510000, 10).tolist()  # 10m pixel size
    base_y_10m = np.arange(4200000, 4190000, -10).tolist()

    base_x_20m = np.arange(500000, 510000, 20).tolist()  # 20m pixel size
    base_y_20m = np.arange(4200000, 4190000, -20).tolist()

    base_x_60m = np.arange(500000, 510000, 60).tolist()  # 60m pixel size
    base_y_60m = np.arange(4200000, 4190000, -60).tolist()

    base_x_120m = np.arange(500000, 510000, 120).tolist()  # 120m pixel size
    base_y_120m = np.arange(4200000, 4190000, -120).tolist()

    # Create root group with multiscales metadata
    root_attrs = {
        "zarr_conventions": [
            {
                "uuid": "d35379db-88df-4056-af3a-620245f8e347",
                "schema_url": "https://raw.githubusercontent.com/zarr-conventions/multiscales/refs/tags/v1/schema.json",
                "spec_url": "https://github.com/zarr-conventions/multiscales/blob/v1/README.md",
                "name": "multiscales",
                "description": "Multiscale layout of zarr datasets",
            },
            {
                "uuid": "689b58e2-cf7b-45e0-9fff-9cfc0883d6b4",
                "schema_url": "https://raw.githubusercontent.com/zarr-conventions/spatial/refs/tags/v1/schema.json",
                "spec_url": "https://github.com/zarr-conventions/spatial/blob/v1/README.md",
                "name": "spatial:",
                "description": "Spatial coordinate and transformation information",
            },
            {
                "uuid": "f17cb550-5864-4468-aeb7-f3180cfb622f",
                "schema_url": "https://raw.githubusercontent.com/zarr-experimental/geo-proj/refs/tags/v1/schema.json",
                "spec_url": "https://github.com/zarr-experimental/geo-proj/blob/v1/README.md",
                "name": "proj:",
                "description": "Coordinate reference system information for geospatial data",
            },
        ],
        "multiscales": {
            "layout": [
                {
                    "asset": "r10m",
                    "spatial:shape": [1000, 1000],
                    "spatial:transform": [10.0, 0.0, 500000, 0.0, -10.0, 4200000],
                },
                {
                    "asset": "r20m",
                    "derived_from": "r10m",
                    "transform": {"scale": [2.0, 2.0], "translation": [0.0, 0.0]},
                    "spatial:shape": [500, 500],
                    "spatial:transform": [20.0, 0.0, 500000, 0.0, -20.0, 4200000],
                },
                {
                    "asset": "r60m",
                    "derived_from": "r20m",
                    "transform": {"scale": [3.0, 3.0], "translation": [0.0, 0.0]},
                    "spatial:shape": [167, 167],
                    "spatial:transform": [60.0, 0.0, 500000, 0.0, -60.0, 4200000],
                },
                {
                    "asset": "r120m",
                    "derived_from": "r60m",
                    "transform": {"scale": [2.0, 2.0], "translation": [0.0, 0.0]},
                    "spatial:shape": [84, 84],
                    "spatial:transform": [100.0, 0.0, 500000, 0.0, -100.0, 4200000],
                },
            ],
            "resampling_method": "average",
        },
        "spatial:dimensions": ["y", "x"],
        "spatial:bbox": [500000, 4190000, 510000, 4200000],
        "spatial:registration": "pixel",
        "proj:code": "EPSG:32633",
    }

    # Create measurements/reflectance group
    reflectance_group = store.create_group("measurements/reflectance")
    reflectance_group.attrs.update(root_attrs)

    def create_data_array(name, x_coords, y_coords, scale_factor=0.0001, offset=-0.1):
        """Create a synthetic data array."""
        height, width = len(y_coords), len(x_coords)
        # Create synthetic but realistic reflectance data
        data = np.random.uniform(1000, 8000, (height, width)).astype(np.uint16)

        da = xr.DataArray(
            data,
            coords={"y": y_coords, "x": x_coords},
            dims=["y", "x"],
            name=name,
            attrs={
                "zarr_conventions": [
                    {
                        "uuid": "d35379db-88df-4056-af3a-620245f8e347",
                        "schema_url": "https://raw.githubusercontent.com/zarr-conventions/multiscales/refs/tags/v1/schema.json",
                        "spec_url": "https://github.com/zarr-conventions/multiscales/blob/v1/README.md",
                        "name": "multiscales",
                        "description": "Multiscale layout of zarr datasets",
                    },
                    {
                        "uuid": "689b58e2-cf7b-45e0-9fff-9cfc0883d6b4",
                        "schema_url": "https://raw.githubusercontent.com/zarr-conventions/spatial/refs/tags/v1/schema.json",
                        "spec_url": "https://github.com/zarr-conventions/spatial/blob/v1/README.md",
                        "name": "spatial:",
                        "description": "Spatial coordinate and transformation information",
                    },
                    {
                        "uuid": "f17cb550-5864-4468-aeb7-f3180cfb622f",
                        "schema_url": "https://raw.githubusercontent.com/zarr-experimental/geo-proj/refs/tags/v1/schema.json",
                        "spec_url": "https://github.com/zarr-experimental/geo-proj/blob/v1/README.md",
                        "name": "proj:",
                        "description": "Coordinate reference system information for geospatial data",
                    },
                ],
                "long_name": f"BOA reflectance from MSI acquisition at spectral band {name}",
                "units": "digital_counts",
                "scale_factor": scale_factor,
                "add_offset": offset,
                "valid_min": 1,
                "valid_max": 65535,
                "fill_value": 0,
                "proj:code": f"EPSG:{crs.to_epsg()}",
                "spatial:dimensions": ["y", "x"],
                "spatial:transform": [
                    x_coords[1] - x_coords[0],
                    0.0,
                    x_coords[0],
                    0.0,
                    y_coords[0] - y_coords[1],
                    y_coords[0],
                ],
                "spatial:shape": [height, width],
                "spatial:bbox": [x_coords[0], y_coords[-1], x_coords[-1], y_coords[0]],
                "spatial:registration": "pixel",
            },
        )

        # Set CRS and spatial dimensions
        da = da.rio.write_crs(crs)
        da = da.rio.set_spatial_dims(x_dim="x", y_dim="y")

        return da

    def create_coord_arrays(x_coords, y_coords):
        """Create coordinate arrays."""
        x_da = xr.DataArray(
            x_coords,
            coords={"x": x_coords},
            dims=["x"],
            attrs={
                "standard_name": "projection_x_coordinate",
                "units": "m",
                "long_name": "x coordinate of projection",
            },
        )

        y_da = xr.DataArray(
            y_coords,
            coords={"y": y_coords},
            dims=["y"],
            attrs={
                "standard_name": "projection_y_coordinate",
                "units": "m",
                "long_name": "y coordinate of projection",
            },
        )

        return x_da, y_da

    # Level 0 (10m): Only native 10m bands
    print("Creating Level 0 (10m) with bands: b02, b03, b04, b08")

    x_da, y_da = create_coord_arrays(base_x_10m, base_y_10m)

    # Native 10m bands
    b02_10m = create_data_array("b02", base_x_10m, base_y_10m)
    b03_10m = create_data_array("b03", base_x_10m, base_y_10m)
    b04_10m = create_data_array("b04", base_x_10m, base_y_10m)
    b08_10m = create_data_array("b08", base_x_10m, base_y_10m)

    # Create level 0 dataset
    level_0_ds = xr.Dataset(
        {
            "b02": b02_10m,
            "b03": b03_10m,
            "b04": b04_10m,
            "b08": b08_10m,
            "x": x_da,
            "y": y_da,
        }
    )

    # Set CRS at dataset level
    level_0_ds = level_0_ds.rio.write_crs(crs)
    level_0_ds = level_0_ds.rio.set_spatial_dims(x_dim="x", y_dim="y")

    # Set grid_mapping attributes
    level_0_ds.attrs["grid_mapping"] = "spatial_ref"
    for var in ["b02", "b03", "b04", "b08"]:
        level_0_ds[var].attrs["grid_mapping"] = "spatial_ref"

    # Create encoding and write level 0
    encoding_0 = create_encoding(level_0_ds)
    level_0_ds.to_zarr(
        fixture_path,
        group="measurements/reflectance/r10m",
        mode="w",
        consolidated=True,
        zarr_format=3,
        encoding=encoding_0,
    )

    # Level 1 (20m): All bands (native 20m + downsampled 10m)
    print("Creating Level 1 (20m) with all bands")

    x_da, y_da = create_coord_arrays(base_x_20m, base_y_20m)

    # All bands at 20m resolution
    bands_20m = {}
    for band in ["b02", "b03", "b04", "b05", "b06", "b07", "b08", "b11", "b12", "b8a"]:
        bands_20m[band] = create_data_array(band, base_x_20m, base_y_20m)

    level_1_ds = xr.Dataset(
        {
            **bands_20m,
            "x": x_da,
            "y": y_da,
        }
    )

    # Set CRS at dataset level
    level_1_ds = level_1_ds.rio.write_crs(crs)
    level_1_ds = level_1_ds.rio.set_spatial_dims(x_dim="x", y_dim="y")

    # Set grid_mapping attributes
    level_1_ds.attrs["grid_mapping"] = "spatial_ref"
    for var in ["b02", "b03", "b04", "b05", "b06", "b07", "b08", "b11", "b12", "b8a"]:
        level_1_ds[var].attrs["grid_mapping"] = "spatial_ref"

    # Create encoding and write level 1
    encoding_1 = create_encoding(level_1_ds)
    level_1_ds.to_zarr(
        fixture_path,
        group="measurements/reflectance/r20m",
        mode="a",
        consolidated=True,
        zarr_format=3,
        encoding=encoding_1,
    )

    # Level 2 (60m): All bands
    print("Creating Level 2 (60m) with all bands")

    x_da, y_da = create_coord_arrays(base_x_60m, base_y_60m)

    # All bands at 60m resolution
    bands_60m = {}
    for band in ["b02", "b03", "b04", "b05", "b06", "b07", "b08", "b11", "b12", "b8a"]:
        bands_60m[band] = create_data_array(band, base_x_60m, base_y_60m)

    level_2_ds = xr.Dataset(
        {
            **bands_60m,
            "x": x_da,
            "y": y_da,
        }
    )

    # Set CRS at dataset level
    level_2_ds = level_2_ds.rio.write_crs(crs)
    level_2_ds = level_2_ds.rio.set_spatial_dims(x_dim="x", y_dim="y")

    # Set grid_mapping attributes
    level_2_ds.attrs["grid_mapping"] = "spatial_ref"
    for var in ["b02", "b03", "b04", "b05", "b06", "b07", "b08", "b11", "b12", "b8a"]:
        level_2_ds[var].attrs["grid_mapping"] = "spatial_ref"

    # Create encoding and write level 2
    encoding_2 = create_encoding(level_2_ds)
    level_2_ds.to_zarr(
        fixture_path,
        group="measurements/reflectance/r60m",
        mode="a",
        consolidated=True,
        zarr_format=3,
        encoding=encoding_2,
    )

    # Level 3 (120m): All bands (downsampled from level 2)
    print("Creating Level 3 (120m) with all bands")

    x_da, y_da = create_coord_arrays(base_x_120m, base_y_120m)

    # All bands at 120m resolution
    bands_120m = {}
    for band in ["b02", "b03", "b04", "b05", "b06", "b07", "b08", "b11", "b12", "b8a"]:
        bands_120m[band] = create_data_array(band, base_x_120m, base_y_120m)

    level_3_ds = xr.Dataset(
        {
            **bands_120m,
            "x": x_da,
            "y": y_da,
        }
    )

    # Set CRS at dataset level
    level_3_ds = level_3_ds.rio.write_crs(crs)
    level_3_ds = level_3_ds.rio.set_spatial_dims(x_dim="x", y_dim="y")

    # Set grid_mapping attributes
    level_3_ds.attrs["grid_mapping"] = "spatial_ref"
    for var in ["b02", "b03", "b04", "b05", "b06", "b07", "b08", "b11", "b12", "b8a"]:
        level_3_ds[var].attrs["grid_mapping"] = "spatial_ref"

    # Create encoding and write level 3
    encoding_3 = create_encoding(level_3_ds)
    level_3_ds.to_zarr(
        fixture_path,
        group="measurements/reflectance/r120m",
        mode="a",
        consolidated=True,
        zarr_format=3,
        encoding=encoding_3,
    )

    print(f"✅ Created optimized pyramid fixture at {fixture_path}")
    print("Structure:")
    print("  - Level 0 (10m): b02, b03, b04, b08 only")
    print("  - Level 1 (20m): all bands")
    print("  - Level 2 (60m): all bands")
    print("  - Level 3 (120m): all bands")

    return fixture_path


if __name__ == "__main__":
    create_optimized_pyramid_fixture()

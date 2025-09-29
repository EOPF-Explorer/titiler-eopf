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
    base_x_10m = np.linspace(500000, 510000, 100)  # 100m resolution at 10m pixel size
    base_y_10m = np.linspace(4200000, 4190000, 100)

    base_x_20m = np.linspace(500000, 510000, 50)  # 200m resolution at 20m pixel size
    base_y_20m = np.linspace(4200000, 4190000, 50)

    base_x_60m = np.linspace(500000, 510000, 17)  # ~600m resolution at 60m pixel size
    base_y_60m = np.linspace(4200000, 4190000, 17)

    base_x_120m = np.linspace(500000, 510000, 8)  # ~1200m resolution at 120m pixel size
    base_y_120m = np.linspace(4200000, 4190000, 8)

    # Create root group with multiscales metadata
    root_attrs = {
        "multiscales": {
            "tile_matrix_set": {
                "crs": f"EPSG:{crs.to_epsg()}",
                "tileMatrices": [
                    {
                        "id": "0",
                        "cellSize": 10.0,
                        "matrixWidth": 100,
                        "matrixHeight": 100,
                    },  # 10m
                    {
                        "id": "1",
                        "cellSize": 20.0,
                        "matrixWidth": 50,
                        "matrixHeight": 50,
                    },  # 20m
                    {
                        "id": "2",
                        "cellSize": 60.0,
                        "matrixWidth": 17,
                        "matrixHeight": 17,
                    },  # 60m
                    {
                        "id": "3",
                        "cellSize": 120.0,
                        "matrixWidth": 8,
                        "matrixHeight": 8,
                    },  # 120m
                ],
            }
        }
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
                "long_name": f"BOA reflectance from MSI acquisition at spectral band {name}",
                "units": "digital_counts",
                "scale_factor": scale_factor,
                "add_offset": offset,
                "valid_min": 1,
                "valid_max": 65535,
                "fill_value": 0,
                "proj:epsg": crs.to_epsg(),
                "proj:transform": [
                    x_coords[1] - x_coords[0],
                    0.0,
                    x_coords[0],
                    0.0,
                    y_coords[0] - y_coords[1],
                    y_coords[0],
                ],
                "proj:shape": [height, width],
                "proj:bbox": [x_coords[0], y_coords[-1], x_coords[-1], y_coords[0]],
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

    level_0_ds.attrs["pyramid_level"] = 0
    level_0_ds.attrs["resolution_meters"] = 10

    # Create encoding and write level 0
    encoding_0 = create_encoding(level_0_ds)
    level_0_ds.to_zarr(
        fixture_path,
        group="measurements/reflectance/0",
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

    level_1_ds.attrs["pyramid_level"] = 1
    level_1_ds.attrs["resolution_meters"] = 20

    # Create encoding and write level 1
    encoding_1 = create_encoding(level_1_ds)
    level_1_ds.to_zarr(
        fixture_path,
        group="measurements/reflectance/1",
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

    level_2_ds.attrs["pyramid_level"] = 2
    level_2_ds.attrs["resolution_meters"] = 60

    # Create encoding and write level 2
    encoding_2 = create_encoding(level_2_ds)
    level_2_ds.to_zarr(
        fixture_path,
        group="measurements/reflectance/2",
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

    level_3_ds.attrs["pyramid_level"] = 3
    level_3_ds.attrs["resolution_meters"] = 120

    # Create encoding and write level 3
    encoding_3 = create_encoding(level_3_ds)
    level_3_ds.to_zarr(
        fixture_path,
        group="measurements/reflectance/3",
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

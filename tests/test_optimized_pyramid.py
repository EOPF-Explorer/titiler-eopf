"""test titiler-eopf optimized pyramid functionality"""

import os

import pytest
import xarray

from titiler.eopf.reader import GeoZarrReader, MissingVariables

DATA_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
OPTIMIZED_PYRAMID = os.path.join(
    DATA_DIR,
    "eopf_geozarr",
    "optimized_pyramid.zarr",
)


@pytest.fixture(scope="session", autouse=True)
def create_optimized_pyramid_fixture():
    """Ensure the optimized pyramid fixture exists before running tests."""
    if not os.path.exists(OPTIMIZED_PYRAMID):
        # Import and run the fixture creation script
        from tests.create_multiscale_fixture import create_optimized_pyramid_fixture

        create_optimized_pyramid_fixture()
    return OPTIMIZED_PYRAMID


def test_optimized_pyramid_structure():
    """test that optimized pyramid fixture has expected structure."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        assert src.input == OPTIMIZED_PYRAMID
        assert isinstance(src.datatree, xarray.DataTree)

        # Should detect single multiscale group
        assert src.groups == ["/measurements/reflectance"]

        # Check multiscale metadata
        group = src.datatree["/measurements/reflectance"]
        assert "multiscales" in group.attrs

        tile_matrices = group.attrs["multiscales"]["tile_matrix_set"]["tileMatrices"]
        assert len(tile_matrices) == 4  # 4 pyramid levels

        # Check scale IDs and resolutions
        scales = [(tm["id"], tm["cellSize"]) for tm in tile_matrices]
        expected_scales = [("0", 10.0), ("1", 20.0), ("2", 60.0), ("3", 120.0)]
        assert scales == expected_scales


def test_variable_collection_across_scales():
    """test that variables from all scales are collected properly."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        # Should collect all unique variables across all scales
        variables = sorted(src.variables)

        # Level 0 has: b02, b03, b04, b08
        # Levels 1,2,3 have: b02, b03, b04, b05, b06, b07, b08, b11, b12, b8a
        # Combined unique set should be all 10 bands
        expected_variables = sorted(
            [
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
        )

        assert variables == expected_variables
        assert len(variables) == 10

        # Verify coordinate variables are excluded
        assert "/measurements/reflectance:spatial_ref" not in variables
        assert "/measurements/reflectance:x" not in variables
        assert "/measurements/reflectance:y" not in variables


def test_variable_fallback_behavior():
    """test that variables fall back to available scales when not present at requested scale."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        # Test accessing b05 (only available at levels 1,2,3 - NOT at level 0/10m)
        # This should automatically fall back to the finest available scale
        group = "/measurements/reflectance"
        variable = "b05"

        # When accessing b05, it should find it at level 1 (20m) since it's not at level 0 (10m)
        da = src._get_variable(group, variable)
        assert da.name == variable
        assert da.ndim == 2

        # The data should come from level 1 (20m resolution, 50x50 pixels)
        assert da.shape == (500, 500)  # Level 1 dimensions

        # Test accessing b02 (available at all levels) - should use finest scale (level 0)
        da_b02 = src._get_variable(group, "b02")
        assert da_b02.shape == (1000, 1000)  # Level 0 dimensions


def test_scale_specific_variable_access():
    """test accessing variables with explicit scale constraints."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        group = "/measurements/reflectance"

        # Test accessing b02 (available at all levels) without spatial constraints
        # Should use finest available scale (level 0)
        da_b02 = src._get_variable(group, "b02")
        assert da_b02.shape == (1000, 1000)  # Level 0 size

        # should select a level close to 800px
        da_b02 = src._get_variable(group, "b02", width=800, height=800)
        assert da_b02.shape == (1000, 1000)  # Level 0 size

        # should select a level close to 600px
        da_b02 = src._get_variable(group, "b02", width=600, height=600)
        assert da_b02.shape == (500, 500)  # Level 1 size

        # should select a level close to 600px
        da_b02 = src._get_variable(group, "b02", width=600)
        assert da_b02.shape == (500, 500)  # Level 1 size

        # should select a level close to 600px
        da_b02 = src._get_variable(group, "b02", height=600)
        assert da_b02.shape == (500, 500)  # Level 1 size

        # should select a level close to 600px
        da_b02 = src._get_variable(group, "b02", max_size=600)
        assert da_b02.shape == (500, 500)  # Level 1 size

        # When just bounds, we select the higher level
        da_b02 = src._get_variable(
            group, "b02", bounds=(500100, 4190100, 509900, 4190900)
        )
        assert da_b02.shape == (1000, 1000)  # Level 0 size

        # Test accessing b05 (not available at level 0)
        # Should automatically use finest available scale (level 1)
        da_b05 = src._get_variable(group, "b05")
        assert da_b05.shape == (500, 500)  # Level 1 size


def test_scale_specific_variable_access_reproj():
    """test accessing variables with explicit scale constraints and reprojection."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        group = "/measurements/reflectance"

        # Test accessing b02 (available at all levels) without spatial constraints
        # Should use finest available scale (level 0)
        da_b02 = src._get_variable(group, "b02", dst_crs="epsg:4326")
        assert da_b02.shape == (1000, 1000)  # Level 0 size

        # should select a level close to 800px
        da_b02 = src._get_variable(
            group, "b02", width=800, height=800, dst_crs="epsg:4326"
        )
        assert da_b02.shape == (1000, 1000)  # Level 0 size

        # should select a level close to 600px
        da_b02 = src._get_variable(
            group, "b02", width=600, height=600, dst_crs="epsg:4326"
        )
        assert da_b02.shape == (500, 500)  # Level 1 size

        # should select a level close to 600px
        da_b02 = src._get_variable(group, "b02", width=600, dst_crs="epsg:4326")
        assert da_b02.shape == (500, 500)  # Level 1 size

        # should select a level close to 600px
        da_b02 = src._get_variable(group, "b02", height=500, dst_crs="epsg:4326")
        assert da_b02.shape == (500, 500)  # Level 1 size

        # should select a level close to 600px
        da_b02 = src._get_variable(group, "b02", max_size=600, dst_crs="epsg:4326")
        assert da_b02.shape == (500, 500)  # Level 1 size

        # tms = morecantile.tms.get("WebMercatorQuad")
        # list(tms.xy_bounds(2219, 1580, 12))
        bounds = (
            1673053.675105922,
            4569099.802774707,
            1682837.6147264242,
            4578883.742395209,
        )

        # When just bounds, we select the higher level
        da_b02 = src._get_variable(
            group,
            "b02",
            bounds=bounds,
            dst_crs="epsg:3857",
        )
        assert da_b02.shape == (1000, 1000)

        da_b02 = src._get_variable(
            group,
            "b02",
            bounds=bounds,
            dst_crs="epsg:3857",
            width=1024,
            height=1024,
        )
        # output resolution is 9.55462853564677m (epsg:3857)
        assert da_b02.shape == (1000, 1000)

        da_b02 = src._get_variable(
            group,
            "b02",
            bounds=bounds,
            dst_crs="epsg:3857",
            width=256,
            height=256,
        )
        # output resolution is 38.21851414258708 (epsg:3857)
        assert da_b02.shape == (500, 500)

        da_b02 = src._get_variable(
            group,
            "b02",
            bounds=bounds,
            dst_crs="epsg:3857",
            width=128,
            height=128,
        )
        # output resolution is 76.43702828517416 (epsg:3857)
        assert da_b02.shape == (167, 167)

        da_b02 = src._get_variable(
            group,
            "b02",
            bounds=bounds,
            dst_crs="epsg:3857",
            width=64,
            height=64,
        )
        # output resolution is 152.87405657034833 (epsg:3857)
        assert da_b02.shape == (84, 84)


def test_missing_variable_error():
    """test proper error handling for truly missing variables."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        # Test requesting a completely non-existent variable
        with pytest.raises(MissingVariables) as exc_info:
            src._get_variable("/measurements/reflectance", "b99_nonexistent")

        assert "not found in any multiscale level" in str(exc_info.value)
        assert "b99_nonexistent" in str(exc_info.value)
        assert "/measurements/reflectance" in str(exc_info.value)


def test_info_method_robustness():
    """test that info method handles optimized pyramid variables robustly."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        # Test info for all variables
        info = src.info()

        # Should return info for all 10 unique variables
        assert len(info) == 10

        # All variables should have valid info
        for _, var_info in info.items():
            assert var_info.width > 0
            assert var_info.height > 0
            assert var_info.crs is not None

        # Test info for specific subset including variables from different scales
        subset_vars = [
            "/measurements/reflectance:b02",  # Available at all levels
            "/measurements/reflectance:b05",  # Only at levels 1,2,3
            "/measurements/reflectance:b08",  # Available at all levels
        ]

        info_subset = src.info(variables=subset_vars)
        assert len(info_subset) == 3

        # Each should return valid info despite coming from different optimal scales
        for var in subset_vars:
            assert var in info_subset
            assert info_subset[var].width > 0


def test_tile_method_with_mixed_variables():
    """test tile method with variables from different pyramid levels."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        tile = src.tms.tile(lon, lat, 10)

        # Test tile with mixed variables (some only at certain levels)
        mixed_variables = [
            "/measurements/reflectance:b02",  # Available at all levels
            "/measurements/reflectance:b05",  # Only at levels 1,2,3 (not level 0)
            "/measurements/reflectance:b08",  # Available at all levels
        ]

        img = src.tile(*tile, variables=mixed_variables)

        # Should successfully create tile despite variables coming from different scales
        assert img.band_names == ["b02", "b05", "b08"]
        assert img.data.shape == (3, 256, 256)

        # All bands should have valid data - check if it's a masked array or regular array
        if hasattr(img.data, "mask"):
            assert not img.data.mask.all()  # Not all masked
        else:
            assert img.data.size > 0  # Has data


def test_point_method_with_mixed_variables():
    """test point method with variables from different pyramid levels."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2

        # Test point extraction with variables from different scales
        mixed_variables = [
            "/measurements/reflectance:b02",  # Level 0 preferred
            "/measurements/reflectance:b05",  # Only levels 1,2,3
        ]

        pt = src.point(lon, lat, variables=mixed_variables)

        # Should successfully extract point values
        assert pt.band_names == ["b02", "b05"]
        assert pt.data.shape == (2,)

        # Values should be valid (not all NaN/masked)
        assert not all(pt.data.mask) if hasattr(pt.data, "mask") else True


def test_expression_with_mixed_variables():
    """test expressions using variables from different pyramid levels."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        bounds = src.bounds
        lon, lat = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        tile = src.tms.tile(lon, lat, 10)

        # Test expression combining variables from different scales
        # b02 is available at level 0, b05 only at levels 1,2,3
        expression = "/measurements/reflectance:b02 + /measurements/reflectance:b05"

        img = src.tile(*tile, expression=expression)

        # Should work despite variables coming from different optimal scales
        assert img.data.shape == (1, 256, 256)
        assert img.band_names == [expression]

        # Should have valid data - check if it's a masked array or regular array
        if hasattr(img.data, "mask"):
            assert not img.data.mask.all()  # Not all masked
        else:
            assert img.data.size > 0  # Has data


def test_pyramid_level_selection_logic():
    """test that appropriate pyramid levels are selected based on variable availability."""
    with GeoZarrReader(OPTIMIZED_PYRAMID) as src:
        group = "/measurements/reflectance"

        # For variables available at multiple scales, verify correct scale selection
        # b02 is available at all scales (0,1,2,3)
        da_b02 = src._get_variable(group, "b02")
        # Should prefer finest scale (level 0) when no constraints given
        assert da_b02.shape == (1000, 1000)  # Level 0 size

        # For variables only available at coarser scales
        # b05 is only at levels 1,2,3 (not level 0)
        da_b05 = src._get_variable(group, "b05")
        # Should use finest available scale (level 1)
        assert da_b05.shape == (500, 500)  # Level 1 size

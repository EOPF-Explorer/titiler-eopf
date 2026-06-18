"""Benchmark."""

import os
import shutil
from unittest.mock import patch

import pytest

from titiler.eopf.reader import GeoZarrReader, open_dataset
from titiler.eopf.settings import EOPFCacheSettings

from ..create_multiscale_fixture import create_geozarr_fixture


@pytest.fixture
def geozarr_benchmark():
    """GeoZarr dataset path."""
    geozarr_path = os.path.join(os.path.dirname(__file__), "geozarr.zarr")
    create_geozarr_fixture(geozarr_path, version="v1")
    yield geozarr_path
    if os.path.exists(geozarr_path):
        shutil.rmtree(geozarr_path)


@pytest.fixture
def geozarr_3d_benchmark():
    """GeoZarr dataset path with a time dimension (for `sel` benchmarks)."""
    geozarr_path = os.path.join(os.path.dirname(__file__), "geozarr_3d.zarr")
    create_geozarr_fixture(geozarr_path, version="v1", with_time=True)
    yield geozarr_path
    if os.path.exists(geozarr_path):
        shutil.rmtree(geozarr_path)


@pytest.mark.benchmark(min_rounds=50)
@patch("titiler.eopf.reader.cache_settings")
def test_open(cache_settings, geozarr_benchmark, benchmark):
    """Benchmark GeoZarrReader open method."""
    cache_settings.side_effect = lambda: EOPFCacheSettings(enable=False)

    benchmark.name = "GeoZarrReader-Open"
    benchmark.fullname = "GeoZarrReader-Open"

    def _open():
        open_dataset.cache_clear()
        with GeoZarrReader(geozarr_benchmark):
            pass

    _ = benchmark(_open)


@pytest.mark.benchmark(min_rounds=50)
@patch("titiler.eopf.reader.cache_settings")
def test_info(cache_settings, geozarr_benchmark, benchmark):
    """Benchmark GeoZarrReader.info method."""
    cache_settings.side_effect = lambda: EOPFCacheSettings(enable=False)

    benchmark.name = "GeoZarrReader-Info"
    benchmark.fullname = "GeoZarrReader-Info"

    def _info():
        open_dataset.cache_clear()
        with GeoZarrReader(geozarr_benchmark) as src:
            _ = src.info(variables=["/measurements/reflectance:b02"])

    _ = benchmark(_info)


@pytest.mark.benchmark(min_rounds=50)
@patch("titiler.eopf.reader.cache_settings")
def test_preview(cache_settings, geozarr_benchmark, benchmark):
    """Benchmark GeoZarrReader.preview method."""
    cache_settings.side_effect = lambda: EOPFCacheSettings(enable=False)

    benchmark.name = "GeoZarrReader-Preview"
    benchmark.fullname = "GeoZarrReader-Preview"

    def _preview():
        open_dataset.cache_clear()
        with GeoZarrReader(geozarr_benchmark) as src:
            return src.preview(
                variables=[
                    "/measurements/reflectance:b04",
                    "/measurements/reflectance:b03",
                    "/measurements/reflectance:b02",
                ]
            )

    _ = benchmark(_preview)


@pytest.mark.benchmark(min_rounds=50)
@patch("titiler.eopf.reader.cache_settings")
def test_tile(cache_settings, geozarr_benchmark, benchmark):
    """Benchmark GeoZarrReader.tile method."""
    cache_settings.side_effect = lambda: EOPFCacheSettings(enable=False)

    benchmark.name = "GeoZarrReader-Tile"
    benchmark.fullname = "GeoZarrReader-Tile"

    def _tile():
        open_dataset.cache_clear()
        with GeoZarrReader(geozarr_benchmark) as src:
            return src.tile(
                554,
                395,
                10,
                variables=[
                    "/measurements/reflectance:b04",
                    "/measurements/reflectance:b03",
                    "/measurements/reflectance:b02",
                ],
            )

    _ = benchmark(_tile)


@pytest.mark.benchmark(min_rounds=50)
@patch("titiler.eopf.reader.cache_settings")
def test_tile_sel(cache_settings, geozarr_3d_benchmark, benchmark):
    """Benchmark a tile read with a datetime `sel` (guards the sel-cast path)."""
    cache_settings.side_effect = lambda: EOPFCacheSettings(enable=False)

    benchmark.name = "GeoZarrReader-Tile-Sel"
    benchmark.fullname = "GeoZarrReader-Tile-Sel"

    def _tile():
        open_dataset.cache_clear()
        with GeoZarrReader(geozarr_3d_benchmark) as src:
            return src.tile(
                554,
                395,
                10,
                variables=["/measurements/reflectance:b02"],
                sel=["time=2022-01-02T00:00:00.000000000"],
            )

    _ = benchmark(_tile)

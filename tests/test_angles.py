"""Sentinel-2 view and sun angle bands from an EOPF Zarr product (angles.py).

The synthetic product has the layout of the live EOPF products: the angle
grids in `conditions/geometry`, the 60 m detector footprint in
`conditions/mask/detector_footprint/r60m`, the tile CRS on
`measurements/reflectance`, and a root `proj:code` of EPSG:4326 (the CRS of
the root `spatial:bbox`, not of the grid).
"""

import json
import os
import shutil
import warnings

import numpy
import pystac
import pytest
import zarr
from openeo_pg_parser_networkx.pg_schema import BoundingBox
from rasterio.crs import CRS
from rasterio.warp import transform_bounds
from rio_tiler.models import ImageData

from titiler.eopf.openeo import angles
from titiler.eopf.openeo.angles import (
    ANGLE_BANDS,
    S2_BANDS,
    AngleDataError,
    ZarrSunAngleGridReader,
    ZarrViewAngleGridReader,
    ZarrViewAngleMeanReader,
    _group,
    _open_product,
    get_angle_grids,
    has_angle_bands,
    has_geozarr_conventions,
    product_root,
)
from titiler.eopf.openeo.reader import STACReader
from titiler.eopf.openeo.stacapi import (
    LoadCollection,
    get_all_band_names,
    stacApiBackend,
)
from titiler.eopf.reader import _clear_open_dataset_caches
from titiler.eopf.stac import _parse_asset

TILE_CRS = CRS.from_epsg(32637)
ULX, ULY = 500000.0, 7900000.0
STEP = 5000.0
NODES = 3  # a 10 km x 10 km grid
TILE_BBOX = (ULX, ULY - 10000.0, ULX + 10000.0, ULY)

# Detector d01 sees the west half, d02 the east half. Their azimuths differ
# by 180 degrees: a mean of the two (190) is correct for neither.
D1_AZIMUTH, D2_AZIMUTH = 100.0, 280.0
D1_ZENITH, D2_ZENITH = 5.0, 6.0


def sun_zenith(x, y):
    """Linear in x and y, so the bilinear interpolation is exact."""
    return 30.0 + 0.001 * (x - ULX) + 0.0005 * (ULY - y)


def sun_azimuth(x, y):
    """Linear in x, so the interpolation is almost exact."""
    return 150.0 + 0.0002 * (x - ULX)


#: The `spatial` and `proj` conventions, as `GeoZarrReader` checks them.
GEOZARR_CONVENTIONS = [
    {"uuid": "689b58e2-cf7b-45e0-9fff-9cfc0883d6b4", "name": "spatial:"},
    {"uuid": "f17cb550-5864-4468-aeb7-f3180cfb622f", "name": "proj:"},
]

#: The dimension names of each array, as in the EOPF products (xarray needs
#: them when GeoZarrReader opens the whole product).
DIMS = {
    "x": ["x"],
    "y": ["y"],
    "angle": ["angle"],
    "band": ["band"],
    "detector": ["detector"],
    "sun_angles": ["angle", "y", "x"],
    "mean_viewing_incidence_angles": ["band", "angle"],
    "viewing_incidence_angles": ["band", "detector", "angle", "y", "x"],
    "b01": ["y", "x"],
}


def write_angle_product(
    path: str,
    *,
    crs: str = "EPSG:32637",
    ulx: float = ULX,
    uly: float = ULY,
    labels_as_bytes: bool = False,
    geometry_conventions: bool = False,
    crs_on: str = "reflectance",
    footprint: numpy.ndarray | None = None,
    footprint_res: float = 1000.0,
) -> None:
    """Add the angle groups of an EOPF Sentinel-2 product at ``path``.

    ``crs_on``: the group that has the tile `proj:code`: `reflectance`
    (`measurements/reflectance`), `footprint` (the 60 m footprint group, as
    in the EODC products) or `none`.
    """
    # Not from the consolidated metadata: it would not show the groups that
    # this function adds (the GeoZarr fixture is already consolidated).
    root = zarr.open_group(path, mode="a", zarr_format=3, use_consolidated=False)
    root.attrs.setdefault("proj:code", "EPSG:4326")
    reflectance = root.require_group("measurements").require_group("reflectance")
    if crs_on == "reflectance":
        reflectance.attrs["proj:code"] = crs

    xs = ulx + STEP * numpy.arange(NODES)
    ys = uly - STEP * numpy.arange(NODES)
    gx, gy = numpy.meshgrid(xs, ys)

    def labels(values):
        array = numpy.array(values)
        return array.astype("S") if labels_as_bytes else array

    geometry = root.require_group("conditions").require_group("geometry")
    if geometry_conventions:
        # As data-model#346 asks: the group declares its CRS and grid.
        geometry.attrs["zarr_conventions"] = GEOZARR_CONVENTIONS
        geometry.attrs["proj:code"] = crs
    geometry.create_array("x", dimension_names=DIMS["x"], data=xs, overwrite=True)
    geometry.create_array("y", dimension_names=DIMS["y"], data=ys, overwrite=True)
    geometry.create_array(
        "angle",
        dimension_names=DIMS["angle"],
        data=labels(["zenith", "azimuth"]),
        overwrite=True,
    )
    geometry.create_array(
        "band",
        dimension_names=DIMS["band"],
        data=labels(list(S2_BANDS)),
        overwrite=True,
    )
    geometry.create_array(
        "detector",
        dimension_names=DIMS["detector"],
        data=labels(["d01", "d02"]),
        overwrite=True,
    )
    geometry.create_array(
        "sun_angles",
        dimension_names=DIMS["sun_angles"],
        data=numpy.stack([sun_zenith(gx, gy), sun_azimuth(gx, gy)]),
        overwrite=True,
    )

    # Mean view angles: zenith 5.0 + 0.1 * band index; azimuths 7 x 355 and
    # 6 x 5, which wrap at 0/360 (arithmetic mean: about 193).
    nbands = len(S2_BANDS)
    mean_view = numpy.stack(
        [5.0 + 0.1 * numpy.arange(nbands), numpy.array([355.0] * 7 + [5.0] * 6)],
        axis=1,
    )
    geometry.create_array(
        "mean_viewing_incidence_angles",
        dimension_names=DIMS["mean_viewing_incidence_angles"],
        data=mean_view,
        overwrite=True,
    )

    # Per-band, per-detector grids. d01 has values in columns 0-1 only, d02
    # in columns 1-2 only, NaN elsewhere (as in the live products). The band
    # adds 0.01 * index to the zenith and 1 * index to the azimuth.
    view = numpy.full((nbands, 2, 2, NODES, NODES), numpy.nan)
    for b in range(nbands):
        view[b, 0, 0, :, 0:2] = D1_ZENITH + 0.01 * b
        view[b, 0, 1, :, 0:2] = D1_AZIMUTH + b
        view[b, 1, 0, :, 1:3] = D2_ZENITH + 0.01 * b
        view[b, 1, 1, :, 1:3] = D2_AZIMUTH + b
    geometry.create_array(
        "viewing_incidence_angles",
        dimension_names=DIMS["viewing_incidence_angles"],
        data=view,
        overwrite=True,
    )

    # Footprint: 10 x 10 pixels of 1 km. West half d01, east half d02, and
    # the two north rows see nothing (more than the 2-pixel growth).
    if footprint is None:
        footprint = numpy.zeros((10, 10), dtype="uint8")
        footprint[2:, :5] = 1
        footprint[2:, 5:] = 2
    nrows, ncols = footprint.shape
    fp = (
        root.require_group("conditions")
        .require_group("mask")
        .require_group("detector_footprint")
        .require_group("r60m")
    )
    if crs_on == "footprint":
        fp.attrs["proj:code"] = crs
    fp.create_array("b01", dimension_names=DIMS["b01"], data=footprint, overwrite=True)
    fp.create_array(
        "x",
        dimension_names=DIMS["x"],
        data=ulx + footprint_res * (numpy.arange(ncols) + 0.5),
        overwrite=True,
    )
    fp.create_array(
        "y",
        dimension_names=DIMS["y"],
        data=uly - footprint_res * (numpy.arange(nrows) + 0.5),
        overwrite=True,
    )

    zarr.consolidate_metadata(path)


@pytest.fixture(autouse=True)
def clear_caches():
    """The products are cached by href; each test writes its own.

    The GeoZarr dataset caches too: `test_load_collection_with_angle_bands`
    adds groups to the shared GeoZarr fixture, and a cached view of it must
    not reach the next tests.
    """
    clears = (
        angles.get_angle_grids.cache_clear,
        angles.get_detector_footprint.cache_clear,
        _clear_open_dataset_caches,
    )
    for clear in clears:
        clear()
    yield
    for clear in clears:
        clear()


@pytest.fixture
def product(tmp_path) -> str:
    """A synthetic product with the angle groups."""
    path = str(tmp_path / "S2B_MSIL2A_TEST.zarr")
    write_angle_product(path)
    return path


def read(reader_cls, product, quantity, band=None, bbox=TILE_BBOX, size=10):
    """Read one angle band of ``product`` on a grid in the tile CRS."""
    with reader_cls(product, quantity=quantity, band=band) as src:
        return src.part(
            bbox, dst_crs=TILE_CRS, bounds_crs=TILE_CRS, width=size, height=size
        )


def pixel_centres(bbox=TILE_BBOX, size=10):
    """The pixel centres of the output grid, in the tile CRS."""
    xs = bbox[0] + (numpy.arange(size) + 0.5) * (bbox[2] - bbox[0]) / size
    ys = bbox[3] - (numpy.arange(size) + 0.5) * (bbox[3] - bbox[1]) / size
    return numpy.meshgrid(xs, ys)


# --------------------------------------------------------------------------
# Product arrays


def test_angle_grids(product):
    """The grid arrays, the CRS and the labels are read."""
    grids = get_angle_grids(product)
    # The CRS of measurements/reflectance, not the root's EPSG:4326.
    assert grids.crs == TILE_CRS
    assert (grids.ulx, grids.uly) == (ULX, ULY)
    assert grids.detectors == (1, 2)
    assert grids.bands == S2_BANDS
    numpy.testing.assert_allclose(grids.lines, [0, 5000, 10000])
    numpy.testing.assert_allclose(grids.pixels, [0, 5000, 10000])


def test_labels_as_bytes(tmp_path):
    """EODC products store the coordinate labels as bytes."""
    path = str(tmp_path / "bytes.zarr")
    write_angle_product(path, labels_as_bytes=True)
    grids = get_angle_grids(path)
    assert grids.bands == S2_BANDS
    assert grids.detectors == (1, 2)


def test_crs_from_footprint_group(tmp_path):
    """The CRS can also come from the 60 m footprint group."""
    path = str(tmp_path / "footprint.zarr")
    write_angle_product(path, crs_on="footprint")
    assert get_angle_grids(path).crs == TILE_CRS


def test_no_crs(tmp_path):
    """The root `proj:code` (EPSG:4326, of the root bbox) is never used."""
    path = str(tmp_path / "nocrs.zarr")
    write_angle_product(path, crs_on="none")
    with pytest.raises(AngleDataError, match="proj:code"):
        get_angle_grids(path)


def test_warns_when_products_have_conventions(tmp_path, caplog):
    """The direct read is temporary (data-model#346): a product whose
    `conditions/geometry` has the conventions gives a warning."""
    fixed = str(tmp_path / "fixed.zarr")
    write_angle_product(fixed, geometry_conventions=True)
    with caplog.at_level("WARNING", logger="titiler.eopf.openeo.angles"):
        get_angle_grids(fixed)
    assert "data-model#346" in caplog.text

    caplog.clear()
    current = str(tmp_path / "current.zarr")
    write_angle_product(current)
    with caplog.at_level("WARNING", logger="titiler.eopf.openeo.angles"):
        get_angle_grids(current)
    assert "data-model#346" not in caplog.text


def test_product_without_geometry(tmp_path):
    """A product with no `conditions/geometry` group is a clear error."""
    path = str(tmp_path / "empty.zarr")
    zarr.open_group(path, mode="w", zarr_format=3)
    # Not a ValueError: STACReader.part would hide it as "no data".
    with pytest.raises(AngleDataError, match="conditions/geometry"):
        get_angle_grids(path)


@pytest.mark.parametrize(
    "href,root",
    [
        ("s3://b/p/S2.zarr/measurements/reflectance", "s3://b/p/S2.zarr"),
        ("https://h/p/S2.zarr", "https://h/p/S2.zarr"),
        ("https://h/p/S2.zarr/", "https://h/p/S2.zarr"),
        ("https://h/p/preview.png", None),
    ],
)
def test_product_root(href, root):
    """The product root comes from the asset href."""
    assert product_root(href) == root


# --------------------------------------------------------------------------
# Readers


def test_sun_angles(product):
    """The sun angles are interpolated from the 5 km grid."""
    xs, ys = pixel_centres()
    zenith = read(ZarrSunAngleGridReader, product, "zenith")
    azimuth = read(ZarrSunAngleGridReader, product, "azimuth")

    assert isinstance(zenith, ImageData)
    assert zenith.crs == TILE_CRS
    assert not zenith.array.mask.any()
    numpy.testing.assert_allclose(zenith.array[0], sun_zenith(xs, ys), rtol=1e-5)
    # Azimuth goes through sin/cos: close to linear over this small range.
    numpy.testing.assert_allclose(azimuth.array[0], sun_azimuth(xs, ys), atol=0.01)


def test_masked_outside_tile(product):
    """Pixels outside the tile's angle grid are masked (for the mosaic)."""
    bbox = (ULX + 5000, ULY - 10000, ULX + 15000, ULY)
    for reader in (ZarrSunAngleGridReader, ZarrViewAngleMeanReader):
        img = read(reader, product, "zenith", bbox=bbox)
        mask = img.array.mask[0]
        assert not mask[:, :5].any()
        assert mask[:, 5:].all()


def test_view_mean(product):
    """The mean view angles are one value for each item."""
    zenith = read(ZarrViewAngleMeanReader, product, "zenith")
    azimuth = read(ZarrViewAngleMeanReader, product, "azimuth")

    numpy.testing.assert_allclose(zenith.array[0], 5.6, rtol=1e-6)
    # Circular mean of 7 x 355 and 6 x 5: near 0, not the arithmetic 193.
    value = float(azimuth.array[0, 0, 0])
    assert numpy.all(azimuth.array[0] == value)
    assert value > 355 or value < 5


def test_view_angles_follow_detector(product):
    """Each pixel takes its own detector's grid, not a mean of detectors."""
    azimuth = read(ZarrViewAngleGridReader, product, "azimuth")
    zenith = read(ZarrViewAngleGridReader, product, "zenith")
    mean_band = numpy.mean(numpy.arange(len(S2_BANDS)))

    # Footprint rows 0-1 see nothing; the growth fills 2 rows -> all valid.
    # In the grown rows the detector boundary can move by up to 2 pixels, so
    # the exact values are checked where the footprint has a detector.
    assert not azimuth.array.mask.any()
    numpy.testing.assert_allclose(
        azimuth.array[0, 2:, :5], D1_AZIMUTH + mean_band, atol=1e-3
    )
    numpy.testing.assert_allclose(
        azimuth.array[0, 2:, 5:], D2_AZIMUTH + mean_band, atol=1e-3
    )
    numpy.testing.assert_allclose(
        zenith.array[0, 2:, :5], D1_ZENITH + 0.01 * mean_band, atol=1e-5
    )
    numpy.testing.assert_allclose(
        zenith.array[0, 2:, 5:], D2_ZENITH + 0.01 * mean_band, atol=1e-5
    )
    # Each grown pixel has the value of one detector, never a mean of two.
    grown = azimuth.array[0, :2].compressed()
    assert numpy.isin(
        numpy.round(grown, 3), [D1_AZIMUTH + mean_band, D2_AZIMUTH + mean_band]
    ).all()


def test_view_angles_one_band(product):
    """A band name selects the grid of that band."""
    b04 = S2_BANDS.index("b04")
    img = read(ZarrViewAngleGridReader, product, "azimuth", band="b04")
    numpy.testing.assert_allclose(img.array[0, 2:, :5], D1_AZIMUTH + b04, atol=1e-3)
    numpy.testing.assert_allclose(img.array[0, 2:, 5:], D2_AZIMUTH + b04, atol=1e-3)


def test_view_angles_masked_without_detector(tmp_path):
    """No detector (after the growth): no viewing angle."""
    path = str(tmp_path / "edge.zarr")
    footprint = numpy.zeros((10, 10), dtype="uint8")
    footprint[5:, :] = 1  # rows 0-4 see nothing; growth reaches rows 3-4
    write_angle_product(path, footprint=footprint)

    img = read(ZarrViewAngleGridReader, path, "zenith")
    mask = img.array.mask[0]
    assert mask[:3].all()
    assert not mask[3:].any()


def test_view_angles_unknown_band(product):
    """A band that the product does not have is an error."""
    with pytest.raises(AngleDataError, match="b13"):
        read(ZarrViewAngleGridReader, product, "zenith", band="b13")


def test_reprojected_output(product):
    """Output in EPSG:4326: the points go to the tile CRS first."""
    wgs84 = CRS.from_epsg(4326)
    bbox = transform_bounds(TILE_CRS, wgs84, *TILE_BBOX)
    with ZarrSunAngleGridReader(product, quantity="zenith") as src:
        img = src.part(bbox, dst_crs=wgs84, bounds_crs=wgs84, width=20, height=20)
    assert img.crs == wgs84
    values = img.array.compressed()
    assert values.size > 0
    assert values.min() >= 30.0 - 1e-3
    assert values.max() <= sun_zenith(ULX + 10000, ULY - 10000) + 1e-3


# --------------------------------------------------------------------------
# STAC reader and collection bands


def make_item(product: str, collection: str = "sentinel-2-l2a") -> pystac.Item:
    """A STAC item for ``product`` in ``collection``."""
    west, south, east, north = transform_bounds(
        TILE_CRS, CRS.from_epsg(4326), *TILE_BBOX
    )
    return pystac.Item.from_dict(
        {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "S2B_MSIL2A_TEST",
            "collection": collection,
            "bbox": [west, south, east, north],
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [west, south],
                        [east, south],
                        [east, north],
                        [west, north],
                        [west, south],
                    ]
                ],
            },
            "properties": {"datetime": "2026-11-09T09:51:31Z"},
            "links": [],
            "assets": {
                "reflectance": {
                    "href": f"{product}/measurements/reflectance",
                    "type": "application/vnd.zarr; version=3; profile=multiscales",
                    "roles": ["data", "reflectance"],
                },
                "thumbnail": {
                    "href": "https://example.com/preview.webp",
                    "type": "image/webp",
                    "roles": ["thumbnail"],
                },
            },
        }
    )


def test_stac_reader_angle_bands(product):
    """STACReader reads the angle bands of an EOPF item."""
    with STACReader(make_item(product)) as src:
        assert set(ANGLE_BANDS) <= set(src._derived_bands)
        img = src.part(
            TILE_BBOX,
            assets=_parse_asset(["sunZenithAngles", "viewAzimuthAngles"]),
            dst_crs=TILE_CRS,
            bounds_crs=TILE_CRS,
            width=10,
            height=10,
        )
    assert img.count == 2
    xs, ys = pixel_centres()
    numpy.testing.assert_allclose(img.array[0], sun_zenith(xs, ys), rtol=1e-5)
    # West half: detector d01 (azimuth about 106); east half: d02 (about 286).
    assert numpy.all(img.array[1, 2:, :5] < 200)
    assert numpy.all(img.array[1, 2:, 5:] > 200)


def test_stac_reader_relative_href(product, tmp_path):
    """A relative asset href resolves against the item, as for the
    reflectance read (not against the server's working directory)."""
    item = make_item(product)
    item.set_self_href(str(tmp_path / "item.json"))
    item.assets["reflectance"].href = "S2B_MSIL2A_TEST.zarr/measurements/reflectance"
    with STACReader(item) as src:
        info = src._get_asset_info("viewZenithMean")
    assert info["url"] == product
    assert info["reader_options"] == {"quantity": "zenith", "band": None}


@pytest.mark.parametrize("collection", ["sentinel-1-grd-rtc", "sentinel-3-olci-l1"])
def test_stac_reader_no_angle_bands(product, collection):
    """Items of other collections get no angle bands."""
    with STACReader(make_item(product, collection)) as src:
        assert not set(ANGLE_BANDS) & set(src._derived_bands)


def _collection(collection_id: str, media_type: str) -> pystac.Collection:
    """A collection with one Zarr reflectance item asset."""
    return pystac.Collection.from_dict(
        {
            "type": "Collection",
            "id": collection_id,
            "stac_version": "1.0.0",
            "description": "test",
            "license": "proprietary",
            "extent": {
                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                "temporal": {"interval": [[None, None]]},
            },
            "links": [],
            "item_assets": {
                "reflectance": {
                    "type": media_type,
                    "roles": ["data", "reflectance"],
                    "bands": [{"name": "b02"}, {"name": "b04"}],
                }
            },
            "stac_extensions": [
                "https://stac-extensions.github.io/item-assets/v1.0.0/schema.json"
            ],
        }
    )


@pytest.mark.parametrize(
    "collection_id,media_type,expected",
    [
        ("sentinel-2-l2a", "application/vnd.zarr; version=3", True),
        ("sentinel-2-l2a-new", "application/vnd.zarr; version=3", True),
        ("sentinel-2-l1c", "application/vnd+zarr; version=2", True),
        ("sentinel-2-l2a", "image/tiff; application=geotiff", False),
        ("sentinel-3-olci-l1-efr", "application/vnd.zarr", False),
    ],
)
def test_collection_band_names(collection_id, media_type, expected):
    """Only EOPF Sentinel-2 Zarr collections list the angle bands."""
    names = get_all_band_names(_collection(collection_id, media_type))
    assert "reflectance|bands=b04" in names
    assert (set(ANGLE_BANDS) <= set(names)) is expected
    if not expected:
        assert not set(ANGLE_BANDS) & set(names)


def test_has_angle_bands():
    """A Zarr asset must have the data role."""
    assert has_angle_bands("sentinel-2-l2a", [("application/vnd.zarr", ["data"])])
    assert not has_angle_bands(
        "sentinel-2-l2a", [("application/vnd.zarr", ["metadata"])]
    )


def test_summaries_describe_angle_bands():
    """The summaries describe the angle bands."""
    collection = {
        "summaries": {"bands": [{"name": "b04", "description": "red"}]},
        "cube:dimensions": {
            "bands": {"values": ["reflectance|bands=b04", "viewZenithAngles_b04"]}
        },
        "item_assets": {},
    }
    stacApiBackend.replace_bands_in_summaries_dict(None, collection)
    bands = {b["name"]: b for b in collection["summaries"]["bands"]}
    assert bands["reflectance|bands=b04"]["description"] == "red"
    assert bands["viewZenithAngles_b04"]["unit"] == "deg"
    assert "b04" in bands["viewZenithAngles_b04"]["description"]


# --------------------------------------------------------------------------
# load_collection on a GeoZarr product


@pytest.mark.parametrize("tile_buffer", [None, 1])
def test_load_collection_with_angle_bands(
    geozarr_stac, geozarr_dataset, tmp_path, tile_buffer
):
    """Reflectance and angle bands together, through load_collection.

    The GeoZarr fixture is a 10 km tile at (500000, 4200000) in EPSG:32633.
    """
    # A copy: the GeoZarr fixture is shared by the whole test session.
    product = str(tmp_path / "geozarr.zarr")
    shutil.copytree(geozarr_dataset, product)
    item = pystac.Item.from_dict(
        json.loads(
            json.dumps(geozarr_stac.to_dict(transform_hrefs=False)).replace(
                geozarr_dataset, product
            )
        )
    )
    write_angle_product(
        product,
        crs="EPSG:32633",
        ulx=500000.0,
        uly=4200000.0,
        footprint=numpy.full((10, 10), 1, dtype="uint8"),
    )

    class FakeBackend:
        url = "https://fake.api.io/stac"

        def get_items(self, *args, **kwargs):
            return [item]

    bbox = BoundingBox(
        west=14.941406249999993,
        south=37.857507156252034,
        east=15.11718749999999,
        north=37.99616267972812,
    )
    bands = ["reflectance|bands=b04", "viewZenithAngles", "sunZenithAngles"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        collection = LoadCollection(FakeBackend()).load_collection(
            "sentinel-2-l2a",
            spatial_extent=bbox,
            width=64,
            height=64,
            bands=bands,
            tile_buffer=tile_buffer,
        )
        (img,) = list(collection.values())
    assert img.count == 3
    assert img.band_descriptions == bands
    # The reflectance and the angle bands have one grid: rio-tiler did not
    # resize one to the other (that would move the angle bands).
    size = 64 + 2 * (tile_buffer or 0)
    assert (img.width, img.height) == (size, size)
    assert not [w for w in caught if "different sizes" in str(w.message)]

    reflectance, view, sun = (img.array[i] for i in range(3))
    tile = ~sun.mask
    assert tile.any()
    # One detector everywhere: the viewing angle is defined on the tile.
    assert numpy.array_equal(~view.mask, tile)
    assert numpy.allclose(view.compressed(), D1_ZENITH + 0.06, atol=1e-4)
    assert 30.0 - 1e-3 <= sun.compressed().min()
    # The reflectance band is read as before.
    assert (~reflectance.mask).any()


@pytest.mark.skipif(
    not os.environ.get("EOPF_LIVE_TESTS"),
    reason="set EOPF_LIVE_TESTS=1 to read live EOPF products",
)
@pytest.mark.parametrize("collection", ["sentinel-2-l2a", "sentinel-2-l2a-new"])
def test_live_collection(collection):
    """Read the angle bands of a live item (network)."""
    import json
    import urllib.request

    url = (
        "https://api.explorer.eopf.copernicus.eu/stac/collections/"
        f"{collection}/items?limit=1"
    )
    with urllib.request.urlopen(url) as response:
        item = pystac.Item.from_dict(json.load(response)["features"][0])

    root = product_root(item.assets["reflectance"].href)
    geometry = _group(_open_product(root), "conditions/geometry")
    assert not has_geozarr_conventions(geometry), (
        "conditions/geometry has the GeoZarr conventions now "
        "(EOPF-Explorer/data-model#346): read it with GeoZarrReader and remove "
        "the temporary direct read in titiler/eopf/openeo/angles.py"
    )

    grids = get_angle_grids(root)
    bbox = (grids.ulx, grids.uly - 109800, grids.ulx + 109800, grids.uly)
    with STACReader(item) as src:
        img = src.part(
            bbox,
            assets=_parse_asset(
                ["reflectance|bands=b04", "viewZenithAngles", "sunZenithAngles"]
            ),
            dst_crs=grids.crs,
            bounds_crs=grids.crs,
            width=512,
            height=512,
        )
    data, view, sun = (~img.array.mask[i] for i in range(3))
    assert sun.all()
    # Each data pixel has a viewing angle.
    assert not (data & ~view).any()
    view_values = img.array[1].compressed()
    assert numpy.nanmin(grids.view[:, :, 0]) - 0.1 <= view_values.min()
    assert view_values.max() <= numpy.nanmax(grids.view[:, :, 0]) + 0.1

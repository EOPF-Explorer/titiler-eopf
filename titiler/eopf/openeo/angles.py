"""Sentinel-2 view and sun angle bands from an EOPF Zarr product.

titiler-openeo gives these bands only from a `granule_metadata` asset
(`MTD_TL.xml`, see its `bandsources/sentinel2_sources.py`). The EOPF STAC
items do not have that asset: the EOPF Zarr product holds the same data as
arrays in its `conditions/geometry` group, with the detector footprints in
`conditions/mask/detector_footprint`. This module reads the angles from
these arrays.

**TEMPORARY: the direct Zarr read.** `get_angle_grids`,
`get_detector_footprint`, `_product_crs` and `_open_product` read the
arrays directly, because `conditions/geometry` has no `proj` and `spatial`
conventions, so `GeoZarrReader` cannot open it
(EOPF-Explorer/data-model#346). When the products have these conventions:

* read `sun_angles`, `viewing_incidence_angles` and the detector footprint
  with `GeoZarrReader` (`sel` for the `angle`, `band` and `detector`
  dimensions; `spatial:registration: node` puts the values at the grid
  nodes);
* remove the direct read functions above and `_product_crs`.

The band names, the masks, the selection of the detector for each pixel and
the azimuth calculation (sine and cosine) stay: `GeoZarrReader` does not do
them. `get_angle_grids` logs a warning when a product has the conventions,
and the live test (`EOPF_LIVE_TESTS=1`) fails then.

Bands:

* `viewZenithMean`, `viewAzimuthMean`: the mean of all the bands, one value
  for each item. Same names and values as the upstream bands.
* `sunZenithAngles`, `sunAzimuthAngles`: interpolated from the 5 km sun angle
  grid. Same names and values as the upstream bands.
* `viewZenithAngles`, `viewAzimuthAngles`: the viewing angles for each pixel,
  the mean of all the bands. Not in upstream.
* `viewZenithAngles_<band>`, `viewAzimuthAngles_<band>`: the viewing angles
  for each pixel, for one band (`b01` to `b12`, `b8a`). Not in upstream.

**Detectors.** The viewing angle grid has one layer for each detector. Where
two detectors overlap on the 5 km grid, their azimuths can differ by more
than 30 degrees (odd and even detectors look in different directions), so a
mean of the detectors is not correct. Each pixel takes the grid of the
detector that sees it, from the detector footprint. The footprint of `b01`
at 60 m is used for all the bands: at 10 m one footprint is a single
10980 x 10980 chunk, and the 60 m detector is the same as the band's own
detector for more than 99% of the pixels. Each detector grid has values
only where that detector sees the ground, so the empty cells are filled from
their neighbours before the interpolation, which is necessary near the
detector edges.

**Masks.** Pixels outside the tile's angle grid are masked, so that when
the items of one date are mosaicked, each tile gives the angles only for its
own area. The viewing angles for each pixel are also masked where no detector
sees the ground (the footprint grows by 120 m at its edges, see
`get_detector_footprint`).

**Azimuths** are interpolated and averaged as unit vectors (sine and cosine),
so that values near 0 and 360 degrees give a correct result.
"""

from __future__ import annotations

import logging
import re
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from threading import Condition
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import attr
import numpy
import zarr
from cachetools import LRUCache, cached
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform
from rasterio.warp import transform_bounds
from rio_tiler.constants import WGS84_CRS
from rio_tiler.errors import RioTilerError
from rio_tiler.models import ImageData
from rio_tiler.types import BBox
from zarr.storage import ObjectStore

from titiler.openeo.bandsources.sentinel2_readers import Sentinel2AngleReader
from titiler.openeo.grid2d import Grid2D
from titiler.openeo.reader import _resolve_asset_href

from ..reader import _get_store, _has_proj, _has_spatial, _normalize_path, buffer_grid

logger = logging.getLogger(__name__)

__all__ = [
    "ANGLE_BANDS",
    "AngleBand",
    "AngleDataError",
    "ZarrSunAngleGridReader",
    "ZarrViewAngleGridReader",
    "ZarrViewAngleMeanReader",
    "angle_source_asset",
    "has_angle_bands",
    "product_root",
]

#: The EOPF Sentinel-2 collections whose products have `conditions/geometry`
#: (`sentinel-2-l2a`, `sentinel-2-l2a-new`, `sentinel-2-l1c`, ...). `search`,
#: not `fullmatch`, as upstream does for its own Sentinel-2 bands.
_S2_COLLECTION = re.compile(r"sentinel-2-l(1c|2a)")

_ZARR_MEDIA_TYPES = frozenset(
    {"application/x-zarr", "application/vnd+zarr", "application/vnd.zarr"}
)

#: The band labels of `conditions/geometry/band`, in product order.
S2_BANDS = (
    "b01",
    "b02",
    "b03",
    "b04",
    "b05",
    "b06",
    "b07",
    "b08",
    "b8a",
    "b09",
    "b10",
    "b11",
    "b12",
)


class AngleDataError(RioTilerError):
    """The product does not have the angle data that a band needs.

    Not a `ValueError`: `STACReader.part` changes a `ValueError` from its
    assets into `TileOutsideBounds` ("no data"), which would hide this error.
    """


_GEOMETRY = "conditions/geometry"
_FOOTPRINT = "conditions/mask/detector_footprint"

#: The product is read again only when it is not in these caches. The angle
#: arrays are small (less than 1 MB); a 60 m footprint is about 3.3 MB.
_ANGLES_CACHE_SIZE = 64
_FOOTPRINT_CACHE_SIZE = 16

#: `condition`: concurrent misses for one product wait for the first load
#: (a read of several angle bands runs them in parallel threads), as upstream
#: `get_tile_metadata` does for `MTD_TL.xml`.
_angles_cache: LRUCache = LRUCache(maxsize=_ANGLES_CACHE_SIZE)
_footprint_cache: LRUCache = LRUCache(maxsize=_FOOTPRINT_CACHE_SIZE)

#: Footprint pixels (60 m) added at the detector edges, see
#: `get_detector_footprint`.
_FOOTPRINT_GROWTH = 2


def _is_zarr(media_type: Any) -> bool:
    if not isinstance(media_type, str):
        return False
    return media_type.split(";")[0].strip() in _ZARR_MEDIA_TYPES


def _is_s2_collection(collection_id: Any) -> bool:
    return isinstance(collection_id, str) and bool(_S2_COLLECTION.search(collection_id))


def product_root(href: Any) -> str | None:
    """The href of the Zarr product that holds ``href``, or None.

    Asset hrefs point into the product (`<root>.zarr/measurements/reflectance`)
    or at its root (`<root>.zarr`, `<root>.zarr/`).
    """
    if not isinstance(href, str):
        return None
    # Only the path: a query (e.g. a signature, `?sv=...&sig=...`) and a
    # fragment stay on the root.
    parts = urlsplit(href)
    match = re.match(r"^(.+?\.zarr)(?:/|$)", parts.path)
    if not match:
        return None
    return urlunsplit(parts._replace(path=match.group(1)))


def has_angle_bands(
    collection_id: str, assets: Iterable[tuple[str | None, Iterable[str] | None]]
) -> bool:
    """True when items of this collection give the angle bands.

    ``assets`` are ``(media_type, roles)`` pairs, from a collection's
    ``item_assets`` or from an item's ``assets``.
    """
    if not _is_s2_collection(collection_id):
        return False
    return any(_is_zarr(media) and "data" in (roles or ()) for media, roles in assets)


def angle_source_asset(collection_id: str, assets: Mapping[str, Any]) -> str | None:
    """The key of the item asset whose product gives the angle bands, or None.

    ``assets`` maps asset keys to `pystac.Asset` objects. `reflectance` is
    preferred, then the first Zarr data asset in key order. The hrefs are
    resolved as for the reflectance read (`_resolve_asset_href`): a relative
    href such as `measurements/reflectance`, from an item in the product, is
    in a Zarr product only after the resolution.
    """
    if not _is_s2_collection(collection_id):
        return None
    candidates = [
        key
        for key, asset in assets.items()
        if _is_zarr(asset.media_type)
        and "data" in (asset.roles or ())
        and product_root(_resolve_asset_href(asset))
    ]
    if not candidates:
        return None
    return "reflectance" if "reflectance" in candidates else sorted(candidates)[0]


# --------------------------------------------------------------------------
# Product arrays


@dataclass(frozen=True)
class AngleGrids:
    """The `conditions/geometry` arrays of one product.

    The grid axes are `lines` (metres south of the first grid row) and
    `pixels` (metres east of the first grid column), both ascending, as
    `Grid2D` needs. Row 0 of each grid is the north row.
    """

    crs: CRS
    ulx: float
    uly: float
    lines: numpy.ndarray
    pixels: numpy.ndarray
    #: (2, rows, cols): zenith, azimuth.
    sun: numpy.ndarray
    #: (bands, 2): zenith, azimuth.
    mean_view: numpy.ndarray
    #: (bands, detectors, 2, rows, cols), NaN where a detector sees nothing.
    view: numpy.ndarray
    bands: tuple[str, ...]
    #: Detector numbers, the values of the footprint (e.g. `d09` -> 9).
    detectors: tuple[int, ...]

    def inside(self, lines: numpy.ndarray, pixels: numpy.ndarray) -> numpy.ndarray:
        """True where a point is inside the angle grid."""
        return (
            (lines >= 0)
            & (lines <= self.lines[-1])
            & (pixels >= 0)
            & (pixels <= self.pixels[-1])
        )


@dataclass(frozen=True)
class DetectorFootprint:
    """The detector number of each footprint pixel (0: no detector)."""

    ids: numpy.ndarray
    #: Centre of the first pixel, and the pixel steps (`dy` is negative).
    x0: float
    y0: float
    dx: float
    dy: float

    def sample(self, xs: numpy.ndarray, ys: numpy.ndarray) -> numpy.ndarray:
        """The detector number at each point (nearest pixel), 0 outside."""
        cols = numpy.floor((xs - self.x0) / self.dx + 0.5).astype("int64")
        rows = numpy.floor((ys - self.y0) / self.dy + 0.5).astype("int64")
        nrows, ncols = self.ids.shape
        inside = (rows >= 0) & (rows < nrows) & (cols >= 0) & (cols < ncols)
        out = numpy.zeros(xs.shape, dtype=self.ids.dtype)
        out[inside] = self.ids[rows[inside], cols[inside]]
        return out


def _open_product(root: str) -> zarr.Group:
    store = ObjectStore(store=_get_store(_normalize_path(root)), read_only=True)
    return zarr.open_group(store, mode="r")


def has_geozarr_conventions(group: zarr.Group) -> bool:
    """True when ``group`` declares the `proj` and `spatial` conventions.

    Then `GeoZarrReader` can read it (see `titiler.eopf.reader._get_groups`).
    """
    conventions = group.attrs.get("zarr_conventions") or []
    if not isinstance(conventions, list) or not all(
        isinstance(c, dict) and "uuid" in c for c in conventions
    ):
        return False
    return _has_spatial(conventions) and _has_proj(conventions)


def _product_crs(root: zarr.Group) -> CRS:
    """The CRS of the product's tile grid.

    `conditions/geometry` has no CRS attribute. The root `proj:code` is not
    the grid CRS: it is the CRS of the geographic root `spatial:bbox`
    (EPSG:4326). The GeoZarr `proj:code` of `measurements/reflectance` (or of
    the 60 m footprint group) is the tile CRS.

    EOPF-Explorer/data-model#346 asks for the `proj` and `spatial`
    conventions on `conditions/geometry`. With them, read the sun angles and
    the footprint with `GeoZarrReader`, and remove this function.
    """
    for path in ("measurements/reflectance", f"{_FOOTPRINT}/r60m"):
        group = _group(root, path)
        if group is not None and (code := group.attrs.get("proj:code")):
            return CRS.from_user_input(code)
    raise AngleDataError(
        "Cannot find the CRS of the product: no proj:code attribute on "
        f"measurements/reflectance or {_FOOTPRINT}/r60m"
    )


def _group(parent: zarr.Group, path: str) -> zarr.Group | None:
    """The group at ``path``, or None."""
    try:
        node = parent[path]
    except KeyError:
        return None
    return node if isinstance(node, zarr.Group) else None


def _read(group: zarr.Group, name: str, dtype: str | None = None) -> numpy.ndarray:
    """The values of the array ``name`` of ``group``."""
    try:
        node = group[name]
    except KeyError:
        node = None
    if not isinstance(node, zarr.Array):
        raise AngleDataError(f"Group {group.path!r} has no array {name!r}")
    return numpy.asarray(node[...], dtype=dtype)


def _labels(group: zarr.Group, name: str) -> tuple[str, ...]:
    """The labels of a coordinate array, as text.

    Some products store them as text, others as bytes (`b'b04'`).
    """
    return tuple(
        v.decode() if isinstance(v, bytes) else str(v)
        for v in _read(group, name).ravel()
    )


def _detector_number(label: str) -> int:
    digits = re.sub(r"\D", "", label)
    if not digits:
        raise AngleDataError(f"Detector label {label!r} has no number")
    return int(digits)


@cached(_angles_cache, condition=Condition())
def get_angle_grids(root: str) -> AngleGrids:
    """Read the `conditions/geometry` arrays of the product at ``root``.

    TEMPORARY, see the module docstring (EOPF-Explorer/data-model#346).
    """
    product = _open_product(root)
    geometry = _group(product, _GEOMETRY)
    if geometry is None:
        raise AngleDataError(f"Product {root} has no {_GEOMETRY} group")
    if has_geozarr_conventions(geometry):
        # Logged one time for each product (this function is cached).
        logger.warning(
            "%s/%s has the GeoZarr proj and spatial conventions: read it with "
            "GeoZarrReader and remove the temporary direct read in %s "
            "(EOPF-Explorer/data-model#346).",
            root,
            _GEOMETRY,
            __name__,
        )

    xs = _read(geometry, "x", "f8")
    ys = _read(geometry, "y", "f8")
    sun = _read(geometry, "sun_angles", "f8")
    view = _read(geometry, "viewing_incidence_angles", "f8")
    mean_view = _read(geometry, "mean_viewing_incidence_angles", "f8")

    angles = _labels(geometry, "angle")
    if angles != ("zenith", "azimuth"):
        raise AngleDataError(f"Unexpected angle labels {angles} in {root}")

    # Make the grid axes ascending: x to the east, rows to the south.
    if xs[0] > xs[-1]:
        xs, sun, view = xs[::-1], sun[..., ::-1], view[..., ::-1]
    if ys[0] < ys[-1]:
        ys, sun, view = ys[::-1], sun[..., ::-1, :], view[..., ::-1, :]

    return AngleGrids(
        crs=_product_crs(product),
        ulx=float(xs[0]),
        uly=float(ys[0]),
        lines=ys[0] - ys,
        pixels=xs - xs[0],
        sun=sun,
        mean_view=mean_view,
        view=view,
        bands=_labels(geometry, "band"),
        detectors=tuple(_detector_number(d) for d in _labels(geometry, "detector")),
    )


def _grow_footprint(ids: numpy.ndarray, pixels: int) -> numpy.ndarray:
    """Give each empty (0) pixel near a detector that detector's number.

    One pixel ring for each step. A pixel near two detectors takes the higher
    number; both grids have values there.
    """
    out = ids.copy()
    rows, cols = out.shape
    for _ in range(pixels):
        empty = out == 0
        if not empty.any():
            break
        padded = numpy.pad(out, 1)
        nearest = numpy.max(
            [
                padded[1 + dy : 1 + dy + rows, 1 + dx : 1 + dx + cols]
                for dy in (-1, 0, 1)
                for dx in (-1, 0, 1)
            ],
            axis=0,
        )
        out = numpy.where(empty, nearest, out)
    return out


@cached(_footprint_cache, condition=Condition())
def get_detector_footprint(root: str) -> DetectorFootprint:
    """Read the 60 m detector footprint of the product at ``root``.

    The footprint grows by `_FOOTPRINT_GROWTH` pixels at its edges: the swath
    edge of `b01` is not exactly the edge of the other bands, and without
    this, pixels at the edge of a band's data would have no viewing angle
    (measured on live EOPF products: up to 0.5% of the `b04` data pixels with
    no growth, none with 2 pixels).
    """
    product = _open_product(root)
    for path in (f"{_FOOTPRINT}/r60m", f"{_FOOTPRINT}/r20m", f"{_FOOTPRINT}/r10m"):
        group = _group(product, path)
        if group is None:
            continue
        arrays = set(group.array_keys()) - {"x", "y", "spatial_ref"}
        names = [n for n in ("b01", "b09", "b10") if n in arrays] or sorted(arrays)
        if not names:
            continue
        xs = _read(group, "x", "f8")
        ys = _read(group, "y", "f8")
        return DetectorFootprint(
            ids=_grow_footprint(_read(group, names[0]), _FOOTPRINT_GROWTH),
            x0=float(xs[0]),
            y0=float(ys[0]),
            dx=float(xs[1] - xs[0]),
            dy=float(ys[1] - ys[0]),
        )
    raise AngleDataError(f"Product {root} has no {_FOOTPRINT} array")


# --------------------------------------------------------------------------
# Calculation


def _nanmean(values: numpy.ndarray, axis: int) -> numpy.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return numpy.nanmean(values, axis=axis)


def _fill_nan(grid: numpy.ndarray) -> numpy.ndarray:
    """Fill NaN cells from their valid neighbours, one ring at a time.

    A grid with no valid cell stays NaN.
    """
    out = grid.copy()
    rows, cols = out.shape
    offsets = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]
    for _ in range(max(rows, cols)):
        missing = numpy.isnan(out)
        if not missing.any() or missing.all():
            break
        padded = numpy.pad(out, 1, constant_values=numpy.nan)
        neighbours = numpy.stack(
            [
                padded[1 + dy : 1 + dy + rows, 1 + dx : 1 + dx + cols]
                for dy, dx in offsets
            ]
        )
        fill = _nanmean(neighbours, axis=0)
        out = numpy.where(missing & ~numpy.isnan(fill), fill, out)
    return out


def _azimuth(sin: numpy.ndarray, cos: numpy.ndarray) -> numpy.ndarray:
    result = numpy.degrees(numpy.arctan2(sin, cos)) % 360.0
    # A result just below 0 can round to 360.0; both are the same angle.
    return numpy.where(result == 360.0, 0.0, result)


def _circular_mean(angles_deg: numpy.ndarray) -> float:
    radians = numpy.radians(angles_deg[~numpy.isnan(angles_deg)])
    sin = numpy.asarray(numpy.mean(numpy.sin(radians)))
    cos = numpy.asarray(numpy.mean(numpy.cos(radians)))
    return float(_azimuth(sin, cos))


def _destination_grid(
    bbox: BBox,
    dst_crs: Any,
    bounds_crs: Any,
    width: int | None,
    height: int | None,
    buffer: float | None,
) -> tuple[BBox, CRS, int, int]:
    """The output grid: the same as `GeoZarrReader.part` gives for the
    reflectance in the same read, so that the bands of the cube align.

    The buffer uses the same function (`buffer_grid`) as `GeoZarrReader`.
    """
    # `GeoZarrReader` without a size uses the native resolution of the data,
    # which these readers do not know: a default here would give a grid
    # different from the other bands. openEO `load_collection` always gives
    # both (`_estimate_output_dimensions`).
    if width is None or height is None:
        raise AngleDataError(
            "The angle bands need the output width and height; "
            f"got width={width}, height={height}"
        )
    width, height = int(width), int(height)

    dst_crs = CRS.from_user_input(dst_crs or bounds_crs)
    if bounds_crs and CRS.from_user_input(bounds_crs) != dst_crs:
        bbox = transform_bounds(bounds_crs, dst_crs, *bbox, densify_pts=21)

    if buffer:
        bbox, width, height = buffer_grid(tuple(bbox), width, height, buffer)  # type: ignore[arg-type]

    return tuple(bbox), dst_crs, width, height  # type: ignore[return-value]


def _tile_coordinates(
    bbox: BBox, width: int, height: int, dst_crs: CRS, tile_crs: CRS
) -> tuple[numpy.ndarray, numpy.ndarray]:
    """The centre of each output pixel, in the tile CRS, as (height, width)."""
    cols = (numpy.arange(width) + 0.5) * (bbox[2] - bbox[0]) / width + bbox[0]
    rows = bbox[3] - (numpy.arange(height) + 0.5) * (bbox[3] - bbox[1]) / height
    xs, ys = numpy.meshgrid(cols, rows)
    if dst_crs != tile_crs:
        txs, tys = warp_transform(dst_crs, tile_crs, xs.ravel(), ys.ravel())
        xs = numpy.asarray(txs, dtype="f8").reshape(height, width)
        ys = numpy.asarray(tys, dtype="f8").reshape(height, width)
    return xs, ys


# --------------------------------------------------------------------------
# Readers


@attr.s
class _ZarrAngleReader(Sentinel2AngleReader):
    """Base of the angle readers. ``input`` is the product root href.

    Uses upstream `Sentinel2AngleReader` for its options (`quantity`, and the
    options that `SimpleSTACReader` gives to every derived band) and for the
    methods that a derived band does not support. Only `part()` is replaced,
    because the upstream one reads `MTD_TL.xml`.
    """

    #: One band label (e.g. `b04`), or None for the mean of all the bands.
    band: str | None = attr.ib(default=None, kw_only=True)

    def part(
        self,
        bbox: BBox,
        dst_crs: Any | None = None,
        bounds_crs: Any = WGS84_CRS,
        width: int | None = None,
        height: int | None = None,
        buffer: float | None = None,
        **kwargs: Any,
    ) -> ImageData:
        """Calculate the band at the centre of each output pixel."""
        if self.quantity not in ("zenith", "azimuth"):
            raise AngleDataError(
                f"{type(self).__name__} requires quantity 'zenith' or 'azimuth', "
                f"got {self.quantity!r}"
            )

        bbox, dst_crs, width, height = _destination_grid(
            bbox, dst_crs, bounds_crs, width, height, buffer
        )
        grids = get_angle_grids(self.input)
        xs, ys = _tile_coordinates(bbox, width, height, dst_crs, grids.crs)

        values = self._evaluate_grid(grids, xs, ys)
        mask = numpy.isnan(values)
        array = numpy.ma.MaskedArray(
            values[numpy.newaxis].astype("float32"), mask=mask[numpy.newaxis]
        )
        return ImageData(array, crs=dst_crs, bounds=bbox)

    def _evaluate_grid(
        self, grids: AngleGrids, xs: numpy.ndarray, ys: numpy.ndarray
    ) -> numpy.ndarray:
        """The band values at the points (tile CRS), NaN where not defined."""
        raise NotImplementedError


@attr.s
class ZarrViewAngleMeanReader(_ZarrAngleReader):
    """`viewZenithMean`/`viewAzimuthMean`: one value for each item.

    The mean of `mean_viewing_incidence_angles` over all the bands, as
    upstream calculates it from `Mean_Viewing_Incidence_Angle_List`.
    """

    def _evaluate_grid(self, grids, xs, ys):
        column = grids.mean_view[:, 0 if self.quantity == "zenith" else 1]
        if self.quantity == "zenith":
            value = float(numpy.nanmean(column))
        else:
            value = _circular_mean(column)
        inside = grids.inside(grids.uly - ys, xs - grids.ulx)
        return numpy.where(inside, value, numpy.nan)


@attr.s
class ZarrSunAngleGridReader(_ZarrAngleReader):
    """`sunZenithAngles`/`sunAzimuthAngles`: bilinear from `sun_angles`."""

    def _evaluate_grid(self, grids, xs, ys):
        lines, pixels = grids.uly - ys, xs - grids.ulx
        zenith, azimuth = grids.sun[0], grids.sun[1]
        if self.quantity == "zenith":
            grid = Grid2D(grids.lines, grids.pixels, {"v": zenith})
            values = grid.interp("v", lines, pixels)
        else:
            rad = numpy.radians(azimuth)
            grid = Grid2D(
                grids.lines,
                grids.pixels,
                {"sin": numpy.sin(rad), "cos": numpy.cos(rad)},
            )
            values = _azimuth(
                grid.interp("sin", lines, pixels), grid.interp("cos", lines, pixels)
            )
        return numpy.where(grids.inside(lines, pixels), values, numpy.nan)


@attr.s
class ZarrViewAngleGridReader(_ZarrAngleReader):
    """`viewZenithAngles[_<band>]`/`viewAzimuthAngles[_<band>]`: per pixel.

    Bilinear from the `viewing_incidence_angles` grid of the detector that
    sees each pixel. See the module docstring.
    """

    def _detector_grids(self, grids: AngleGrids) -> numpy.ndarray:
        """(detectors, 3, rows, cols): zenith, sin(azimuth), cos(azimuth)."""
        view = grids.view
        if self.band is not None:
            if self.band not in grids.bands:
                raise AngleDataError(
                    f"Band {self.band!r} is not in the product's angle bands "
                    f"{list(grids.bands)}"
                )
            view = view[[grids.bands.index(self.band)]]

        rad = numpy.radians(view[:, :, 1])
        # Mean over the bands (one band when `band` is set), for each detector.
        stacked = numpy.stack(
            [
                _nanmean(view[:, :, 0], axis=0),
                _nanmean(numpy.sin(rad), axis=0),
                _nanmean(numpy.cos(rad), axis=0),
            ],
            axis=1,
        )
        return numpy.stack(
            [
                numpy.stack([_fill_nan(stacked[d, q]) for q in range(3)])
                for d in range(stacked.shape[0])
            ]
        )

    def _evaluate_grid(self, grids, xs, ys):
        footprint = get_detector_footprint(self.input)
        detector = footprint.sample(xs, ys)
        lines, pixels = grids.uly - ys, xs - grids.ulx
        detector_grids = self._detector_grids(grids)

        values = numpy.full(xs.shape, numpy.nan)
        for index, number in enumerate(grids.detectors):
            selected = detector == number
            if not selected.any():
                continue
            zenith, sin, cos = detector_grids[index]
            grid = Grid2D(
                grids.lines, grids.pixels, {"zenith": zenith, "sin": sin, "cos": cos}
            )
            line, pixel = lines[selected], pixels[selected]
            if self.quantity == "zenith":
                values[selected] = grid.interp("zenith", line, pixel)
            else:
                values[selected] = _azimuth(
                    grid.interp("sin", line, pixel), grid.interp("cos", line, pixel)
                )
        return values


# --------------------------------------------------------------------------
# Band registry


@dataclass(frozen=True)
class AngleBand:
    """How to read one angle band."""

    reader: type[_ZarrAngleReader]
    quantity: str
    band: str | None
    description: str


def _angle_bands() -> dict[str, AngleBand]:
    bands: dict[str, AngleBand] = {}
    for quantity in ("zenith", "azimuth"):
        name = quantity.capitalize()
        bands[f"view{name}Mean"] = AngleBand(
            ZarrViewAngleMeanReader,
            quantity,
            None,
            f"Mean viewing {quantity} angle (degrees) of all the bands, from "
            f"{_GEOMETRY}/mean_viewing_incidence_angles. One value for each item.",
        )
        bands[f"sun{name}Angles"] = AngleBand(
            ZarrSunAngleGridReader,
            quantity,
            None,
            f"Sun {quantity} angle (degrees), interpolated from the 5 km grid in "
            f"{_GEOMETRY}/sun_angles.",
        )
        bands[f"view{name}Angles"] = AngleBand(
            ZarrViewAngleGridReader,
            quantity,
            None,
            f"Viewing {quantity} angle (degrees) for each pixel, mean of all the "
            f"bands, interpolated from the 5 km grid of the pixel's detector in "
            f"{_GEOMETRY}/viewing_incidence_angles.",
        )
        for band in S2_BANDS:
            bands[f"view{name}Angles_{band}"] = AngleBand(
                ZarrViewAngleGridReader,
                quantity,
                band,
                f"Viewing {quantity} angle (degrees) of band {band} for each pixel, "
                f"interpolated from the 5 km grid of the pixel's detector in "
                f"{_GEOMETRY}/viewing_incidence_angles.",
            )
    return bands


#: Band name -> how to read it.
ANGLE_BANDS: dict[str, AngleBand] = _angle_bands()

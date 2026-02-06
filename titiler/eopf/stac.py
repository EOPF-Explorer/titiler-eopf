"""titiler-eopf stac backend."""

import attr

from titiler.eopf.reader import GeoZarrReader
from titiler.stacapi.backend import STACAPIBackend
from titiler.stacapi.reader import SimpleSTACReader, STACAPIReader


@attr.s
class EOPFSTACAPIReader(STACAPIReader):
    """Custom EOPF STAC Reader."""

    include_asset_types: set[str] = attr.ib(
        factory=lambda: {
            "application/vnd+zarr",
            "application/vnd+zarr; version=2; profile=multiscales",
        }
    )
    reader: type[GeoZarrReader] = attr.ib(default=GeoZarrReader)


@attr.s
class EOPFSimpleSTACReader(SimpleSTACReader):
    """Custom EOPF Simple STAC Reader."""

    reader: type[GeoZarrReader] = attr.ib(default=GeoZarrReader)


@attr.s
class EOPFSTACAPIBackend(STACAPIBackend):
    """Custom EOPF STACAPI Backend."""

    reader: type[EOPFSimpleSTACReader] = attr.ib(default=EOPFSimpleSTACReader)

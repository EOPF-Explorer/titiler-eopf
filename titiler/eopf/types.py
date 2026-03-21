"""Shared typing helpers for TiTiler-EOPF."""

from typing import Annotated

from pydantic import StringConstraints

SelDimStr = Annotated[
    str,
    StringConstraints(
        pattern=r"^[^=]+=((nearest|pad|ffill|backfill|bfill)::)?[^=]+$"
    ),
]

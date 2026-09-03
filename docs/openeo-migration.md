# titiler-eopf openEO catch-up

Status: living plan, tracking upstream as it moves. Originally audited against
`EOPF-Explorer/titiler-eopf@5cfd069` and `sentinel-hub/titiler-openeo` tags `v0.14.1`…`v0.17.0`
(first pass below, §§1–6); updated when `v0.18.0` landed (§7, at the end) — read §7 first for
what actually changed since the first pass, then the rest for the parts that are still current.
Filed as `docs/openeo-migration-0.17.md` in an earlier pass of this same doc; renamed here since
it now tracks a moving target rather than one fixed version. (Issue references elsewhere that say
`0.17.md` mean this file.)

| component | from | to (current target) |
| --- | --- | --- |
| titiler-openeo in `main` | 0.14.1 → **0.18.0** | landed, see §7 |
| titiler-openeo in production | **0.12.0** | 0.18.0 |
| titiler-eopf | 0.9.0 | — |

The openEO side of this repo had not moved since early June when this started. `main` was pinned to
titiler-openeo 0.14.1, production was still serving 0.12.0, and this repo's copies of the upstream
reader and STAC backend had drifted away from them. §§1–6 are the original plan to bump the
dependency, re-sync those copies, and follow the breaking changes downstream — written against
0.17.0 as the target. §7 records what changed once 0.18.0 shipped and updates the target.

---

## 1. State of play

### Production is further behind than this repo

`api.explorer.eopf.copernicus.eu/openeo` reports `"backend_version": "0.12.0"`. That field is
`titiler.openeo.__version__`, so the deployed image runs **titiler-openeo 0.12.0**, pinned back in
February (`7f70a41`). The repo moved to 0.14.1 in the 0.8.0 cycle (`32d265c`) and never shipped. The
real move is therefore **0.12.0 → 0.17.0** in production terms, with an un-deployed 0.14.1 step
already sitting in `main`.

The lag is **deliberate**: each step carried breaking changes and the deploy was held back rather than
break published services. That is the right frame for this whole plan — it is not a routine version
bump with some fallout, it is a deferred-breaking-change backlog being cleared in one go, and it should
be planned and communicated as a cutover. Production is currently healthy and self-consistent: both
`ndci.md` narrative services return 200 PNGs at their published zoom levels, so nothing is broken today
and there is no time pressure beyond the cost of deferring further.

It is definitely the EOPF app and not stock upstream: `load_zarr` is registered (EOPF-only) and
`load_collection` advertises the stale `options` parameter from this repo's local spec. It exposes 85
processes and is missing everything added since — `filter_temporal`, `mask`, `array_apply`,
`rename_labels`, `resample_cube_spatial`, `sar_backscatter`, logical `or`.

### 0.17.0 is on PyPI

The publish landed. Pin `titiler-openeo>=0.17,<0.18` normally — no git URL, and no collision with the
Chainguard Wolfi base in [PR #138](https://github.com/EOPF-Explorer/titiler-eopf/pull/138), which is
parked. 0.18.0 is on its way upstream and is a follow-up, not part of this move.

### What PR #99 already covers — and what it did not

[PR #99](https://github.com/EOPF-Explorer/titiler-eopf/pull/99) ("use experimental xarray-GeoZarr
Reader", merged 2026-06-03) rewrote `titiler/eopf/reader.py` — 374 lines added, 539 removed — and that
new `GeoZarrReader` is **shared** by both apps. So the openEO path already gets, for free:

- the GeoZarr V1 multiscale layout and automatic overview-level selection;
- the `ScaleOffset` zarr codec, decoded to float32 at read (this matters — see §2);
- `_FillValue`/nodata masking, the shared datatree LRU + Redis cache in `open_dataset`, and
  obstore/S3 credential handling;
- dimension selection through `sel=` and multi-band variables.

But what #99 changed *inside* `titiler/eopf/openeo/` was 5 lines in `reader.py` and 22 in
`stacapi.py`, and almost all of it was `Dict`→`dict` / `Optional[X]`→`X | None` modernisation. The one
functional change was `reader(uri, …)`→`reader(input=uri, …)`, required by rio-tiler 9.x. **The openEO
module was made to keep running against titiler v2 and the new reader; it did not absorb anything from
titiler-openeo.** That is the gap this plan closes.

### Other findings

- The pin lives in **two** places in `pyproject.toml` — the `openeo` extra and the `dev` dependency
  group. Both say `==0.14.1`.
- The openEO app runs without `TileCacheMiddleware`, unlike the main tiler. That is **deliberate** and
  out of scope here.
- Resolution is healthy: the 0.16/0.17 line resolves cleanly against current constraints (titiler-core
  2.2.1, rio-tiler 9.4.2, zarr 3.3.0, pystac 1.15.2). 0.17.0 adds two runtime deps,
  `obstore>=0.11` (already present) and `defusedxml>=0.7.1` (new).
- No parser bump needed. 0.17.0 passes a `results_cache` to `OpenEOProcessGraph.to_callable()`, and the
  already-pinned `openeo-pg-parser-networkx 2026.3.3` supports it.
- CI does exercise the openEO backend (`uv sync` installs the dev group), but only through **5 tests**
  across `test_openeo_app.py` and `test_openeo_processes.py`. They pass today. That is not enough
  coverage to land this bump safely.

---

## 2. Breaking changes

### 2.1 Already shipped, already breaking: the band notation

**Local to titiler-eopf, not an upstream change.** The GeoZarr band selector changed from
`<asset>|<band>` to `<asset>|bands=<band>`. It landed in the **0.8.0** cycle (PR #93, `958b949`), which
generalised the pipe suffix into `key=value` options — `bands=`, `variables=`, `sel=`, `bidx=`,
`expression=`. The 0.8.0 release notes never flagged it as breaking, which is why it is still
propagating.

The old form does not degrade — `_parse_asset` rejects it outright:

```text
'reflectance|b02'       -> ValueError: Invalid asset option 'b02' in 'reflectance|b02'.
                           Options must be in 'key=value' format.
'reflectance|bands=b02' -> [{'name': 'reflectance', 'bands': ['b02']}]
```

`services/eopf-explorer.json` is **partially migrated**: 66 references use the new form, **11 still use
the old one**, across two services that are broken as shipped:

| service | title | stale refs |
| --- | --- | --- |
| `811f37c5-b5a9-48af-8d2b-59ce16556306` | ndci | 8 (`reflectance\|b02` … `reflectance\|b8a`) |
| `56d93fd9-4f60-452e-b81b-6b763d98bd7e` | Test Mosaic | 3 (`reflectance\|red`, `\|green`, `\|blue`) |

Five docstrings in `titiler/eopf/openeo/stacapi.py` and the 0.4.0 changelog entry still document the
old form.

#### It is not only the option key — the asset half changed too

The band names live in the **openEO** `/collections` response
(`api.explorer.eopf.copernicus.eu/openeo/collections`), not in the STAC API behind it. They are
synthesised entirely by this repo: `_fix_collection` → `add_data_cubes_if_missing` →
`getzarrdimensions` → `get_all_band_names`. The STAC source carries none of them —
`stac.core.eopf.eodc.eu/collections/sentinel-2-l2a` has no `cube:dimensions` at all, plain
`summaries.bands` of `B01, B02, …`, and `item_assets` keys `SR_10m, SR_20m, SR_60m, AOT_10m, B01_20m,
B02_10m, …`.

That means we own the vocabulary — but it also means the vocabulary has drifted twice, not once:

| source | advertised band names | count |
| --- | --- | ---: |
| deployed (0.12.0) | `AOT_10m`, `SCL_20m`, `WVP_10m`, `reflectance&#124;b01` … | 16 |
| `main`, run against today's STAC collection | `AOT_10m`, `SCL_20m`, `B02_10m&#124;bands=B02` … | **44** |

The `bands=` key is the smaller half. The **asset** half changed too, because the STAC catalogue was
restructured from a single multi-band `reflectance` asset to per-band assets. Live items carry 22
assets and **no `reflectance` asset at all**, so `reflectance|bands=b01` is not merely old syntax — it
resolves to `self.input.assets["reflectance"]` and raises `InvalidAssetName`.

The deployed backend still advertises `reflectance|b01` because its image predates both changes — the
notation move in 0.8.0 and the STAC restructure — and was deliberately held back rather than break
published services. It is internally consistent with the catalogue it reads: both `ndci.md` services
render 200 PNGs today. So this is a clean cutover from one working vocabulary to another, not a repair
of something already broken.

Querying the live openEO `/collections` endpoint today, across all collections:

| collection | bands | old form | example |
| --- | ---: | ---: | --- |
| `sentinel-3-olci-l1-efr-staging` | 21 | **21** | `measurements\|oa01_radiance` |
| `sentinel-2-l2a` | 16 | **13** | `reflectance\|b01` |
| `sentinel-1-grd-rtc-acquisitions-staging` | 7 | **6** | `gamma0-rtc-backscatter-asc\|vh` |
| `sentinel-2-l2a-staging` | 4 | 0 | per-band assets, no pipe |
| `sentinel-1-grd-rtc-staging` | 3 | 0 | per-band assets, no pipe |
| `sentinel-2-l1c` | 1 | 0 | per-band assets, no pipe |

**40 band identifiers across three collections** are published in a form `main` rejects — in both
`cube:dimensions` and `summaries.bands`, which is exactly what openEO Studio and the openeo Python
client read to build a graph. So the exposure is not two services in a JSON file: it is *every* stored
graph and every notebook built against production since February. They all break the moment `main`
deploys.

**Decided: the new notation ships as-is. No alias, no compatibility shim.** `_parse_asset` keeps
rejecting the old form, and `main`'s derivation stays the source of truth for what a band is called.

The cost is that this is a coordinated cutover, not a rolling upgrade. Every stored graph, narrative
URL, notebook and Studio project that names a band has to be rewritten against the new vocabulary, and
because the asset half moved too, that is a rewrite rather than a search-and-replace:
`reflectance|b01` → `B01_20m|bands=B01`, and the caller has to pick the right resolution suffix, which
the old single-asset form never made them think about. The rewrite and the deploy have to land
together — there is no window in which both vocabularies work.

### 2.2 Upstream, 0.14.1 → 0.17.0

Ordered by how far the blast radius reaches.

| change | what breaks | reach |
| --- | --- | --- |
| **`raster:scale` / `raster:offset`** (PR #322) — *hazard* | Applied per band on read, on by default. **For EOPF this double-applies:** the GeoZarr store carries a `ScaleOffset` codec (`scale_factor=0.0001, add_offset=-0.1`) that `GeoZarrReader` decodes to float32, and the STAC assets advertise the *same* pair (`B04_10m`: `raster:scale 0.0001`, `raster:offset -0.1`). **Decided:** disable the flag here; real fix filed as [data-pipeline#384](https://github.com/EOPF-Explorer/data-pipeline/issues/384). | this repo — correctness |
| **`ndwi` band args** (PR #332, #333) | `nir`/`swir` retyped in the spec from `{"type":"number"}` (1-based index) to `{"type":"string","subtype":"band-name"}`, plus optional `target_band`. Integers still work at runtime, but a spec-validating client rejects them. `ndvi` was *already* band-name in 0.14.1 and on deployed 0.12.0, so only `ndwi` moves. Both gain suffix-tolerant resolution against rio-tiler's `_b<n>` labels. | studio, notebooks |
| **`save_result`, GTiff** (PR #297) | GTiff is now a data format: native dtype, all bands, real nodata — no uint8/RGB rendering. Separately, saving a multi-slice RasterStack to a single-frame format (PNG/JPEG) now **raises** instead of silently rendering one slice. | notebooks, `/result` consumers |
| **callback parameter scope** (PR #257) | A callback (`reducer`, `process`, `overlap_resolver`…) has its own scope. Outer UDP parameters must be threaded through `context`. **Good news:** a scan of all 28 graphs in `services/eopf-explorer.json` found zero occurrences of the old pattern — but user-stored and Studio-generated graphs still need auditing. | stored services, studio |
| **error codes** (PR #351) | `ProcessParameterMissing` → `ProcessParameterRequired`, status 422 → 400. `ServerError` → `Internal`. A bare `TypeError` from a process now surfaces as 400 `ProcessParameterInvalid` instead of 500. | studio, monitoring |
| **`load_collection_and_reduce`** (PR #277) | Removed. `EndpointsFactory.load_nodes_ids` now defaults to `["load_collection"]`. This repo never registered it and the deployed backend does not expose it, so nothing here breaks — but any client graph still calling it will 400. | old client graphs |
| ~~**service access control** (PR #363)~~ — *no action* | 0.17.0 made `GET /services/{id}` optional-auth plus a `ServiceAuthorizationManager` check. 0.18.0 (#373) reverts it to Bearer-only per spec. Transient churn inside the 0.17.0 window; not worth planning around. The `DELETE`/`PATCH` 403-for-non-owners part stands and is a tightening, not a break, for the narratives (which only read tiles). | — |
| `spatial_extent_*` — *deprecation* | Deprecated in favour of `bounding_box`. Still injected in 0.17.0, so no break yet, but graphs should migrate. | stored services |
| helm chart 2.0.0 (PR #267) — *ops* | Chart moved to a GHCR OCI registry; Postgres DSN became GitOps-compatible. Only relevant if `platform-deploy` consumes the upstream chart. | platform-deploy |
| `/healthz`, `/readyz` — *new, opt-in* | Upstream registers these inside `create_app()`. This repo builds its own module-level app, so it will **not** get them for free. | platform-deploy |

### 2.3 Worth having, once the bump lands

The actual reason to move: `filter_temporal`, `mask`, `array_apply`, `rename_labels`,
`resample_cube_spatial`, `sar_backscatter`, logical `or`; reference-counted eviction of process-graph
intermediates (bounded peak memory); float32 promotion for float math; streaming NDVI/NDWI; concurrent
prefetch of in-interval slices; and a pile of aggregation/temporal-axis correctness fixes.

---

## 3. Divergence from upstream inside `titiler/eopf/openeo/`

"Divergence" here means source-level, not git: `titiler/eopf/openeo/` subclasses `titiler.openeo` and, in
several places, holds hand-copied versions of upstream functions. Upstream has since moved and the copies
have not, so each one has to be re-synced by hand. Nothing here is about branches or repository forks.

This is the bulk of the effort — more than the version bump itself. **All of it is in scope.**

### 3.0 Which copies earn their keep

Every copy was diffed against its original — upstream at `v0.17.0`, or rio-tiler 9.4.2 where the original
is there. The pattern is consistent: each copy exists for a real reason, but the reason is one or two
lines and the copy is the whole function.

| copy | size vs original | what actually differs | verdict |
| --- | --- | --- | --- |
| `openeo/main.py` | 107 sig-lines, 79% verbatim upstream | EOPF backend + loaders, `load_nodes_ids`, description | **keep** — app entrypoint |
| `_reader` | 57L vs 94L | **one line** — `STACReader` instead of `SimpleSTACReader` | **drop, or minimise** |
| `STACReader.part` | 141L vs 81L | bbox pre-check, widened `allowed_exceptions`, OVH URL rewrite | **keep** — narrow the exceptions, propose the guard upstream |
| `STACReader._get_options` | 73L vs 48L | Zarr `bands`→`variables` branch, `variables`/`sel` pass-through | **keep, narrow** |
| `LoadCollection.load_collection` | 84L vs 189L | `_parse_asset(bands)` and the EOPF `_reader` — that is all | **narrow hard** |
| `processes/data/load_collection.json` | — | nothing (verified: no Zarr/notation text) | **drop** — or keep `bands.description` only |
| `stac.py::_get_asset_info` ↔ `_get_options` | two EOPF copies of one algorithm | only how media type is read (proven: 36/36 cases identical) | **deduplicate** — and fix the 2 bugs in §3.5 |

This is not a style complaint. Copying whole functions to change one line is precisely how the two live
bugs in §3.1 got in: `max_items` and the missing `items` task metadata are both upstream fixes that
landed inside functions this repo had already copied, so they never arrived. Narrowing the copies is the
fix that stops the next pair.

Two of these are worth pushing upstream rather than solving locally, because the generalisation is
small and obviously useful to any backend with a non-default reader. Both are filed as
[titiler-openeo#379](https://github.com/sentinel-hub/titiler-openeo/issues/379):

- **`_reader` should take its reader class as a parameter.** It hardcodes `SimpleSTACReader` in one
  place. With `reader_cls=SimpleSTACReader` as a keyword, this repo drops its copy entirely and uses
  `functools.partial(_reader, reader_cls=STACReader)`. Everything the copy currently loses — mask
  inheritance, item-id logging, and any future fix — comes back for free.
- **`LoadCollection` should expose its reader and asset parser as attrs fields.** It is already an
  `attrs` class with a `stac_api` field. Two more fields (`reader`, `asset_parser`) would let this repo
  set them and inherit `load_collection` instead of re-implementing 189 lines to change three.

The bbox-intersection guard in `STACReader.part` is also generic — it skips assets whose bounds do not
meet the requested bbox before opening them — and is a reasonable upstream proposal on its own.

### 3.1 `titiler/eopf/openeo/stacapi.py` — highest risk

- **The whole method is a re-organisation of upstream's** (84L vs 189L) whose only real content is
  **two** things: `_parse_asset(bands)` for the EOPF band notation, and the EOPF `_reader`. The rest —
  extracting `_validate_limits`, `_group_items_by_date`, `_build_tasks`, a ternary for `output_bbox` —
  is a restyling of code upstream also maintains, and it is where both bugs below came in. Checked line
  by line, `_validate_limits` and `_group_items_by_date` are upstream's inline logic unchanged. If
  upstream grew `reader` and `asset_parser` fields on `LoadCollection`
  ([#379](https://github.com/sentinel-hub/titiler-openeo/issues/379)), this method could be deleted
  outright.
- **One of the three "real" differences is a no-op.** `_make_mosaic_task` passes
  `allowed_exceptions=(TileOutsideBounds,)` to `mosaic_reader` — which is already rio-tiler 9.4.2's
  default for that parameter. The accompanying `EmptyMosaicError` → `TileOutsideBounds` conversion is
  real and worth keeping; the explicit tuple is not.
- **Silent 100-item cap.** `LoadCollection.load_collection` calls `_get_items(…, limit=100)` and never
  passes `max_items`. Upstream's `get_items` does `max_items = max_items or 100`, so wide temporal
  extents get truncated — exactly the bug upstream fixed in #302 by passing
  `max_items=processing_settings.max_items + 1`. Port that.
- **Task metadata is missing `items`.** 0.17.0 attaches `"items": date_items` to each task so
  `RasterStack.get_source_items()` can reach per-item STAC metadata. `_build_tasks` here does not, so
  `sar_backscatter` and anything else needing source items cannot work on this backend.
- **Resolution estimation is inert for EOPF, and this is a data gap, not a copy gap.**
  `load_collection` calls `_estimate_output_dimensions`, which reaches `_get_assets_resolutions` →
  `_get_asset_resolution`. That function needs, in order: asset-level `proj:transform`, asset-level
  `proj:shape`, or `src_dst.transform`. Checked against a live Sentinel-2 L2A item — **none of the
  three is available**:

  | source | present? |
  | --- | --- |
  | asset `proj:transform` | no — assets carry only `gsd`, `bands`, `nodata`, `data_type`, `raster:scale/offset` |
  | asset `proj:shape` | no |
  | `SimpleSTACReader.transform` | `None` — the reader resolves to `crs=EPSG:4326`, `width=height=None`, falling back to the item's WGS84 bbox |

  So every asset yields `(None, None)` and `_estimate_output_dimensions` returns the *requested* width
  and height unchanged. Measured: `1024x1024` for EOPF band names, plain asset names and old-notation
  names alike — the notation is not what breaks it. Consequences: `target_crs` and native-resolution
  preservation are inert, and mosaic-level bounds are a WGS84 approximation of a UTM grid. Identical
  upstream, so nothing to re-sync — but several 0.17.0 features assume this path works, so it is worth
  knowing they will do nothing here.

  The CRS half already works: pystac's `AssetProjectionExtension` falls back to the owning item's
  properties, so `asset_proj_ext.epsg` resolves to `32637` from the item's `proj:code` and
  `_get_asset_crs` returns `EPSG:32637`. **Only the resolution is missing**, and the assets already
  carry `gsd: 10` — in a projected, metre-based CRS, which is exactly the unit
  `_get_asset_resolution` wants. Two fixes, not exclusive: publish per-asset
  `proj:transform`/`proj:shape` from the pipeline (the standard answer), or add a `gsd` fallback
  upstream, gated on the resolved CRS being projected. Filed as
  [titiler-openeo#381](https://github.com/sentinel-hub/titiler-openeo/issues/381).
- **The whole product store is advertised as a band.** `get_all_band_names` filters `item_assets` on
  `"data" in roles` alone. Sentinel-2 L2A has an asset `product` — `application/vnd+zarr`, roles
  `["data", "metadata"]`, "The full Zarr store of the EOPF product" — which passes that filter and, having
  no `bands` metadata, is emitted as the bare band name `product`. It is 1 of the 44 names `main` would
  publish. Selecting it resolves to `GeoZarrReader` over the entire store with no `variables`, which
  raises `MissingVariables` — a `RioTilerError`, so it is neither swallowed nor mapped to a 4xx and
  surfaces as a 500. Upstream 0.17.0 added a related guard (`_ARCHIVE_MEDIA_TYPES`, for CDSE's zipped
  S1 `Product`) but it keys on media type and would not catch this one, which is a genuine Zarr
  container. Exclude container assets explicitly — the `metadata` role alongside `data` is the available
  signal.
- **`_fix_collection` drops `_add_band_summaries()`.** The override calls `_normalize_summaries` and
  `replace_bands_in_summaries_dict` only, so the new upstream derivation of `summaries.bands` from
  `item_assets` never runs.
- **Band dimension shape differs.** This repo publishes a `bands` cube dimension whose values look like
  `reflectance|bands=b04`; upstream 0.17.0 publishes a `spectral` dimension with sorted `item_assets`
  keys. openEO Studio's band parser fix
  ([openeo-studio#103](https://github.com/developmentseed/openeo-studio/pull/103)) targets the upstream
  shape. Reconcile, or the Studio band picker stays wrong for EOPF collections.

### 3.2 `titiler/eopf/openeo/reader.py` — highest risk

- **The module-level `_reader` is a stale copy** of upstream's (57L vs 94L), and **exactly one line is a
  real override**: `STACReader(item)` where upstream has `SimpleSTACReader(item)`. Everything else the
  copy does is lose something. There is no hook — upstream hardcodes the class — so the copy cannot be
  removed until upstream accepts a `reader_cls` parameter (§3.0). Three losses:
  - `_inherit_derived_band_masks` — needed for band-source/SAR bands. **Port it.**
  - Item-id and datetime logging. Upstream logs the item being read at DEBUG and names it in the retry
    warning and the final error; the copy's messages say only "RasterioIOError encountered". Across a
    mosaic of many items that is the difference between a diagnosable failure and a wall of identical
    lines. **Port it.**
  - `_apply_scale_offset` — correctly omitted, but the reasoning is narrower than the code. The
    justification (the GeoZarr `ScaleOffset` codec already applied it) holds **only for Zarr assets**;
    for a COG asset carrying `raster:scale`, upstream would apply it and this copy would not. Checked
    against a live S2 item: 20 `application/vnd+zarr` assets, one `application/zip`, one
    `application/json`, and **no non-Zarr asset carries `raster:scale`** — so the unconditional omission
    is correct for today's data. The principled shape is per-asset, and once
    [data-pipeline#384](https://github.com/EOPF-Explorer/data-pipeline/issues/384) removes the duplicated
    STAC fields the question disappears and the flag can go back on. Treat the disabled setting as a
    temporary state with an exit condition, not a permanent fork.
- **The retry loop is a shared liability, not a divergence.** Both copies use `max_retries = 10` with a
  1 s delay doubling each attempt — 511 s, about 8.5 minutes, of a blocked worker before a persistent
  `RasterioIOError` is finally re-raised. Identical upstream, so out of scope here, but worth raising
  there: with `RasterStack`'s thread pool feeding it, a dead object store can tie up workers for a long
  time.
- **0.18.0 will widen the gap again.** PR #371 adds a `signer` parameter to upstream's `_reader`, which
  this copy will have to absorb by hand. That is the concrete cost of not having `reader_cls`.
- **`OpenEOReader` arrives for free — but `_get_reader` drops derived bands.** `STACReader` overrides
  only `_get_reader`, `_get_options` and `part`; it never redefines the `reader` attribute, so after the
  bump `self.reader` *is* `OpenEOReader` (GCP warping, 204–2042 m of geolocation error at 81–86°N
  avoided) with no work. What the override does break is the other half: upstream's `_get_reader` first
  checks `self._derived_bands` and returns that band's own reader, and the EOPF version never consults
  it — so a band-source-derived band (SAR noise/calibration LUTs, S2 view/sun angles) would be read with
  `OpenEOReader` instead of its `NoiseBandReader`/`CalibrationBandReader`. The fix is one line:
  `return super()._get_reader(asset_info)` in place of `return self.reader`.
- **`STACReader.part` is a hand-copied version** of `rio_tiler.io.MultiBaseReader.part` (141L vs 81L),
  not of anything in titiler-openeo — upstream's `SimpleSTACReader` does not override `part` at all.
  Diffed against rio-tiler 9.4.2, **nothing was dropped**: `_update_statistics`, the metadata merge,
  `band_descriptions`, `asset_as_band` and the expression tail are all present, and the only rio-tiler
  lines absent are the two the copy deliberately replaces. It is a faithful superset, so there is no
  stale drift *from rio-tiler* to repair. It adds three things: a bbox-intersection pre-check that skips
  assets that cannot contribute, a widened `allowed_exceptions` plus a `ValueError` →
  `TileOutsideBounds` conversion, and the OVH URL rewrite below. The pre-check is generic and worth
  proposing upstream; until it is accepted, the copy has to stay, because the guard sits inside `part`'s
  inner `_reader` closure and cannot be added from a subclass.
- **The `allowed_exceptions` tuple is too broad, and it swallows real errors.** `part` passes
  `allowed_exceptions=(TileOutsideBounds, ValueError, IndexError)` to `multi_arrays`, one level below
  `mosaic_reader`, which allows only `(TileOutsideBounds,)`. `rio_tiler.tasks.filter_tasks` discards an
  allowed exception with nothing but `logger.info(err)`, so a genuine option error is dropped silently.
  Traced end to end for a mistyped band name on a COG asset:

  1. `_get_options` raises `ValueError: Band 'nope' not found in asset metadata`
  2. `filter_tasks` swallows it — INFO log only — and drops the asset
  3. with every asset dropped, `ImageData.create_from_list([])` raises
     `ValueError: not enough values to unpack (expected 2, got 0)` (verified)
  4. `part`'s outer handler turns that into `TileOutsideBounds("No valid data found…")`
  5. `mosaic_reader` allows `TileOutsideBounds` → `EmptyMosaicError` → converted again in
     `_make_mosaic_task`

  The user gets a generic no-data failure; the sentence naming the bad band never leaves the log. On the
  live backend this class of error already surfaces as HTTP 500. Narrow the tuple to
  `(TileOutsideBounds,)` so option errors propagate, and keep the empty-list conversion, which is a
  genuine rio-tiler wart. Note this compounds §3.5's Zarr passthrough: for a Zarr asset the typo does
  not even raise — it becomes a bogus variable name.
- **`part` also forwards derived-band `reader_options`.** `_get_derived_asset_info` puts `fetcher`,
  `quantity`, `sibling_href` and the inverse-map cache into `reader_options`, and `part` splats them
  into the reader class returned by `_get_reader`. With the `_get_reader` bug above that class is
  `OpenEOReader`, which accepts none of them — a `TypeError` rather than a working derived band. Fixing
  `_get_reader` fixes this too.
- Two incidental improvements over rio-tiler worth keeping when re-syncing: `stacklevel=2` on both
  `warnings.warn` calls (rio-tiler omits it, so its warnings point at library frames), and
  `reader(input=uri, …)` as a keyword.
- **Hard-coded OVH host rewrite.** The `https://esa-zarr-sentinel-explorer-fra… → s3://` substitution is
  already marked `TODO` in the source. 0.17.0 added `_resolve_asset_href`, which honours STAC
  `alternate` hrefs — the right home for this. Removing it is what lets `part` shrink to the two guards.
- **`STACReader._get_options` (73L vs 48L) is the one copy that is genuinely EOPF.** It adds the
  `variables`/`sel` pass-through and the Zarr branch that maps `bands` → `variables` by media type;
  upstream only knows `indexes`. But its non-Zarr `else` branch is a verbatim copy of upstream's body,
  so delegate that to `super()._get_options()` and keep only the Zarr path.

### 3.3 `titiler/eopf/openeo/processes/data/load_collection.json` — user-visible

This local copy shadows upstream's (the EOPF spec dict is merged last), and it is older than 0.14.1. It
advertises an `options` parameter the implementation does not accept, and omits `tile_buffer`,
`target_crs`, and `width`'s default of 1024 — all three of which the EOPF implementation *does* support.
Confirmed against production, which publishes exactly
`['id','spatial_extent','temporal_extent','bands','properties','width','height','options']`.

Compared parameter by parameter against the 0.17.0 spec and against the implementation's own signature:

| | EOPF spec | upstream spec | implementation accepts |
| --- | --- | --- | --- |
| `options` | declared | — | **no** |
| `target_crs` | — | declared | **yes** |
| `tile_buffer` | — | declared | **yes** |
| `height` default | unset | `1024` | defaults to `1024` |

Upstream's spec matches the implementation **exactly** — every declared parameter is accepted, every
accepted parameter is declared. The EOPF copy is wrong in both directions. And nothing in it is
EOPF-specific: searched for `Zarr`, `GeoZarr`, `variables` and `|bands=`, and there is **no mention of
any of them**. So **delete the file**; `PROCESS_SPECIFICATIONS = {**OpenEOSpecifications,
**EOPF_OPENEO_SPECIFICATIONS}` then falls through to upstream's. `load_zarr.json` in the same directory
is genuinely EOPF-only and stays.

One thing deleting it does *not* fix: neither spec documents the `<asset>|bands=<band>` notation.
Upstream's `bands` description talks about unique names and common names, which is not what this
backend expects — a user following it passes `B04` and gets a `ValueError`. With §2.1 shipping the new
notation without a shim, `GET /processes` is exactly where someone will look for the new form. Whether
to keep a **one-key** override customising only `bands.description`, or delete the file outright and
document the notation elsewhere, is tracked as
[titiler-eopf#142](https://github.com/EOPF-Explorer/titiler-eopf/issues/142).

### 3.4 `titiler/eopf/openeo/main.py` — moderate

- **Not a copy to remove.** This is the application entrypoint: assembling your own app from the
  library's pieces is the intended use, and the 79% overlap with upstream's `create_app()` is what an
  app wiring the same middleware looks like. Left as is. The two items below are content, not
  duplication.
- No `/healthz` or `/readyz`.
- `process_registry["load_collection"] = process_registry["load_collection"] = Process(…)` is a double
  assignment; upstream cleaned up the same line in 0.17.0.

### 3.5 One algorithm, two EOPF copies

`titiler/eopf/stac.py::EOPFSimpleSTACReader._get_asset_info` (the main app's STACAPI mosaic reader) and
`titiler/eopf/openeo/reader.py::STACReader._get_options` (the openEO one) both carry the same
Zarr `bands` → `variables` mapping.

#### The two base classes are legitimately different

Worth settling first, because it decides what can be shared. Both extend `MultiBaseReader`, but they are
not interchangeable:

| aspect | `titiler.stacapi.SimpleSTACReader` | `titiler.openeo.SimpleSTACReader` |
| --- | --- | --- |
| `input` | `Item` — a **TypedDict** (plain JSON) | `pystac.Item` |
| default `reader` | rio-tiler `Reader` | `OpenEOReader` (GCP warping) |
| methods | `__attrs_post_init__` (13L), `_get_asset_info` (89L) | + `_get_reader`, `_get_options`, `_get_derived_asset_info`, `read`; post-init is 58L |
| band sources | — | `_derived_bands`, `band_source_fetcher`, inverse-map cache + lock |
| SAR `proj:*` guard | — | `_item_has_untrustworthy_proj` |

The openEO base brings four things the stacapi one does not: band-source derivation, `OpenEOReader`, the
untrustworthy-`proj:*` SAR guard, and the `_get_options`/`_get_asset_info` split. Each app is on the
right base. **The duplication is structural, forced by the two upstreams** — stacapi has no
`_get_options` hook at all, so the EOPF subclass had to inline the band logic inside `_get_asset_info`
and read `asset_info["type"]`, while the openEO subclass overrides `_get_options` and reads
`metadata.media_type`. The *method* cannot be shared; only the algorithm can.

#### The algorithm is provably the same

Both paths were run over 36 cases — three Zarr media types plus a parameterised one
(`application/vnd+zarr; version=3`), a COG type and `None`; bands matched by `name`, by
`eo:common_name`, several at once, an unknown name, an unnamed band, and missing band metadata. **Zero
divergences.** The extraction is safe: one free function taking `(media_type, bands, stac_bands)`, in
`titiler/eopf/stac.py` — which `titiler/eopf/openeo/stacapi.py` already imports (`_parse_asset`), so it
adds no coupling that is not already there. It is also the natural home for the §2.1 band vocabulary.

#### Two bugs the comparison exposed

Identical in both copies, and EOPF-only — upstream has no Zarr branch, so these are ours:

- **An unknown band name is silently accepted for Zarr assets.** The Zarr branch ends in
  `common_to_variable.get(v, v)`, a passthrough default, so `bands=["nope"]` yields
  `variables=["nope"]` and fails much later inside `GeoZarrReader`, or produces the wrong band. The COG
  branch raises `ValueError: Band 'nope' not found in asset metadata` for the same input. The
  passthrough may have been meant to allow raw variable names, but `_parse_asset` already has an
  explicit `variables=` option for that, so the asymmetry looks accidental. Making it strict does not
  break the current vocabulary — every advertised band name is present in its asset's `bands` metadata.
- **Band metadata without a `name` raises `KeyError`.** The Zarr comprehension subscripts `b["name"]`
  where the COG branch uses `b.get("name") or str(ix)`. A `KeyError` is neither `ValueError` nor
  `TypeError`, so 0.17.0's `general_exception_handler` returns **500 `Internal`** where the COG path
  would return 400.

Fix both while extracting — one helper means fixing them once.

### 3.6 `tests/fixtures/item.json` — test realism

The fixture models a single `reflectance` asset carrying a `bands` list. The live catalogue publishes
both grouped assets (`SR_10m`, `SR_20m`, `SR_60m`) *and* per-band assets (`B04_10m`, `AOT_10m`,
`SCL_20m`) with their own `raster:scale`, `nodata` and `data_type`. The two shapes drive different
branches of `_get_options` and of the band-summary derivation, and only one is under test.

### 3.7 `pyproject.toml` · `Dockerfile` — mechanical

- Move both the `openeo` extra and the `dev` group to `titiler-openeo>=0.17,<0.18`. A range rather than
  `==`, so patch fixes flow.
- Add the `boto3` extra if the SAR annotation fetcher will run under AWS profile/SSO credentials.
  `boto3` is already present via the `cache` extra and dev group.
- The Dockerfile installs `".[cache,openeo]"` — no change needed, but rebuild to pick up `defusedxml`.

---

## 4. Sequence

Each phase lands as its own PR and stays green on its own. Phases 2 and 3 are separated deliberately:
the mechanical bump should not be entangled with the re-sync of the copied code, or a bisect later will
be useless.

### Phase 0 — inventory every band reference

Scope: titiler-eopf · narratives · openeo-studio · blocks the deploy, not the code

The new notation ships without a shim, so nothing that names a band survives the deploy untouched. Before
anything is cut over, the full set has to be known:

- `services/eopf-explorer.json` — 11 stale references across `811f37c5…` (ndci) and `56d93fd9…`
  (Test Mosaic); the other 66 use `bands=` but still name the `reflectance` asset, so they need the
  asset half rewritten too.
- The deployed service store — needs a bearer token to enumerate. This is the unknown that sizes the
  cutover.
- `narratives/ndci.md` — four service IDs. These are updated in place via `PATCH /services/{id}`, which
  merges a new `process` into the existing record and preserves the ID, so **no narrative link changes**.
- openEO Studio sample scenes and any saved projects.
- Notebooks under `docs/` and in the narratives repo.

Produce the old → new mapping once, from `get_all_band_names()` run against the current STAC collection,
and drive every rewrite from that table rather than hand-editing. It is the same table §3 needs for the
`bands` → `spectral` dimension reconciliation, so build it once.

#### The services file is not the migration mechanism

`services/eopf-explorer.json` looks like a seed with stable IDs. It is neither. `default_services_file`
is read lazily inside `GET /services`, only when the *calling user* has zero services, and it does
`del service_config["id"]` before `add_service` — so the UUID keys in the file are decorative and fresh
IDs are minted. Editing the file changes nothing for any user who already has services, which is
everyone in production. Consistent with that, none of the three service IDs in `narratives/ndci.md`
appear in the file at all; they exist only in the deployed store.

So the cutover runs against the store, via `PATCH /services/{id}` per service. Two constraints:

- **Owner-only.** 0.17.0 added `if existing.get("user_id") != user.user_id: raise 403` to both `PATCH`
  and `DELETE`. The migration must authenticate as the owning user of each service, or write to the
  store directly. Worth confirming who owns the narrative services before the cutover window opens.
- The file still wants fixing for new deployments and for the two broken entries, but treat that as
  housekeeping, not as the migration.

### Phase 1 — raise the floor before touching anything

Scope: titiler-eopf · tests only

Five tests is not a safety net for this. Before the bump, add coverage for what the migration will move:
`load_collection` item paging and the items cap, band/variable resolution through `_parse_asset`, the
cube dimensions and `summaries.bands` emitted for an EOPF collection, and at least one end-to-end XYZ
tile render per shipped default service shape. These tests are what tell you whether phase 3 changed
pixels.

### Phase 2 — bump the pin, fix only what fails

Scope: titiler-eopf · mechanical

Move both pins to `>=0.17,<0.18`, rebuild the lock, run the suite. Expect fallout in the renamed error
classes (`ProcessParameterMissing`) and in anything asserting on GTiff output. Rebase
`load_collection.json` on the 0.17.0 spec in the same PR, since it is a straight file replacement plus
the EOPF-specific bits. Set `TITILER_OPENEO_PROCESSING_APPLY_SCALE_OFFSET=false` in the same change,
with a comment pointing at the GeoZarr `ScaleOffset` codec — this is the one setting that silently
corrupts values if left at its new default.

### Phase 3 — re-sync the copied upstream code

Scope: titiler-eopf · the real work

Two things at once, and the order matters. **First narrow the copies** per the §3.0 verdicts — delete
`load_collection.json`, delegate `_get_options`'s
non-Zarr branch to `super()`, strip `part` down to its two guards, extract the shared Zarr band helper.
**Then apply the fixes** — `max_items`, task `items` metadata, `_add_band_summaries`, the band-dimension
shape, mask inheritance in `_reader`, `_get_reader`'s derived-band fallthrough, the asset-href rewrite, plus health
endpoints in `main.py` — plus the
band-notation cleanup: migrate the 11 stale references in `services/eopf-explorer.json` and fix the five
docstrings that still document `asset|band`.

Narrowing first is what makes the fixes small: `max_items` and the missing `items` metadata are one-line
changes against upstream's `load_collection`, and only became hand-ports because a 189-line function had
been copied to change three lines of it. PR #99 showed the same cost from the other direction.

### Phase 4 — verify against real data, then compare pixels

Scope: titiler-eopf · staging

Replay each of the 28 default services against staging and diff the rendered tiles against production.
With scale/offset disabled the expectation is *no* pixel change, which makes this a strong check: any
difference is either a fix you meant or a regression you did not. Two of the 28 will not render at all
until their band notation is migrated. Re-check the `ndci` and `ndvi` narrative tile URLs specifically,
since those are the published ones.

### Phase 5 — ship downstream

Scope: narratives · openeo-studio · platform-deploy

Only once tile output is settled. Sequence matters: the narratives reference service IDs that must exist
and render correctly before their docs are updated.

---

## 5. Downstream follow-ups

### EOPF-Explorer/narratives

Four documents, of which `ndci.md` carries the openEO tile URLs — four distinct service IDs, each with
JSON-encoded `?time=[…]` query parameters and, in one case, a `color_formula`.

1. **Do their graphs still use the old `asset|band` notation?** Two of the 28 services in this repo do,
   and they fail outright. The narratives point at graphs in the deployed store, which nobody has
   checked. Do this first — it may already be broken, independently of the bump.
2. With `apply_scale_offset` off, tile values should be unchanged — so the gamma/sigmoidal/saturation
   values in `ndci.md` stay valid. Confirm by diffing tiles, not by assuming.
3. Graphs are rewritten in place with `PATCH /services/{id}`, so service IDs are stable and the
   published links keep working. The narratives need no edit for this migration — only verification
   that their tiles still render afterwards.
4. The `?time=` query-parameter form itself is unchanged in 0.17.0, so those URLs stay valid in shape.

Service metadata auth is not on this list: 0.17.0 loosens `GET /services/{id}` and 0.18.0 puts it back,
and the narratives only read tiles anyway.

### developmentseed/openeo-studio

- [PR #103](https://github.com/developmentseed/openeo-studio/pull/103) ("Fix STAC band parsing for cube
  dimensions") is open and is *referenced by name* in upstream's 0.17.0 source as the reason
  `_add_band_summaries` exists. Land it, or keep the workaround.
- Emit `<asset>|bands=<band>`, not `<asset>|<band>`, wherever the Studio builds a band reference for an
  EOPF collection. The old form is rejected, not tolerated.
- Update spec-driven form generation for `ndwi`: band *names*, not indices, plus `target_band`.
- Update error handling for `ProcessParameterRequired` and `Internal`, and the 422→400 status change.
- Audit any graph the Studio emits for outer parameters referenced directly inside callbacks; route them
  through `context`.
- Expose the new processes in the picker: `filter_temporal`, `mask`, `array_apply`, `rename_labels`,
  `resample_cube_spatial`, `sar_backscatter`.

### platform-deploy

- Wire `/healthz` and `/readyz` into the EOPF openEO app, then point liveness/readiness probes at them.
- Set `TITILER_OPENEO_PROCESSING_APPLY_SCALE_OFFSET=false` — not optional, see §6.
- Review `TITILER_OPENEO_PROCESSING_MAX_ITEMS` against the `max_items` fix — the guard now fails loudly
  where it used to truncate.
- If the upstream Helm chart is in use, it moved to GHCR OCI at 2.0.0 with a changed Postgres DSN.

---

## 6. Decisions

### Settled

- **Scale/offset — disable it here.** Not ideal, since it diverges this deployment from stock
  titiler-openeo, but not blocking. The real fix is upstream of both: stop publishing
  `raster:scale`/`raster:offset` on assets whose Zarr codec already applies them. Filed as
  [data-pipeline#384](https://github.com/EOPF-Explorer/data-pipeline/issues/384); re-enable the flag once
  that ships.
- **Tile cache — out of scope.** Its absence from the openEO app is deliberate.
- **Upstream divergence — take all of it, and narrow while re-syncing.** Every item in §3 is in. A copy
  that exists to override something real stays, reduced to the override; a copy that only re-styles
  upstream goes. §3.0 has the per-copy verdict.
- **Version — 0.17.0, from PyPI.** Pin `>=0.17,<0.18`. 0.18.0 is on its way upstream and is a follow-up.
  PR #138 is parked, so the Wolfi/`git` question does not arise.
- **The two-release lag was a deliberate deferral.** Each step carried breaking changes and the deploy
  was held rather than break published services. Production is healthy today. This plan clears the
  accumulated backlog in one cutover — that framing, not "routine bump", is what the schedule and the
  downstream comms should assume.
- **Band notation — ship the new form, no shim.** `<asset>|<band>` → `<asset>|bands=<band>` landed in
  titiler-eopf 0.8.0, and the STAC restructure moved the asset half on top of it. `_parse_asset` keeps
  rejecting the old form; downstream migrates in lockstep with the deploy. See §2.1.

### Still open

- **How many stored graphs carry the old notation, and who owns them?** Unknown, and now a prerequisite:
  with no alias, the count is the size of the cutover, and `PATCH` is owner-only, so the owning identity
  decides who can run it. Enumerating the store needs a bearer token.
- **Will the two upstream generalisations land in time?** Filed as
  [titiler-openeo#379](https://github.com/sentinel-hub/titiler-openeo/issues/379) — `reader_cls` on
  `_reader`, and `reader`/`asset_parser` fields on `LoadCollection`. Together they delete this repo's
  two widest copies. If they land before Phase 3, the re-sync targets the narrowed shape; if not,
  Phase 3 re-syncs the copies as they stand and narrows later. Worth knowing which before starting.

---

## 7. Update — v0.18.0 landed

titiler-openeo `v0.18.0` published on PyPI 2026-08-31. This section records what changed since the
§§1–6 pass (audited against `v0.17.0`), what it means for the plan above, and what has already been
done in this repo as a result. Read this section first; treat §§1–6 as still-valid detail except
where corrected below.

### 7.1 Mechanical: pin bumped, resolves and boots clean

`titiler-openeo` is on PyPI at 0.18.0 — the git-tag workaround floated in the original §4 Phase 0
never became necessary. `pyproject.toml`'s two pins (the `openeo` extra and the `dev` group) are now
`titiler-openeo>=0.18,<0.19`. `uv lock` resolves without conflict, pulling in `defusedxml` and
bumping `obstore` 0.9.4 → 0.11.1 as expected. The openEO app boots
(`titiler.eopf.openeo.main.app`, `GET /` → 200, `backend_version: "0.18.0"`), and the full test
suite — 110 tests across both apps, not just the 5 openEO ones — passes unchanged.

### 7.2 One real break, one-line fix: `LoadCollection.stac_api`

Upstream's `LoadCollection` (`titiler/openeo/stacapi.py`) gained a new attrs field in 0.18.0:

```python
signer_key: Optional[str] = field(default=None)
```

This repo's `LoadCollection(BaseLoadCollection)` subclass redeclares `stac_api: stacApiBackend =
field()` purely to narrow the type annotation to the EOPF `stacApiBackend` subclass — attrs doesn't
enforce type annotations at runtime, so the redeclaration was never functionally necessary. But attrs
places an *overridden* field at the subclass's declaration position, which put the now-mandatory-again
`stac_api` (no default) after the inherited `signer_key` (has a default), and attrs refuses to build
the class:

```
ValueError: No mandatory attributes allowed after an attribute with a default value or factory.
Attribute in question: Attribute(name='stac_api', ...)
```

Fixed by deleting the redeclaration — `stac_api` is inherited from the base class unchanged, typed as
the upstream `stacApiBackend`, and an instance of the EOPF subclass still satisfies it. Already applied
in `titiler/eopf/openeo/stacapi.py`; tests pass. `titiler/eopf/openeo/main.py`'s
`LoadCollection(stac_client)` construction needed no change — `signer_key` defaults to `None`, which is
exactly what EOPF wants (no Planetary Computer signing).

This is exactly the failure mode §3.0 predicted for hand-copied fields, just one level up from the
methods that section audited — worth remembering as a category, not just a one-off fix, when Phase 3
re-syncs the rest of `stacapi.py`.

### 7.3 The signer refactor does not widen the gap — it removes the concern

§3.2 predicted, based on 0.17.0's PR #371, that "0.18.0 will widen the gap again" by adding a `signer`
parameter to upstream's `_reader` that this repo's copy would have to absorb by hand. **That did not
happen — 0.18.0 went the other way.** PR #382 (`refactor!: sign asset hrefs at ingest instead of
threading a signer`) removed the threaded `signer` parameter entirely, following review pushback on
#371's approach. Signing is now decided once per deployment
(`TITILER_OPENEO_ASSET_SIGNER`, empty string = off), stamped onto each STAC item as a
`titiler:sign` property at the point `LoadCollection._get_items` retrieves it, and resolved back to a
signer inside `SimpleSTACReader.__attrs_post_init__` when an asset is actually opened — no parameter
threading through `_reader`, `_get_target_crs_bbox`, `_get_cube_resolutions`, or `part`.

For this repo: `SigningSettings().asset_signer` defaults to `""` → `None`, so every href is opened
exactly as the catalogue published it — the unchanged path, byte-identical per upstream's own test.
Nothing to configure, and the earlier "0.18.0 will widen the gap" note in §3.2 is superseded by this.

### 7.4 `#384` changes the band-notation landscape — read this before touching §2.1 or Phase 0

The largest thing in 0.18.0 for this migration. PR #384 (`feat(api): resolve bands published inside
one STAC asset`, refs `sentinel-hub/titiler-openeo#379`) adds a native mechanism for exactly EOPF's
situation — a catalogue that publishes several bands inside one asset's `bands` array instead of one
asset per band — and does it **without any pipe notation**. New module
`titiler/openeo/assetbands.py`: given an asset with 2+ declared bands and no rendering role
(`visual`/`overview`/`thumbnail`), each band becomes independently addressable by its own display name
(`eo:common_name` → `common_name` → `name`, the same precedence `_get_options` already used). A bare
`load_collection(bands=["blue"])` now resolves to `{"name": "<asset>", "bands": ["blue"]}` internally
and flows through the **existing** `_get_options` machinery — including this repo's Zarr branch, which
still runs unmodified, since `_get_asset_info`'s rewrite happens before `_get_options` is called. This
is wired into all four places that need it: collection discovery (`getdimensions`), band summaries
(`_add_band_summaries`), the read path (`_get_asset_info`), and resolution estimation
(`_get_assets_resolutions`).

Two consequences, one mechanical and already landed, one a real decision.

**Landed for free: the `gsd` fallback (closes most of #381).** The PR's own writeup names EOPF's
`AOT_10m`/`SCL_20m`/`WVP_10m` as the motivating case and adds `gsd` as a fourth fallback in
`_get_asset_resolution`, after `proj:transform`, `proj:shape`, and `src_dst.transform` — exactly what
`titiler-openeo#381` asked for. **One gap versus what was proposed:** the landed version has no
projected-CRS gate —

```python
if gsd := asset.extra_fields.get("gsd"):
    return abs(float(gsd)), abs(float(gsd))
```

— `gsd` is metres, and this value is later handed to `_reproject_resolution`, which treats it as
already being in the asset CRS's own units. Confirmed this is safe *for EOPF today*: `_get_asset_crs`
resolves the asset's CRS from the item's `proj:code` (traced through pystac's own extension fallback,
not `_get_asset_resolution`'s own logic), and EOPF's S2 items carry a UTM `proj:code` — projected,
metres, matching `gsd`'s unit. So resolution estimation now actually works end to end for this
catalogue for the first time. But the gap is real for any catalogue whose items lack `proj:code` and
whose reader falls back to a geographic CRS (`_get_asset_crs` → `None` → `src_dst.crs`, typically
`EPSG:4326`) — there `gsd` in metres would be misread as degrees. Left a comment on
`titiler-openeo#381` with this, rather than closing it outright, since the fix is real but not
complete.

**Not automatically solved: EOPF's own vocabulary is still redundant, independent of notation.** Ran
this repo's `get_all_band_names()` against the *current* live `sentinel-2-l2a` collection
(`stac.core.eopf.eodc.eu`) to check how #384's mechanism would interact with it, and found the
catalogue has moved further than §2.1 described. It is not just "per-band assets replaced a single
`reflectance` asset" — the live item now carries **three overlapping shapes at once**:

- 13 single-band, per-resolution assets (`B01_20m` … `B12_20m`, one band each)
- 3 multi-band composites (`SR_10m`: 4 bands: B02,B03,B04,B08; `SR_20m`: 10 bands; `SR_60m`: 11 bands)
- `TCI_10m`: 3 bands (B04,B03,B02), `roles: ["data"]` — **not** tagged `visual`/`overview`/`thumbnail`

so the same physical band is reachable several ways — `B02` alone is `B02_10m`, and also inside
`SR_10m`, `SR_20m`, `SR_60m`, and (as `B02`) inside `TCI_10m`. This repo's *current*
`get_all_band_names()` already has this redundancy — it is not new drift, and not caused by the pipe
notation — confirmed by running it: of the 44 names it emits today, `B02` alone is reachable as
`B02_10m|bands=B02`, `SR_10m|bands=B02`, `SR_20m|bands=B02`, and `SR_60m|bands=B02`. Applying
upstream's own dedup logic (qualify a name as `{asset}_{band}` only when the same display name appears
in more than one multi-band asset) to the *same* catalogue would replace those 4 aliases with cleaner
but still-plural names (`SR_10m_B02`, `SR_20m_B02`, `SR_60m_B02`) — not zero, because the catalogue
itself publishes the same band at multiple resolutions and again inside `TCI_10m`, and no purely
mechanical resolver can know which of those a caller should prefer without a policy on top.

**The actual decision this raises, which §2.1's "ship the new notation as-is, no shim" call did not
anticipate:** whether to keep growing this repo's own `get_all_band_names`/`_parse_asset` scheme, or
to drop it in favour of upstream's native bare-name resolution (which Phase 3 gets access to purely by
re-syncing `_get_options`/`_get_asset_info` per §3.0–3.5, no extra work) plus a small EOPF-side
*filter* — excluding `SR_*` composites and `TCI_10m` from what gets advertised, keeping only the
single-band per-resolution assets, mirroring the "prefer the least ambiguous source" policy this repo
already applies informally. That would shrink the 44-name (partly redundant) vocabulary to something
close to the clean, non-redundant single-name-per-band set, using upstream's own read mechanism instead
of a hand-maintained one. This is a real strategic choice, not a mechanical one, and it changes what
Phase 0's "produce the old → new mapping once" work actually produces — worth deciding before Phase 0
starts, not during it.

**`titiler-openeo#379` (the `reader_cls`/`asset_parser` ask) is unaffected and still fully open** —
`#384` is stacked on top of the existing hardcoded `SimpleSTACReader(item)` at all three call sites
this repo's `_reader` copy still has to override; nothing in 0.18.0 changed that.

### 7.5 Filed-issue status

| issue | state | note |
| --- | --- | --- |
| [titiler-openeo#378](https://github.com/sentinel-hub/titiler-openeo/pull/378) | **merged**, in 0.18.0 | positional band fallback fix |
| [titiler-openeo#379](https://github.com/sentinel-hub/titiler-openeo/issues/379) | open, unaddressed | `reader_cls` / `LoadCollection` fields |
| [titiler-openeo#381](https://github.com/sentinel-hub/titiler-openeo/issues/381) | open, **mostly fixed** (#384) | commented: works for EOPF today, unit gate still missing for the general case |
| [titiler-eopf#142](https://github.com/EOPF-Explorer/titiler-eopf/issues/142) | open | `bands.description` question — now sharper: does EOPF keep its own notation at all, per §7.4 |

### 7.6 What this changes about Phase 0–3

- **Phase 0 gains a precondition**: decide §7.4's vocabulary question (keep EOPF's scheme, narrowed;
  or adopt upstream's bare-name resolution plus an asset-exclusion filter) before building the old →
  new band-name mapping, since the two choices produce different mappings.
- **Phase 2's pin-bump work is done** — see §7.1–7.2. What remains from the original Phase 2 scope is
  re-basing `load_collection.json` on upstream's current spec (§3.3) and setting
  `TITILER_OPENEO_PROCESSING_APPLY_SCALE_OFFSET=false` (§2.2, §6) — neither touched yet.
- **Phase 3's `_get_options`/`_get_asset_info` narrowing (§3.0–3.2, §3.5) is unaffected** by any of
  this — the plan there still holds, and now additionally decides whether EOPF keeps generating its
  own `|bands=` vocabulary on top of the inherited read path, or leans on `_inner_bands` resolution
  instead.

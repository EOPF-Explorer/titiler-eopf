User: Here is a profiling benchmarking: https://gist.github.com/vincentsarago/410949848e72509771a3657623c5f2ec. I would like to understand why the dataset opener 1st case is taking so long because of thwe coordinates reading whilst it should be lazy loading. I would like to se if you could find some insights to write a proper issue to solve that poor performance.

GitHub Copilot: 

 





Fetched https://gist.github.com/vincentsarago/410949848e72509771a3657623c5f2ec

The gist content wasn't extracted from the rendered page. Let me fetch the raw notebook content directly. 



Fetched https://gist.github.com/vincentsarago/410949848e72509771a3657623c5f2ec/raw/46004cff437bdcf43fde6f5724784be0733036b9/profiling.ipynb



Fetched https://gist.githubusercontent.com/vincentsarago/410949848e72509771a3657623c5f2ec/raw/46004cff437bdcf43fde6f5724784be0733036b9/profiling.ipynb

Now I have the full profiling data. Let me trace through the critical xarray code paths to understand the root cause. 

Created 6 todos

Trace eager coordinate loading paths

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#400-400), lines 400 to 450

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#460-460), lines 460 to 520

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#990-990), lines 990 to 1050

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#670-670), lines 670 to 730

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#1575-1575), lines 1575 to 1650

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/coordinates.py#265-265), lines 265 to 330

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/variable.py#430-430), lines 430 to 480

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree_mapping.py#30-30), lines 30 to 90

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree_mapping.py#130-130), lines 130 to 190

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexing.py#715-715), lines 715 to 780

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#410-410), lines 410 to 450

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#470-470), lines 470 to 545

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#1000-1000), lines 1000 to 1055

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#685-685), lines 685 to 760

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#1580-1580), lines 1580 to 1650

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/coordinates.py#275-275), lines 275 to 330

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree_mapping.py#100-100), lines 100 to 200

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexing.py#720-720), lines 720 to 750

Searched for text `def _maybe_create_default_indexes` (`**/xarray/backends/api.py`), 1 result

Searched for text `def _datatree_from_backend_datatree` (`**/xarray/backends/api.py`), 1 result

Searched for text `def open_datatree` (`**/xarray/backends/api.py`), 1 result

Searched for text `def wrapper` (`**/xarray/core/datatree_mapping.py`), no results

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#270-270), lines 270 to 330

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#330-330), lines 330 to 430

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#860-860), lines 860 to 960

Searched for regex `^\s+def wrapper` (`**/xarray/core/datatree_mapping.py`), no results

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree_mapping.py#100-100), lines 100 to 180

Searched for text `def map_over_datasets` (`**/xarray/core/datatree.py`), 4 results

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree.py#1560-1560), lines 1560 to 1600

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree.py#1750-1750), lines 1750 to 1820

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#960-960), lines 960 to 1000

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#1000-1000), lines 1000 to 1050

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#1045-1045), lines 1045 to 1130

Searched for regex `TODO.*index|FIXME.*index|TODO.*eager|FIXME.*eager` (`**/xarray/backends/api.py`), no results

Searched for regex `TODO.*eager|FIXME.*eager|TODO.*load` (`**/xarray/core/indexes.py`), no results

Searched for regex `TODO.*index|FIXME.*index|TODO.*eager` (`**/xarray/core/coordinates.py`), 3 results

Searched for regex `TODO.*index|FIXME.*lazy` (`**/xarray/core/variable.py`), 2 results

Searched for regex `PandasIndexingAdapter|accessing.*data.*load|can load data` (`**/xarray/core/indexes.py`), 5 results

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#700-700), lines 700 to 750

Searched for text `ZarrArrayWrapper` (`**/xarray/backends/zarr.py`), 2 results

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/zarr.py#240-240), lines 240 to 300

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexing.py#700-700), lines 700 to 950

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/variable.py#440-440), lines 440 to 475

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#1590-1590), lines 1590 to 1650

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#1620-1620), lines 1620 to 1700

Searched for regex `create_default_index|eager.*coordinate|lazy.*index`, 20 results

Read [](file:///home/emathot/.config/Code/User/workspaceStorage/21cf6324b918e0c8d8107c06e08d98da/GitHub.copilot-chat/chat-session-resources/fc7a30d0-2ef1-4d88-8f7d-cd24b69c6e05/toolu_bdrk_016yZ2K9FCwNn9MzR4cfVakV__vscode-1774450854273/content.txt#1-1), lines 1 to 200

Read [](file:///home/emathot/.config/Code/User/workspaceStorage/21cf6324b918e0c8d8107c06e08d98da/GitHub.copilot-chat/chat-session-resources/fc7a30d0-2ef1-4d88-8f7d-cd24b69c6e05/toolu_bdrk_016yZ2K9FCwNn9MzR4cfVakV__vscode-1774450854273/content.txt#200-200), lines 200 to 400

Read [](file:///home/emathot/.config/Code/User/workspaceStorage/21cf6324b918e0c8d8107c06e08d98da/GitHub.copilot-chat/chat-session-resources/fc7a30d0-2ef1-4d88-8f7d-cd24b69c6e05/toolu_bdrk_016yZ2K9FCwNn9MzR4cfVakV__vscode-1774450854273/content.txt#400-400), lines 400 to 458

Starting: *Identify potential fix approaches* (5/6)

Let me verify the exact lines of the critical code paths to make sure the analysis is precise:   

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#720-720), lines 720 to 775

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#270-270), lines 270 to 380

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/coordinates.py#275-275), lines 275 to 340

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#1625-1625), lines 1625 to 1680

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/variable.py#440-440), lines 440 to 465

Starting: *Write issue summary with evidence* (6/6)

Now let me check if there's already an existing issue about this:  

Searched for text `create_default_indexes` (`**/xarray/backends/api.py`), 20 results

Searched for regex `TODO|FIXME|HACK` (`**/xarray/core/indexes.py`), 7 results

Now let me also check the docstring to confirm that `create_default_indexes` is documented as the workaround: 

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#990-990), lines 990 to 1005

Completed: *Write issue summary with evidence* (6/6)

Here's the full analysis and a ready-to-file issue:

---

## Root Cause Analysis

The profiling shows **7.17s out of 7.8s (92%)** is spent eagerly loading coordinate data from S3 during `open_datatree`, despite the data being wrapped in lazy indexing arrays. Here's the exact call chain and why it happens:

### The Call Chain

1. `open_datatree()` calls `_datatree_from_backend_datatree()` with `create_default_indexes=True` (the default)
2. This calls `backend_tree.map_over_datasets(_maybe_create_default_indexes)` — api.py
3. `_maybe_create_default_indexes()` at api.py collects 1-D dimension coordinates and wraps them in `Coordinates(to_index)`
4. `Coordinates.__init__()` at coordinates.py calls `create_default_index_implicit(var, ...)`
5. `create_default_index_implicit()` at indexes.py calls `PandasIndex.from_variables(dim_var, options={})`
6. **THE BOTTLENECK** — `PandasIndex.from_variables()` at indexes.py:
   ```python
   # preserve wrapped pd.Index (if any)
   # accessing `.data` can load data from disk, so we only access if needed
   data = var._data if isinstance(var._data, PandasIndexingAdapter) else var.data
   ```
   For Zarr-backed coordinates, `var._data` is a `LazilyIndexedArray` (not a `PandasIndexingAdapter`), so it falls through to `var.data`.
7. `Variable.data` at variable.py calls `self._data.get_duck_array()` for any `ExplicitlyIndexed` wrapper
8. `LazilyIndexedArray.get_duck_array()` hits `ZarrArrayWrapper.__getitem__` → actual S3 I/O → **7.15s of blocking `lock.acquire`**

### The Design Issue

The comment on indexes.py explicitly says *"accessing `.data` can load data from disk, so we only access if needed"* — but the guard only checks for `PandasIndexingAdapter`. All other `ExplicitlyIndexed` types (like `LazilyIndexedArray` wrapping a `ZarrArrayWrapper`) still trigger eager data loading.

**This is fundamentally unavoidable with the current `PandasIndex` design**: a `PandasIndex` wraps a `pd.Index`, which is an in-memory data structure. Building one *requires* materializing the coordinate data. The "lazy" wrappers are only lazy until something actually needs the values — and `PandasIndex` creation is that something.

### The Second-Order Problem

This is particularly bad for `open_datatree` because `map_over_datasets` applies `_maybe_create_default_indexes` to **every node** in the tree. For a Sentinel-2 Zarr product with many groups, each with their own coordinate variables, this multiplies the S3 reads.

---

## Workaround (Available Today)

```python
dt = xr.open_datatree("s3://...", engine="zarr", create_default_indexes=False)
```

This is already documented ([api.py L995-998](xarray/backends/api.py#L995)):
> *If True, create pandas indexes for dimension coordinates, which loads the coordinate data into memory. Set it to False if you want to avoid loading data into memory.*

However, `create_default_indexes=True` is the **default**, so users unaware of this will hit the performance cliff. With `create_default_indexes=False`, certain operations that rely on label-based indexing (`.sel()`, alignment) won't work until indexes are explicitly built.

---

## Draft Issue

Here's a ready-to-file issue:

---

**Title**: `open_datatree` eagerly loads all coordinate data from remote stores to build PandasIndex (92% of open time)

**Labels**: `topic-performance`, `topic-indexes`, `topic-backends`, `topic-zarr`

**Body**:

### What happened?

Opening a remote Zarr DataTree with `xr.open_datatree()` spends 92% of wall time (7.17s out of 7.8s) eagerly reading coordinate data from S3 to build `PandasIndex` objects, even though the data is wrapped in lazy indexing arrays.

### Profiling evidence

(Link the gist: https://gist.github.com/vincentsarago/410949848e72509771a3657623c5f2ec)

```
open_datatree                                          7.786s
  └─ _datatree_from_backend_datatree                   7.292s
       └─ map_over_datasets(_maybe_create_default_indexes)
            └─ Coordinates.__init__                    7.182s
                 └─ create_default_index_implicit
                      └─ PandasIndex.from_variables    7.175s
                           └─ Variable.data            7.170s  ← triggers S3 I/O
                                └─ LazilyIndexedArray.get_duck_array
                                     └─ ZarrArrayWrapper.__getitem__
                                          └─ zarr sync → lock.acquire  7.151s
```

### Root cause

In `PandasIndex.from_variables()` ([indexes.py L732](https://github.com/pydata/xarray/blob/main/xarray/core/indexes.py#L732)):

```python
# preserve wrapped pd.Index (if any)
# accessing `.data` can load data from disk, so we only access if needed
data = var._data if isinstance(var._data, PandasIndexingAdapter) else var.data
```

The guard only skips loading for `PandasIndexingAdapter`. For Zarr-backed coordinates (`LazilyIndexedArray` wrapping `ZarrArrayWrapper`), it falls through to `var.data`, which calls `get_duck_array()` → actual I/O.

This is especially painful for `open_datatree` because `_maybe_create_default_indexes` is applied to **every node** in the tree via `map_over_datasets`.

### Workaround

```python
dt = xr.open_datatree("s3://...", engine="zarr", create_default_indexes=False)
```

This avoids the eager load but disables label-based indexing until indexes are explicitly created.

### What could be improved?

1. **Consider changing the default** to `create_default_indexes=False` for remote backends (or at least for `open_datatree`), since building PandasIndex objects defeats the purpose of lazy loading.

2. **Lazy/deferred index creation**: Instead of building PandasIndex eagerly at open time, create indexes on first use (e.g., when `.sel()` is called). This would require a new lazy index type that wraps the variable and only materializes the pd.Index when needed.

3. **Better documentation/warnings**: The `create_default_indexes` parameter is documented but not prominently featured. Users hitting this performance cliff may not know about it. Consider emitting a performance warning when coordinate loading exceeds a threshold, or documenting this more visibly in the Zarr backend docs.

### Environment

- xarray: main branch
- zarr: v3
- Data: Remote Zarr on S3 (Sentinel-2 product with multiple groups)
- Profiler: pyinstrument

---

The key insight is that this isn't a bug per se — `PandasIndex` **must** load data to build a `pd.Index`. The issue is that `create_default_indexes=True` is the default, which is a poor default for remote/cloud-backed stores where the cost of materializing coordinates is dominated by network I/O. A lazy index type or a smarter default would solve this without breaking existing workflows.

User:  `create_default_indexes=False` opens faster but then how can I create the indexes for a specific group?

GitHub Copilot: 

 

Find how to create indexes post-open

Searched codebase for "create default indexes after loading dataset DataTree index creation", 26 results

Searched for regex `set_xindex|_maybe_create_default_indexes`, 20 results

Searched for regex `def set_index|def reset_index|def create_default_indexes` (`**/xarray/**`), 4 results

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/backends/api.py#273-273), lines 273 to 295

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/dataset.py#4983-4983), lines 4983 to 5050

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/dataarray.py#2865-2865), lines 2865 to 2920

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#1952-1952), lines 1952 to 1980

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/coordinates.py#1280-1280), lines 1280 to 1320

Searched codebase for "create_default_index_implicit function implementation 1D coordinate", 21 results

Searched for regex `def set_xindex|def reset_index|def drop_indexes|xindexes` (`**/xarray/core/datatree.py`), 3 results

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/indexes.py#1629-1629), lines 1629 to 1700

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree.py#1456-1456), lines 1456 to 1475

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree.py#615-615), lines 615 to 640

Searched for text `set_xindex` (`**/xarray/core/datatree.py`), no results

Searched for regex `def (dataset|ds)\b` (`**/xarray/core/datatree.py`), 2 results

Read [](file:///home/emathot/Workspace/pydata/xarray/xarray/core/datatree.py#645-645), lines 645 to 700

Now I have all the info needed. Here's the answer:

After opening with `create_default_indexes=False`, you can create indexes selectively for the group you need. Two approaches:

### 1. Use `set_xindex` on the group's dataset (specific coordinates)

```python
tree = xr.open_datatree("s3://...", engine="zarr", create_default_indexes=False)

# Create indexes for specific coordinates on a specific group
ds = tree["/measurements/reflectance"].to_dataset()
ds = ds.set_xindex("x").set_xindex("y")
tree["/measurements/reflectance"].dataset = ds
```

### 2. Replicate `_maybe_create_default_indexes` for a single node (all dimension coordinates)

```python
from xarray.core.coordinates import Coordinates

tree = xr.open_datatree("s3://...", engine="zarr", create_default_indexes=False)

# Create all default indexes for one group — same logic xarray uses internally
node_ds = tree["/measurements/reflectance"].to_dataset()
to_index = {
    name: coord.variable
    for name, coord in node_ds.coords.items()
    if coord.dims == (name,) and name not in node_ds.xindexes
}
tree["/measurements/reflectance"].dataset = node_ds.assign_coords(Coordinates(to_index))
```

This only materializes the coordinate data for that one group (triggering I/O for those coordinates only), rather than for every node in the tree.

### Helper function

You could wrap this into a reusable helper:

```python
from xarray.core.coordinates import Coordinates

def create_indexes_for_node(tree, path):
    """Create default PandasIndex for all dimension coordinates on one DataTree node."""
    ds = tree[path].to_dataset()
    to_index = {
        name: coord.variable
        for name, coord in ds.coords.items()
        if coord.dims == (name,) and name not in ds.xindexes
    }
    tree[path].dataset = ds.assign_coords(Coordinates(to_index))
```

Note that `DataTree` itself doesn't expose `set_xindex` directly — you have to go through `.to_dataset()`, modify, then assign back via `.dataset = ...`.
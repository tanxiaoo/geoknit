# Writing components

A GeoKnit component is one small Python file with typed inputs and outputs.
Every node on the canvas that does work is one: the built-ins, the Python
component you type into, the components you save, and the ones community
packs ship. They all use the same format, described here. The format is a
public contract (SPEC section 4): files written today keep working.

- [A first component](#a-first-component)
- [The header](#the-header)
- [The settings block](#the-settings-block)
- [The code block](#the-code-block)
- [Data types](#data-types)
- [Special ports](#special-ports)
- [Helpers](#helpers)
- [Where components live](#where-components-live)
- [Testing a component](#testing-a-component)
- [In an exported script](#in-an-exported-script)

## A first component

A normalized difference of two bands (NDVI for a red and a near-infrared
band):

```python
# geoknit: component
# name: Normalized Difference
# category: Raster
# icon: gis:layers
# description: (a - b) / (a + b) of two bands, e.g. NDVI from NIR and red.
# inputs:
#   raster: Raster
# outputs:
#   index: Raster
# requires: [numpy]

# --- settings ---
band_a = "A07"  # band name or number, e.g. the near infrared
band_b = "A03"  # band name or number, e.g. red

# --- code ---
from geoknit.helpers import band_indices

i, j = band_indices(raster, [band_a, band_b])
a = raster.isel(band=i).astype("float32")
b = raster.isel(band=j).astype("float32")
index = ((a - b) / (a + b)).expand_dims(band=[1])
index.attrs["long_name"] = ("index",)
print(f"({band_a} - {band_b}) / ({band_a} + {band_b})")
```

The file has three parts, in this order:

1. **Header**: the first comment block, starting with `# geoknit: component`.
   It names the component and declares its ports.
2. **Settings**: between `# --- settings ---` and `# --- code ---`. Plain
   assignments of literals; they become the component's Settings tab.
3. **Code**: everything after `# --- code ---`. Ordinary Python. Inputs are
   variables; outputs are the variables you assign.

To try it, add a **Python** component (Script tab), open it with a
double-click, paste the file into the Code tab, and wire a raster into
`raster`. The node takes its name and ports from the header as soon as you
leave the Code tab.

## The header

The header is YAML inside comments: GeoKnit strips the leading `# ` from each
line and parses the rest.

| Key | Required | Meaning |
|-----|----------|---------|
| `name` | yes | Shown on the node and in the ribbon. |
| `category` | no (`Script`) | The ribbon tab. A new category becomes a new tab. |
| `icon` | no | An icon name such as `gis:layers` (below), or a relative `.svg` path; otherwise the category's icon is used. |
| `description` | no | One sentence, shown in the ribbon and search. |
| `inputs` | no | Port name → type, or a mapping with `type`, `access`, `file`. |
| `outputs` | no | Port name → type. |
| `requires` | no | pip package names the code needs, e.g. `[scikit-learn]`. |

Icon names are `<set>:<name>`, from [Font-GIS](https://github.com/Viglino/font-gis)
(`gis:`), [Lucide](https://lucide.dev) (`lucide:`) or
[Tabler](https://tabler.io/icons) (`tabler:`), for example `icon: gis:map-legend`.
GeoKnit bundles only the icons it uses; [icons.md](icons.md) lists every
available name with a preview. A name that is not in that list falls back to
the category's icon (with a warning in the browser console). For any other
icon, ship an `.svg` file with your component and give its path relative to
the component file, e.g. `icon: icons/my-icon.svg`; it must stay inside your
pack's folder. Icons are drawn in one colour, so draw them in black or
`currentColor` on a transparent background.

Port names must be valid Python names, and an output cannot share its name
with an input. A component that returns a changed copy of an input names its
output after the result: `clipped`, `selected`, `reprojected`.

## The settings block

```python
# --- settings ---
n_trees = 300        # range: 1..5000
task = "regression"  # options: regression | classification
breaks = "0 | 0-20"  # multiline
seed = 42
```

- Only top-level assignments of literals: numbers, text, `True`/`False`,
  `None`, or a list or tuple of those. Anything else (a function call, an
  expression, an import) is a parse error, shown in the component's Output,
  and the Settings tab stays disabled until it is fixed.
- Each name is set once.
- A trailing comment shapes the form field: `# options: a | b | c` gives a
  dropdown, `# range: 0..100` a number field with limits, `# multiline` a text
  area. Any other comment, or none, gives a text field. Option values that read
  as numbers, `True`/`False` or `None` are those values.
- **A setting named like an input is that input's default.** Above, if the
  header declares an input `seed: Number`, the node runs with `seed = 42`
  until a wire is connected to `seed`; then the wired value wins. An input
  with no same-named setting is required: running without a wire fails with
  `input "raster" is not connected`.

Editing a value in the Settings tab rewrites only that literal in the file;
comments and formatting stay as they are. So the file you see in the Code tab
is always the whole truth about the node.

## The code block

```python
# --- code ---
import numpy as np
from geoknit.helpers import invalid_mask, nodata_value

bad = invalid_mask(raster.values, nodata_value(raster))
print(f"{int(bad.sum())} invalid pixels")
count = int(bad.sum())
```

When the node runs, GeoKnit:

1. starts from a fresh namespace and runs the settings block;
2. assigns every wired input to its variable (overriding a same-named
   setting), checking its type;
3. runs the code with the **project folder as working directory**, so a
   relative path such as `data/aoi.gpkg` works;
4. reads every declared output back from the variables, checking its type.

Everything printed, written to stderr, warned with `warnings.warn` or logged
at INFO and above appears in the node's **Output**, one line per entry. An
exception shows its traceback there, with line numbers of the component file.
A missing output (`output "count" was not set by the code`) or a value of the
wrong type (`output "count": expected Number, got Text`) is an error too.

Imports go in the code block, not the settings block. Import what the code
needs each time: every run starts from a fresh namespace.

## Data types

| Type | Python object | Notes |
|------|---------------|-------|
| `Number` | `int` or `float` | not `bool` |
| `Text` | `str` | a Number wired into a Text input becomes `str(value)` |
| `Raster` | `xarray.DataArray`, dims `(band, y, x)`, opened with rioxarray | lazy (dask) |
| `Vector` | `geopandas.GeoDataFrame` | |
| `Table` | `pandas.DataFrame` | not geographic |
| `Model` | `geoknit.core.types.ModelBundle` | `estimator`, `task`, `target`, `feature_names`, `info` |
| `Any` | anything | only for inputs that accept every type |

**Keep rasters lazy.** Rasters come in as dask-backed arrays and may be
larger than memory (a city at 10 m with 64 bands is several GB). Prefer
`xarray` operations, `xr.apply_ufunc(..., dask="parallelized")` and the
helpers below over `.values` or `.load()` on a whole raster. Band names
travel in `raster.attrs["long_name"]` (a tuple, one per band); set it on
rasters you create, as the example above does, so downstream components and
the Map Viewer can name the bands.

Results are cached on disk (`<project>/.geoknit/cache/`): a raster as a
Cloud Optimized GeoTIFF, vectors as GeoParquet, tables as Parquet, models
with joblib. A node runs again only when its code, settings, inputs, or a
file it names change.

## Special ports

**`out: Text`, the printed text.** A component with an output `out` of type
Text that its code does not set receives everything it printed there, as in
Grasshopper's GHPython. The Python component has it by default.

**`file: write`, a file the component writes.** GeoKnit notices when a file
named by a Text value changes (size and modification time) and runs the
nodes that read it again. Mark an input that names a file the component
*writes*, so writing it does not make the node out of date again:

```python
# inputs:
#   map: Raster
#   path: {type: Text, file: write}
```

**`access: list`, several wires.** An input with `access: list` takes any
number of wires and receives a Python list, in wire order. The Map Viewer's
`layers: {type: Any, access: list}` is the built-in example.

## Helpers

`geoknit.helpers` holds what the built-ins share. Use it freely: an exported
script carries a copy, so it still runs without GeoKnit.

| Helper | What it does |
|--------|--------------|
| `parse_breaks(text)`, `classify(values, rules, dtype)`, `class_dtype(n)` | Reclassify's break rules (`0 \| 0-20 \| 20-40`) |
| `band_indices(raster, bands)`, `select_bands(raster, bands)` | bands by number or name (`"1,2"`, `"A00,A05"`), with a clear error naming missing bands |
| `raster_band_names(raster)` | band names from the descriptions, else `b01, b02, …` |
| `nodata_value(raster)`, `invalid_mask(values, nodata)` | the nodata value still in the data, and a mask of NaN or nodata pixels |
| `write_cog(raster, path, compress)` | write a Cloud Optimized GeoTIFF window by window |
| `values_at_points(raster, points)`, `pixel_of(raster, xs, ys)` | raster values at points without loading the raster |
| `RASTER_CHUNKS` | the chunks GeoKnit opens rasters with |

`geoknit.helpers.model` has `choose_features(table, target, features)` and
`training_data(table, target, features)`, used by Random Forest and SVM.

## Where components live

**On the canvas.** The Python component (Script tab) is an empty component
whose ports you add, rename and type in its Settings tab. Built-ins can be
edited too: change the code of any node and it is stored inside the workflow,
marked *modified*, without touching the library.

**Your library.** In the component window, **Save as component…** writes the
file to `~/.geoknit/components/<category>/<name>.py`, both names from the
header in lower case (`My NDVI!` → `my_ndvi`). It appears in the ribbon under
its category, marked as a user component, with the reference
`user/<category>/<name>`. You can also drop files into that folder yourself;
they are loaded when GeoKnit starts. The environment variable
`GEOKNIT_USER_COMPONENTS` moves the folder.

**A pack.** A pip package can bring a whole folder of components. Declare an
entry point in the group `geoknit.components` whose value is the folder (a
path string, or a function returning one):

```toml
# pyproject.toml of the pack
[project]
name = "geoknit-water"
version = "0.2.0"

[project.entry-points."geoknit.components"]
water = "geoknit_water:components_folder"
```

```python
# geoknit_water/__init__.py
from pathlib import Path

def components_folder() -> Path:
    return Path(__file__).parent / "components"
```

The folder holds `<category>/<name>.py` files; files starting with `_` are
ignored. Once the package is installed, its components appear in the ribbon
with references `water/<category>/<name>` and the package version. The names
`builtin`, `user`, `inline` and `param` are reserved. A file that does not
parse is skipped with a warning; it never stops GeoKnit from starting.

| Source | Reference in a workflow |
|--------|-------------------------|
| built-in | `builtin/raster/reclassify` |
| `~/.geoknit/components/` | `user/<category>/<name>` |
| pack with entry point `water` | `water/<category>/<name>` |

A workflow stores an unchanged library component by reference plus its
settings, so sharing a workflow that uses a pack means installing the pack.

## Testing a component

In the component window, **Test** runs only this node, using the cached
results of its inputs. The Output shows what it printed and any traceback.

Outside GeoKnit, a component is easy to test with pytest:

```python
from pathlib import Path

import rioxarray

from geoknit.core.component import parse_component, run_component
from geoknit.helpers import RASTER_CHUNKS


def test_normalized_difference() -> None:
    spec = parse_component(Path("normalized_difference.py").read_text(encoding="utf-8"))
    raster = rioxarray.open_rasterio("data/predictors.tif", chunks=dict(RASTER_CHUNKS))
    result = run_component(spec, {"raster": raster})
    assert result.ok, result.error
    index = result.outputs["index"]
    assert index.sizes["band"] == 1
    assert float(abs(index).max()) <= 1
```

`run_component` follows the same steps as a run on the canvas; `result.log`
holds the Output lines. `python examples/synthetic/make_data.py` creates
small test rasters and vectors.

## In an exported script

**Export .py** (top bar, or `geoknit export file.geoknit`) turns the
workflow into one Python script that runs without GeoKnit. Each component
becomes a function whose body is its settings and code:

```python
# n07 · Normalized Difference (user/raster/normalized_difference 0.1.0)
def n07_normalized_difference(raster):
    # --- settings ---
    band_a = "A07"  # band name or number, e.g. the near infrared
    band_b = "A03"  # band name or number, e.g. red

    # --- code ---
    # from geoknit.helpers import band_indices  (vendored above)
    ...
    return index
```

A setting whose input is wired is commented out, so the parameter is used.
Imports from `geoknit.helpers` are served by a copy of the helpers at the top
of the script. Any other `geoknit` import is reported as a warning, because
that script would still need GeoKnit. So a component that sticks to its
inputs, its settings, ordinary packages and the helpers exports cleanly.

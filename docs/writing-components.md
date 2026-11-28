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
| `group` | no (`Other`) | The labelled group inside the tab, e.g. `Overlay`. |
| `icon` | no | An icon name such as `gis:layers` (below), or a relative `.svg` path; otherwise the category's icon is used. |
| `description` | no | One sentence, shown in the ribbon and search. |
| `inputs` | no | Port name → type, or a mapping with `type` (one type or a list), `access`, `file`. |
| `outputs` | no | Port name → type, or a mapping with `type` or `like`, and `access`. |
| `ports` | no | Lets the user add, remove and rename ports in the Settings tab (below). |
| `requires` | no | pip package names the code needs, e.g. `[scikit-learn]`. |

In the ribbon, a pack's groups come after the built-in groups of the same
tab, in alphabetical order, and components are alphabetical inside a group. A
`group:` that names a built-in group of the tab (such as `Split` in Sampling)
joins it. A component without `group:` goes to the group *Other*, shown last.

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
output after the result: `clipped`, `selected`, `reprojected`. The name
`INPUTS` is reserved (see [The code block](#the-code-block)).

### Inputs that take several types, outputs that follow them

An input can accept several types, and an output can take the type of the
value wired into an input with `like:`. A component that keeps the first rows
of a table or of a vector layer:

```python
# geoknit: component
# name: First Rows
# category: Table
# group: Select
# icon: lucide:table
# description: Keep the first n rows of a table or vector layer.
# inputs:
#   data: {type: [Table, Vector]}
#   n: Number
# outputs:
#   first: {like: data}

# --- settings ---
n = 10  # range: 1..100000

# --- code ---
first = data.head(int(n))
print(f"kept {len(first)} of {len(data)} rows")
```

- `type: [Table, Vector]`: a wire connects when its type is one of the listed
  ones. A value of another type is refused with
  `input "data": expected Table | Vector, got Raster`. `Any` cannot be in a
  list, and a type cannot be listed twice. Only inputs take a list.
- `like: data`: the output's type is the type of whatever is wired into
  `data`. Wired from a Vector, `first` is a Vector and connects only where a
  Vector can go; re-wiring `data` from a Table re-checks the wires leaving
  `first` and removes those that no longer fit. Before `data` is wired, `first`
  can go wherever one of `data`'s types can. The code must then return a
  value of that type: a GeoDataFrame for a Vector, a plain DataFrame for a
  Table. `like:` names an input of the same component and cannot be combined
  with `type:`.

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
   setting), checking its type, and sets `INPUTS`, a dict of every input name
   → its value (wired, or the setting's) in header order;
3. runs the code with the **project folder as working directory**, so a
   relative path such as `data/aoi.gpkg` works;
4. reads every declared output back from the variables, checking its type.

Everything printed, written to stderr, warned with `warnings.warn` or logged
at INFO and above appears in the node's **Output**, one line per entry. An
exception shows its traceback there, with line numbers of the component file.
A missing output (`output "count" was not set by the code`) or a value of the
wrong type (`output "count": expected Number, got Text`) is an error too.

`INPUTS` is handy when the inputs are not known in advance, for example in a
component with editable ports that evaluates an expression over them
(`eval(expression, {}, INPUTS)`). A port or setting cannot be called `INPUTS`.

Imports go in the code block, not the settings block. Import what the code
needs each time: every run starts from a fresh namespace.

## Data types

| Type | Python object | Notes |
|------|---------------|-------|
| `Number` | `int` or `float` | not `bool` |
| `Text` | `str` | a Number or Boolean wired into a Text input becomes `str(value)` |
| `Boolean` | `bool` | `numpy.bool_` counts too (`flag = a > b` works); `0`/`1` is not a Boolean |
| `Color` | `geoknit.core.types.Color` | `Color("#0B7A7C")` or `Color.parse("11,122,124")`; `.hex`, `.rgba` |
| `Colormap` | `geoknit.core.types.Colormap` | `Colormap.named("viridis")`, or `stops` / `classes`; see below |
| `Raster` | `xarray.DataArray`, dims `(band, y, x)`, opened with rioxarray | lazy (dask) |
| `Vector` | `geopandas.GeoDataFrame` | |
| `Table` | `pandas.DataFrame` | not geographic |
| `Model` | `geoknit.core.types.ModelBundle` | `estimator`, `task`, `target`, `feature_names`, `info` |
| `Any` | anything | only for inputs that accept every type |

A `Colormap` is continuous (`kind="continuous"`: a `name` from the ten named
ramps viridis, magma, plasma, cividis, turbo, greys_r, terrain, rdylgn,
spectral, blues, or `stops=((0, Color(...)), (1, Color(...)))`; `min`/`max`,
`None` for the layer's 2–98 % stretch; `reverse`) or a set of classes
(`kind="classes"`, `classes=((1, Color(...), "urban"), ...)`, and `other` for
values not listed). On the canvas a Colormap node (Params › Style) holds one,
edited in its window, and a component can take it as an input or return one.

There is also a `Layer` type, made only by the Map Layer node (Display ›
Style): a `geoknit.core.types.MapLayer` with `source` (the cache key of the
data), `kind` (`"raster"` or `"vector"`), `name`, `colormap`, `color`,
`opacity`, `bands` and `field`. It holds no pixels or features; the Map
Viewer draws it.

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

**`access: list`, lists.** An input with `access: list` takes any number of
wires and receives a Python list, in wire order. The Map Viewer's
`layers: {type: [Raster, Vector, Layer], access: list}` is the built-in
example. An output can be
a list too:

```python
# outputs:
#   values: {type: Number, access: list}
#   sorted: {like: items, access: list}
```

Its value must be a Python `list` (a tuple is turned into one), and every
element is checked against the type: `output "values": item 2: expected
Number, got Text`. A list output connects only to a list input; there the
lists of all its wires are joined in wire order (a single-value wire adds one
element), so the receiver gets `[3, 1, 2, 7]` from a list `[3, 1, 2]` and a
Number `7`. A list wired into an ordinary input is refused
(`Numbers gives a list; "x" takes one value — use List Item`); only a Panel
takes a whole list. List ports and wires are drawn with a double line.

**`ports:`, editable ports.** The Python component lets the user add, remove,
rename and retype its ports in the Settings tab. Any component can allow the
same:

```python
# ports: {inputs: editable, types: [Raster, Number]}
```

`inputs: editable` and/or `outputs: editable` say which side can be edited;
`types` limits the types offered (by default every type except `Layer`, and
`Any` on inputs). Edits to a side that is not editable, or to a type outside
`types`, are refused. A new port gets a free name and the first of `types`.
Combine it with `INPUTS` to use ports whose names you do not know in advance.

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

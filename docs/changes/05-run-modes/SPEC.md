# Change 05: Run modes, radial menu, disabling nodes

Status: agreed (checked against the code, 26 Nov 2026) · Brief: `BRIEF.md` ·
Release 0.1.0 · Needs 01 (icon registry), 03 (view nodes: Map Layer and
Map Viewer never need a Run) · Touches `docs/SPEC.md` sections 5, 6, 8, 9,
10, 12

## Questions for Xiao

None open. The answers of 26 Nov 2026 are in `BRIEF.md` and built in below:
the run works on a snapshot with a "superseded" check (section 3), file
writers changed mid-run (section 3), what still answers `409` (section 3),
and trusting counts as opening (section 1).

---

## 1. Run modes (SPEC 6, 8)

Replaces "Runs are manual only in v0.1" in SPEC 6.

- **Switch.** The canvas toolbar gets a switch Auto | Manual next to the
  banner. It is saved in the workflow's `view` as `"run_mode": "auto" |
  "manual"` and changed with `PATCH /api/view`.
  - `graph_to_dict` writes only known top-level keys, so `view` is the place
    that survives a save. It is also already "not undone", which fits a mode
    switch.
  - A workflow without the key is in Auto: new workflows, the examples, and
    every file saved before this change.
- **Manual** is today's behaviour: nothing runs until Run, Run to here or
  Test.
- **Auto.**
  - After an edit that changes results (anything that makes a node out of
    date: settings, code, ports, wires, values, undo/redo, restoring an
    autosave, enabling or disabling), the server waits 0.5 s. A new edit
    restarts the wait.
  - It then starts an *auto run*: Run all over the nodes that are
    `out_of_date` or `never_run`. Nodes in `error` or `skipped` are retried
    only once an edit makes them out of date.
  - Position, display, group and view changes never start one.
  - The wait lives in the server (`Session`), not the browser, so edits made
    through the API by an agent run the same way.
  - If a run is active when the wait ends, nothing starts: the run's end
    takes over (section 3).
  - Switching from Manual to Auto counts as an edit.
- **No time limit.** Every out-of-date node runs in Auto, however long it
  took last time. There is no setting. A long workflow is the moment to switch
  to Manual or press Stop.
- **Opening a workflow in Auto** (trusted only) starts an auto run of
  everything out of date, as Grasshopper does when it opens a definition.
  This covers `POST /api/workflow/open`, a file named on the command line
  (`geoknit file.geoknit`), and trusting a read-only workflow
  (`POST /api/workflow/trust`), which counts as opening it. Cache
  hits come back at once; only nodes that changed or were never cached
  compute. Opening Milan with an empty cache starts the full workflow.
- **Sliders run on release.** The Number Slider already sends its value only
  on pointer-up and key-up (`SliderNode.tsx`, `commit`). The slider window and
  the inline Text and Number fields send on Enter or when they lose focus. So
  the wait never fires in the middle of a drag, and no slider change is
  needed.
- **Untrusted workflows never auto-run.** A read-only workflow refuses edits
  (`403`), and opening one starts nothing.
- **Stop** only stops: the running node gets `error: stopped` as today. Auto
  does not restart until the next edit (or open).
- **CLI.** `geoknit run` ignores `run_mode` and runs everything, as today.
- `POST /api/run` keeps its modes (`all`, `to_node`, `test`). Auto runs are
  started by the server and show up on `/ws` like any run, with
  `run_finished {report, auto: true}`. `GET /api/graph` and the `states`
  event add `run_mode`.

## 2. The banner (SPEC 6, 8)

- The banner's count stays "every node that is not `done`". Excluded from
  it: disabled nodes, the nodes skipped because of them (section 5), and
  view nodes (change 03).
- In Auto, the banner shows "Running…" during a run. Otherwise it shows the
  count and Run only when something is left, such as errors, or nodes made
  out of date by an edit during the run before the next auto run picks them
  up.

## 3. Edits during a run (SPEC 6, 9)

Today, while a run is active, every request that changes results answers
`409` ("stop the run first"). Position, display and group changes are
already allowed, and undo/redo are refused (`Session._check_idle`). Instead:

- **Edits apply at once.** Node, wire, delete, paste, ports, settings and
  value edits, undo/redo and autosave restore are applied to the graph
  immediately. They answer as usual: `200`/`201`/`204`, or `400` with the
  usual message. Out-of-date marking happens as usual.
- **The running plan is a snapshot.** Today only the cache keys are captured
  when a run starts (`WorkerExecutor.run` → `compute_keys`). The runner thread
  then reads the live graph (`graph.node(nid)`, `node.source` at the node's
  turn, the parents' live states) and writes `solver.states` without the
  session lock. Instead, when a run starts, the server records under the
  session lock:
  - the plan's node ids;
  - each node's source and kind;
  - the input port keys and node keys from `compute_keys`;
  - the Params values sent with `put_value`.

  The runner never reads live code or live states. Inside the run, a node is
  skipped when a parent *in this run* failed, and otherwise runs with its
  parents' results from this run (by snapshot key).
- **Superseded nodes.** During a run, every edit also adds the nodes it marks
  out of date to a *superseded* set for the current run, as does deleting a
  node, which supersedes the node and its children.
  - Before starting each snapshot node, the runner checks that set under the
    lock.
  - A superseded node, and every node downstream of it in the snapshot, is
    not run. It stays `out_of_date`, its Output logs "skipped: changed
    during the run", and Auto picks it up in the next run.
  - These nodes are not reported as `skipped` or failed in `run_finished`;
    they go in a `superseded` list of the report.
  - A node that is already running when it is superseded finishes. Its result
    is cached under its old key, and the key check below keeps it out of
    date.
- **File writers changed mid-run.** A node with a `file: write` input (Write
  Raster, Write Vector, Write Table) that is changed before its turn is
  superseded and skipped, so the old path is not written. If it is already
  running when its path changes, it writes the old path. The server then
  adds to its Output "writing <old path> — path changed during the run".
  The path counts as changed when the setting or the wired Text value behind
  the `file: write` input now gives another path.
- **Results and the key check.** When a node's result arrives, the server
  takes the lock and compares the node's *current* key, computed from the
  live graph, with the key it was run with.
  - Equal: the node becomes `done` as today, with summaries and
    `done_port_key`.
  - Different, or the node no longer exists: the result stays in the worker
    memory and disk cache under its key, and the node stays `out_of_date`.
    The `done` event is still sent (`stale: true`), so the Output log shows
    what ran.
  - A node whose current key is different but whose new key is already in
    the cache gets its result on the next run as a cache hit.
- **States while running.** An edit that invalidates the running node does
  not change its shown state. It stays `running`, and the key check decides
  at the end. Other nodes are invalidated as usual.
- **Deleting a running node** is allowed. It finishes, its result stays in
  the cache, and the graph forgets it. Its snapshot downstream is superseded
  and not run. Undo and redo during a run are edits like any other.
- **When the run ends** (finished or failed), Auto starts a new run for
  whatever is out of date, after the 0.5 s wait if an edit is still recent.
  Manual leaves it to the user. After Stop, nothing restarts until the next
  edit.
- **Still `409` during a run**, and only these:
  - a second Run or Test;
  - opening another workflow;
  - Clear cache, because it deletes files the run may be reading;
  - Save as into another folder, which changes the project folder and
    re-attaches the executor (`Session.save`).

  The message says a run is active and to stop it or wait: "A run is
  active: stop it or wait for it to finish". A plain Save, and Save as within
  the same folder, are allowed during a run and save the live graph.
- SPEC 9's sentence "While a run is active, a second run and every edit that
  changes results answer `409`…" is replaced by the rules above.

## 4. Middle-click radial menu (SPEC 8)

- **Opening.** A middle-button press on a node followed by a release that
  moved less than 4 px opens the radial menu, centred on the pointer.
  - The press is `preventDefault`-ed, which stops Windows autoscroll and
    Linux primary-selection paste.
  - A middle drag (4 px or more) pans as today. React Flow pans on the middle
    button (`panOnDrag={[1]}` in `Canvas.tsx`); the build checks that a drag
    started on a node also pans, and makes it so if it does not.
  - Esc, a click outside, or choosing an item closes it.
- **Items**, clockwise from the top. An item that does not apply to the node
  is shown greyed, with a tooltip saying why.

  | Item | Does | Icon |
  |------|------|------|
  | Enable / Disable | toggles `enabled` (section 5); not for Params nodes | `lucide:power` / `lucide:power-off` |
  | Run to here | as the right-click menu (`POST /api/run` `to_node`) | `lucide:step-forward` |
  | Settings / Code | opens the component window; for Map Viewer the map window, for Number Slider its window, for Map Layer and the change 01 Params nodes their window; Text and Panel: greyed | `lucide:settings-2` |
  | Show as Text \| Icon | sets the node's `display` to the other one; components and Map Layer only | `lucide:type` / `lucide:image` |
  | Help | a popover with the description and the ports (name, type, list or item), from the node view | `lucide:circle-help` |

  No Font-GIS icon fits these actions, so they come from Lucide (the rule's
  second set). All names exist in `lucide-react` 1.79 and go into the icon
  registry of change 01.
- Params nodes have no description in a header. Their descriptions come
  from the server's Params entries (change 01, section 7), like a component
  header's. Menu labels and tooltips are in `strings.ts`.
- The right-click menu (`Canvas.tsx`) gains "Disable (Ctrl+E)" / "Enable
  (Ctrl+E)" next to Run to here, so the action is not only behind the middle
  button.

## 5. Enable / Disable (SPEC 5, 6, 8, 9, 10, 12)

- **Which nodes.** Components, Map Layer and Map Viewer. Params nodes (Text,
  Slider, Panel and the change 01 Params) cannot be disabled:
  `400 "Params nodes cannot be disabled"`.
- **Workflow file.** `"enabled": false` on the node; the key is omitted when
  enabled, so existing files keep their bytes. It joins `_NODE_KEYS`, and
  `Node` gets an `enabled` field. `apply_dict` / `_update_node` handle a
  change of `enabled` alone, because it changes results and is not a layout
  key.
- **API.** `PATCH /api/nodes/{id}` `{enabled}` (one undo step), and
  `POST /api/enable {nodes, enabled}` for a selection (one undo step for
  all). Both are result-changing edits: refused on a read-only workflow, and
  applied at once during a run (section 3).
- **Ctrl+E** toggles the selected nodes through `POST /api/enable`: if any
  of them is enabled, all become disabled, otherwise all become enabled.
  Params nodes in the selection are left out. If only Params nodes are
  selected, nothing happens.
- **States.** A new node state, `disabled`.
  - Disabling a node sets it `disabled` at once and every node downstream of
    it `skipped`, with the message "input from <name> (<id>), which is
    disabled", without a Run.
  - Those nodes are not in run plans (Auto, Manual, Run to here) and not
    counted in the banner.
  - Test on a node downstream of a disabled one answers with the same
    message.
- **Enabling again** sets the node and its downstream `out_of_date`.
  `enabled` is not part of the cache key, so the next run finds the old
  results in worker memory or the disk cache (`cached: true`), unless
  something else changed meanwhile. In Auto, that run starts after the wait.
- **Canvas.** A disabled node is drawn greyed (lower opacity, desaturated
  strip), and so are its outgoing wires. Downstream nodes show the
  `skipped` look they have today, with the message in their Output.
- **Map Viewer and Map Layer.**
  - Only the affected layer is skipped. A layer whose source is disabled
    (directly, through a Map Layer, or further upstream) is shown greyed in
    the layer list with "source disabled". No tiles or GeoJSON are requested
    for it, and the other layers still show.
  - A disabled Map Layer gives such a layer.
  - A disabled Map Viewer's window says it is disabled and draws no layers.
  - Components with a list input (Build Multiband) are skipped whole.
- **`geoknit run`.**
  - Disabled nodes are not run. The nodes downstream of them are skipped,
    and a Panel among them prints `(skipped: input from …, which is
    disabled)` under its `--- Panel <id> ---` line.
  - The summary on stderr says "N skipped (disabled upstream)".
  - `RunReport` gets a `disabled` list (disabled nodes and the nodes skipped
    because of them), kept apart from `failed` and `skipped`, so `ok`
    ignores them.
  - The exit code is 0 when the only skips come from disabled nodes. Errors,
    and skips caused by errors, still give 1.
- **Export (SPEC 10).**
  - A disabled node and everything downstream of it are written as comments:
    the function definition with `# ` before each line, and the call in
    `main()` likewise.
  - A Panel downstream prints nothing.
  - The export adds one warning per disabled node: "n7 Reclassify is
    disabled: it and 3 nodes downstream are commented out".
  - Constants that feed only commented-out nodes stay as constants.

## 6. SPEC text that changes

- SPEC 5: `enabled` in the node keys; `view.run_mode`.
- SPEC 6:
  - node states gain `disabled`;
  - "Run commands": Auto and Manual, the auto run on open, edits during a
    run, the key check;
  - "Worker protocol": runs work on a snapshot.
- SPEC 8: the toolbar switch, the banner texts, the radial menu, Ctrl+E, the
  disabled look.
- SPEC 9:
  - `PATCH /api/view` `run_mode`;
  - `PATCH /api/nodes/{id}` `enabled`;
  - `POST /api/enable`;
  - the `409` paragraph rewritten (section 3);
  - `/ws` `run_finished.auto`, `report.superseded` and `done.stale`;
  - `GET /api/graph` `run_mode`.
- SPEC 10: disabled nodes as comments.
- SPEC 12: `geoknit run` and disabled nodes, and the exit code.

## Not in this change

- Cancelling a running auto run when a new edit arrives (the run finishes on
  its snapshot; Stop is still there).
- A time limit for slow nodes in Auto (decided against).
- Running only the part of the graph in view, or per-group run modes.
- Disabling a wire, or Params nodes.

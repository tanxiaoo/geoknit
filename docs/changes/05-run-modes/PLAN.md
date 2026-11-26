# Change 05 plan: Run modes, radial menu, disabling nodes

Read `CLAUDE.md`, `docs/SPEC.md`, `docs/changes/05-run-modes/BRIEF.md` and
`SPEC.md` before each step. Needs change 01 (icon registry) and change 03
step 3 (view nodes). Part of release 0.1.0.

---

## Step 1: Runs on a snapshot, edits during a run

- [ ] `WorkerExecutor.run` takes a snapshot under the session lock (plan
      ids, sources, kinds, input keys, node keys, Params values); the runner
      thread never reads live code or live states; skip decisions use
      outcomes within this run
- [ ] Superseded set per run: every edit (and delete) during a run adds the
      nodes it marks out of date; the runner checks it under the lock before
      each node and skips that node and its snapshot downstream with
      "skipped: changed during the run" (`report.superseded`)
- [ ] File writers: "writing <old path> — path changed during the run" when
      a running node's `file: write` path changes
- [ ] Result handling under the lock: `done` only when the node's current
      key equals its run key, otherwise it stays `out_of_date` (`done` event
      with `stale: true`); a deleted node's result is discarded; a running
      node keeps showing `running` until its result
- [ ] `Session`: result-changing edits, undo/redo and recover no longer call
      `_check_idle`; still `409` only for Run/Test, open, Clear cache, Save
      as into another folder, with "A run is active: stop it or wait for it
      to finish"; Save into the same folder allowed
- [ ] The same in the in-process executor (`core/executor.py`), which has no
      threads but shares the plan code
- [ ] SPEC 9 `409` paragraph rewritten

**Done when** (pytest):
- during a run on a test component that sleeps 0.5 s, a setting change
  answers `200`; the node ends `out_of_date`, its old result is in the disk
  cache, and the next run computes only it and its downstream
- deleting the running node answers `204`, the run finishes without an
  error, and its downstream is not run; undo during the run restores it
- an edit to a node that has not started yet makes the runner skip it and
  its snapshot downstream, with "skipped: changed during the run"; they end
  `out_of_date`, and the next run computes them with the new settings
- Write Raster whose path setting changes before its turn writes nothing in
  that run; whose path changes while it runs writes the old path and logs
  the "path changed during the run" line
- a plain Save during a run answers `200`
- during a run, `POST /api/run`, open and Clear cache answer `409`
- the existing `409` tests in `tests/server/test_api.py` and
  `test_component_window_api.py` are changed to the new behaviour, not
  deleted

## Step 2: Auto and Manual

- [ ] `view.run_mode` (`auto` when missing), `PATCH /api/view`; `run_mode` in
      `GET /api/graph` and `states`
- [ ] `Session`: 0.5 s wait after each result-changing edit, then an auto
      run of everything out of date or never run; a new auto run when a run
      ends and something is out of date; none after Stop; switching to Auto
      counts as an edit
- [ ] Auto run on open (open endpoint, `geoknit file.geoknit`, and on
      trusting a read-only workflow) for trusted workflows only;
      `run_finished.auto`
- [ ] Toolbar switch Auto | Manual; banner texts (`strings.ts`)

**Done when:**
- pytest: in Auto, a setting change runs the downstream nodes about 0.5 s
  later; three edits 0.2 s apart start one run; in Manual nothing runs
- pytest: an edit during an auto run leads to a second auto run when the
  first ends; Stop leads to none
- pytest: opening the synthetic workflow in Auto runs it, and a second open
  with a full cache reports every component `cached`; an untrusted open runs
  nothing until trusted; `geoknit run` ignores `run_mode`
- Playwright: on the synthetic example in Auto, moving the `n` slider and
  releasing it updates the metrics Panel without pressing Run

## Step 3: Enable / Disable

- [ ] `Node.enabled`, `"enabled": false` in the workflow (omitted when
      enabled), `_NODE_KEYS`, `apply_dict`
- [ ] Solver: `disabled` state; downstream `skipped` at once with the
      message; excluded from plans and the banner; enabling makes them out
      of date (cache key unchanged)
- [ ] `PATCH /api/nodes/{id}` `enabled`, `POST /api/enable` (one undo step);
      Params nodes refused
- [ ] Map Viewer: affected layer greyed with "source disabled"; disabled Map
      Layer / Map Viewer
- [ ] `geoknit run`: disabled nodes not run, Panels print the skip message,
      "N skipped (disabled upstream)", `RunReport.disabled`, exit code 0 when
      those are the only skips
- [ ] Export: disabled node and downstream as comments, one warning each
- [ ] Canvas: greyed node and wires; Ctrl+E; "Disable (Ctrl+E)" in the
      right-click menu

**Done when:**
- pytest: disabling Reclassify in the synthetic workflow makes its
  downstream `skipped` with "input from Reclassify (n4), which is disabled"
  without a run; enabling it again and running gives `cached` for it
- pytest: save → load → save keeps `"enabled": false` and omits it for
  enabled nodes; the examples keep their bytes
- pytest: `POST /api/enable` on two nodes is undone by one `POST /api/undo`
- pytest (`tests/test_cli.py`): a workflow with a disabled branch exits 0 and
  prints "skipped (disabled upstream)"; the same workflow with a failing
  node exits 1
- pytest: the exported script of a workflow with a disabled node runs, has
  the node as comments and returns one warning
- Playwright: Ctrl+E on two selected nodes greys both; a Map Viewer with one
  disabled source shows the other layer and lists the first as "source
  disabled"

## Step 4: Radial menu

- [ ] Middle press + release under 4 px on a node opens the menu; middle
      drag still pans (also when started on a node); `preventDefault` on the
      press
- [ ] Items Enable/Disable, Run to here, Settings/Code, Show as Text|Icon,
      Help, greyed where they do not apply; icons in the registry; text in
      `strings.ts`
- [ ] Help popover: description and ports from the node view

**Done when:**
- vitest: the menu lists the five items for a component, with
  Enable/Disable greyed for a Slider and Settings/Code greyed for a Panel
- Playwright: middle click on a node opens the menu and "Disable" disables
  it; a middle drag of 50 px from a node pans the canvas and opens no menu
- this SPEC merged into `docs/SPEC.md` (SPEC 6 no longer says runs are
  manual only); change 05 marked done in the index

# Change 05 brief: Run modes, radial menu, disabling nodes

Decisions from the discussion of 26 Nov 2026. They are fixed: a decision
that conflicts with the code, or is much harder than it looks, goes under
"Questions for Xiao" in `SPEC.md` and is not changed there.

## Run modes

- A toolbar switch Auto | Manual, saved in the workflow. Auto is the default
  run mode for new workflows.
- Auto runs out-of-date nodes about 0.5 s after an edit; sliders run on
  release.
- In Auto, a node whose last run took longer than a limit (default 5 s, a
  setting) is not re-run automatically; it stays out of date and the banner
  asks for Run.
- Edits during a run are queued and run when the current run ends, instead
  of answering 409.
- Untrusted workflows never auto-run; the CLI is unaffected.
- It replaces "runs are manual only in v0.1" in SPEC 6.

## Middle-click radial menu on a node (Grasshopper-style)

- A middle click (moving less than about 4 px) opens the menu; a middle drag
  still pans.
- Items: Enable/Disable, Run to here, Settings/Code, Show as Text|Icon, Help
  (description and ports).
- Icons come from the icon registry (Font-GIS → Lucide → Tabler).
- All UI text goes in `strings.ts`.

## Enable / Disable

- A disabled node is greyed out and never runs (Auto, Manual or
  `geoknit run`).
- Downstream nodes are skipped with "input from <name> (<id>), which is
  disabled".
- Enabling it again reuses the cache.
- It is saved as `"enabled": false` in the workflow (the key is omitted when
  enabled) and is one undo step.
- Ctrl+E toggles it for the selected nodes.
- It applies to components, Map Layer and Map Viewer, not Params nodes.
- API: `PATCH /api/nodes/{id}` with `enabled`.
- Export writes a disabled node and its downstream as comments, with a
  warning.

## Answers to the first spec's questions (26 Nov 2026)

1. Change 05 goes in 0.1.0.
2. No time limit, so no setting: every out-of-date node runs in Auto. This
   replaces the "longer than a limit (default 5 s)" decision above.
3. No queue. An edit during a run is applied to the graph immediately and
   answered normally (200 or 400, the usual errors).
   - The running plan finishes on the snapshot of keys and sources it started
     with.
   - When a result arrives, the node becomes done only if its current key
     equals the key it was run with. Otherwise it stays out of date, and the
     result just stays in the cache.
   - When the run ends, Auto starts a new run for whatever is out of date.
   - Deleting a running node is allowed (its result is discarded); undo and
     redo work the same way.
   - Stop only stops; after Stop, Auto does not restart until the next edit.

   This replaces "edits during a run are queued" above.
4. On open in Auto (trusted workflows only), run everything out of date, as
   Grasshopper does when it opens a definition. Cache hits come back
   instantly; only nodes that changed or were never cached compute.
5. `geoknit run` exits 0 when the only skips are caused by disabled nodes,
   and reports "N skipped (disabled upstream)". Errors, and skips caused by
   errors, still give 1.
6. `POST /api/enable {nodes, enabled}`, one undo step.
7. A disabled source skips only that layer of a Map Viewer, shown greyed in
   the layer list with "source disabled".

## Answers to the second spec's questions (26 Nov 2026)

1. Snapshot under the lock, decide done under the lock. Addition: during a
   run, every edit also records the nodes it marks out of date in a
   "superseded" set for the current run.
   - Before starting each snapshot node, the runner checks that set under the
     lock.
   - A superseded node (and its snapshot downstream) is not run: it stays out
     of date, logs "skipped: changed during the run", and Auto picks it up in
     the next run.
   - A node already running finishes, and its result is cached under its old
     key.
   - The runner never reads live code or live states.
2. With the check above, a file writer changed mid-run is skipped if it had
   not started. If it was already running, it writes the old path and logs
   "writing <old path> — path changed during the run".
3. 409 only for a second Run or Test, opening another workflow, Clear cache,
   and Save as into another folder. A plain Save is allowed. The 409 message
   says a run is active and to stop it or wait.
4. Trusting a read-only workflow counts as opening it, and starts the auto
   run.

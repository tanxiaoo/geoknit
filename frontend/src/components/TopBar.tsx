import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, Play, Spline, Square } from "lucide-react";
import type { FileNode } from "../apiTypes";
import { store, useStore } from "../store";
import { strings } from "../strings";

/** Every .geoknit file in the project folder, by relative path. */
export function workflowFiles(tree: FileNode | null): string[] {
  if (!tree) return [];
  if (tree.kind === "file") return tree.name.toLowerCase().endsWith(".geoknit") ? [tree.path] : [];
  return (tree.children ?? []).flatMap(workflowFiles);
}

/** Open another workflow, asking first when this one has unsaved changes. */
export function openWorkflow(path: string): void {
  const g = store.getState().graph;
  if (g?.dirty && !window.confirm(strings.discardChanges)) return;
  void store.open(path);
}

/** Where Export .py writes by default: next to the workflow, so its relative paths work. */
export function exportPath(workflow: string | null): string {
  if (!workflow) return "workflow.py";
  return workflow.replace(/\.geoknit$/i, "") + ".py";
}

function ExportMenu({ path, onClose }: { path: string | null; onClose: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    input.current?.focus();
    const close = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [onClose]);
  const doExport = () => {
    const name = input.current?.value.trim();
    if (!name) return;
    void store.exportPy(name, (m) => window.confirm(m)).then((ok) => ok && onClose());
  };
  return (
    <div className="gk-popover gk-export-menu" ref={box} data-testid="export-menu">
      <div className="gk-save-as">
        <label>{strings.exportAs}</label>
        <input
          ref={input}
          defaultValue={exportPath(path)}
          placeholder={strings.exportPlaceholder}
          onFocus={(e) =>
            e.currentTarget.setSelectionRange(0, e.currentTarget.value.lastIndexOf("."))
          }
          onKeyDown={(e) => {
            if (e.key === "Enter") doExport();
            if (e.key === "Escape") onClose();
          }}
          data-testid="export-input"
        />
        <div className="gk-popover-buttons">
          <button onClick={onClose}>{strings.cancel}</button>
          <button onClick={doExport} data-testid="export-ok">
            {strings.exportButton}
          </button>
        </div>
      </div>
    </div>
  );
}

function FileMenu({ path }: { path: string | null }) {
  const mode = useStore((s) => s.fileMenu);
  const files = useStore((s) => s.files);
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (mode === "closed") return;
    const close = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) store.set({ fileMenu: "closed" });
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [mode]);
  useEffect(() => {
    if (mode === "saveAs") input.current?.focus();
  }, [mode]);

  if (mode === "closed") return null;
  const saveAs = () => {
    const name = input.current?.value.trim();
    if (name) void store.save(name);
  };
  return (
    <div className="gk-popover gk-file-menu" ref={box} data-testid="file-menu">
      {mode === "saveAs" ? (
        <div className="gk-save-as">
          <label>{strings.saveAs}</label>
          <input
            ref={input}
            defaultValue={path ?? strings.untitled}
            placeholder={strings.saveAsPlaceholder}
            onFocus={(e) =>
              e.currentTarget.setSelectionRange(0, e.currentTarget.value.lastIndexOf("."))
            }
            onKeyDown={(e) => {
              if (e.key === "Enter") saveAs();
              if (e.key === "Escape") store.set({ fileMenu: "closed" });
            }}
            data-testid="save-as-input"
          />
          <div className="gk-popover-buttons">
            <button onClick={() => store.set({ fileMenu: "closed" })}>{strings.cancel}</button>
            <button onClick={saveAs} data-testid="save-as-ok">
              {strings.save}
            </button>
          </div>
        </div>
      ) : (
        <div className="gk-menu">
          <button onClick={() => void store.save()} data-testid="menu-save">
            {strings.shortcut(strings.save, "Ctrl+S")}
          </button>
          <button onClick={() => store.set({ fileMenu: "saveAs" })} data-testid="menu-save-as">
            {strings.saveAs}
          </button>
          <div className="gk-menu-heading">{strings.open}</div>
          {workflowFiles(files).length ? (
            workflowFiles(files).map((f) => (
              <button
                key={f}
                className={f === path ? "gk-current" : ""}
                onClick={() => openWorkflow(f)}
                data-testid={`menu-open-${f}`}
              >
                {f}
              </button>
            ))
          ) : (
            <span className="gk-muted">{strings.noWorkflows}</span>
          )}
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const path = useStore((s) => s.graph?.path ?? null);
  const dirty = useStore((s) => s.graph?.dirty ?? false);
  const menu = useStore((s) => s.fileMenu);
  const status = useStore((s) => s.status);
  const connected = useStore((s) => s.connected);
  const name = path ? (path.split("/").pop() ?? path) : strings.untitled;
  const saveState = !path ? strings.notSaved : dirty ? strings.unsaved : strings.saved;
  const worker = !connected
    ? strings.workerOffline
    : status?.worker === "running"
      ? strings.workerRunning
      : strings.workerIdle;
  const state = !connected ? "offline" : (status?.worker ?? "idle");
  const [exporting, setExporting] = useState(false);
  const closeExport = useCallback(() => setExporting(false), []);
  return (
    <header className="gk-topbar">
      <div className="gk-logo">
        <Spline size={22} />
        <span>{strings.appTitle}</span>
      </div>
      <div className="gk-file">
        <button
          className="gk-filename"
          title={strings.fileMenu}
          onClick={() => store.set({ fileMenu: menu === "closed" ? "menu" : "closed" })}
          data-testid="file-name"
        >
          {name}
          <span className={`gk-save-state${dirty ? " gk-dirty" : ""}`} data-testid="save-state">
            {" "}
            · {saveState}
          </span>
          <ChevronDown size={13} />
        </button>
        <FileMenu path={path} />
      </div>
      <div className="gk-spacer" />
      <span className={`gk-worker gk-worker-${state}`} data-testid="worker-status">
        <span className="gk-worker-dot" />
        {strings.workerStatus(status?.python ?? "?", worker)}
      </span>
      <div className="gk-export">
        <button
          className="gk-top-button"
          title={strings.exportHint}
          onClick={() => setExporting(!exporting)}
          data-testid="export-py"
        >
          {strings.exportPy}
        </button>
        {exporting && <ExportMenu path={path} onClose={closeExport} />}
      </div>
      <button className="gk-top-button" onClick={() => void store.stop()} data-testid="stop">
        <Square size={14} />
        {strings.stop}
      </button>
      <button className="gk-top-button gk-run" onClick={() => void store.run()} data-testid="run">
        <Play size={14} />
        {strings.run}
      </button>
    </header>
  );
}

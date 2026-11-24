import { Play, Spline, Square } from "lucide-react";
import { store, useStore } from "../store";
import { strings } from "../strings";

export function TopBar() {
  const path = useStore((s) => s.graph?.path ?? null);
  const status = useStore((s) => s.status);
  const connected = useStore((s) => s.connected);
  const name = path ? (path.split("/").pop() ?? path) : strings.untitled;
  const worker = !connected
    ? strings.workerOffline
    : status?.worker === "running"
      ? strings.workerRunning
      : strings.workerIdle;
  const state = !connected ? "offline" : (status?.worker ?? "idle");
  return (
    <header className="gk-topbar">
      <div className="gk-logo">
        <Spline size={22} />
        <span>{strings.appTitle}</span>
      </div>
      <span className="gk-filename" data-testid="file-name">
        {name}
        {!path && <span className="gk-save-state"> · {strings.notSaved}</span>}
      </span>
      <div className="gk-spacer" />
      <span className={`gk-worker gk-worker-${state}`} data-testid="worker-status">
        <span className="gk-worker-dot" />
        {strings.workerStatus(status?.python ?? "?", worker)}
      </span>
      <button className="gk-top-button" disabled title={strings.exportLater}>
        {strings.exportPy}
      </button>
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

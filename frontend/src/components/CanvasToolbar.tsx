import { useReactFlow, useViewport } from "@xyflow/react";
import { Minus, Plus } from "lucide-react";
import { store, useStore } from "../store";
import { strings } from "../strings";

export function CanvasToolbar() {
  const flow = useReactFlow();
  const { zoom } = useViewport();
  const display = useStore((s) => s.graph?.workflow.view.display ?? "text");
  const outOfDate = useStore((s) => s.graph?.out_of_date ?? 0);
  const lastChange = useStore((s) => s.lastChange);
  const trusted = useStore((s) => s.graph?.trusted ?? true);
  const running = useStore((s) => s.status?.worker === "running");

  return (
    <div className="gk-toolbar">
      <button onClick={() => void flow.zoomOut()} title={strings.zoomOut} data-testid="zoom-out">
        <Minus size={14} />
      </button>
      <span className="gk-zoom" data-testid="zoom">
        {Math.round(zoom * 100)}%
      </span>
      <button onClick={() => void flow.zoomIn()} title={strings.zoomIn} data-testid="zoom-in">
        <Plus size={14} />
      </button>
      <button onClick={() => void flow.fitView({ padding: 0.1, maxZoom: 1 })} data-testid="fit">
        {strings.fit}
      </button>
      <span className="gk-muted">{strings.showAs}</span>
      <div className="gk-toggle">
        {(["text", "icon"] as const).map((d) => (
          <button
            key={d}
            className={display === d ? "gk-on" : ""}
            onClick={() => void store.setDisplay(d)}
            data-testid={`show-${d}`}
          >
            {d === "text" ? strings.showText : strings.showIcon}
          </button>
        ))}
      </div>
      <span className="gk-hint">{strings.canvasHint}</span>
      <div className="gk-spacer" />
      {!trusted ? (
        <div className="gk-banner gk-banner-trust">
          {strings.untrusted}
          <button onClick={() => void store.trust()}>{strings.trust}</button>
        </div>
      ) : (
        outOfDate > 0 &&
        !running && (
          <div className="gk-banner" data-testid="banner">
            <span className="gk-dot-inline" />
            <span data-testid="banner-text">
              {lastChange ? `${strings.changed(lastChange)} · ` : ""}
              {strings.outOfDate(outOfDate)}
            </span>
            <button onClick={() => void store.run()} data-testid="banner-run">
              {strings.run}
            </button>
          </div>
        )
      )}
    </div>
  );
}

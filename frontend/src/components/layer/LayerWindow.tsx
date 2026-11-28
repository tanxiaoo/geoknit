import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { RotateCcw, X } from "lucide-react";
import type { ColormapJson, MapLayerInfo, NamedRamps, NodePatch, NodeView } from "../../apiTypes";
import { DEFAULT_VECTOR_COLOUR } from "../../palettes";
import { store, useCategoryColour, useStore } from "../../store";
import { strings } from "../../strings";
import { CommitInput } from "../colormap/ColormapWindow";
import { normHex } from "../colormap/edit";
import { pickerValue, withAlpha } from "../nodes/ColorNode";
import { colormapLabel, isColormap, Strip } from "../nodes/ColormapNode";
import {
  clampOpacity,
  fieldLabel,
  plainRamp,
  shownFields,
  shownValue,
  wiredFrom,
  type StyleField,
} from "./style";

/** The colormap dropdown's entry for a colormap that is more than a named ramp. */
const EDITED = "__edited__";
const WIDTH = 380;
/** A picker or slider sends a value per move; the patch waits until it rests. */
export const LAYER_DELAY_MS = 400;

type StyleEdit = NonNullable<NodePatch["style"]>;

/** The floating style window of the open Map Layer (change 03, section 3): the values of
 * its unwired style inputs, saved on the node under `style`. */
export function LayerWindow() {
  const id = useStore((s) => s.layerNode);
  const view = useStore((s) => (id ? s.graph?.nodes[id] : undefined));
  if (!id || !view) return null;
  return <Window key={id} view={view} />;
}

function Window({ view }: { view: NodeView }) {
  const id = view.id;
  const graph = useStore((s) => s.graph);
  const ramps: NamedRamps = useStore((s) => s.ramps) ?? {};
  const runCount = useStore((s) => s.runCount);
  const colour = useCategoryColour("Display");
  const build = view.layer ?? null;
  const style = view.style ?? {};
  const kind = build?.value?.kind ?? null;

  // the data's columns (the `field` dropdown), once it has a result
  const [info, setInfo] = useState<MapLayerInfo | null>(null);
  useEffect(() => {
    let live = true;
    store.api.layerInfo(id).then(
      (i) => live && setInfo(i),
      () => live && setInfo(null),
    );
    return () => {
      live = false;
    };
  }, [id, build?.key, view.state, runCount]);

  // what the window shows: the saved style, or edits not answered yet (a drag, a picker)
  const [draft, setDraft] = useState<StyleEdit>({});
  const pending = useRef<StyleEdit>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [refused, setRefused] = useState(0); // remounts the text fields after a refusal
  // PATCHes sent and not answered: the saved style may not hold the last edit yet
  const inflight = useRef(0);
  const [settled, setSettled] = useState(0);
  const epoch = useRef(store.workflowEpoch);

  useEffect(() => {
    if (!Object.keys(pending.current).length && !timer.current && !inflight.current) setDraft({});
  }, [view, settled]);

  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const patch = pending.current;
    pending.current = {};
    if (!Object.keys(patch).length) return;
    if (store.workflowEpoch !== epoch.current) return; // another workflow is open now
    inflight.current += 1;
    void store.tryPatchNode(id, { style: patch }).then((ok) => {
      inflight.current -= 1;
      if (!ok) {
        setDraft({});
        setRefused((n) => n + 1);
      }
      setSettled((n) => n + 1);
    });
  }, [id]);
  useEffect(() => () => flush(), [flush]); // closing the window sends what is left

  /** One edit, one PATCH (one undo step); ``defer`` waits until the edits rest. */
  const change = <K extends StyleField>(field: K, value: StyleEdit[K], defer = false) => {
    setDraft((d) => ({ ...d, [field]: value }));
    pending.current = { ...pending.current, [field]: value };
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (defer) timer.current = setTimeout(flush, LAYER_DELAY_MS);
    else flush();
  };
  const current = <K extends StyleField>(field: K): StyleEdit[K] | undefined =>
    field in draft ? draft[field] : style[field];

  const resetAll = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    pending.current = {};
    setDraft({});
    void store.patchNode(id, { style: null });
  };

  // ── moving the window by its header (as the Colormap editor) ──
  const [pos, setPos] = useState(() => ({
    x: Math.max(20, window.innerWidth - WIDTH - 340),
    y: 110,
  }));
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const onHeaderDown = (e: ReactPointerEvent) => {
    if ((e.target as Element).closest("button")) return;
    drag.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };
  const onHeaderMove = (e: ReactPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    setPos({
      x: Math.min(Math.max(0, e.clientX - d.dx), window.innerWidth - 120),
      y: Math.min(Math.max(0, e.clientY - d.dy), window.innerHeight - 60),
    });
  };

  const issues = build?.issues ?? {};
  const fields = shownFields(kind, build?.wired ?? {});

  const editor = (field: StyleField) => {
    switch (field) {
      case "colormap":
        return (
          <ColormapField
            value={current("colormap")}
            ramps={ramps}
            onChange={(v) => change("colormap", v)}
          />
        );
      case "color": {
        const value = current("color") ?? null;
        return (
          <span className="gk-cm-colour">
            <input
              type="color"
              value={pickerValue(value ?? DEFAULT_VECTOR_COLOUR)}
              onChange={(e) => change("color", withAlpha(e.currentTarget.value, value ?? ""), true)}
              aria-label={strings.colorPicker}
              data-testid="layer-color-picker"
            />
            <CommitInput
              key={refused}
              value={value ?? ""}
              placeholder={DEFAULT_VECTOR_COLOUR.toUpperCase()}
              className="gk-cm-hex"
              aria-label={strings.colorHex}
              onCommit={(text) => {
                if (!text.trim()) {
                  change("color", null);
                  return true;
                }
                const hex = normHex(text);
                if (!hex) return false;
                change("color", hex);
                return true;
              }}
              data-testid="layer-color-hex"
            />
          </span>
        );
      }
      case "opacity": {
        const raw = current("opacity");
        const value = typeof raw === "number" ? raw : 1;
        return (
          <span className="gk-layer-opacity">
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={value}
              onChange={(e) => change("opacity", clampOpacity(Number(e.currentTarget.value)), true)}
              onPointerUp={flush}
              onKeyUp={flush}
              aria-label={strings.opacity}
              data-testid="layer-opacity"
            />
            <span className="gk-layer-number" data-testid="layer-opacity-value">
              {value.toFixed(2)}
            </span>
          </span>
        );
      }
      case "bands":
      case "name":
        return (
          <CommitInput
            key={refused}
            value={current(field) ?? ""}
            placeholder={
              field === "name" ? (build?.value?.name ?? strings.layerDefault) : strings.layerDefault
            }
            title={field === "bands" ? strings.layerBandsHint : undefined}
            aria-label={fieldLabel(field)}
            onCommit={(text) => {
              change(field, text.trim() ? text.trim() : null);
              return true;
            }}
            data-testid={`layer-${field}`}
          />
        );
      case "field": {
        const value = current("field") ?? "";
        const columns = info?.columns ?? null;
        const options = columns ?? (value ? [value] : []);
        return (
          <select
            value={value}
            disabled={columns === null}
            title={columns === null ? strings.layerFieldLater : undefined}
            onChange={(e) => change("field", e.currentTarget.value || null)}
            data-testid="layer-field"
          >
            <option value="">{strings.layerFieldNone}</option>
            {options.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        );
      }
    }
  };

  const wiredValue = (field: Exclude<StyleField, "field">) => {
    const v = build?.value?.[field] ?? null;
    if (field === "colormap" && isColormap(v)) {
      return (
        <span className="gk-panel-inline">
          <Strip cm={v} ramps={ramps} />
          {colormapLabel(v)}
        </span>
      );
    }
    if (field === "color" && typeof v === "string") {
      return (
        <span className="gk-panel-inline">
          <span className="gk-panel-chip" style={{ background: v }} />
          {v}
        </span>
      );
    }
    return <>{shownValue(v)}</>;
  };

  return (
    <div
      className="gk-window gk-cm-window gk-layer-window"
      style={{ left: pos.x, top: pos.y, width: WIDTH }}
      role="dialog"
      aria-label={strings.mapLayer}
      data-testid="layer-window"
      onKeyDown={(e) => {
        if (e.key === "Escape") store.closeLayer();
        // typing in the window is not a canvas shortcut
        if ((e.ctrlKey || e.metaKey) && ["c", "v", "x"].includes(e.key.toLowerCase())) {
          e.stopPropagation();
        }
      }}
    >
      <header
        className="gk-window-header"
        onPointerDown={onHeaderDown}
        onPointerMove={onHeaderMove}
        onPointerUp={() => (drag.current = null)}
      >
        <span className="gk-window-category" style={{ color: colour }}>
          {strings.displayTab}
        </span>
        <span className="gk-window-title">{view.title}</span>
        <div className="gk-spacer" />
        <button
          className="gk-icon-button"
          onClick={() => store.closeLayer()}
          aria-label={strings.close}
          data-testid="layer-close"
        >
          <X size={16} />
        </button>
      </header>
      <div className="gk-cm-body">
        {issues.data && (
          <p className="gk-layer-issue" role="status" data-testid="layer-issue-data">
            {strings.layerIssue(fieldLabel("data"), issues.data)}
          </p>
        )}
        {fields.map((field) => {
          const from = field === "field" ? null : wiredFrom(graph, build, id, field);
          return (
            <div className="gk-layer-row" key={field} data-testid={`layer-row-${field}`}>
              <div className="gk-cm-field">
                <span>{fieldLabel(field)}</span>
                {from && field !== "field" ? (
                  <span className="gk-layer-wired" data-testid={`layer-${field}-wired`}>
                    {wiredValue(field)}
                    <span className="gk-layer-from">{from}</span>
                  </span>
                ) : (
                  editor(field)
                )}
              </div>
              {issues[field] && (
                <p className="gk-layer-issue" role="status" data-testid={`layer-issue-${field}`}>
                  {strings.layerIssue(fieldLabel(field), issues[field])}
                </p>
              )}
              {field === "field" && info?.columns === null && build?.value && (
                <p className="gk-cm-hint">{strings.layerFieldLater}</p>
              )}
            </div>
          );
        })}
        <div className="gk-layer-footer">
          <span className="gk-cm-hint">{strings.layerNoRunHint}</span>
          <button
            type="button"
            onClick={resetAll}
            disabled={!Object.keys(style).length}
            data-testid="layer-reset-all"
          >
            <RotateCcw size={13} aria-hidden />
            {strings.layerResetAll}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Named ramps plus none; a colormap set otherwise (wired before, or edited) shows as such. */
function ColormapField({
  value,
  ramps,
  onChange,
}: {
  value: ColormapJson | string | null | undefined;
  ramps: NamedRamps;
  onChange: (v: string | null) => void;
}) {
  const cm: ColormapJson | null =
    typeof value === "string"
      ? { kind: "continuous", name: value, min: null, max: null, reverse: false }
      : (value ?? null);
  const plain = cm ? plainRamp(cm) : null;
  const selected = !cm ? "" : (plain ?? EDITED);
  const names = Object.keys(ramps);
  if (plain && !names.includes(plain)) names.push(plain);
  return (
    <span className="gk-layer-colormap">
      {cm && <Strip cm={cm} ramps={ramps} />}
      <select
        value={selected}
        onChange={(e) => {
          const v = e.currentTarget.value;
          if (v !== EDITED) onChange(v || null);
        }}
        aria-label={strings.colormap}
        data-testid="layer-colormap"
      >
        <option value="">{strings.layerColormapNone}</option>
        {names.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
        {selected === EDITED && cm && (
          <option value={EDITED} disabled>
            {strings.layerColormapEdited(colormapLabel(cm))}
          </option>
        )}
      </select>
    </span>
  );
}

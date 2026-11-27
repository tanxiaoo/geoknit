import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ClipboardEvent as ReactClipboardEvent,
  type InputHTMLAttributes,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { ArrowDown, ArrowUp, Plus, Trash2, X } from "lucide-react";
import type { ColormapJson, NamedRamps, NodeView } from "../../apiTypes";
import { DEFAULT_OTHER_COLOUR } from "../../palettes";
import { store, useCategoryColour, useStore } from "../../store";
import { strings } from "../../strings";
import { pickerValue, withAlpha } from "../nodes/ColorNode";
import { DEFAULT_COLORMAP, gradientCss, isColormap, stopsOf, Strip } from "../nodes/ColormapNode";
import {
  addClass,
  addStop,
  clampPos,
  evenStops,
  fillFromRamp,
  moveClass,
  moveStop,
  normHex,
  parseClassTable,
  problem,
  removeClass,
  removeStop,
  setClass,
  setStopColour,
  startClasses,
  START_CONTINUOUS,
  type ClassRow,
  type Classes,
  type Continuous,
  type Stop,
} from "./edit";

/** The ramp picker's entry for edited stops. */
const CUSTOM = "__custom__";
const WIDTH = 480;
/** A colour picker sends a value per move; the patch waits until it rests. */
const PICKER_DELAY_MS = 400;

/** The floating editor window of the open Colormap node (change 03, section 2). */
export function ColormapWindow() {
  const id = useStore((s) => s.colormapNode);
  const view = useStore((s) => (id ? s.graph?.nodes[id] : undefined));
  if (!id || !view) return null;
  return <Editor key={id} view={view} />;
}

const same = (a: ColormapJson, b: ColormapJson): boolean => JSON.stringify(a) === JSON.stringify(b);

function Editor({ view }: { view: NodeView }) {
  const id = view.id;
  const ramps: NamedRamps = useStore((s) => s.ramps) ?? {};
  const colour = useCategoryColour("Params");
  const server = isColormap(view.value) ? view.value : DEFAULT_COLORMAP;
  const serverRef = useRef(server);
  serverRef.current = server;

  // what the window shows: the server's value, or an edit not sent yet (a drag, a picker)
  const [draft, setDraft] = useState<ColormapJson>(server);
  const pending = useRef<ColormapJson | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const busy = useRef(false); // a stop is being dragged
  // the other kind as last edited, so switching Kind back and forth keeps it
  const otherKind = useRef<ColormapJson | null>(null);

  useEffect(() => {
    if (!pending.current && !busy.current) setDraft(serverRef.current);
  }, [view]);

  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const next = pending.current;
    pending.current = null;
    if (!next || same(next, serverRef.current)) return;
    const why = problem(next);
    if (why) {
      store.showToast(why);
      setDraft(serverRef.current);
      return;
    }
    void store.patchNode(id, { value: next });
  }, [id]);
  useEffect(() => () => flush(), [flush]); // closing the window sends what is left

  /** One edit, one PATCH (one undo step); ``defer`` waits until the edits rest. */
  const change = (next: ColormapJson, defer = false) => {
    setDraft(next);
    pending.current = next;
    if (timer.current) clearTimeout(timer.current);
    if (defer) timer.current = setTimeout(flush, PICKER_DELAY_MS);
    else flush();
  };

  const setKind = (kind: ColormapJson["kind"]) => {
    if (kind === draft.kind) return;
    const back = otherKind.current?.kind === kind ? otherKind.current : null;
    otherKind.current = draft;
    change(back ?? (kind === "classes" ? startClasses(stopsOf(draft, ramps)) : START_CONTINUOUS));
  };

  // ── moving the window by its header (as the map window) ──
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

  return (
    <div
      className="gk-window gk-cm-window"
      style={{ left: pos.x, top: pos.y, width: WIDTH }}
      role="dialog"
      aria-label={strings.colormap}
      data-testid="colormap-window"
      onKeyDown={(e) => {
        if (e.key === "Escape") store.closeColormap();
        // a paste into the class table is not a paste of nodes on the canvas
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
          {strings.paramsTab}
        </span>
        <span className="gk-window-title">{view.title}</span>
        <div className="gk-spacer" />
        <button
          className="gk-icon-button"
          onClick={() => store.closeColormap()}
          aria-label={strings.close}
          data-testid="colormap-close"
        >
          <X size={16} />
        </button>
      </header>
      <div className="gk-cm-body">
        <Strip cm={draft} ramps={ramps} className="gk-cm-preview" testId="cm-preview" />
        <div className="gk-cm-field">
          <span>{strings.cmKind}</span>
          <div className="gk-cm-segmented" role="radiogroup" aria-label={strings.cmKind}>
            {(["continuous", "classes"] as const).map((k) => (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={draft.kind === k}
                className={draft.kind === k ? "gk-cm-on" : ""}
                onClick={() => setKind(k)}
                data-testid={`cm-kind-${k}`}
              >
                {k === "continuous" ? strings.cmContinuous : strings.cmClasses}
              </button>
            ))}
          </div>
        </div>
        {draft.kind === "continuous" ? (
          <ContinuousEditor cm={draft} ramps={ramps} change={change} preview={setDraft} busy={busy} />
        ) : (
          <ClassesEditor cm={draft} ramps={ramps} change={change} />
        )}
      </div>
    </div>
  );
}

type Change = (next: ColormapJson, defer?: boolean) => void;

// ── continuous ──

function ContinuousEditor({
  cm,
  ramps,
  change,
  preview,
  busy,
}: {
  cm: Continuous;
  ramps: NamedRamps;
  change: Change;
  preview: (next: ColormapJson) => void;
  busy: { current: boolean };
}) {
  const custom = Boolean(cm.stops) || !cm.name;
  const names = Object.keys(ramps);
  const onRamp = (v: string) => {
    if (v === CUSTOM) {
      if (custom) return;
      change({ ...cm, name: null, stops: evenStops(ramps[cm.name ?? ""] ?? []) });
    } else {
      change({ kind: "continuous", name: v, min: cm.min, max: cm.max, reverse: cm.reverse });
    }
  };
  return (
    <>
      <label className="gk-cm-field">
        <span>{strings.cmRamp}</span>
        <select
          value={custom ? CUSTOM : (cm.name ?? CUSTOM)}
          onChange={(e) => onRamp(e.currentTarget.value)}
          data-testid="cm-ramp"
        >
          {names.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
          <option value={CUSTOM} disabled={!custom && !ramps[cm.name ?? ""]}>
            {strings.cmCustomRamp}
          </option>
        </select>
      </label>
      <label className="gk-cm-field">
        <span>{strings.colormapReverse}</span>
        <input
          type="checkbox"
          checked={cm.reverse}
          onChange={(e) => change({ ...cm, reverse: e.currentTarget.checked })}
          data-testid="cm-reverse"
        />
      </label>
      <Bound
        label={strings.min}
        value={cm.min}
        fallback={cm.max !== null ? cm.max - 1 : 0}
        onChange={(min) => change({ ...cm, min })}
        testId="cm-min"
      />
      <Bound
        label={strings.max}
        value={cm.max}
        fallback={cm.min !== null ? cm.min + 1 : 1}
        onChange={(max) => change({ ...cm, max })}
        testId="cm-max"
      />
      {cm.stops && (
        <StopsEditor
          stops={cm.stops}
          change={(stops, defer) => change({ ...cm, stops }, defer)}
          preview={(stops) => preview({ ...cm, stops })}
          busy={busy}
        />
      )}
    </>
  );
}

function Bound({
  label,
  value,
  fallback,
  onChange,
  testId,
}: {
  label: string;
  value: number | null;
  fallback: number;
  onChange: (v: number | null) => void;
  testId: string;
}) {
  return (
    <div className="gk-cm-field">
      <span>{label}</span>
      <div className="gk-cm-bound">
        <label title={strings.cmAutoHint}>
          <input
            type="checkbox"
            checked={value === null}
            onChange={(e) => onChange(e.currentTarget.checked ? null : fallback)}
            data-testid={`${testId}-auto`}
          />
          <span>{strings.cmAuto}</span>
        </label>
        <CommitInput
          value={value === null ? "" : String(value)}
          disabled={value === null}
          inputMode="decimal"
          aria-label={label}
          onCommit={(text) => {
            const n = text.trim() === "" ? NaN : Number(text);
            if (!Number.isFinite(n)) return false;
            onChange(n);
            return true;
          }}
          data-testid={testId}
        />
      </div>
    </div>
  );
}

function StopsEditor({
  stops,
  change,
  preview,
  busy,
}: {
  stops: Stop[];
  change: (stops: Stop[], defer?: boolean) => void;
  preview: (stops: Stop[]) => void;
  busy: { current: boolean };
}) {
  const [sel, setSel] = useState(0);
  const index = Math.min(sel, stops.length - 1);
  const bar = useRef<HTMLDivElement>(null);
  const dragging = useRef<{ from: Stop[]; index: number; latest: Stop[] | null } | null>(null);
  const dragged = useRef(false); // the click that ends a drag adds no stop

  const at = (clientX: number): number => {
    const r = bar.current?.getBoundingClientRect();
    return r && r.width > 0 ? clampPos((clientX - r.left) / r.width) : 0;
  };
  const onStopDown = (e: ReactPointerEvent, i: number) => {
    e.stopPropagation();
    setSel(i);
    dragging.current = { from: stops, index: i, latest: null };
    busy.current = true;
    bar.current?.setPointerCapture(e.pointerId);
  };
  const onMove = (e: ReactPointerEvent) => {
    const d = dragging.current;
    if (!d) return;
    const moved = moveStop(d.from, d.index, at(e.clientX));
    d.latest = moved.stops;
    setSel(moved.index);
    preview(moved.stops);
  };
  const onUp = () => {
    const d = dragging.current;
    if (!d) return;
    dragging.current = null;
    busy.current = false;
    dragged.current = true;
    if (d.latest) change(d.latest); // the whole drag is one patch
  };
  const onBarClick = (e: ReactMouseEvent) => {
    if (dragged.current) {
      dragged.current = false;
      return;
    }
    if (e.target !== e.currentTarget) return;
    const added = addStop(stops, at(e.clientX));
    setSel(added.index);
    change(added.stops);
  };

  const [p, c] = stops[index];
  return (
    <div className="gk-cm-stops">
      <span className="gk-cm-hint">{strings.cmStopsHint}</span>
      <div
        ref={bar}
        className="gk-cm-bar"
        style={{ background: gradientCss(stops) }}
        onClick={onBarClick}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        data-testid="cm-stops-bar"
      >
        {stops.map(([sp, sc], i) => (
          <span
            key={i}
            className={`gk-cm-stop${i === index ? " gk-cm-on" : ""}`}
            style={{ left: `${sp * 100}%`, background: sc }}
            onPointerDown={(e) => onStopDown(e, i)}
            title={strings.cmStop(i)}
            data-testid={`cm-stop-${i}`}
          />
        ))}
      </div>
      <div className="gk-cm-stop-edit" data-testid="cm-stop-edit">
        <span className="gk-cm-stop-name">{strings.cmStop(index)}</span>
        <ColourField
          value={c}
          onChange={(hex, defer) => change(setStopColour(stops, index, hex), defer)}
          testId="cm-stop"
        />
        <label className="gk-cm-pos">
          <span>{strings.cmPosition}</span>
          <CommitInput
            value={String(p)}
            inputMode="decimal"
            onCommit={(text) => {
              const n = text.trim() === "" ? NaN : Number(text);
              if (!Number.isFinite(n) || n < 0 || n > 1) return false;
              const moved = moveStop(stops, index, n);
              setSel(moved.index);
              change(moved.stops);
              return true;
            }}
            data-testid="cm-stop-pos"
          />
        </label>
        <button
          type="button"
          className="gk-icon-button"
          disabled={stops.length <= 2}
          onClick={() => {
            setSel(Math.max(0, index - 1));
            change(removeStop(stops, index));
          }}
          title={strings.cmRemoveStop}
          aria-label={strings.cmRemoveStop}
          data-testid="cm-stop-remove"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}

// ── classes ──

function ClassesEditor({ cm, ramps, change }: { cm: Classes; ramps: NamedRamps; change: Change }) {
  const names = Object.keys(ramps);
  const [fillRamp, setFillRamp] = useState("viridis");
  const fillFrom = ramps[fillRamp] ? fillRamp : (names[0] ?? "");
  const set = (classes: ClassRow[], defer = false) => change({ ...cm, classes }, defer);

  const onPaste = (e: ReactClipboardEvent) => {
    const rows = parseClassTable(e.clipboardData.getData("text/plain"));
    if (rows) {
      e.preventDefault();
      set(rows);
    } else if (!(e.target instanceof HTMLInputElement)) {
      store.showToast(strings.cmPasteFailed);
    }
  };

  return (
    <>
      <div
        className="gk-cm-table"
        tabIndex={0}
        onPaste={onPaste}
        title={strings.cmPasteHint}
        data-testid="cm-classes"
      >
        <div className="gk-cm-row gk-cm-head">
          <span>{strings.cmValue}</span>
          <span>{strings.colour}</span>
          <span>{strings.cmLabel}</span>
          <span />
        </div>
        {cm.classes.map(([value, colour, label], i) => (
          <div className="gk-cm-row" key={i} data-testid={`cm-class-${i}`}>
            <CommitInput
              value={String(value)}
              inputMode="decimal"
              aria-label={strings.cmValue}
              onCommit={(text) => {
                const n = text.trim() === "" ? NaN : Number(text);
                if (!Number.isFinite(n)) return false;
                set(setClass(cm.classes, i, { value: n }));
                return true;
              }}
              data-testid={`cm-class-value-${i}`}
            />
            <ColourField
              value={colour}
              onChange={(hex, defer) => set(setClass(cm.classes, i, { colour: hex }), defer)}
              testId={`cm-class-colour-${i}`}
            />
            <CommitInput
              value={label}
              aria-label={strings.cmLabel}
              onCommit={(text) => {
                set(setClass(cm.classes, i, { label: text }));
                return true;
              }}
              data-testid={`cm-class-label-${i}`}
            />
            <div className="gk-cm-row-buttons">
              <button
                type="button"
                className="gk-icon-button"
                disabled={i === 0}
                onClick={() => set(moveClass(cm.classes, i, -1))}
                title={strings.cmMoveUp}
                aria-label={strings.cmMoveUp}
                data-testid={`cm-class-up-${i}`}
              >
                <ArrowUp size={13} />
              </button>
              <button
                type="button"
                className="gk-icon-button"
                disabled={i === cm.classes.length - 1}
                onClick={() => set(moveClass(cm.classes, i, 1))}
                title={strings.cmMoveDown}
                aria-label={strings.cmMoveDown}
                data-testid={`cm-class-down-${i}`}
              >
                <ArrowDown size={13} />
              </button>
              <button
                type="button"
                className="gk-icon-button"
                disabled={cm.classes.length <= 1}
                onClick={() => set(removeClass(cm.classes, i))}
                title={strings.cmRemoveClass}
                aria-label={strings.cmRemoveClass}
                data-testid={`cm-class-remove-${i}`}
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="gk-cm-actions">
        <button type="button" onClick={() => set(addClass(cm.classes))} data-testid="cm-class-add">
          <Plus size={13} />
          <span>{strings.cmAddClass}</span>
        </button>
        <span className="gk-cm-hint">{strings.cmPasteHint}</span>
      </div>
      <div className="gk-cm-field">
        <span>{strings.cmOther}</span>
        <div className="gk-cm-other">
          <label>
            <input
              type="radio"
              name="gk-cm-other"
              checked={cm.other === null}
              onChange={() => change({ ...cm, other: null })}
              data-testid="cm-other-transparent"
            />
            <span>{strings.cmTransparent}</span>
          </label>
          <label>
            <input
              type="radio"
              name="gk-cm-other"
              checked={cm.other !== null}
              onChange={() => change({ ...cm, other: DEFAULT_OTHER_COLOUR })}
              data-testid="cm-other-colour"
            />
            <span>{strings.colour}</span>
          </label>
          {cm.other !== null && (
            <ColourField
              value={cm.other}
              onChange={(hex, defer) => change({ ...cm, other: hex }, defer)}
              testId="cm-other"
            />
          )}
        </div>
      </div>
      <div className="gk-cm-field">
        <span>{strings.cmFill}</span>
        <div className="gk-cm-fill">
          <select
            value={fillFrom}
            onChange={(e) => setFillRamp(e.currentTarget.value)}
            aria-label={strings.cmFillRamp}
            data-testid="cm-fill-ramp"
          >
            {names.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!ramps[fillFrom]}
            onClick={() => set(fillFromRamp(cm.classes, ramps[fillFrom] ?? []))}
            data-testid="cm-fill"
          >
            {strings.cmFill}
          </button>
        </div>
      </div>
    </>
  );
}

// ── small fields ──

/** A colour picker and a hex field. The picker's moves are sent once it rests. */
function ColourField({
  value,
  onChange,
  testId,
}: {
  value: string;
  onChange: (hex: string, defer: boolean) => void;
  testId: string;
}) {
  return (
    <span className="gk-cm-colour">
      <input
        type="color"
        value={pickerValue(value)}
        onChange={(e) => onChange(withAlpha(e.currentTarget.value, value), true)}
        aria-label={strings.colorPicker}
        data-testid={`${testId}-picker`}
      />
      <CommitInput
        value={value}
        className="gk-cm-hex"
        aria-label={strings.colorHex}
        onCommit={(text) => {
          const hex = normHex(text);
          if (!hex) return false;
          onChange(hex, false);
          return true;
        }}
        data-testid={`${testId}-hex`}
      />
    </span>
  );
}

type CommitProps = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
  value: string;
  /** False puts the field back to ``value``. */
  onCommit: (text: string) => boolean;
  "data-testid"?: string;
};

/** A text field that sends its text on Enter or when it loses focus, not per key. */
function CommitInput({ value, onCommit, ...rest }: CommitProps) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = () => {
    if (text !== value && !onCommit(text)) setText(value);
  };
  return (
    <input
      {...rest}
      value={text}
      onChange={(e) => setText(e.currentTarget.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        else if (e.key === "Escape") {
          setText(value);
          e.stopPropagation(); // the first Escape only undoes the typing
        }
      }}
    />
  );
}

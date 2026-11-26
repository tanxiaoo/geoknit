import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { X } from "lucide-react";
import type {
  GraphView,
  NodeView,
  PortEdit,
  PortType,
  PortView,
  SettingView,
} from "../../apiTypes";
import { store, useStore } from "../../store";
import { strings } from "../../strings";
import {
  categoryColour,
  EDITABLE_PORT_TYPES,
  PARAM_SLIDER,
  PARAM_TEXT,
  PORT_COLOURS,
} from "../../types";
import { CodeEditor } from "./CodeEditor";
import { defaultFor, errorLine, freshName, parseValue, valueText } from "./values";

type Tab = "settings" | "code";

/** The floating component window of the node being edited (SPEC 8). */
export function ComponentWindow() {
  const id = useStore((s) => s.windowNode);
  const view = useStore((s) => (id ? s.graph?.nodes[id] : undefined));
  if (!id || !view || view.source === undefined) return null;
  return <Window key={id} view={view} />;
}

const WIDTH = 680;

function Window({ view }: { view: NodeView }) {
  const id = view.id;
  const source = view.source ?? "";
  const [tab, setTab] = useState<Tab>("settings");
  const [pos, setPos] = useState(() => ({
    x: Math.max(20, window.innerWidth - WIDTH - 320),
    y: 110,
  }));
  // The Code tab edits a draft; it is applied on leaving the tab, Test, OK, blur or Ctrl+S.
  const [draft, setDraft] = useState(source);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const base = useRef(source);
  useEffect(() => {
    // follow outside changes (Settings, undo, VS Code) unless the draft has its own edits
    if (draftRef.current === base.current || draftRef.current === source) setDraft(source);
    base.current = source;
  }, [source]);

  const pending = useRef<{ text: string; done: Promise<void> } | null>(null);
  const apply = (): Promise<void> => {
    const text = draftRef.current;
    if (pending.current?.text === text) return pending.current.done; // blur, then a click
    if (text === (store.getState().graph?.nodes[id]?.source ?? text)) return Promise.resolve();
    base.current = text;
    const done = store.patchNode(id, { source: text });
    pending.current = { text, done };
    return done;
  };

  // Ctrl+S with unapplied code: apply it first, then save the workflow.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "s") return;
      if (draftRef.current === store.getState().graph?.nodes[id]?.source) return;
      e.preventDefault();
      e.stopPropagation();
      void apply().then(() => store.save());
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const switchTo = async (next: Tab) => {
    if (next === tab) return;
    if (tab === "code") await apply();
    setTab(next);
  };

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
      className="gk-window"
      style={{ left: pos.x, top: pos.y, width: WIDTH }}
      role="dialog"
      aria-label={view.title}
      data-testid="component-window"
    >
      <header
        className="gk-window-header"
        onPointerDown={onHeaderDown}
        onPointerMove={onHeaderMove}
        onPointerUp={() => (drag.current = null)}
      >
        <span className="gk-window-category" style={{ color: categoryColour(view.category) }}>
          {view.category}
        </span>
        <span className="gk-window-title" data-testid="window-title">
          {view.title}
        </span>
        {view.modified && (
          <span className="gk-badge" title={strings.modifiedHint}>
            {strings.modified}
          </span>
        )}
        <div className="gk-spacer" />
        <button
          className="gk-icon-button"
          onClick={() => store.closeWindow()}
          aria-label={strings.close}
          data-testid="window-close"
        >
          <X size={16} />
        </button>
      </header>
      <div className="gk-window-tabs" role="tablist">
        {(["settings", "code"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`gk-tab${tab === t ? " gk-tab-active" : ""}`}
            onClick={() => void switchTo(t)}
            data-testid={`window-tab-${t}`}
          >
            {t === "settings" ? strings.settingsTab : strings.codeTab}
          </button>
        ))}
      </div>
      <div className="gk-window-body">
        {tab === "settings" ? (
          <SettingsTab view={view} />
        ) : (
          <div className="gk-code-tab">
            <div className="gk-code-bar">
              <span className="gk-muted">{strings.codeNote}</span>
              <button
                onClick={() => void apply().then(() => store.openInVsCode(id))}
                data-testid="open-vscode"
              >
                {strings.openInVsCode}
              </button>
            </div>
            <CodeEditor
              value={draft}
              onChange={setDraft}
              onBlur={() => void apply()}
              errorLine={errorLine(view.parse_error)}
            />
          </div>
        )}
      </div>
      <OutputPane view={view} />
      <footer className="gk-window-footer">
        <button
          onClick={() => void apply().then(() => store.saveComponent(id, (m) => window.confirm(m)))}
          data-testid="save-component"
        >
          {strings.saveAsComponent}
        </button>
        <span className="gk-muted gk-window-hint">{strings.testHint}</span>
        <button onClick={() => void apply().then(() => store.test(id))} data-testid="window-test">
          {strings.test}
        </button>
        <button
          className="gk-primary"
          onClick={() => void apply().then(() => store.closeWindow())}
          data-testid="window-ok"
        >
          {strings.ok}
        </button>
      </footer>
    </div>
  );
}

// ── Settings tab ──

/** "wired: Extract Values › table", or the Text / Number Slider value. */
export function wiredLabel(graph: GraphView, nodeId: string, port: string): string | null {
  const wires = graph.workflow.wires.filter((w) => w.to[0] === nodeId && w.to[1] === port);
  if (!wires.length) return null;
  return wires
    .map((w) => {
      const src = graph.nodes[w.from[0]];
      if (!src) return strings.wiredFrom(w.from[0], w.from[1]);
      if (src.component === PARAM_TEXT) return strings.wiredText(String(src.value ?? ""));
      if (src.component === PARAM_SLIDER) return strings.wiredSlider(String(src.value ?? ""));
      return strings.wiredFrom(src.title, w.from[1]);
    })
    .join(" · ");
}

function toEdit(p: PortView): PortEdit {
  return { name: p.name, type: p.type, access: p.access, file: p.file ?? null };
}

function SettingsTab({ view }: { view: NodeView }) {
  const graph = useStore((s) => s.graph);
  const settings = view.settings ?? [];
  const broken = !!view.parse_error;
  const editablePorts = view.category === "Script";
  const inputNames = new Set(view.inputs.map((p) => p.name));
  const own = settings.filter((s) => !inputNames.has(s.name));

  const setSetting = (name: string, value: unknown) =>
    void store.patchNode(view.id, { settings: { [name]: value } });

  const setPorts = (inputs: PortEdit[], outputs: PortEdit[]) =>
    void store.patchNode(view.id, { ports: { inputs, outputs } });
  const ins = view.inputs.map(toEdit);
  const outs = view.outputs.map(toEdit);
  const change = (side: "in" | "out", index: number, edit: Partial<PortEdit>) => {
    const list = (side === "in" ? ins : outs).map((p, i) =>
      i === index ? { ...p, ...edit, was: edit.name ? p.name : undefined } : p,
    );
    if (side === "in") setPorts(list, outs);
    else setPorts(ins, list);
  };
  const remove = (side: "in" | "out", index: number) => {
    if (side === "in")
      setPorts(
        ins.filter((_, i) => i !== index),
        outs,
      );
    else
      setPorts(
        ins,
        outs.filter((_, i) => i !== index),
      );
  };
  const add = (side: "in" | "out") => {
    const taken = [...ins, ...outs].map((p) => p.name);
    const port: PortEdit = { name: freshName(side === "in" ? "x" : "y", taken), type: "Number" };
    if (side === "in") setPorts([...ins, port], outs);
    else setPorts(ins, [...outs, port]);
  };

  return (
    <div className="gk-settings" data-testid="settings-tab">
      {broken && (
        <div className="gk-parse-error" role="alert" data-testid="settings-parse-error">
          <div>{strings.settingsBroken}</div>
          <pre>{view.parse_error}</pre>
        </div>
      )}
      <fieldset disabled={broken}>
        <h4>{strings.inputsHeading}</h4>
        {view.inputs.map((p, i) => {
          const wired = graph ? wiredLabel(graph, view.id, p.name) : null;
          const fallback = defaultFor(settings, p.name);
          return (
            <div className="gk-setting-row" key={p.name} data-testid={`input-${p.name}`}>
              <PortLabel
                port={p}
                editable={editablePorts}
                types={[...EDITABLE_PORT_TYPES, "Any"]}
                onRename={(name) => change("in", i, { name })}
                onType={(type) => change("in", i, { type })}
                onRemove={() => remove("in", i)}
              />
              <div className="gk-setting-value">
                {wired ? (
                  <span className="gk-wired">{wired}</span>
                ) : fallback ? (
                  <SettingField
                    key={`${fallback.name}=${valueText(fallback.value)}`}
                    setting={fallback}
                    onCommit={(v) => setSetting(fallback.name, v)}
                  />
                ) : (
                  <span className="gk-muted">{strings.notConnected}</span>
                )}
              </div>
            </div>
          );
        })}
        {editablePorts && (
          <button className="gk-add-port" onClick={() => add("in")} data-testid="add-input">
            + {strings.addInput}
          </button>
        )}
        {editablePorts && (
          <>
            <h4>{strings.outputsHeading}</h4>
            {view.outputs.map((p, i) => (
              <div className="gk-setting-row" key={p.name} data-testid={`output-${p.name}`}>
                <PortLabel
                  port={p}
                  editable
                  types={EDITABLE_PORT_TYPES}
                  onRename={(name) => change("out", i, { name })}
                  onType={(type) => change("out", i, { type })}
                  onRemove={() => remove("out", i)}
                />
              </div>
            ))}
            <button className="gk-add-port" onClick={() => add("out")} data-testid="add-output">
              + {strings.addOutput}
            </button>
          </>
        )}
        <h4>{strings.settingsHeading}</h4>
        {own.length === 0 && <p className="gk-muted">{strings.noSettings}</p>}
        {own.map((s) => (
          <div className="gk-setting-row" key={s.name}>
            <span className="gk-setting-name">{s.name}</span>
            <div className="gk-setting-value">
              <SettingField
                key={`${s.name}=${valueText(s.value)}`}
                setting={s}
                onCommit={(v) => setSetting(s.name, v)}
              />
            </div>
          </div>
        ))}
      </fieldset>
      <div className="gk-setting-row">
        <span className="gk-setting-name gk-setting-label">{strings.showOnCanvasAs}</span>
        <div className="gk-setting-value">
          <div className="gk-segmented">
            {(
              [
                ["default", strings.displayDefault],
                ["text", strings.displayText],
                ["icon", strings.displayIcon],
              ] as const
            ).map(([d, label]) => (
              <button
                key={d}
                className={view.display === d ? "gk-active" : ""}
                onClick={() => void store.patchNode(view.id, { display: d })}
                data-testid={`display-${d}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

interface PortLabelProps {
  port: PortView;
  editable: boolean;
  types: PortType[];
  onRename: (name: string) => void;
  onType: (type: PortType) => void;
  onRemove: () => void;
}

function PortLabel({ port, editable, types, onRename, onType, onRemove }: PortLabelProps) {
  const [name, setName] = useState(port.name);
  const dot = <span className="gk-type-dot" style={{ background: PORT_COLOURS[port.type] }} />;
  if (!editable)
    return (
      <>
        <span className="gk-setting-name">
          {dot}
          {port.name}
        </span>
        <span className="gk-setting-type">{port.type}</span>
      </>
    );
  const commit = () => {
    const n = name.trim();
    if (n && n !== port.name) onRename(n);
    else setName(port.name);
  };
  return (
    <>
      <span className="gk-setting-name">
        {dot}
        <input
          className="gk-port-name"
          value={name}
          aria-label={strings.portName}
          onChange={(e) => setName(e.currentTarget.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          data-testid={`port-name-${port.name}`}
        />
      </span>
      <select
        className="gk-setting-type"
        value={port.type}
        aria-label={strings.portType}
        onChange={(e) => onType(e.currentTarget.value as PortType)}
        data-testid={`port-type-${port.name}`}
      >
        {types.map((t) => (
          <option key={t}>{t}</option>
        ))}
      </select>
      <button
        className="gk-icon-button"
        onClick={onRemove}
        aria-label={strings.removePort}
        title={strings.removePort}
        data-testid={`port-remove-${port.name}`}
      >
        <X size={14} />
      </button>
    </>
  );
}

/** One settings field, shaped by its hint comment (SPEC 4). Commits on change / blur / Enter. */
function SettingField({
  setting,
  onCommit,
}: {
  setting: SettingView;
  onCommit: (v: unknown) => void;
}) {
  const [text, setText] = useState(valueText(setting.value));
  const testId = `setting-${setting.name}`;
  const commit = (value: unknown) => {
    if (valueText(value) !== valueText(setting.value) || typeof value !== typeof setting.value)
      onCommit(value);
  };

  if (setting.widget === "dropdown" && setting.options) {
    const options = setting.options;
    const index = options.findIndex((o) => valueText(o) === valueText(setting.value));
    return (
      <select
        value={index}
        onChange={(e) => commit(options[Number(e.currentTarget.value)])}
        data-testid={testId}
      >
        {index < 0 && <option value={-1}>{valueText(setting.value)}</option>}
        {options.map((o, i) => (
          <option key={i} value={i}>
            {valueText(o)}
          </option>
        ))}
      </select>
    );
  }
  if (setting.widget === "multiline") {
    return (
      <textarea
        value={text}
        rows={4}
        onChange={(e) => setText(e.currentTarget.value)}
        onBlur={() => commit(parseValue(text, setting.value))}
        data-testid={testId}
      />
    );
  }
  const numeric = setting.widget === "number";
  const read = () =>
    numeric && text.trim() !== "" ? Number(text) : parseValue(text, setting.value);
  return (
    <input
      type={numeric ? "number" : "text"}
      step="any"
      min={setting.range?.[0]}
      max={setting.range?.[1]}
      value={text}
      onChange={(e) => setText(e.currentTarget.value)}
      onBlur={() => commit(read())}
      onKeyDown={(e) => e.key === "Enter" && commit(read())}
      data-testid={testId}
    />
  );
}

// ── Output ──

function OutputPane({ view }: { view: NodeView }) {
  const log = useStore((s) => s.logs[view.id]);
  const error = useStore((s) => s.errors[view.id]);
  const state = view.state ?? "never_run";
  const empty = !log?.length && !error;
  return (
    <section className="gk-output" data-testid="output">
      <div className="gk-output-head">
        <strong>{strings.output}</strong>
        <span className="gk-muted">{strings.outputHint}</span>
      </div>
      <div className="gk-output-body">
        <div className={`gk-output-state gk-output-${state}`} data-testid="output-state">
          {strings.stateLabels[state] ?? state}
        </div>
        {log?.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
        {error && (
          <pre className="gk-output-error" data-testid="output-error">
            {error}
          </pre>
        )}
        {empty && <div className="gk-muted">{strings.outputEmpty}</div>}
      </div>
    </section>
  );
}

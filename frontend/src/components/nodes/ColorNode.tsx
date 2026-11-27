import { useState } from "react";
import type { NodeProps } from "@xyflow/react";
import { FALLBACK_COLOR_VALUE } from "../../palettes";
import { store } from "../../store";
import { strings } from "../../strings";
import { needsRun } from "../../types";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

const HEX = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i;

/** The `#rrggbb` part of a colour, for `<input type="color">` (which has no alpha). */
export function pickerValue(hex: string): string {
  const m = HEX.exec(hex.trim());
  return m ? `#${m[1].toLowerCase()}` : FALLBACK_COLOR_VALUE;
}

/** A picked `#rrggbb` with the alpha of ``hex`` kept, upper case like the server's. */
export function withAlpha(picked: string, hex: string): string {
  const alpha = HEX.exec(hex.trim())?.[2] ?? "";
  return `${picked}${alpha}`.toUpperCase();
}

/** Color Swatch: a swatch with its hex; double-click opens a colour picker (change 01, 8). */
export function ColorNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const hex = typeof view.value === "string" ? view.value : FALLBACK_COLOR_VALUE;
  const [open, setOpen] = useState(false);
  const state = view.state ?? "never_run";
  return (
    <div
      className={`gk-node gk-text gk-color gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      title={strings.colorHint}
      onDoubleClick={(e) => {
        e.stopPropagation();
        setOpen(true);
      }}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <span className="gk-swatch" style={{ background: hex }} data-testid={`swatch-${id}`} />
      <span className="gk-text-value">{hex}</span>
      <Port nodeId={id} side="out" name="value" types={["Color"]} />
      {open && (
        <ColorWindow
          value={hex}
          onCancel={() => setOpen(false)}
          onOk={(v) => {
            setOpen(false);
            if (v !== hex) void store.patchNode(id, { value: v });
          }}
        />
      )}
    </div>
  );
}

interface WindowProps {
  value: string;
  onOk: (value: string) => void;
  onCancel: () => void;
}

/** A colour picker and a hex field; the field also takes `r,g,b[,a]` (checked by the server). */
export function ColorWindow(props: WindowProps) {
  const [text, setText] = useState(props.value);
  return (
    <form
      className="nodrag nowheel gk-popover gk-slider-window"
      onSubmit={(e) => {
        e.preventDefault();
        props.onOk(text.trim());
      }}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === "Escape") props.onCancel();
        e.stopPropagation();
      }}
      data-testid="color-window"
    >
      <label>
        <span>{strings.colorPicker}</span>
        <input
          type="color"
          className="gk-color-input"
          value={pickerValue(text)}
          onChange={(e) => setText(withAlpha(e.currentTarget.value, text))}
          data-testid="color-picker"
        />
      </label>
      <label>
        <span>{strings.colorHex}</span>
        <input
          value={text}
          autoFocus
          onChange={(e) => setText(e.currentTarget.value)}
          data-testid="color-hex"
        />
      </label>
      <div className="gk-popover-buttons">
        <button type="button" onClick={props.onCancel}>
          {strings.cancel}
        </button>
        <button type="submit" className="gk-primary" data-testid="color-ok">
          {strings.ok}
        </button>
      </div>
    </form>
  );
}

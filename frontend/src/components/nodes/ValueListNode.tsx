import { useState } from "react";
import type { NodeProps } from "@xyflow/react";
import { List, X } from "lucide-react";
import type { ValueOption } from "../../apiTypes";
import { store } from "../../store";
import { strings } from "../../strings";
import { needsRun, portTypes } from "../../types";
import { parseNumber } from "../window/values";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

/** The option whose value is ``value``, by kind as the server compares (`1` is not `"1"`). */
export function optionIndex(options: ValueOption[], value: unknown): number {
  return options.findIndex((o) => typeof o.value === typeof value && o.value === value);
}

/** Value List: a dropdown of its options; double-click edits them (change 01, section 8).
 * Its output is Number when every value is a number, else Text (from the server). */
export function ValueListNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const options = view.options ?? [];
  const index = optionIndex(options, view.value);
  const [open, setOpen] = useState(false);
  const state = view.state ?? "never_run";
  const out = view.outputs[0];
  return (
    <div
      className={`gk-node gk-text gk-value-list gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      title={strings.valueListHint}
      onDoubleClick={(e) => {
        e.stopPropagation();
        setOpen(true);
      }}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <span className="gk-badge gk-badge-list">
        <List size={15} />
      </span>
      <select
        className="nodrag gk-value-select"
        value={index}
        aria-label={strings.valueListChoose}
        onChange={(e) => {
          const chosen = options[Number(e.currentTarget.value)];
          if (chosen) void store.patchNode(id, { value: chosen.value });
        }}
        onDoubleClick={(e) => e.stopPropagation()}
        data-testid={`value-list-${id}`}
      >
        {index < 0 && <option value={-1}>{String(view.value ?? "")}</option>}
        {options.map((o, i) => (
          <option key={i} value={i}>
            {o.label}
          </option>
        ))}
      </select>
      <Port nodeId={id} side="out" name="value" types={out ? portTypes(out) : ["Number"]} />
      {open && (
        <ValueListWindow
          options={options}
          onCancel={() => setOpen(false)}
          onOk={(next) => {
            setOpen(false);
            void store.patchNode(id, { options: next });
          }}
        />
      )}
    </div>
  );
}

interface Row {
  label: string;
  text: string;
  /** The value the row had, kept while its text is not edited (so text "1" stays text). */
  original: number | string | null;
}

function valueOf(row: Row): number | string {
  if (row.original !== null && row.text === String(row.original)) return row.original;
  return parseNumber(row.text) ?? row.text;
}

/** The rows as options: a value that reads as a number is a number; a blank label is the
 * value's text. */
export function rowsToOptions(rows: Row[]): ValueOption[] {
  return rows.map((r) => ({ label: r.label.trim() || r.text.trim(), value: valueOf(r) }));
}

interface WindowProps {
  options: ValueOption[];
  onOk: (options: ValueOption[]) => void;
  onCancel: () => void;
}

/** The options window of a Value List: label and value per row, add and remove. */
export function ValueListWindow(props: WindowProps) {
  const [rows, setRows] = useState<Row[]>(() =>
    props.options.map((o) => ({ label: o.label, text: String(o.value), original: o.value })),
  );
  const change = (i: number, patch: Partial<Row>) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const submit = () => {
    if (!rows.length) {
      store.showToast(strings.valueListEmpty);
      return;
    }
    props.onOk(rowsToOptions(rows));
  };
  return (
    <form
      className="nodrag nowheel gk-popover gk-slider-window gk-options-window"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === "Escape") props.onCancel();
        e.stopPropagation();
      }}
      data-testid="value-list-window"
    >
      <strong>{strings.valueListOptions}</strong>
      <div className="gk-option-row gk-option-head">
        <span>{strings.optionLabel}</span>
        <span title={strings.optionValueHint}>{strings.optionValue}</span>
      </div>
      {rows.map((r, i) => (
        <div className="gk-option-row" key={i}>
          <input
            value={r.label}
            aria-label={strings.optionLabel}
            onChange={(e) => change(i, { label: e.currentTarget.value })}
            data-testid={`option-label-${i}`}
          />
          <input
            value={r.text}
            aria-label={strings.optionValue}
            title={strings.optionValueHint}
            onChange={(e) => change(i, { text: e.currentTarget.value })}
            data-testid={`option-value-${i}`}
          />
          <button
            type="button"
            className="gk-icon-button"
            aria-label={strings.removeOption}
            title={strings.removeOption}
            onClick={() => setRows(rows.filter((_, j) => j !== i))}
            data-testid={`option-remove-${i}`}
          >
            <X size={14} />
          </button>
        </div>
      ))}
      <button
        type="button"
        className="gk-add-port"
        onClick={() => setRows([...rows, { label: "", text: "", original: null }])}
        data-testid="option-add"
      >
        + {strings.addOption}
      </button>
      <div className="gk-popover-buttons">
        <button type="button" onClick={props.onCancel}>
          {strings.cancel}
        </button>
        <button type="submit" className="gk-primary" data-testid="options-ok">
          {strings.ok}
        </button>
      </div>
    </form>
  );
}

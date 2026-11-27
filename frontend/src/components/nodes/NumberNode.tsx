import { useState, type KeyboardEvent } from "react";
import type { NodeProps } from "@xyflow/react";
import { store } from "../../store";
import { strings } from "../../strings";
import { needsRun } from "../../types";
import { parseNumber } from "../window/values";
import { Port } from "./Port";
import { formatNumber } from "./SliderNode";
import type { GkNode } from "./kinds";

/** Number: a pill with a "#" badge; double-click to edit inline (change 01, section 8).
 * While editing, a "whole numbers" box switches integer mode (section 2). */
export function NumberNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const value = typeof view.value === "number" ? view.value : 0;
  const integer = view.integer ?? false;
  const [editing, setEditing] = useState(false);
  const state = view.state ?? "never_run";

  const commit = (text: string) => {
    setEditing(false);
    const n = parseNumber(text);
    if (n === null) {
      if (text.trim() !== formatNumber(value)) store.showToast(strings.notANumber(text.trim()));
      return;
    }
    if (n !== value) void store.patchNode(id, { value: n });
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") commit(e.currentTarget.value);
    else if (e.key === "Escape") setEditing(false);
    e.stopPropagation();
  };

  return (
    <div
      className={`gk-node gk-text gk-number gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      data-integer={integer}
      onDoubleClick={(e) => {
        e.stopPropagation();
        setEditing(true);
      }}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <span className="gk-badge gk-badge-number">{strings.numberBadge}</span>
      {editing ? (
        <>
          <input
            className="nodrag gk-text-input gk-number-input"
            autoFocus
            inputMode="decimal"
            defaultValue={formatNumber(value)}
            onKeyDown={onKey}
            onBlur={(e) => commit(e.currentTarget.value)}
            data-testid={`number-input-${id}`}
          />
          <label
            className="nodrag gk-integer"
            title={strings.integerHint}
            // keep the focus in the value field, so the box does not end the edit
            onMouseDown={(e) => e.preventDefault()}
          >
            <input
              type="checkbox"
              checked={integer}
              onChange={(e) => void store.patchNode(id, { integer: e.currentTarget.checked })}
              data-testid={`number-integer-${id}`}
            />
            {strings.integer}
          </label>
        </>
      ) : (
        <span className="gk-text-value" data-testid={`number-value-${id}`}>
          {formatNumber(value)}
        </span>
      )}
      <Port nodeId={id} side="out" name="value" types={["Number"]} />
    </div>
  );
}

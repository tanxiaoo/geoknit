import { useState, type KeyboardEvent } from "react";
import type { NodeProps } from "@xyflow/react";
import { store } from "../../store";
import { strings } from "../../strings";
import { needsRun } from "../../types";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

/** Text: a pill with a "T" badge; double-click to edit inline. */
export function TextNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const value = typeof view.value === "string" ? view.value : "";
  const [editing, setEditing] = useState(false);
  const state = view.state ?? "never_run";

  const commit = (text: string) => {
    setEditing(false);
    if (text !== value) void store.patchNode(id, { value: text });
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") commit(e.currentTarget.value);
    else if (e.key === "Escape") setEditing(false);
    e.stopPropagation();
  };

  return (
    <div
      className={`gk-node gk-text gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      onDoubleClick={(e) => {
        e.stopPropagation();
        setEditing(true);
      }}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <span className="gk-badge">T</span>
      {editing ? (
        <input
          className="nodrag gk-text-input"
          autoFocus
          defaultValue={value}
          onKeyDown={onKey}
          onBlur={(e) => commit(e.currentTarget.value)}
          data-testid={`text-input-${id}`}
        />
      ) : (
        <span className={`gk-text-value${value ? "" : " gk-placeholder"}`} title={value}>
          {value || strings.textPlaceholder}
        </span>
      )}
      <Port nodeId={id} side="out" name="value" type="Text" />
    </div>
  );
}

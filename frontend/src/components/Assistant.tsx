import { useState } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { strings } from "../strings";

/** Placeholder for the assistant (SPEC 1: not in v0.1). */
export function Assistant() {
  const [open, setOpen] = useState(true);
  if (!open) {
    return (
      <aside className="gk-assistant gk-assistant-closed">
        <button onClick={() => setOpen(true)} title={strings.expand}>
          <PanelRightOpen size={16} />
        </button>
      </aside>
    );
  }
  return (
    <aside className="gk-assistant" data-testid="assistant">
      <div className="gk-assistant-head">
        <strong>{strings.assistant}</strong>
        <span className="gk-pill">{strings.nextVersion}</span>
        <button onClick={() => setOpen(false)} title={strings.collapse}>
          <PanelRightClose size={16} />
        </button>
      </div>
      <p className="gk-reserved">{strings.assistantReserved}</p>
      <h4>{strings.plannedAbilities}</h4>
      <ul className="gk-abilities">
        {strings.abilities.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
      <h4>{strings.exampleRequests}</h4>
      {strings.examples.map((e) => (
        <div key={e} className="gk-example">
          {e}
        </div>
      ))}
      <div className="gk-spacer-v" />
      <label className="gk-field">
        {strings.model}
        <select disabled>
          <option>{strings.assistantModel}</option>
        </select>
      </label>
      <label className="gk-field">
        {strings.message}
        <textarea disabled placeholder={strings.messagePlaceholder} rows={3} />
      </label>
      <button disabled className="gk-send">
        {strings.send}
      </button>
    </aside>
  );
}

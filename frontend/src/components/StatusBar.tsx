import { strings } from "../strings";
import { DATA_TYPES, PORT_COLOURS } from "../types";

export function StatusBar() {
  return (
    <footer className="gk-statusbar">
      <strong>{strings.dataTypes}</strong>
      {DATA_TYPES.map((t) => (
        <span key={t} className="gk-legend">
          <span className="gk-legend-dot" style={{ background: PORT_COLOURS[t] }} />
          {t}
        </span>
      ))}
      <div className="gk-spacer" />
      <span className="gk-legend">
        <span className="gk-legend-dot gk-legend-outofdate" />
        {strings.legendOutOfDate}
      </span>
      <span className="gk-legend">
        <span className="gk-legend-box gk-legend-error" />
        {strings.legendError}
      </span>
      <span className="gk-legend">
        <span className="gk-legend-box gk-legend-selected" />
        {strings.legendSelected}
      </span>
    </footer>
  );
}

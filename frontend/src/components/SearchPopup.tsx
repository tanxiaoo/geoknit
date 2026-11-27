import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentEntry } from "../apiTypes";
import { fittingPort, matches, placeOf, type WireFrom } from "../catalog";
import { iconFor } from "../icons";
import { useStore } from "../store";
import { strings } from "../strings";
import { categoryColour } from "../types";

interface Props {
  x: number;
  y: number;
  from?: WireFrom;
  onPick: (entry: ComponentEntry) => void;
  onClose: () => void;
}

/** Component search at the cursor (double-click canvas, or a wire dropped in empty space). */
export function SearchPopup({ x, y, from, onPick, onClose }: Props) {
  const library = useStore((s) => s.components);
  const tabs = useStore((s) => s.tabs);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  const list = useMemo(
    () =>
      library
        .filter((e) => matches(e, query))
        .filter((e) => !from || fittingPort(e, from) !== null)
        .slice(0, 30),
    [library, query, from],
  );

  useEffect(() => {
    const close = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", close, true);
    return () => window.removeEventListener("pointerdown", close, true);
  }, [onClose]);

  return (
    <div className="gk-popover gk-search-popup" style={{ left: x, top: y }} ref={ref}>
      <input
        autoFocus
        placeholder={strings.searchPlaceholder}
        value={query}
        data-testid="search-popup-input"
        onChange={(e) => {
          setQuery(e.currentTarget.value);
          setIndex(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          else if (e.key === "ArrowDown") setIndex((i) => Math.min(i + 1, list.length - 1));
          else if (e.key === "ArrowUp") setIndex((i) => Math.max(i - 1, 0));
          else if (e.key === "Enter" && list[index]) onPick(list[index]);
          e.stopPropagation();
        }}
      />
      <ul>
        {list.length === 0 && <li className="gk-muted">{strings.noMatches}</li>}
        {list.map((e, i) => {
          const Icon = iconFor(e.icon, e.category);
          return (
            <li
              key={e.ref}
              className={i === index ? "gk-active" : ""}
              onMouseEnter={() => setIndex(i)}
              onClick={() => onPick(e)}
              data-testid={`search-item-${e.ref}`}
            >
              <span className="gk-search-icon" style={{ background: categoryColour(tabs, e.category) }}>
                <Icon size={13} />
              </span>
              <span>{e.name}</span>
              <span className="gk-muted">{placeOf(e)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

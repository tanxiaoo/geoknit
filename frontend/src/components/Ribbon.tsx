import { useMemo, useState } from "react";
import { useReactFlow } from "@xyflow/react";
import { Search, SlidersHorizontal } from "lucide-react";
import type { ComponentEntry } from "../apiTypes";
import { allEntries, categories, matches, paramEntries } from "../catalog";
import { iconFor } from "../icons";
import { store, useStore } from "../store";
import { strings } from "../strings";
import { categoryColour } from "../types";
import { MIME_COMPONENT } from "./Canvas";

/** Category tabs with component buttons, plus the search box (SPEC 8). */
export function Ribbon() {
  const library = useStore((s) => s.components);
  const tabs = useMemo(() => categories(library), [library]);
  const [tab, setTab] = useState("Params");
  const [query, setQuery] = useState("");
  const flow = useReactFlow();

  const items =
    tab === "Params" ? paramEntries() : library.filter((c) => c.category === tab);
  const found = query ? allEntries(library).filter((e) => matches(e, query)).slice(0, 12) : [];

  /** Add at the centre of the visible canvas. */
  const add = (entry: ComponentEntry) => {
    const rect = document.querySelector(".gk-canvas")?.getBoundingClientRect();
    const centre = rect
      ? flow.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 })
      : { x: 0, y: 0 };
    void store.addNode(entry.ref, [Math.round(centre.x), Math.round(centre.y)]);
    setQuery("");
  };

  return (
    <nav className="gk-ribbon">
      <div className="gk-tabs">
        {tabs.map((t) => (
          <button
            key={t}
            className={`gk-tab${t === tab ? " gk-tab-active" : ""}`}
            onClick={() => setTab(t)}
            data-testid={`tab-${t}`}
          >
            {t === "Params" ? strings.paramsTab : t}
          </button>
        ))}
        <div className="gk-spacer" />
        <div className="gk-search">
          <Search size={15} />
          <input
            placeholder={strings.searchPlaceholder}
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && found[0]) add(found[0]);
              if (e.key === "Escape") setQuery("");
            }}
            data-testid="ribbon-search"
          />
          {query && (
            <ul className="gk-popover gk-search-results">
              {found.length === 0 && <li className="gk-muted">{strings.noMatches}</li>}
              {found.map((e) => (
                <li key={e.ref} onClick={() => add(e)}>
                  {e.name} <span className="gk-muted">{e.category}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="gk-buttons">
        {items.map((e) => {
          const Icon = e.category === "Params" ? SlidersHorizontal : iconFor(e.icon, e.category);
          return (
            <button
              key={e.ref}
              className="gk-component-button"
              draggable
              title={`${e.description || e.name}\n${strings.addHint}`}
              onDragStart={(ev) => {
                ev.dataTransfer.setData(MIME_COMPONENT, e.ref);
                ev.dataTransfer.effectAllowed = "copy";
              }}
              onClick={() => add(e)}
              data-testid={`ribbon-${e.ref}`}
            >
              <span className="gk-button-icon" style={{ color: categoryColour(e.category) }}>
                <Icon size={16} />
              </span>
              {e.name}
              {e.origin === "user" && (
                <span className="gk-badge" title={strings.userComponent}>
                  {strings.userComponent}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

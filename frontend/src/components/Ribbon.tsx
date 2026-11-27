import { useMemo, useState } from "react";
import { useReactFlow } from "@xyflow/react";
import { Search } from "lucide-react";
import type { ComponentEntry } from "../apiTypes";
import { groupsOf, matches, placeOf } from "../catalog";
import { iconFor } from "../icons";
import { store, useStore } from "../store";
import { strings } from "../strings";
import { categoryColour } from "../types";
import { MIME_COMPONENT } from "./Canvas";

/** Category tabs with component buttons in labelled groups, plus the search box (SPEC 8).
 * Tabs, groups and order come from `GET /api/components` (change 01, section 7). */
export function Ribbon() {
  const library = useStore((s) => s.components);
  const tabs = useStore((s) => s.tabs);
  const [picked, setPicked] = useState("Params");
  const [query, setQuery] = useState("");
  const flow = useReactFlow();

  const current = tabs.find((t) => t.name === picked) ?? tabs[0];
  const groups = useMemo(() => (current ? groupsOf(library, current) : []), [library, current]);
  const found = query ? library.filter((e) => matches(e, query)).slice(0, 12) : [];

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
            key={t.name}
            className={`gk-tab${t.name === current?.name ? " gk-tab-active" : ""}`}
            onClick={() => setPicked(t.name)}
            data-testid={`tab-${t.name}`}
          >
            {t.name === "Params" ? strings.paramsTab : t.name}
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
                  {e.name} <span className="gk-muted">{placeOf(e)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="gk-buttons">
        {groups.map(({ group, entries }) => (
          <section className="gk-ribbon-group" key={group} data-testid={`ribbon-group-${group}`}>
            <div className="gk-ribbon-group-buttons">
              {entries.map((e) => {
                const Icon = iconFor(e.icon, e.category);
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
                    <span
                      className="gk-button-icon"
                      style={{ color: categoryColour(tabs, e.category) }}
                    >
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
            <div className="gk-ribbon-group-label">{group}</div>
          </section>
        ))}
      </div>
    </nav>
  );
}

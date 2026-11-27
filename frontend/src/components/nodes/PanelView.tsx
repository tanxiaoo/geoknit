// What a Panel draws for a value (change 01, section 11): the value, a swatch, a gradient,
// list rows, or a paging grid for a Table / Vector.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  CellValue,
  ColormapJson,
  ElementView,
  ListView,
  PanelView as View,
  TableView,
} from "../../apiTypes";
import { store, useStore } from "../../store";
import { strings } from "../../strings";
import { colormapLabel, Strip } from "./ColormapNode";

/** Rows per page: the first page comes with the view, later ones from `GET /api/table`. */
export const PAGE_ROWS = 200;
/** The next page is asked for when the grid is scrolled this close to its end (px). */
const NEAR_END_PX = 120;
/** Column widths in `ch`, from the header and the first page. */
const MIN_CH = 3;
const MAX_CH = 32;
const PAD_CH = 2;

/** A cell or index label as text: missing values are blank, booleans True / False. */
export function cellText(v: CellValue): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? strings.toggleTrue : strings.toggleFalse;
  return String(v);
}

/** Column widths in `ch` (the index column first), from the header and the first page. */
export function columnWidths(page: TableView): number[] {
  const clamp = (n: number) => Math.min(MAX_CH, Math.max(MIN_CH, n)) + PAD_CH;
  const index = Math.max(
    String(Math.max(page.total_rows - 1, 0)).length,
    ...page.index.map((v) => cellText(v).length),
  );
  const columns = page.columns.map((name, j) =>
    clamp(Math.max(name.length, ...page.rows.map((r) => cellText(r[j] ?? null).length))),
  );
  return [clamp(index), ...columns];
}

interface Props {
  nodeId: string;
  view: View;
}

/** The Panel's body for one view. */
export function PanelView({ nodeId, view }: Props) {
  switch (view.kind) {
    case "value":
      return <pre className="gk-panel-value">{valueText(view.value, view.type)}</pre>;
    case "color":
      return (
        <div className="gk-panel-color">
          <span
            className="gk-swatch gk-panel-swatch"
            style={{ background: view.value }}
            data-testid={`panel-swatch-${nodeId}`}
          />
          <code>{view.value}</code>
        </div>
      );
    case "colormap":
      return <ColormapView nodeId={nodeId} cm={view.value} />;
    case "list":
      return <ListRows nodeId={nodeId} view={view} />;
    case "table":
      return <TableGrid nodeId={nodeId} view={view} />;
    default:
      return <pre className="gk-panel-value">{view.text}</pre>;
  }
}

function valueText(value: number | string | boolean, type: string): string {
  if (type === "Boolean" || typeof value === "boolean")
    return value ? strings.toggleTrue : strings.toggleFalse;
  return String(value);
}

/** A gradient with the ramp's name; classes: one chip per class with its label. */
function ColormapView({ nodeId, cm }: { nodeId: string; cm: ColormapJson }) {
  const ramps = useStore((s) => s.ramps);
  useEffect(() => void store.loadRamps(), []);
  if (cm.kind === "classes") {
    const classes: [string, string][] = cm.classes.map(([value, colour, label]) => [
      colour,
      label || String(value),
    ]);
    if (cm.other) classes.push([cm.other, strings.panelOtherClass]);
    return (
      <ul className="gk-panel-classes" data-testid={`panel-classes-${nodeId}`}>
        {classes.map(([colour, label], i) => (
          <li key={i} data-testid={`panel-class-${nodeId}-${i}`}>
            <span className="gk-panel-chip" style={{ background: colour }} />
            <span>{label}</span>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="gk-panel-colormap">
      <Strip cm={cm} ramps={ramps} testId={`panel-ramp-${nodeId}`} />
      <span>{colormapLabel(cm)}</span>
    </div>
  );
}

/** A list element on one line: the value, a swatch with its hex, a small gradient, or the
 * first line of its describe(). */
function ElementLine({ view }: { view: ElementView }) {
  switch (view.kind) {
    case "value":
      return <>{valueText(view.value, view.type)}</>;
    case "color":
      return (
        <span className="gk-panel-inline">
          <span className="gk-panel-chip" style={{ background: view.value }} />
          {view.value}
        </span>
      );
    case "colormap":
      return <InlineColormap cm={view.value} />;
    default:
      return <>{view.text}</>;
  }
}

function InlineColormap({ cm }: { cm: ColormapJson }) {
  const ramps = useStore((s) => s.ramps);
  useEffect(() => void store.loadRamps(), []);
  return (
    <span className="gk-panel-inline">
      <Strip cm={cm} ramps={ramps} />
      {colormapLabel(cm)}
    </span>
  );
}

/** One row per element with its index, under "list of N Type". */
function ListRows({ nodeId, view }: { nodeId: string; view: ListView }) {
  const more = view.count - view.items.length;
  return (
    <>
      <div className="gk-panel-header" data-testid={`panel-header-${nodeId}`}>
        {strings.panelListHeader(view.count, view.type)}
      </div>
      <div className="nodrag nowheel gk-panel-scroll">
        <table className="gk-panel-grid gk-panel-list" data-testid={`panel-list-${nodeId}`}>
          <tbody>
            {view.items.map((item, i) => (
              <tr key={i} data-testid={`panel-item-${nodeId}-${i}`}>
                <th className="gk-panel-index">{i}</th>
                <td>
                  <ElementLine view={item} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {more > 0 && <div className="gk-panel-more">{strings.moreItems(more)}</div>}
      </div>
    </>
  );
}

interface GridState {
  view: TableView;
  rows: CellValue[][];
  index: CellValue[];
  loading: boolean;
  error: string | null;
  /** A page came back empty before `total_rows` were shown: stop asking. */
  ended: boolean;
}

const fresh = (view: TableView): GridState => ({
  view,
  rows: view.rows,
  index: view.index,
  loading: false,
  error: null,
  ended: false,
});

/** A scrollable grid with an index column and the column headers, under "N rows × M
 * columns"; scrolling near the end asks for the next page. */
function TableGrid({ nodeId, view }: { nodeId: string; view: TableView }) {
  const paging = useStore((s) => s.paging[nodeId]);
  useEffect(() => void store.loadPaging(nodeId), [nodeId, paging]);
  const [st, setSt] = useState<GridState>(() => fresh(view));
  if (st.view !== view) setSt(fresh(view)); // a new result starts from its first page
  const widths = useMemo(() => columnWidths(view), [view]);
  const geometry = useMemo(() => new Set(view.geometry), [view]);
  const scroller = useRef<HTMLDivElement>(null);
  const busy = useRef(false);

  const more = !st.ended && st.rows.length < view.total_rows;
  const diskOff = paging !== undefined && !paging.diskCache;
  const key = paging?.diskCache ? paging.key : null;

  const loadMore = useCallback(() => {
    if (busy.current || !key || st.view !== view || !more || st.error) return;
    const el = scroller.current;
    if (!el || el.scrollHeight === 0) return; // not laid out
    if (el.scrollHeight - el.scrollTop - el.clientHeight > NEAR_END_PX) return;
    const offset = view.offset + st.rows.length;
    busy.current = true;
    setSt((s) => ({ ...s, loading: true }));
    store.api.table(key, offset, PAGE_ROWS).then(
      (page) => {
        busy.current = false;
        setSt((s) =>
          s.view === view && s.view.offset + s.rows.length === offset
            ? {
                ...s,
                rows: [...s.rows, ...page.rows],
                index: [...s.index, ...page.index],
                loading: false,
                // an empty page would be asked for again at the same offset forever
                ended: page.rows.length === 0,
              }
            : { ...s, loading: false },
        );
      },
      (e: unknown) => {
        busy.current = false;
        const message = e instanceof Error ? e.message : String(e);
        setSt((s) => (s.view === view ? { ...s, loading: false, error: message } : s));
      },
    );
  }, [key, st, view, more]);

  // a Panel taller than the rows shown fills itself, as if scrolled to the end
  useEffect(loadMore, [loadMore]);

  const total = widths.reduce((a, b) => a + b, 0);
  return (
    <>
      <div className="gk-panel-header" data-testid={`panel-header-${nodeId}`}>
        {strings.panelTableHeader(view.total_rows, view.columns.length)}
      </div>
      <div
        ref={scroller}
        className="nodrag nowheel gk-panel-scroll"
        onScroll={loadMore}
        data-testid={`panel-grid-${nodeId}`}
        data-rows={st.rows.length}
      >
        <table className="gk-panel-grid" style={{ width: `${total}ch` }}>
          <colgroup>
            {widths.map((w, j) => (
              <col key={j} style={{ width: `${w}ch` }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th className="gk-panel-index" />
              {view.columns.map((c, j) => (
                <th key={j} title={c}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {st.rows.map((row, i) => (
              <tr key={i} data-testid={`panel-row-${nodeId}-${i}`}>
                <th className="gk-panel-index">{cellText(st.index[i] ?? null)}</th>
                {row.map((v, j) => {
                  const text = cellText(v);
                  return (
                    <td
                      key={j}
                      className={geometry.has(view.columns[j]) ? "gk-panel-geom" : undefined}
                      title={text}
                    >
                      {text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {st.loading && <div className="gk-panel-more">{strings.panelLoading}</div>}
        {st.error && (
          <div className="gk-panel-error" data-testid={`panel-error-${nodeId}`}>
            {strings.panelPageError(st.error)}
          </div>
        )}
      </div>
      {diskOff && more && (
        <div className="gk-panel-note" data-testid={`panel-note-${nodeId}`}>
          {strings.panelNoDiskCache}
        </div>
      )}
    </>
  );
}

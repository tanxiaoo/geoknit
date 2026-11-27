import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { RotateCcw, X } from "lucide-react";
import type {
  Basemap,
  InspectLayer,
  LayerStyle,
  MapLayer,
  MapView,
  NodeView,
  RasterStats,
} from "../../apiTypes";
import { store, useCategoryColour, useStore } from "../../store";
import { strings } from "../../strings";
import { MapCanvas, type VectorHit } from "./MapCanvas";
import {
  bandsKey,
  CATEGORICAL,
  effectiveStyle,
  formatValue,
  isRgb,
  legendFor,
  range,
  renderLayers,
  statsFor,
  unionBounds,
  VECTOR_COLOURS,
  type Legend,
} from "./layers";

/** The floating map window of the open Map Viewer (SPEC 8). */
export function MapWindow() {
  const id = useStore((s) => s.mapNode);
  const view = useStore((s) => (id ? s.graph?.nodes[id] : undefined));
  if (!id || !view) return null;
  return <Window key={id} view={view} />;
}

const WIDTH = 1040;
const HEIGHT = 660;

interface Inspected {
  lon: number;
  lat: number;
  rasters: InspectLayer[] | null;
  vectors: VectorHit[];
}

function Window({ view }: { view: NodeView }) {
  const id = view.id;
  const runCount = useStore((s) => s.runCount);
  const colour = useCategoryColour("Params");
  // the wires into the viewer, as a string so the effect below only reruns when they change
  const wired = useStore((s) =>
    (s.graph?.workflow.wires ?? [])
      .filter((w) => w.to[0] === id)
      .map((w) => w.from.join("."))
      .join(" "),
  );
  const [data, setData] = useState<MapView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Record<string, RasterStats>>({});
  const [inspected, setInspected] = useState<Inspected | null>(null);

  useEffect(() => {
    let live = true;
    store.api.mapView(id).then(
      (d) => live && (setData(d), setError(null)),
      (e: unknown) => live && setError(e instanceof Error ? e.message : String(e)),
    );
    return () => {
      live = false;
    };
  }, [id, runCount, wired]);

  const saved = useMemo(() => view.map?.styles ?? {}, [view.map]);
  const basemap: Basemap = view.map?.basemap ?? "light";
  const layers = data?.layers ?? [];

  // statistics for bands other than the defaults, fetched when chosen
  useEffect(() => {
    for (const l of layers) {
      if (!l.raster || !l.key) continue;
      const style = effectiveStyle(l, saved[l.id]);
      const k = bandsKey(l.key, style.bands);
      if (statsFor(l, style, stats) || k in stats) continue;
      const key = l.key;
      store.api.rasterStats(key, style.bands).then(
        (s) => setStats((prev) => ({ ...prev, [k]: s })),
        () => undefined,
      );
    }
  }, [layers, saved, stats]);

  const rendered = useMemo(() => renderLayers(layers, saved), [layers, saved]);
  const bounds = useMemo(() => unionBounds(layers), [layers]);
  const fitKey = layers
    .filter((l) => l.status === "ready")
    .map((l) => l.id)
    .join(" ");

  const setStyle = (layer: string, change: Partial<LayerStyle> | null) =>
    void store.patchNode(id, { map: { styles: { [layer]: change } } });
  const setBasemap = (b: Basemap) => void store.patchNode(id, { map: { basemap: b } });

  const onInspect = (lon: number, lat: number, vectors: VectorHit[]) => {
    setInspected({ lon, lat, rasters: null, vectors });
    store.api.mapInspect(id, lon, lat).then(
      (r) => setInspected((cur) => (cur?.lon === lon && cur.lat === lat ? { ...cur, rasters: r.layers } : cur)),
      (e: unknown) => store.showToast(e instanceof Error ? e.message : String(e)),
    );
  };

  const [pos, setPos] = useState(() => ({
    x: Math.max(20, (window.innerWidth - WIDTH) / 2),
    y: Math.max(20, Math.min(100, window.innerHeight - HEIGHT - 20)),
  }));
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const onHeaderDown = (e: ReactPointerEvent) => {
    if ((e.target as Element).closest("button")) return;
    drag.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };
  const onHeaderMove = (e: ReactPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    setPos({
      x: Math.min(Math.max(0, e.clientX - d.dx), window.innerWidth - 120),
      y: Math.min(Math.max(0, e.clientY - d.dy), window.innerHeight - 60),
    });
  };

  return (
    <div
      className="gk-window gk-map-window"
      style={{ left: pos.x, top: pos.y, width: WIDTH, height: HEIGHT }}
      role="dialog"
      aria-label={strings.mapViewer}
      data-testid="map-window"
    >
      <header
        className="gk-window-header"
        onPointerDown={onHeaderDown}
        onPointerMove={onHeaderMove}
        onPointerUp={() => (drag.current = null)}
      >
        <span className="gk-window-category" style={{ color: colour }}>
          {strings.paramsTab}
        </span>
        <span className="gk-window-title">{strings.mapViewer}</span>
        <div className="gk-spacer" />
        <button
          className="gk-icon-button"
          onClick={() => store.closeMap()}
          aria-label={strings.close}
          data-testid="map-close"
        >
          <X size={16} />
        </button>
      </header>
      <div className="gk-map-body">
        <aside className="gk-map-side">
          <label className="gk-map-row">
            <span>{strings.basemap}</span>
            <select
              value={basemap}
              onChange={(e) => setBasemap(e.target.value as Basemap)}
              data-testid="map-basemap"
            >
              {(data?.basemaps ?? ["light", "none"]).map((b) => (
                <option key={b} value={b}>
                  {strings.basemapNames[b] ?? b}
                </option>
              ))}
            </select>
          </label>
          <h3 className="gk-map-heading">{strings.layers}</h3>
          {!data && !error && (
            <p className="gk-map-note" data-testid="map-loading">
              {strings.loadingLayers}
            </p>
          )}
          {error && <p className="gk-map-error">{error}</p>}
          {data && !layers.length && <p className="gk-map-note">{strings.noLayers}</p>}
          <ul className="gk-map-layers">
            {layers.map((l) => (
              <LayerItem
                key={l.id}
                layer={l}
                style={effectiveStyle(l, saved[l.id])}
                stats={statsFor(l, effectiveStyle(l, saved[l.id]), stats)}
                colormaps={data?.colormaps ?? {}}
                customised={l.id in saved}
                onChange={(change) => setStyle(l.id, change)}
              />
            ))}
          </ul>
          <InspectPanel inspected={inspected} layers={layers} />
        </aside>
        <MapCanvas
          basemap={basemap}
          layers={rendered}
          fitBounds={bounds}
          fitKey={fitKey}
          onInspect={onInspect}
        />
      </div>
    </div>
  );
}

// ── one layer in the list ──

interface LayerItemProps {
  layer: MapLayer;
  style: LayerStyle;
  stats: RasterStats | null;
  colormaps: Record<string, string[]>;
  customised: boolean;
  onChange: (change: Partial<LayerStyle> | null) => void;
}

export function LayerItem({ layer, style, stats, colormaps, customised, onChange }: LayerItemProps) {
  const ready = layer.status === "ready";
  return (
    <li className="gk-map-layer" data-testid={`layer-${layer.id}`} data-status={layer.status}>
      <div className="gk-map-layer-head">
        <input
          type="checkbox"
          checked={ready && style.visible}
          disabled={!ready}
          onChange={(e) => onChange({ visible: e.target.checked })}
          aria-label={strings.showLayer}
          data-testid={`layer-visible-${layer.id}`}
        />
        <span className="gk-map-layer-title">{layer.title}</span>
        {layer.type && <span className="gk-map-layer-type">{layer.type}</span>}
        {customised && (
          <button
            className="gk-icon-button"
            onClick={() => onChange(null)}
            title={strings.resetStyle}
            aria-label={strings.resetStyle}
            data-testid={`layer-reset-${layer.id}`}
          >
            <RotateCcw size={13} />
          </button>
        )}
      </div>
      {!ready && layer.message && <p className="gk-map-note">{layer.message}</p>}
      {ready && layer.raster && (
        <RasterControls layer={layer} style={style} stats={stats} colormaps={colormaps} onChange={onChange} />
      )}
      {ready && layer.vector && (
        <>
          <div className="gk-map-row">
            <span>{strings.colour}</span>
            <div className="gk-map-swatches">
              {VECTOR_COLOURS.map((c) => (
                <button
                  key={c}
                  className={`gk-map-swatch${c === style.color ? " gk-map-swatch-on" : ""}`}
                  style={{ background: c }}
                  onClick={() => onChange({ color: c })}
                  aria-label={c}
                  data-testid={`layer-colour-${layer.id}-${c.slice(1)}`}
                />
              ))}
            </div>
          </div>
          <p className="gk-map-note">
            {strings.featuresShown(layer.vector.shown, layer.vector.features)}
          </p>
        </>
      )}
      {ready && (
        <label className="gk-map-row">
          <span>{strings.opacity}</span>
          <Opacity value={style.opacity} onCommit={(opacity) => onChange({ opacity })} id={layer.id} />
        </label>
      )}
      {ready && <LegendView legend={legendFor(layer, style, stats, colormaps)} layer={layer.id} />}
    </li>
  );
}

function RasterControls({
  layer,
  style,
  stats,
  colormaps,
  onChange,
}: {
  layer: MapLayer;
  style: LayerStyle;
  stats: RasterStats | null;
  colormaps: Record<string, string[]>;
  onChange: (change: Partial<LayerStyle>) => void;
}) {
  const names = layer.raster?.bands ?? [];
  const rgb = isRgb(style);
  // new bands: let the server stretch them again
  const setBands = (bands: number[]) => onChange({ bands, min: null, max: null });
  const bandSelect = (value: number, onPick: (b: number) => void, testid: string, label: string) => (
    <select
      value={value}
      onChange={(e) => onPick(Number(e.target.value))}
      aria-label={label}
      data-testid={testid}
    >
      {names.map((n, i) => (
        <option key={n + i} value={i + 1}>
          {n}
        </option>
      ))}
    </select>
  );
  const r = range(style, stats);
  const colormapNames = Object.keys(colormaps);
  const categorical = stats?.classes ? [CATEGORICAL] : [];
  return (
    <>
      {names.length >= 3 && (
        <div className="gk-map-row">
          <span>{strings.band}</span>
          <div className="gk-map-segmented">
            <button
              className={!rgb ? "gk-on" : ""}
              onClick={() => rgb && setBands([style.bands[0]])}
              data-testid={`layer-single-${layer.id}`}
            >
              {strings.singleBand}
            </button>
            <button
              className={rgb ? "gk-on" : ""}
              onClick={() => !rgb && setBands(names.length === 3 ? [1, 2, 3] : [3, 2, 1])}
              data-testid={`layer-rgb-${layer.id}`}
            >
              {strings.rgb}
            </button>
          </div>
        </div>
      )}
      {rgb ? (
        <div className="gk-map-row gk-map-rgb">
          {([strings.red, strings.green, strings.blue] as const).map((label, i) => (
            <label key={label}>
              <span>{label}</span>
              {bandSelect(
                style.bands[i],
                (b) => setBands(style.bands.map((x, j) => (j === i ? b : x))),
                `layer-band-${layer.id}-${i}`,
                label,
              )}
            </label>
          ))}
        </div>
      ) : (
        names.length > 1 && (
          <label className="gk-map-row">
            <span>{strings.band}</span>
            {bandSelect(style.bands[0], (b) => setBands([b]), `layer-band-${layer.id}`, strings.band)}
          </label>
        )
      )}
      {!rgb && (
        <label className="gk-map-row">
          <span>{strings.colormap}</span>
          <select
            value={style.colormap}
            onChange={(e) => onChange({ colormap: e.target.value })}
            data-testid={`layer-colormap-${layer.id}`}
          >
            {[...categorical, ...colormapNames].map((c) => (
              <option key={c} value={c}>
                {strings.colormapNames[c] ?? c}
              </option>
            ))}
          </select>
        </label>
      )}
      {(rgb || style.colormap !== CATEGORICAL) && (
        <div className="gk-map-row gk-map-range">
          <NumberField
            label={strings.min}
            value={style.min}
            placeholder={r ? formatValue(r[0]) : strings.autoStretch}
            onCommit={(min) => onChange({ min })}
            testid={`layer-min-${layer.id}`}
          />
          <NumberField
            label={strings.max}
            value={style.max}
            placeholder={r ? formatValue(r[1]) : strings.autoStretch}
            onCommit={(max) => onChange({ max })}
            testid={`layer-max-${layer.id}`}
          />
        </div>
      )}
    </>
  );
}

/** A number applied on Enter or leaving the field; empty means "automatic" (null). */
function NumberField({
  label,
  value,
  placeholder,
  onCommit,
  testid,
}: {
  label: string;
  value: number | null;
  placeholder: string;
  onCommit: (v: number | null) => void;
  testid: string;
}) {
  const shown = value === null ? "" : formatValue(value);
  const [text, setText] = useState(shown);
  useEffect(() => setText(shown), [shown]);
  const commit = () => {
    const t = text.trim();
    if (t === shown) return; // untouched (the field shows a rounded value)
    const next = t === "" ? null : Number(t);
    if (next !== null && !Number.isFinite(next)) return setText(shown);
    onCommit(next);
  };
  return (
    <label>
      <span>{label}</span>
      <input
        value={text}
        placeholder={placeholder}
        inputMode="decimal"
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
        data-testid={testid}
      />
    </label>
  );
}

/** Opacity slider: one change (one undo step) when the slider is let go. */
function Opacity({ value, onCommit, id }: { value: number; onCommit: (v: number) => void; id: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => v !== value && onCommit(v);
  return (
    <input
      type="range"
      min={0}
      max={1}
      step={0.05}
      value={v}
      onChange={(e) => setV(Number(e.target.value))}
      onPointerUp={commit}
      onKeyUp={commit}
      onBlur={commit}
      data-testid={`layer-opacity-${id}`}
    />
  );
}

export function LegendView({ legend, layer }: { legend: Legend | null; layer: string }) {
  if (!legend) return null;
  const testid = `legend-${layer}`;
  switch (legend.kind) {
    case "ramp":
      return (
        <div className="gk-map-legend" data-testid={testid} data-kind="ramp">
          <div
            className="gk-map-ramp"
            style={{ background: `linear-gradient(to right, ${legend.colours.join(", ")})` }}
          />
          <div className="gk-map-ramp-labels">
            <span>{formatValue(legend.min)}</span>
            <span>{formatValue(legend.max)}</span>
          </div>
        </div>
      );
    case "classes":
      return (
        <ul className="gk-map-legend gk-map-classes" data-testid={testid} data-kind="classes">
          {legend.classes.map((c) => (
            <li key={c.value}>
              <span className="gk-map-swatch-small" style={{ background: c.color }} />
              {strings.classValue(c.value)}
            </li>
          ))}
        </ul>
      );
    case "rgb":
      return (
        <div className="gk-map-legend" data-testid={testid} data-kind="rgb">
          {strings.rgb}: {legend.bands.join(" · ")} ({formatValue(legend.min)}–{formatValue(legend.max)})
        </div>
      );
    case "vector":
      return null; // the swatches above already show the colour
  }
}

// ── inspect ──

function InspectPanel({ inspected, layers }: { inspected: Inspected | null; layers: MapLayer[] }) {
  const titles = Object.fromEntries(layers.map((l) => [l.id, l.title]));
  return (
    <section
      className="gk-map-inspect"
      data-testid="inspect"
      data-lon={inspected?.lon}
      data-lat={inspected?.lat}
    >
      <h3 className="gk-map-heading">{strings.inspect}</h3>
      {!inspected && <p className="gk-map-note">{strings.inspectHint}</p>}
      {inspected && (
        <>
          <p className="gk-map-note">
            {inspected.lat.toFixed(5)}, {inspected.lon.toFixed(5)}
          </p>
          {inspected.rasters?.map((r) => (
            <div key={r.id} className="gk-map-inspect-layer" data-testid={`inspect-${r.id}`}>
              <div className="gk-map-layer-title">{r.title}</div>
              {r.outside ? (
                <span className="gk-map-note">{strings.inspectOutside}</span>
              ) : (
                <table>
                  <tbody>
                    {r.values.map((v) => (
                      <tr key={v.band}>
                        <th>{v.band}</th>
                        <td data-testid={`inspect-value-${r.id}-${v.band}`}>
                          {v.value === null ? strings.inspectNodata : formatValue(v.value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
          {inspected.vectors.map((hit, i) => (
            <div key={`${hit.layer}-${i}`} className="gk-map-inspect-layer" data-testid={`inspect-${hit.layer}`}>
              <div className="gk-map-layer-title">{titles[hit.layer] ?? hit.layer}</div>
              <table>
                <tbody>
                  {Object.entries(hit.properties).map(([k, v]) => (
                    <tr key={k}>
                      <th>{k}</th>
                      <td>{typeof v === "number" ? formatValue(v) : String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </section>
  );
}

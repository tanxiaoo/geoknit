// The MapLibre map of the Map Viewer window. MapLibre is bundled locally and
// loaded the first time a map opens, so the canvas does not pay for it.

import { useEffect, useRef, useState } from "react";
import type { GeoJSONSource, Map as MlMap, Marker } from "maplibre-gl";
import type { Basemap } from "../../apiTypes";
import { strings } from "../../strings";
import type { RenderLayer } from "./layers";

type MapLibre = typeof import("maplibre-gl");

export interface VectorHit {
  layer: string;
  properties: Record<string, unknown>;
}

interface Props {
  basemap: Basemap;
  layers: RenderLayer[];
  /** Fit the view to these bounds whenever ``fitKey`` changes. */
  fitBounds: [number, number, number, number] | null;
  fitKey: string;
  onInspect: (lon: number, lat: number, hits: VectorHit[]) => void;
}

declare global {
  interface Window {
    __geoknitMap?: MlMap; // for end-to-end tests
  }
}

// OpenStreetMap's own tiles: no API key, attribution shown (tile usage policy:
// https://operations.osmfoundation.org/policies/tiles/). Greyed below for a light map.
const BASEMAP_TILES = ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"];
const BASEMAP = "gk-basemap";
const PREFIX = "gk-layer-";

const sourceId = (id: string) => `${PREFIX}${id}`;
/** MapLibre loads tiles in a worker, which cannot resolve a URL relative to the page. */
const absolute = (url: string) => `${window.location.origin}${url}`;
const vectorParts = (id: string) => ["fill", "line", "circle"].map((p) => `${PREFIX}${id}-${p}`);
const layerIds = (l: RenderLayer) => (l.kind === "raster" ? [sourceId(l.id)] : vectorParts(l.id));

const POLYGON = ["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false];
const LINE = [
  "match",
  ["geometry-type"],
  ["Polygon", "MultiPolygon", "LineString", "MultiLineString"],
  true,
  false,
];
const POINT = ["match", ["geometry-type"], ["Point", "MultiPoint"], true, false];

/** Bring the map in line with ``layers`` (top first) and ``basemap``; ``urls`` remembers sources. */
function sync(map: MlMap, layers: RenderLayer[], basemap: Basemap, urls: Map<string, string>) {
  // the basemap is added or removed, so "none" never contacts the tile service
  if (basemap === "light" && !map.getSource(BASEMAP)) {
    map.addSource(BASEMAP, {
      type: "raster",
      tiles: BASEMAP_TILES,
      tileSize: 256,
      maxzoom: 19,
      attribution: strings.basemapAttribution,
    });
    map.addLayer({
      id: BASEMAP,
      type: "raster",
      source: BASEMAP,
      paint: {
        "raster-saturation": -0.85,
        "raster-brightness-min": 0.25,
        "raster-contrast": -0.15,
      },
    });
  } else if (basemap === "none" && map.getSource(BASEMAP)) {
    map.removeLayer(BASEMAP);
    map.removeSource(BASEMAP);
  }

  const wanted = new Set(layers.map((l) => sourceId(l.id)));
  for (const src of [...urls.keys()]) {
    if (wanted.has(src)) continue;
    const id = src.slice(PREFIX.length);
    for (const layer of [src, ...vectorParts(id)]) if (map.getLayer(layer)) map.removeLayer(layer);
    if (map.getSource(src)) map.removeSource(src);
    urls.delete(src);
  }

  for (const l of layers) {
    const src = sourceId(l.id);
    if (urls.get(src) !== l.url) {
      for (const layer of layerIds(l)) if (map.getLayer(layer)) map.removeLayer(layer);
      if (map.getSource(src)) {
        const existing = map.getSource(src);
        if (l.kind === "vector" && existing?.type === "geojson") {
          (existing as GeoJSONSource).setData(absolute(l.url));
        } else {
          map.removeSource(src);
        }
      }
      if (!map.getSource(src)) {
        map.addSource(
          src,
          l.kind === "raster"
            ? { type: "raster", tiles: [absolute(l.url)], tileSize: 256, bounds: l.bounds }
            : { type: "geojson", data: absolute(l.url) },
        );
      }
      urls.set(src, l.url);
    }
    const visibility = l.visible ? "visible" : "none";
    if (l.kind === "raster") {
      if (!map.getLayer(src)) {
        map.addLayer({
          id: src,
          type: "raster",
          source: src,
          paint: { "raster-fade-duration": 0 },
        });
      }
      map.setPaintProperty(src, "raster-opacity", l.opacity);
      map.setPaintProperty(src, "raster-resampling", l.nearest ? "nearest" : "linear");
      map.setLayoutProperty(src, "visibility", visibility);
    } else {
      const [fill, line, circle] = vectorParts(l.id);
      if (!map.getLayer(fill)) {
        map.addLayer({ id: fill, type: "fill", source: src, filter: POLYGON as never });
        map.addLayer({ id: line, type: "line", source: src, filter: LINE as never });
        map.addLayer({ id: circle, type: "circle", source: src, filter: POINT as never });
      }
      map.setPaintProperty(fill, "fill-color", l.colour);
      map.setPaintProperty(fill, "fill-opacity", 0.25 * l.opacity);
      map.setPaintProperty(line, "line-color", l.colour);
      map.setPaintProperty(line, "line-opacity", l.opacity);
      map.setPaintProperty(line, "line-width", 1.5);
      map.setPaintProperty(circle, "circle-color", l.colour);
      map.setPaintProperty(circle, "circle-opacity", l.opacity);
      map.setPaintProperty(circle, "circle-radius", 4);
      map.setPaintProperty(circle, "circle-stroke-color", "#ffffff");
      map.setPaintProperty(circle, "circle-stroke-width", 1);
      for (const part of [fill, line, circle]) map.setLayoutProperty(part, "visibility", visibility);
    }
  }

  // the first layer in the list is drawn on top: move each to the top, last first
  for (const l of [...layers].reverse()) {
    for (const id of layerIds(l)) if (map.getLayer(id)) map.moveLayer(id);
  }
}

export function MapCanvas({ basemap, layers, fitBounds, fitKey, onInspect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const libRef = useRef<MapLibre | null>(null);
  const urls = useRef(new Map<string, string>());
  const marker = useRef<Marker | null>(null);
  const inspect = useRef(onInspect);
  inspect.current = onInspect;
  const vectorLayers = useRef<string[]>([]);
  vectorLayers.current = layers.filter((l) => l.kind === "vector").flatMap((l) => vectorParts(l.id));
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    void Promise.all([import("maplibre-gl"), import("maplibre-gl/dist/maplibre-gl.css")])
      .then(([lib]) => {
        if (disposed || !container.current) return;
        const maplibre = (lib as unknown as { default?: MapLibre }).default ?? lib;
        libRef.current = maplibre;
        const map = new maplibre.Map({
          container: container.current,
          style: {
            version: 8,
            sources: {},
            layers: [{ id: "gk-background", type: "background", paint: { "background-color": "#f1f3f4" } }],
          },
          center: [0, 20],
          zoom: 1,
          attributionControl: { compact: true },
        });
        map.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-right");
        map.addControl(new maplibre.ScaleControl({}), "bottom-left");
        map.on("load", () => !disposed && setReady(true));
        map.on("click", (e) => {
          const hits = map
            .queryRenderedFeatures(e.point, {
              layers: vectorLayers.current.filter((id) => map.getLayer(id)),
            })
            .map((f) => ({
              layer: f.layer.id.slice(PREFIX.length).replace(/-(fill|line|circle)$/, ""),
              properties: { ...f.properties },
            }));
          marker.current?.remove();
          marker.current = new maplibre.Marker({ color: "#2563eb", scale: 0.7 })
            .setLngLat(e.lngLat)
            .addTo(map);
          inspect.current(e.lngLat.lng, e.lngLat.lat, hits);
        });
        mapRef.current = map;
        window.__geoknitMap = map;
      })
      .catch((e: unknown) => !disposed && setFailed(e instanceof Error ? e.message : String(e)));
    return () => {
      disposed = true;
      mapRef.current?.remove();
      mapRef.current = null;
      urls.current.clear();
      if (window.__geoknitMap) delete window.__geoknitMap;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (ready && map) sync(map, layers, basemap, urls.current);
  }, [ready, layers, basemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !fitBounds) return;
    const [w, s, e, n] = fitBounds;
    map.fitBounds(
      [
        [w, s],
        [e, n],
      ],
      { padding: 40, duration: 0, maxZoom: 18 },
    );
  }, [ready, fitKey]); // not fitBounds: refit only when the set of layers changes

  return (
    <div className="gk-map-canvas" data-testid="map-canvas" data-ready={ready}>
      <div ref={container} className="gk-map-gl" />
      {!ready && !failed && <div className="gk-map-overlay">{strings.loadingMap}</div>}
      {failed && <div className="gk-map-overlay">{strings.mapFailed(failed)}</div>}
    </div>
  );
}

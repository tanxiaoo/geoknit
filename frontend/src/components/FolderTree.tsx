import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Folder } from "lucide-react";
import type { FileNode } from "../apiTypes";
import { store, useStore } from "../store";
import { MIME_PATH } from "./Canvas";

const RASTER = [".tif", ".tiff", ".vrt", ".img", ".jp2", ".nc"];
const VECTOR = [".gpkg", ".shp", ".geojson", ".json", ".parquet", ".fgb", ".kml"];

/** The badge before a file name: R raster, V vector, G workflow. */
export function fileBadge(name: string): { letter: string; kind: string } | null {
  const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
  if (RASTER.includes(ext)) return { letter: "R", kind: "raster" };
  if (VECTOR.includes(ext)) return { letter: "V", kind: "vector" };
  if (ext === ".geoknit") return { letter: "G", kind: "workflow" };
  return null;
}

function Entry({ node, depth }: { node: FileNode; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  const pad = { paddingLeft: 8 + depth * 14 };
  if (node.kind === "dir") {
    return (
      <li>
        <div className="gk-tree-row" style={pad} onClick={() => setOpen(!open)}>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Folder size={14} className="gk-folder-icon" />
          {node.name}
        </div>
        {open && (
          <ul>
            {node.children?.map((c) => <Entry key={c.path} node={c} depth={depth + 1} />)}
          </ul>
        )}
      </li>
    );
  }
  const badge = fileBadge(node.name);
  return (
    <li>
      <div
        className="gk-tree-row gk-tree-file"
        style={{ paddingLeft: 8 + depth * 14 + 14 }}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(MIME_PATH, node.path);
          e.dataTransfer.effectAllowed = "copy";
        }}
        title={node.path}
        data-testid={`file-${node.path}`}
      >
        <span className={`gk-file-badge gk-badge-${badge?.kind ?? "other"}`}>
          {badge?.letter ?? ""}
        </span>
        {node.name}
      </div>
    </li>
  );
}

/** The project folder (SPEC 8): drag a file onto the canvas for a Text with its path. */
export function FolderTree() {
  const files = useStore((s) => s.files);
  useEffect(() => {
    const refresh = () => void store.refreshFiles();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, []);
  return (
    <aside className="gk-folder" data-testid="folder-tree">
      <div className="gk-folder-title">{files?.name}</div>
      <ul>{files?.children?.map((c) => <Entry key={c.path} node={c} depth={0} />)}</ul>
    </aside>
  );
}

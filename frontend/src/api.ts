// Typed client for the GeoKnit server (SPEC 9). Every UI action goes through here.

import type {
  ComponentEntry,
  FileNode,
  GraphView,
  NodeOutput,
  NodePatch,
  NodeView,
  Status,
  ViewJson,
} from "./apiTypes";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data: unknown = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | undefined)?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg ?? "").join("; ")
          : res.statusText;
    throw new ApiError(message, res.status);
  }
  return data as T;
}

export const api = {
  components: () => request<ComponentEntry[]>("GET", "/api/components"),
  graph: () => request<GraphView>("GET", "/api/graph"),
  status: () => request<Status>("GET", "/api/status"),
  files: () => request<FileNode>("GET", "/api/files"),
  addNode: (component: string, position: [number, number], source?: string) =>
    request<NodeView>("POST", "/api/nodes", { component, position, source }),
  patchNode: (id: string, patch: NodePatch) =>
    request<NodeView>("PATCH", `/api/nodes/${encodeURIComponent(id)}`, patch),
  removeNode: (id: string) => request<void>("DELETE", `/api/nodes/${encodeURIComponent(id)}`),
  addWire: (from: [string, string], to: [string, string]) =>
    request<unknown>("POST", "/api/wires", { from, to }),
  removeWire: (from: [string, string], to: [string, string]) =>
    request<void>("DELETE", "/api/wires", { from, to }),
  patchView: (view: ViewJson) => request<ViewJson>("PATCH", "/api/view", view),
  run: (mode: "all" | "to_node" | "test" = "all", nodeId?: string) =>
    request<{ plan: string[] }>("POST", "/api/run", { mode, node_id: nodeId }),
  stop: () => request<unknown>("POST", "/api/stop"),
  output: (id: string) =>
    request<NodeOutput>("GET", `/api/nodes/${encodeURIComponent(id)}/output`),
  trust: () => request<unknown>("POST", "/api/workflow/trust"),
};

export type Api = typeof api;

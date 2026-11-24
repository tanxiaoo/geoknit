// /ws client: feeds server events into the store and reconnects when dropped.

import type { ServerEvent } from "./apiTypes";
import type { Store } from "./store";

export function connectEvents(store: Store): () => void {
  let socket: WebSocket | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | undefined;

  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws`);
    socket.onopen = () => {
      store.setConnected(true);
      void store.refreshGraph(); // catch up on anything missed while away
    };
    socket.onmessage = (msg) => {
      try {
        store.applyEvent(JSON.parse(String(msg.data)) as ServerEvent);
      } catch {
        /* ignore malformed events */
      }
    };
    socket.onclose = () => {
      store.setConnected(false);
      if (!closed) retry = setTimeout(open, 1000);
    };
  };
  open();

  return () => {
    closed = true;
    clearTimeout(retry);
    socket?.close();
  };
}

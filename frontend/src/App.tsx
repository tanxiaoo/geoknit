import { useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Assistant } from "./components/Assistant";
import { Canvas } from "./components/Canvas";
import { CanvasToolbar } from "./components/CanvasToolbar";
import { FolderTree } from "./components/FolderTree";
import { Ribbon } from "./components/Ribbon";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { ColormapWindow } from "./components/colormap/ColormapWindow";
import { LayerWindow } from "./components/layer/LayerWindow";
import { MapWindow } from "./components/map/MapWindow";
import { ComponentWindow } from "./components/window/ComponentWindow";
import { store, useStore } from "./store";
import { connectEvents } from "./ws";

function Tip() {
  const tip = useStore((s) => s.tip);
  if (!tip) return null;
  return (
    <div className="gk-tip" style={{ left: tip.x + 14, top: tip.y + 14 }} data-testid="tip">
      {tip.text}
    </div>
  );
}

function Toast() {
  const toast = useStore((s) => s.toast);
  if (!toast) return null;
  const style =
    toast.x !== undefined && toast.y !== undefined
      ? { left: toast.x + 12, top: toast.y + 12 }
      : { left: "50%", bottom: 48, transform: "translateX(-50%)" };
  return (
    <div className="gk-toast" style={style} role="alert" data-testid="toast">
      {toast.message}
    </div>
  );
}

export function App() {
  useEffect(() => {
    void store.load();
    void store.loadSettings();
    return connectEvents(store);
  }, []);
  return (
    <ReactFlowProvider>
      <div className="gk-app">
        <TopBar />
        <Ribbon />
        <div className="gk-main">
          <FolderTree />
          <section className="gk-center">
            <CanvasToolbar />
            <Canvas />
            <StatusBar />
          </section>
          <Assistant />
        </div>
        <ComponentWindow />
        <MapWindow />
        <ColormapWindow />
        <LayerWindow />
        <Tip />
        <Toast />
      </div>
    </ReactFlowProvider>
  );
}

// All user-facing text lives here, so translations can be added later.
export const strings = {
  appTitle: "GeoKnit",
  appTagline: "Visual programming for geospatial analysis",

  // top bar
  untitled: "untitled.geoknit",
  notSaved: "not saved",
  workerStatus: (python: string, worker: string) => `Python ${python} · worker ${worker}`,
  workerIdle: "idle",
  workerRunning: "running",
  workerOffline: "offline",
  exportPy: "Export .py",
  exportLater: "Export to Python arrives in a later version",
  stop: "Stop",
  run: "Run",

  // ribbon
  paramsTab: "Params",
  numberSlider: "Number Slider",
  text: "Text",
  panel: "Panel",
  searchPlaceholder: "Search components (or double-click empty canvas)",
  noMatches: "No matching components",
  addHint: "Click to add, or drag onto the canvas",

  // canvas toolbar
  zoomOut: "Zoom out",
  zoomIn: "Zoom in",
  fit: "Fit",
  showAs: "Show as",
  showText: "Text",
  showIcon: "Icon",
  canvasHint: "Double-click a component for settings, code and output",
  outOfDate: (n: number) => `${n} component${n === 1 ? "" : "s"} out of date`,
  changed: (what: string) => `${what} changed`,

  // trust (SPEC 11)
  untrusted: "This workflow contains Python code. Trust and allow running?",
  trust: "Trust",

  // nodes
  textPlaceholder: "double-click to type",
  panelEmpty: "(empty)",
  panelRunToUpdate: "run to update",
  runToHere: "Run to here",
  deleteNode: "Delete",
  sliderMin: "min",
  sliderMax: "max",
  sliderStep: "step",
  sliderValue: "value",
  ok: "OK",
  cancel: "Cancel",

  // status bar
  dataTypes: "Data types",
  legendOutOfDate: "out of date",
  legendError: "error",
  legendSelected: "open / selected",

  // assistant placeholder
  assistant: "Assistant",
  nextVersion: "Next version",
  assistantReserved:
    "Reserved for an AI agent (Claude Code or another LLM) that works directly on this canvas.",
  plannedAbilities: "Planned abilities",
  abilities: [
    "Create a new component from a description",
    "Build or rewire a workflow on the canvas",
    "Read the Output log and fix errors",
    "Explain what a component or wire carries",
  ],
  exampleRequests: "Example requests",
  examples: [
    "Make a component that computes NDVI from a Sentinel-2 raster",
    "Add an SVM next to Random Forest and validate both",
    "Why did the Python component fail?",
  ],
  model: "Model",
  assistantModel: "Claude",
  message: "Message",
  messagePlaceholder: "Describe a component or workflow…",
  send: "Send",
  collapse: "Collapse",
  expand: "Assistant",

  // errors
  cannotReachServer: "Cannot reach the GeoKnit server",
  runFailed: (message: string) => `Run failed: ${message}`,
} as const;

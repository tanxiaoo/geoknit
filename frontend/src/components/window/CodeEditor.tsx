import { useEffect, useRef, useState } from "react";
import type * as Monaco from "monaco-editor";
import { strings } from "../../strings";
import { useTheme, type Theme } from "../../theme";

declare global {
  interface Window {
    /** The open Code tab's editor, for end-to-end tests. */
    __geoknitEditor?: Monaco.editor.IStandaloneCodeEditor;
  }
}

/** Monaco's built-in theme for a GeoKnit theme. */
const MONACO_THEME: Record<Theme, string> = { light: "vs", dark: "vs-dark" };

interface Props {
  value: string;
  onChange: (value: string) => void;
  /** Called when the editor loses focus (the window applies the code then). */
  onBlur?: () => void;
  /** Line to highlight (a parse error), 1-based. */
  errorLine?: number | null;
}

/** Monaco editor for a whole component file (SPEC 8 Code tab). */
export function CodeEditor({ value, onChange, onBlur, errorLine }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof Monaco | null>(null);
  const decorations = useRef<Monaco.editor.IEditorDecorationsCollection | null>(null);
  const callbacks = useRef({ onChange, onBlur });
  callbacks.current = { onChange, onBlur };
  const [ready, setReady] = useState(false);
  const theme = useTheme();
  const themeRef = useRef(theme);
  themeRef.current = theme;

  useEffect(() => {
    let disposed = false;
    void import("./monaco").then(({ monaco }) => {
      if (disposed || !host.current) return;
      monacoRef.current = monaco;
      const ed = monaco.editor.create(host.current, {
        value,
        language: "python",
        theme: MONACO_THEME[themeRef.current],
        automaticLayout: true,
        minimap: { enabled: false },
        fontSize: 13,
        lineNumbersMinChars: 3,
        scrollBeyondLastLine: false,
        tabSize: 4,
        insertSpaces: true,
        renderWhitespace: "selection",
      });
      ed.onDidChangeModelContent(() => callbacks.current.onChange(ed.getValue()));
      ed.onDidBlurEditorText(() => callbacks.current.onBlur?.());
      editor.current = ed;
      decorations.current = ed.createDecorationsCollection();
      window.__geoknitEditor = ed;
      setReady(true);
    });
    return () => {
      disposed = true;
      if (window.__geoknitEditor === editor.current) delete window.__geoknitEditor;
      editor.current?.dispose();
      editor.current = null;
    };
    // the editor is created once; `value` updates go through the effect below
  }, []);

  // Follow outside changes (Settings tab, VS Code) without losing the cursor.
  useEffect(() => {
    const ed = editor.current;
    if (!ed || ed.getValue() === value) return;
    const model = ed.getModel();
    if (!model) return;
    ed.pushUndoStop();
    ed.executeEdits("geoknit", [{ range: model.getFullModelRange(), text: value }]);
    ed.pushUndoStop();
  }, [value, ready]);

  // Follow the theme live (the theme is global to Monaco, not per editor).
  useEffect(() => {
    if (ready) monacoRef.current?.editor.setTheme(MONACO_THEME[theme]);
  }, [theme, ready]);

  useEffect(() => {
    const monaco = monacoRef.current;
    if (!monaco || !decorations.current) return;
    decorations.current.set(
      errorLine
        ? [
            {
              range: new monaco.Range(errorLine, 1, errorLine, 1),
              options: { isWholeLine: true, className: "gk-code-error-line" },
            },
          ]
        : [],
    );
  }, [errorLine, ready]);

  return (
    <div className="gk-code-editor" data-testid="code-editor">
      {!ready && <div className="gk-muted gk-code-loading">{strings.loadingEditor}</div>}
      <div ref={host} className="gk-code-host" />
    </div>
  );
}

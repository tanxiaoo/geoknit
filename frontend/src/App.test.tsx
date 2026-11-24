import { render, screen } from "@testing-library/react";
import { App } from "./App";
import { strings } from "./strings";

test("renders the app title", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: strings.appTitle })).toBeTruthy();
});

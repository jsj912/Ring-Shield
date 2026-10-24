import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App, { makeQueryClient } from "./App";
import "./index.css";

const client = makeQueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App client={client} />
  </StrictMode>,
);

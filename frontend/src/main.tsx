import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

const iconLink =
  document.querySelector<HTMLLinkElement>("link[rel='icon']") ??
  document.head.appendChild(document.createElement("link"));

iconLink.rel = "icon";
iconLink.type = "image/png";
iconLink.href = "/favicon.png";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>
);

window.requestAnimationFrame(() => {
  window.requestAnimationFrame(() => {
    const loader = document.getElementById("app-loader");
    if (!loader) {
      return;
    }

    loader.style.opacity = "0";
    window.setTimeout(() => loader.remove(), 220);
  });
});

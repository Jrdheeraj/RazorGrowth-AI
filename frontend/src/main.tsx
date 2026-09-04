import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

// Self-hosted fonts (no runtime network dependency)
import "@fontsource-variable/archivo";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

// Design system
import "./styles/tokens.css";
import "./styles/global.css";
import "./styles/components.css";

// Auth context wraps the whole application so every component can read
// the authenticated user via useAuth().
import { AuthProvider } from "./lib/AuthContext";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);

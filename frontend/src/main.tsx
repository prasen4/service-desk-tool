import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { JobActivityProvider } from "./hooks/useJobActivity";
import "./theme.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <JobActivityProvider>
        <App />
      </JobActivityProvider>
    </BrowserRouter>
  </React.StrictMode>
);

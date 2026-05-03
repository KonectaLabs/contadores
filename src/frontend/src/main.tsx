import React, { type CSSProperties, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

const fallbackShellStyle: CSSProperties = {
  minHeight: "100vh",
  display: "grid",
  placeItems: "center",
  padding: 24,
  background: "#f5f7f8",
  color: "#1d2b32",
  fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
};

const fallbackPanelStyle: CSSProperties = {
  width: "min(420px, 100%)",
  border: "1px solid #d8e0e4",
  borderRadius: 8,
  background: "#ffffff",
  padding: 24,
  boxShadow: "0 18px 44px rgba(29, 43, 50, 0.12)",
};

const fallbackTextStyle: CSSProperties = {
  margin: "0 0 18px",
  color: "#50616b",
  lineHeight: 1.5,
};

const fallbackButtonStyle: CSSProperties = {
  border: 0,
  borderRadius: 8,
  background: "#0f766e",
  color: "#ffffff",
  cursor: "pointer",
  font: "600 14px Inter, system-ui, sans-serif",
  padding: "10px 14px",
};

type ErrorBoundaryProps = {
  children: ReactNode;
};

type ErrorBoundaryState = {
  hasError: boolean;
};

class RootErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Contadores CRM render failed", error, info);
  }

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <main style={fallbackShellStyle}>
        <section style={fallbackPanelStyle}>
          <h1 style={{ margin: "0 0 8px", fontSize: 22, lineHeight: 1.2 }}>CRM could not load</h1>
          <p style={fallbackTextStyle}>
            An unexpected interface error stopped the app. Reloading usually restores the session.
          </p>
          <button type="button" onClick={() => window.location.reload()} style={fallbackButtonStyle}>
            Reload CRM
          </button>
        </section>
      </main>
    );
  }
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </React.StrictMode>,
);

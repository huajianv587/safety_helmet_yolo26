import { useEffect } from 'react';
import { initLegacyConsole } from './legacy/bootstrap';

function App() {
  useEffect(() => {
    void initLegacyConsole();
  }, []);

  return (
    <>
      <div id="c-dot" />
      <div id="c-ring" />
      <div id="c-pulse" />
      <div className="bg-grid" aria-hidden="true" />
      <div className="bg-scanline" aria-hidden="true" />

      <div className="app-shell">
        <aside className="app-sidebar" id="sidebar">
          <div className="sidebar-logo">
            <div className="logo-mark">SH</div>
            <div>
              <div className="logo-name">Safety Helmet</div>
              <div className="logo-tag">FIELD CONTROL LIVE</div>
            </div>
          </div>
          <nav className="sidebar-nav" id="nav-links" />
          <div className="sidebar-status">
            <div className="status-row">
              <span className="status-dot" id="health-dot" />
              <span id="health-text" className="status-label">
                Connecting
              </span>
            </div>
            <div className="status-version">Helmet OS 2026</div>
          </div>
        </aside>

        <div className="app-main">
          <header className="app-topbar">
            <button className="mobile-menu-btn" id="mobile-menu-btn" aria-label="Open navigation">
              MENU
            </button>
            <div className="topbar-crumb">
              <span className="crumb-root">SH</span>
              <span className="crumb-sep">/</span>
              <span className="crumb-page" id="page-title">
                Dashboard
              </span>
            </div>
            <div className="topbar-right" id="header-actions" />
          </header>
          <main className="app-content" id="app-root" />
        </div>
      </div>
      <div className="sidebar-scrim" id="sidebar-scrim" />

      <div id="toast-container" />
    </>
  );
}

export default App;

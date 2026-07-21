"""Simulator page CSS — Blue Watch / Deep Chrome palette (DESIGN.md tokens)."""

SIM_CSS = """
        <style>
          :root {
              --sim-bg: #0A1A2E; /* Blue Watch shell (DESIGN.md) */
              --sim-surface: #0D2137;
              --sim-border: rgba(59, 125, 216, 0.35);
              --sim-border-glow: rgba(59, 125, 216, 0.8);
              --sim-primary: #3B7DD8;
              --sim-primary-hover: #5B8DEF;
              --sim-text: #E8EDF4;
              --muted: #9AABC4;
              --accent: #f43f5e;
          }

          /* Full Page Background */
          .q-page {
              background: var(--sim-bg) !important;
              color: var(--sim-text) !important;
              font-family: 'IBM Plex Sans', 'Roboto', sans-serif !important;
          }

          /* Constraint / option rows — compact, calm (declutter pass) */
          .sim-option-card {
              background: var(--sim-surface);
              border: 1px solid rgba(197,206,217,0.12);
              border-radius: 8px;
              padding: 10px 14px;
              margin-bottom: 8px;
          }
          .sim-option-card:hover {
              border-color: var(--sim-border);
          }
          .sim-option-card.active {
              border: 2px solid var(--sim-primary);
              box-shadow: 0 0 20px rgba(59,125,216,0.2);
          }

          /* NiceGUI / Quasar Form Elements */
          .q-field__control {
              background: rgba(0,0,0,0.3) !important;
              border: 1px solid rgba(255,255,255,0.1) !important;
              border-radius: 8px !important;
              transition: all 0.2s ease !important;
          }
          .q-field__control:hover {
              border-color: rgba(59, 125, 216, 0.5) !important;
          }
          .q-field--focused .q-field__control {
              border-color: var(--sim-primary) !important;
              box-shadow: 0 0 12px rgba(59,125,216,0.2) !important;
          }

          /* Checkboxes and Toggles */
          .q-checkbox__inner { color: var(--muted) !important; }
          .q-checkbox__inner--truthy { color: var(--sim-primary) !important; }

          /* Titles and Typography */
          .sim-panel-title, .sim-section-title {
              font-family: 'Rajdhani', 'IBM Plex Sans', sans-serif;
              font-size: 1.25rem; /* DESIGN.md title 20px */
              font-weight: 600;
              letter-spacing: -0.02em;
              color: #fff;
              margin-bottom: 0.75rem;
              display: flex;
              align-items: center;
              gap: 10px;
              border-bottom: 1px solid rgba(255,255,255,0.05);
              padding-bottom: 10px;
          }
          .sim-micro {
              font-family: 'IBM Plex Sans', sans-serif;
              font-size: 11px;
              font-weight: 600;
              letter-spacing: 0.06em;
              text-transform: uppercase;
              color: var(--muted);
          }
          .sim-hero-sub {
              font-size: 0.875rem;
              color: var(--muted);
              max-width: 42rem;
              line-height: 1.4;
              margin: 0 0 0.75rem 0;
          }
          .sim-quickstart {
              padding: 8px 0 4px;
              border-bottom: 1px solid rgba(255,255,255,0.04);
              margin-bottom: 8px;
          }

          /*
           * CRITICAL DIALOG FIX
           * Overriding Quasar's raw dialogs that attach to the body
           */
          body .q-dialog__backdrop {
              background: rgba(6, 15, 28, 0.85) !important;
              backdrop-filter: blur(8px) !important;
          }
          body .q-dialog__inner > div {
              background: var(--sim-surface) !important;
              border: 1px solid var(--sim-border) !important;
              border-radius: 16px !important;
              box-shadow: 0 24px 64px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.05) inset !important;
              color: var(--sim-text) !important;
              padding: 32px !important;
              max-width: 95vw !important;
              width: 1100px !important;
              max-height: 90vh !important;
              overflow-y: auto !important;
          }
          /* Custom scrollbar for dialogs */
          body .q-dialog__inner > div::-webkit-scrollbar {
              width: 8px;
          }
          body .q-dialog__inner > div::-webkit-scrollbar-track {
              background: rgba(0,0,0,0.2);
              border-radius: 4px;
          }
          body .q-dialog__inner > div::-webkit-scrollbar-thumb {
              background: var(--sim-border);
              border-radius: 4px;
          }
          body .q-dialog__inner > div::-webkit-scrollbar-thumb:hover {
              background: var(--sim-primary);
          }

          /* Step Rail */
          .sim-step-rail {
              display: flex;
              align-items: center;
              gap: 16px;
              background: rgba(0,0,0,0.2);
              padding: 16px 24px;
              border-radius: 12px;
              margin-bottom: 32px;
              border: 1px solid rgba(255,255,255,0.05);
          }
          .sim-step {
              padding: 12px 24px;
              border-radius: 8px;
              cursor: pointer;
              transition: all 0.2s ease;
              color: var(--muted);
              font-weight: 500;
          }
          .sim-step:hover { background: rgba(255,255,255,0.05); }
          .sim-step-on {
              background: rgba(59, 125, 216, 0.1);
              color: var(--sim-primary);
              box-shadow: 0 0 16px rgba(59, 125, 216, 0.1) inset;
              border: 1px solid rgba(59, 125, 216, 0.2);
          }
          .sim-step-done { color: #fff; }
          .sim-step-num {
              display: inline-flex;
              width: 24px; height: 24px;
              align-items: center; justify-content: center;
              border-radius: 50%;
              background: rgba(255,255,255,0.1);
              font-size: 12px;
          }
          .sim-step-on .sim-step-num {
              background: var(--sim-primary);
              color: #fff;
              font-weight: bold;
              box-shadow: 0 0 12px var(--sim-primary);
          }

          /* Buttons */
          .q-btn {
              border-radius: 8px !important;
              text-transform: none !important;
              font-weight: 500 !important;
              letter-spacing: 0.3px !important;
          }
          .q-btn--outline {
              border: 1px solid var(--sim-border) !important;
              color: var(--sim-primary) !important;
          }
          .q-btn--outline:hover {
              background: rgba(59,125,216,0.1) !important;
              box-shadow: 0 0 12px rgba(59,125,216,0.2) !important;
          }

          /* Given / Solve-for rows (Phase 2) */
          .sim-dim-head { display: flex; flex-direction: column; gap: 6px; }
          .sim-dim-label { font-weight: 600; color: var(--sim-text); font-size: 0.95rem; }
          .sim-given-toggle { max-width: 12rem; }
          .sim-free-hint { color: var(--muted); font-size: 0.8rem; font-style: italic; }
          .sim-quickstart { padding: 12px 0; }
          .sim-section-label { font-weight: 700; color: var(--sim-text); margin-bottom: 8px; }

          /* Decision table (Phase 3) */
          .sim-decision-scroll { overflow-x: auto; }
          .sim-decision-table { border-collapse: collapse; min-width: 34rem; }
          .sim-decision-table th, .sim-decision-table td {
              padding: 6px 14px; text-align: left; font-size: 0.88rem;
              border-bottom: 1px solid rgba(255,255,255,0.07); color: var(--sim-text);
          }
          .sim-decision-table thead th { font-weight: 700; }
          .sim-decision-table tbody th { font-weight: 500; color: var(--muted); white-space: nowrap; }
          .sim-win-cell { background: rgba(59,125,216,0.18); font-weight: 600; }
        </style>
        """


def apply_simulator_css(ui) -> None:
    ui.add_head_html(SIM_CSS)

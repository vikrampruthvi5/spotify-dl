import { useState, useEffect } from "react";
import { api } from "./api/client";

// Pages (each built as a self-contained panel)
import DownloadPage  from "./pages/DownloadPage";
import LibraryPage   from "./pages/LibraryPage";
import DJToolsPage   from "./pages/DJToolsPage";
import WatcherPage   from "./pages/WatcherPage";

type Page = "download" | "library" | "dj" | "watcher";

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: "download", label: "Download",  icon: "⬇" },
  { id: "library",  label: "Library",   icon: "♪" },
  { id: "dj",       label: "DJ Tools",  icon: "♫" },
  { id: "watcher",  label: "Watcher",   icon: "⚡" },
];

export default function App() {
  const [page, setPage]       = useState<Page>("download");
  const [ready, setReady]     = useState(false);
  const [config, setConfig]   = useState<{ output_dir: string; quality: string } | null>(null);

  useEffect(() => {
    api.health()
      .then(() => api.config())
      .then((cfg) => { setConfig(cfg); setReady(true); })
      .catch(() => {
        // Retry every second until server is up (Tauri spawns it in background)
        const id = setInterval(() => {
          api.health()
            .then(() => api.config())
            .then((cfg) => { setConfig(cfg); setReady(true); clearInterval(id); })
            .catch(() => {});
        }, 1000);
      });
  }, []);

  if (!ready) return (
    <div style={{ display:"flex", alignItems:"center", justifyContent:"center",
                  height:"100vh", flexDirection:"column", gap:16 }}>
      <div style={{ fontSize:32 }}>♪</div>
      <div style={{ color:"var(--text-dim)" }}>Starting SpotiDL server…</div>
    </div>
  );

  return (
    <div style={{ display:"flex", height:"100vh", overflow:"hidden" }}>
      {/* Sidebar */}
      <nav style={{
        width: 200,
        background: "var(--surface)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        padding: "16px 0",
        gap: 4,
        flexShrink: 0,
      }}>
        {/* Logo */}
        <div style={{
          padding: "0 20px 20px",
          fontSize: 18,
          fontWeight: 700,
          color: "var(--accent)",
          letterSpacing: -0.5,
          borderBottom: "1px solid var(--border)",
          marginBottom: 8,
        }}>
          SpotiDL
        </div>

        {NAV.map(({ id, label, icon }) => (
          <button
            key={id}
            onClick={() => setPage(id)}
            style={{
              background: page === id ? "var(--surface-2)" : "transparent",
              color: page === id ? "var(--text)" : "var(--text-dim)",
              borderRadius: 0,
              padding: "10px 20px",
              textAlign: "left",
              display: "flex",
              alignItems: "center",
              gap: 10,
              fontSize: 13,
              fontWeight: page === id ? 600 : 400,
              borderLeft: `3px solid ${page === id ? "var(--accent)" : "transparent"}`,
            }}
          >
            <span style={{ fontSize:16 }}>{icon}</span>
            {label}
          </button>
        ))}

        {/* Footer */}
        <div style={{
          marginTop: "auto",
          padding: "16px 20px 0",
          borderTop: "1px solid var(--border)",
          color: "var(--text-dim)",
          fontSize: 11,
        }}>
          v1.1.0 · {config?.quality ?? "320"}kbps
        </div>
      </nav>

      {/* Main content */}
      <main style={{ flex: 1, overflow: "auto", background: "var(--bg)" }}>
        {config && (
          <>
            {page === "download" && <DownloadPage outputDir={config.output_dir} quality={config.quality} />}
            {page === "library"  && <LibraryPage  outputDir={config.output_dir} />}
            {page === "dj"       && <DJToolsPage  outputDir={config.output_dir} />}
            {page === "watcher"  && <WatcherPage  outputDir={config.output_dir} />}
          </>
        )}
      </main>
    </div>
  );
}

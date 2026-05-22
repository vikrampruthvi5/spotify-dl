import { useState, useEffect, useRef } from "react";
import { api, streamWatcherEvents, type WatchedPlaylist, type WatcherStatus } from "../api/client";

interface Props { outputDir: string; home: string; }

export default function WatcherPage({ outputDir, home }: Props) {
  const [status, setStatus]       = useState<WatcherStatus | null>(null);
  const [playlists, setPlaylists] = useState<WatchedPlaylist[]>([]);
  const [log, setLog]             = useState<string[]>([]);
  const [addUrl, setAddUrl]       = useState("");
  const [addFolder, setAddFolder] = useState("");
  const [adding, setAdding]       = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const refresh = async () => {
    const [s, w] = await Promise.all([api.watcherStatus(), api.listPlaylists()]);
    setStatus(s);
    setPlaylists((w as { playlists: WatchedPlaylist[] }).playlists ?? []);
  };

  useEffect(() => {
    refresh();
    // Subscribe to watcher notifications
    esRef.current = streamWatcherEvents(msg =>
      setLog(prev => [...prev.slice(-99), msg])
    );
    return () => esRef.current?.close();
  }, []);

  const toggleWatcher = async () => {
    if (status?.running) {
      await api.watcherStop();
    } else {
      await api.watcherStart({ organize: false });
    }
    await refresh();
  };

  const triggerCheck = async () => {
    await api.watcherCheck().catch(() => {});
    setLog(prev => [...prev, "Manual check triggered."]);
  };

  const addPlaylist = async () => {
    if (!addUrl.trim()) return;
    setAdding(true);
    try {
      await api.addPlaylist({ url: addUrl.trim(), folder: addFolder || undefined });
      setAddUrl(""); setAddFolder("");
      await refresh();
    } catch (e: unknown) {
      setLog(prev => [...prev, `Error: ${String((e as Error).message ?? e)}`]);
    }
    setAdding(false);
  };

  const removePlaylist = async (url: string) => {
    await api.deletePlaylist(url);
    await refresh();
  };

  return (
    <div style={{ padding:32, maxWidth:860, margin:"0 auto" }}>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:24 }}>
        <h1 style={{ fontSize:22, fontWeight:700 }}>
          Watcher
          <span style={{
            marginLeft:10, fontSize:12, padding:"2px 8px", borderRadius:20,
            background: status?.running ? "#0d2e1a" : "var(--surface-2)",
            color: status?.running ? "var(--accent)" : "var(--text-dim)",
            fontWeight:600,
          }}>
            {status?.running ? "RUNNING" : "STOPPED"}
          </span>
        </h1>
        <div style={{ display:"flex", gap:8 }}>
          <button onClick={triggerCheck} disabled={!status?.running}
            style={{ background:"var(--surface-2)", color:"var(--text)",
                     padding:"8px 16px", border:"1px solid var(--border)" }}>
            Check Now
          </button>
          <button onClick={toggleWatcher}
            style={{ background: status?.running ? "var(--red)" : "var(--accent)",
                     color: status?.running ? "#fff" : "#000",
                     padding:"8px 20px", fontWeight:600 }}>
            {status?.running ? "Stop Watcher" : "Start Watcher"}
          </button>
        </div>
      </div>

      {/* Playlists table */}
      <div style={{ background:"var(--surface)", border:"1px solid var(--border)",
                    borderRadius:12, overflow:"hidden", marginBottom:20 }}>
        <div style={{ padding:"12px 16px", borderBottom:"1px solid var(--border)",
                      display:"grid", gridTemplateColumns:"1fr 1fr 64px 64px 40px",
                      fontSize:11, color:"var(--text-dim)", fontWeight:600 }}>
          <span>NAME</span><span>FOLDER</span>
          <span style={{ textAlign:"right" }}>SPOTIFY</span>
          <span style={{ textAlign:"right" }}>SYNCED</span>
          <span></span>
        </div>
        {playlists.length === 0 && (
          <div style={{ padding:24, textAlign:"center", color:"var(--text-dim)", fontSize:13 }}>
            No playlists configured yet.
          </div>
        )}
        {playlists.map((p, i) => {
          const synced = p.downloaded_ids?.length ?? 0;
          const pct    = p.total_tracks ? Math.round(synced / p.total_tracks * 100) : 0;
          return (
            <div key={p.url} style={{
              display:"grid", gridTemplateColumns:"1fr 1fr 64px 64px 40px",
              padding:"10px 16px", borderBottom:"1px solid var(--border)",
              background: i % 2 ? "var(--surface-2)" : "transparent",
              alignItems:"center", fontSize:13,
            }}>
              <div>
                <div style={{ fontWeight:500 }}>{p.name}</div>
                <div style={{ fontSize:11, color:"var(--text-dim)", marginTop:2 }}>
                  <div style={{ width:80, height:3, background:"var(--border)",
                                borderRadius:2, overflow:"hidden", marginTop:4 }}>
                    <div style={{ width:`${pct}%`, height:"100%", background:"var(--accent)" }} />
                  </div>
                </div>
              </div>
              <span style={{ fontSize:11, color:"var(--text-dim)", overflow:"hidden",
                             textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                {p.folder.replace(home, "~")}
              </span>
              <span style={{ textAlign:"right", color:"var(--yellow)", fontWeight:600 }}>
                {p.total_tracks ?? "?"}
              </span>
              <span style={{ textAlign:"right", color:"var(--accent)", fontWeight:600 }}>
                {synced}
              </span>
              <button onClick={() => removePlaylist(p.url)}
                style={{ background:"transparent", color:"var(--red)", padding:"4px 8px",
                         fontSize:16, border:"none" }}>
                ×
              </button>
            </div>
          );
        })}
      </div>

      {/* Add playlist form */}
      <div style={{ background:"var(--surface)", border:"1px solid var(--border)",
                    borderRadius:12, padding:"16px 20px", marginBottom:20 }}>
        <div style={{ fontSize:13, fontWeight:600, marginBottom:10 }}>Add Playlist</div>
        <div style={{ display:"flex", gap:8 }}>
          <input value={addUrl} onChange={e => setAddUrl(e.target.value)}
            placeholder="Spotify playlist URL…" style={{ flex:2 }} />
          <input value={addFolder} onChange={e => setAddFolder(e.target.value)}
            placeholder={`Folder (default: ${outputDir}/…)`} style={{ flex:2 }} />
          <button onClick={addPlaylist} disabled={adding || !addUrl.trim()}
            style={{ background:"var(--accent)", color:"#000",
                     padding:"8px 18px", fontWeight:600 }}>
            {adding ? "Adding…" : "Add"}
          </button>
        </div>
      </div>

      {/* Live log */}
      {log.length > 0 && (
        <div style={{
          background:"var(--surface)", border:"1px solid var(--border)",
          borderRadius:12, padding:"12px 16px",
          fontFamily:"monospace", fontSize:12, color:"var(--text-dim)",
          maxHeight:200, overflowY:"auto", whiteSpace:"pre-wrap",
        }}>
          {log.join("\n")}
        </div>
      )}
    </div>
  );
}

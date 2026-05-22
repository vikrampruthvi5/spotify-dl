import { useState, useEffect, useMemo } from "react";
import { api, type LibraryTrack } from "../api/client";

interface Props { outputDir: string; }

const COLS = ["ARTIST", "TITLE", "ALBUM", "BPM", "KEY", "ENERGY"];

export default function LibraryPage({ outputDir }: Props) {
  const [tracks, setTracks]   = useState<LibraryTrack[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch]   = useState("");
  const [sort, setSort]       = useState<"artist"|"bpm"|"energy">("artist");

  const load = () => {
    setLoading(true);
    api.getLibrary(outputDir)
      .then(setTracks)
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [outputDir]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return tracks
      .filter(t => !q || t.artist?.toLowerCase().includes(q) || t.title?.toLowerCase().includes(q))
      .sort((a, b) => {
        if (sort === "bpm")    return (b.bpm ?? 0) - (a.bpm ?? 0);
        if (sort === "energy") return (b.energy ?? 0) - (a.energy ?? 0);
        return (a.artist ?? "").localeCompare(b.artist ?? "");
      });
  }, [tracks, search, sort]);

  const energyBar = (e: number | undefined) => {
    if (e == null) return null;
    const pct = Math.round(e * 100);
    return (
      <div style={{ display:"flex", alignItems:"center", gap:6 }}>
        <div style={{ width:40, height:4, background:"var(--border)", borderRadius:2, overflow:"hidden" }}>
          <div style={{ width:`${pct}%`, height:"100%",
                        background: pct > 70 ? "var(--accent)" : pct > 40 ? "var(--yellow)" : "var(--text-dim)" }} />
        </div>
        <span style={{ fontSize:11, color:"var(--text-dim)" }}>{pct}%</span>
      </div>
    );
  };

  return (
    <div style={{ padding: 32 }}>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:20 }}>
        <h1 style={{ fontSize:22, fontWeight:700 }}>
          Library
          <span style={{ fontSize:14, color:"var(--text-dim)", fontWeight:400, marginLeft:10 }}>
            {tracks.length} tracks
          </span>
        </h1>
        <button onClick={load} disabled={loading}
          style={{ background:"var(--surface-2)", color:"var(--text)",
                   padding:"7px 16px", border:"1px solid var(--border)" }}>
          {loading ? "Scanning…" : "Refresh"}
        </button>
      </div>

      {/* Toolbar */}
      <div style={{ display:"flex", gap:10, marginBottom:16 }}>
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search artist or title…" style={{ flex:1 }} />
        <select value={sort} onChange={e => setSort(e.target.value as typeof sort)}
          style={{ background:"var(--surface-2)", border:"1px solid var(--border)",
                   color:"var(--text)", borderRadius:8, padding:"6px 10px", fontSize:13 }}>
          <option value="artist">Sort: Artist</option>
          <option value="bpm">Sort: BPM ↓</option>
          <option value="energy">Sort: Energy ↓</option>
        </select>
      </div>

      {/* Table */}
      <div style={{ background:"var(--surface)", border:"1px solid var(--border)", borderRadius:12, overflow:"hidden" }}>
        {/* Header */}
        <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr 60px 60px 90px",
                      padding:"10px 16px", borderBottom:"1px solid var(--border)",
                      fontSize:11, color:"var(--text-dim)", fontWeight:600 }}>
          {COLS.map(c => <span key={c}>{c}</span>)}
        </div>

        <div style={{ maxHeight:"calc(100vh - 280px)", overflowY:"auto" }}>
          {loading && (
            <div style={{ padding:32, textAlign:"center", color:"var(--text-dim)" }}>Scanning…</div>
          )}
          {!loading && filtered.length === 0 && (
            <div style={{ padding:32, textAlign:"center", color:"var(--text-dim)" }}>No tracks found.</div>
          )}
          {filtered.map((t, i) => (
            <div key={t.path} style={{
              display:"grid", gridTemplateColumns:"1fr 1fr 1fr 60px 60px 90px",
              padding:"8px 16px", borderBottom:"1px solid var(--border)",
              background: i % 2 ? "var(--surface-2)" : "transparent",
              alignItems:"center", fontSize:13,
            }}>
              <span style={{ color:"var(--text-dim)", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                {t.artist || "—"}
              </span>
              <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                {t.title || t.filename}
              </span>
              <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", color:"var(--text-dim)" }}>
                {t.album || "—"}
              </span>
              <span style={{ color:"var(--accent-2)", fontWeight:600 }}>
                {t.bpm ? Math.round(t.bpm) : "—"}
              </span>
              <span style={{ fontSize:11, color:"var(--accent-2)" }}>
                {t.camelot || t.key || "—"}
              </span>
              <span>{energyBar(t.energy)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

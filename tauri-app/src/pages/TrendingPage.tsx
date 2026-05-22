import { useState, useEffect, useRef } from "react";
import { api, streamJobEvents, type JobEvent,
         type TrendingResult, type TrendingTrack } from "../api/client";
import PlaylistPickerModal from "../components/PlaylistPickerModal";

interface Props { outputDir: string; quality: string; }

const REGIONS = [
  { id: "bollywood", label: "Bollywood", icon: "♬" },
  { id: "hollywood", label: "Hollywood", icon: "★" },
  { id: "tollywood", label: "Tollywood", icon: "✦" },
  { id: "tamil",     label: "Tamil",     icon: "◈" },
  { id: "punjabi",   label: "Punjabi",   icon: "✧" },
];

const _mmss = (ms: number) => {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const STATUS_COLOR: Record<string, string> = {
  ok: "var(--accent)", skip: "var(--yellow)", fail: "var(--red)",
};

export default function TrendingPage({ outputDir, quality }: Props) {
  const [region, setRegion]       = useState("bollywood");
  const [data, setData]           = useState<TrendingResult | null>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState("");
  const [selected, setSelected]   = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [trackStatus, setTrackStatus] = useState<Record<string, "ok"|"skip"|"fail">>({});
  const [summary, setSummary]     = useState<{downloaded:number;skipped:number;failed:number}|null>(null);
  const [browser, setBrowser]     = useState<string>(
    () => localStorage.getItem("spotidl.browser") ?? "chrome"
  );
  const [showPicker, setShowPicker] = useState(false);
  const [authed, setAuthed]         = useState(false);
  const [toast, setToast]           = useState("");
  const [playingId, setPlayingId]   = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const esRef    = useRef<EventSource | null>(null);

  useEffect(() => {
    api.authStatus().then(r => setAuthed(r.authenticated)).catch(() => {});
  }, []);

  // Cleanup audio on unmount
  useEffect(() => () => { audioRef.current?.pause(); }, []);

  const playPreview = (track: TrendingTrack) => {
    if (!track.preview_url) {
      setToast("Spotify did not provide a preview for this track.");
      setTimeout(() => setToast(""), 2500);
      return;
    }
    // Toggle: clicking the same track again pauses
    if (playingId === track.id) {
      audioRef.current?.pause();
      setPlayingId(null);
      return;
    }
    audioRef.current?.pause();
    const a = new Audio(track.preview_url);
    a.volume = 0.7;
    a.onended = () => setPlayingId(null);
    a.play().catch(() => setPlayingId(null));
    audioRef.current = a;
    setPlayingId(track.id);
  };

  const load = async (r: string) => {
    setLoading(true); setError(""); setSelected(new Set());
    setTrackStatus({}); setSummary(null);
    try {
      const d = await api.getTrending(r);
      setData(d);
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(region); }, [region]);

  const toggleOne = (id: string) =>
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const selectAll = () => data && setSelected(new Set(data.tracks.map(t => t.id)));
  const clearAll  = () => setSelected(new Set());

  // Build a lookup for finding tracks by artist+title from SSE events
  const trackByName: Record<string, string> = {};
  data?.tracks.forEach(t => { trackByName[`${t.artist}|${t.title}`] = t.id; });

  const downloadSelected = async () => {
    if (selected.size === 0 || !data) return;
    setDownloading(true); setTrackStatus({}); setSummary(null);
    localStorage.setItem("spotidl.browser", browser);
    try {
      const { job_id } = await api.downloadTracks({
        track_ids:  Array.from(selected),
        output_dir: outputDir,
        quality,
        browser:    browser === "none" ? null : browser,
        jobs:       4,
        name:       `${data.label} trending`,
      });
      esRef.current = streamJobEvents(job_id, (ev: JobEvent) => {
        if (ev.type === "track_done") {
          const id = trackByName[`${ev.artist}|${ev.title}`];
          if (id) setTrackStatus(prev => ({ ...prev, [id]: ev.status }));
        } else if (ev.type === "summary") {
          setSummary({ downloaded: ev.downloaded, skipped: ev.skipped, failed: ev.failed });
        }
      }, () => setDownloading(false));
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
      setDownloading(false);
    }
  };

  return (
    <div style={{ height:"100%", display:"flex", flexDirection:"column", overflow:"hidden" }}>
      {/* Tab bar */}
      <div style={{ display:"flex", gap:0, padding:"16px 32px 0",
                    borderBottom:"1px solid var(--border)" }}>
        {REGIONS.map(r => (
          <button key={r.id} onClick={() => setRegion(r.id)}
            style={{
              background:"transparent",
              color: region === r.id ? "var(--text)" : "var(--text-dim)",
              padding:"10px 18px", borderRadius:0, fontSize:13,
              fontWeight: region === r.id ? 600 : 400,
              borderBottom: `2px solid ${region === r.id ? "var(--accent)" : "transparent"}`,
              marginBottom:-1, display:"flex", alignItems:"center", gap:6,
            }}>
            <span style={{ fontSize:14 }}>{r.icon}</span> {r.label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div style={{ flex:1, overflow:"auto", padding:"24px 32px 100px" }}>
        {loading && (
          <div style={{ padding:48, textAlign:"center", color:"var(--text-dim)" }}>
            Loading trending tracks from Spotify…
          </div>
        )}

        {error && (
          <div style={{ background:"#1a0505", border:"1px solid var(--red)", borderRadius:8,
                        padding:"10px 14px", color:"var(--red)", marginBottom:16, fontSize:13 }}>
            {error}
          </div>
        )}

        {!loading && data && (
          <>
            {/* Header — playlist hero */}
            <div style={{ display:"flex", gap:20, marginBottom:24, alignItems:"center" }}>
              {data.cover_url && (
                <img src={data.cover_url} alt=""
                  style={{ width:96, height:96, borderRadius:10,
                           boxShadow:"0 4px 20px rgba(0,0,0,0.5)", objectFit:"cover" }} />
              )}
              <div style={{ flex:1 }}>
                <div style={{ color:"var(--text-dim)", fontSize:11, textTransform:"uppercase",
                              letterSpacing:1, marginBottom:6 }}>
                  Trending · {data.language}
                </div>
                <div style={{ fontSize:22, fontWeight:700, marginBottom:4 }}>
                  {data.playlist_name}
                </div>
                <div style={{ color:"var(--text-dim)", fontSize:13 }}>
                  {data.tracks.length} tracks
                </div>
              </div>
              <div style={{ display:"flex", gap:8 }}>
                <button onClick={() => load(region)}
                  style={{ background:"var(--surface-2)", color:"var(--text)",
                           padding:"7px 14px", border:"1px solid var(--border)" }}>
                  Refresh
                </button>
                <button onClick={selectAll}
                  style={{ background:"var(--surface-2)", color:"var(--text)",
                           padding:"7px 14px", border:"1px solid var(--border)" }}>
                  Select all
                </button>
              </div>
            </div>

            {/* Track list */}
            <div style={{ background:"var(--surface)", border:"1px solid var(--border)",
                          borderRadius:12, overflow:"hidden" }}>
              {data.tracks.length === 0 && (
                <div style={{ padding:32, textAlign:"center", color:"var(--text-dim)" }}>
                  No tracks returned by Spotify.
                </div>
              )}
              {data.tracks.map((t, i) => (
                <TrackRow key={t.id} track={t} index={i + 1}
                  selected={selected.has(t.id)}
                  status={trackStatus[t.id]}
                  playing={playingId === t.id}
                  onToggle={() => toggleOne(t.id)}
                  onPlay={() => playPreview(t)} />
              ))}
            </div>
          </>
        )}

        {/* Final summary */}
        {summary && (
          <div style={{ display:"flex", gap:16, marginTop:20 }}>
            {[
              ["Downloaded", summary.downloaded, "var(--accent)"],
              ["Skipped",    summary.skipped,    "var(--yellow)"],
              ["Failed",     summary.failed,     "var(--red)"],
            ].map(([label, val, color]) => (
              <div key={String(label)} style={{
                flex:1, background:"var(--surface)", border:"1px solid var(--border)",
                borderRadius:10, padding:"14px 20px", textAlign:"center",
              }}>
                <div style={{ fontSize:26, fontWeight:700, color: String(color) }}>{String(val)}</div>
                <div style={{ color:"var(--text-dim)", fontSize:12, marginTop:2 }}>{String(label)}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Sticky action bar — only visible when something is selected */}
      {selected.size > 0 && (
        <div style={{
          position:"absolute", bottom:0, left:200, right:0,
          background:"var(--surface)", borderTop:"1px solid var(--border)",
          padding:"14px 32px", display:"flex", alignItems:"center", gap:16,
          backdropFilter:"blur(8px)", boxShadow:"0 -4px 20px rgba(0,0,0,0.3)",
        }}>
          <span style={{ fontWeight:600, color:"var(--text)" }}>
            {selected.size} {selected.size === 1 ? "track" : "tracks"} selected
          </span>
          <span style={{ flex:1 }} />
          <select value={browser} onChange={e => setBrowser(e.target.value)}
            title="Browser cookies to use for YouTube"
            style={{ background:"var(--surface-2)", border:"1px solid var(--border)",
                     color:"var(--text)", borderRadius:8, padding:"7px 10px", fontSize:13 }}>
            <option value="chrome">cookies: chrome</option>
            <option value="firefox">cookies: firefox</option>
            <option value="safari">cookies: safari</option>
            <option value="brave">cookies: brave</option>
            <option value="edge">cookies: edge</option>
            <option value="none">no cookies</option>
          </select>
          <button onClick={clearAll} disabled={downloading}
            style={{ background:"transparent", color:"var(--text-dim)",
                     padding:"8px 14px", border:"1px solid var(--border)" }}>
            Clear
          </button>
          {authed && (
            <button onClick={() => setShowPicker(true)} disabled={downloading}
              style={{ background:"var(--surface-2)", color:"var(--text)",
                       padding:"8px 16px", border:"1px solid var(--border)" }}>
              + Spotify Playlist
            </button>
          )}
          <button onClick={downloadSelected} disabled={downloading}
            style={{ background:"var(--accent)", color:"#000",
                     padding:"9px 22px", fontWeight:600 }}>
            {downloading ? "Downloading…" : `Download ${selected.size}`}
          </button>
        </div>
      )}

      {/* Add to Spotify Playlist modal */}
      {showPicker && data && (
        <PlaylistPickerModal
          trackIds={Array.from(selected)}
          defaultName={`${data.label} Trending · ${new Date().toLocaleDateString()}`}
          onClose={() => setShowPicker(false)}
          onSuccess={({ playlistName, added }) => {
            setToast(`Added ${added} track${added === 1 ? "" : "s"} to "${playlistName}"`);
            setTimeout(() => setToast(""), 4000);
          }}
        />
      )}

      {/* Toast */}
      {toast && (
        <div style={{
          position:"fixed", bottom: selected.size > 0 ? 78 : 24, right:24,
          background:"var(--surface)", border:"1px solid var(--accent)",
          color:"var(--text)", padding:"10px 16px", borderRadius:10,
          boxShadow:"0 8px 24px rgba(0,0,0,0.4)", fontSize:13, zIndex:50,
        }}>
          {toast}
        </div>
      )}
    </div>
  );
}

// ─── Track row component ────────────────────────────────────────────────────

interface RowProps {
  track: TrendingTrack;
  index: number;
  selected: boolean;
  playing: boolean;
  status?: "ok" | "skip" | "fail";
  onToggle: () => void;
  onPlay: () => void;
}

function TrackRow({ track, index, selected, playing, status, onToggle, onPlay }: RowProps) {
  const hasPreview = !!track.preview_url;
  return (
    <div
      onClick={onToggle}
      style={{
        display:"grid",
        gridTemplateColumns:"28px 36px 48px 1fr 1fr 60px 60px",
        padding:"10px 16px", borderBottom:"1px solid var(--border)",
        background: selected ? "rgba(29, 185, 84, 0.08)" : (index % 2 ? "var(--surface-2)" : "transparent"),
        alignItems:"center", fontSize:13, cursor:"pointer", gap:10,
      }}
    >
      <input type="checkbox" checked={selected} onChange={onToggle}
        onClick={e => e.stopPropagation()}
        style={{ cursor:"pointer", accentColor:"var(--accent)" }} />

      <span style={{ color:"var(--text-dim)", fontSize:12, textAlign:"center" }}>
        {status ? <span style={{ color: STATUS_COLOR[status], fontWeight:700 }}>
          {status === "ok" ? "✓" : status === "skip" ? "○" : "✕"}
        </span> : index}
      </span>

      {/* Album art with play-on-hover overlay */}
      <div onClick={e => { e.stopPropagation(); onPlay(); }}
        title={hasPreview ? (playing ? "Pause preview" : "Play 30s preview") : "No preview available"}
        style={{
          width:40, height:40, borderRadius:4, position:"relative",
          background:"var(--surface-2)", overflow:"hidden",
          cursor: hasPreview ? "pointer" : "default", flexShrink:0,
        }}>
        {track.cover_url && (
          <img src={track.cover_url} alt=""
            style={{ width:"100%", height:"100%", objectFit:"cover",
                     opacity: playing ? 0.4 : 1, transition:"opacity 0.15s" }} />
        )}
        <div style={{
          position:"absolute", inset:0, display:"flex",
          alignItems:"center", justifyContent:"center",
          background: playing
            ? "rgba(0,0,0,0.4)"
            : hasPreview ? "rgba(0,0,0,0)" : "rgba(0,0,0,0)",
          color: hasPreview ? "#fff" : "var(--text-dim)",
          fontSize:14, opacity: playing ? 1 : 0,
          transition:"opacity 0.15s",
        }}
          className={hasPreview ? "play-hover" : ""}>
          {playing ? "❚❚" : "▶"}
        </div>
        {!playing && hasPreview && (
          <div style={{
            position:"absolute", inset:0, display:"flex",
            alignItems:"center", justifyContent:"center",
            background:"rgba(0,0,0,0.55)", color:"#fff", fontSize:13,
            opacity:0, transition:"opacity 0.15s",
          }}
          onMouseEnter={e => (e.currentTarget.style.opacity = "1")}
          onMouseLeave={e => (e.currentTarget.style.opacity = "0")}>
            ▶
          </div>
        )}
      </div>

      <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
        {track.title}
      </span>
      <span style={{ color:"var(--text-dim)", overflow:"hidden",
                     textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
        {track.artist}
      </span>

      {/* Popularity bar */}
      <div style={{ display:"flex", alignItems:"center", gap:6 }}>
        <div style={{ width:36, height:3, background:"var(--border)", borderRadius:2, overflow:"hidden" }}>
          <div style={{ width: `${track.popularity}%`, height:"100%",
                        background: track.popularity > 70 ? "var(--accent)"
                                   : track.popularity > 40 ? "var(--yellow)"
                                   : "var(--text-dim)" }} />
        </div>
      </div>

      <span style={{ color:"var(--text-dim)", fontSize:11, textAlign:"right" }}>
        {_mmss(track.duration_ms)}
      </span>
    </div>
  );
}

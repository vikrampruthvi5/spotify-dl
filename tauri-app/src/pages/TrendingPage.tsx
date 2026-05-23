import { useState, useEffect, useRef } from "react";
import { api, streamJobEvents, type JobEvent,
         type TrendingResult, type TrendingTrack,
         type WatchedPlaylist } from "../api/client";
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
  const [hiddenIds, setHiddenIds]   = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem("spotidl.hidden_tracks") ?? "[]")); }
    catch { return new Set(); }
  });
  const [showHidden, setShowHidden] = useState(false);
  const [watched, setWatched]       = useState<WatchedPlaylist[]>([]);
  const [showFolderMenu, setShowFolderMenu] = useState(false);
  const audioRef      = useRef<HTMLAudioElement | null>(null);
  const folderMenuRef = useRef<HTMLDivElement | null>(null);
  const esRef         = useRef<EventSource | null>(null);

  useEffect(() => {
    api.authStatus().then(r => setAuthed(r.authenticated)).catch(() => {});
    api.listPlaylists()
      .then(r => setWatched((r as { playlists: WatchedPlaylist[] }).playlists ?? []))
      .catch(() => {});
  }, []);

  // Close the folder dropdown when clicking outside
  useEffect(() => {
    if (!showFolderMenu) return;
    const onDown = (e: MouseEvent) => {
      if (folderMenuRef.current && !folderMenuRef.current.contains(e.target as Node))
        setShowFolderMenu(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [showFolderMenu]);

  // Persist hidden track IDs across sessions
  useEffect(() => {
    localStorage.setItem("spotidl.hidden_tracks", JSON.stringify(Array.from(hiddenIds)));
  }, [hiddenIds]);

  const hideTrack = (id: string) => {
    setHiddenIds(prev => new Set(prev).add(id));
    setSelected(prev => { const next = new Set(prev); next.delete(id); return next; });
  };

  const restoreTrack = (id: string) => {
    setHiddenIds(prev => { const next = new Set(prev); next.delete(id); return next; });
  };

  const clearAllHidden = () => setHiddenIds(new Set());

  // Cleanup audio on unmount
  useEffect(() => () => { audioRef.current?.pause(); }, []);

  const previewCache = useRef<Record<string, string | null>>({});

  const playPreview = async (track: TrendingTrack) => {
    // Toggle: clicking the same track again pauses
    if (playingId === track.id) {
      audioRef.current?.pause();
      setPlayingId(null);
      return;
    }
    audioRef.current?.pause();

    // Resolve the preview URL: try Spotify first, then iTunes fallback (cached).
    let url: string | null | undefined = track.preview_url;
    if (!url) url = previewCache.current[track.id];
    if (!url) {
      setPlayingId(track.id);       // visual feedback while we fetch
      try {
        const res = await api.previewUrl(track.artist, track.title);
        url = res.preview_url;
        previewCache.current[track.id] = url;
      } catch {
        url = null;
      }
    }
    if (!url) {
      setPlayingId(null);
      setToast("No preview available — neither Spotify nor iTunes has one.");
      setTimeout(() => setToast(""), 2500);
      return;
    }

    const a = new Audio(url);
    a.volume = 0.7;
    a.onended = () => setPlayingId(null);
    a.onerror = () => { setPlayingId(null);
      setToast("Could not play preview."); setTimeout(() => setToast(""), 2200); };
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

  // Shared SSE event handler — uses the track id directly (more robust than
  // matching by artist|title, which can mismatch on locale / encoding).
  const wireJobEvents = (job_id: string) => {
    esRef.current = streamJobEvents(job_id, (ev: JobEvent) => {
      if (ev.type === "track_done") {
        const id = (ev as { id?: string }).id;
        if (id) setTrackStatus(prev => ({ ...prev, [id]: ev.status }));
      } else if (ev.type === "summary") {
        setSummary({ downloaded: ev.downloaded, skipped: ev.skipped, failed: ev.failed });
      }
    }, () => setDownloading(false));
  };

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
      wireJobEvents(job_id);
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
      setDownloading(false);
    }
  };

  const downloadToWatched = async (playlist: WatchedPlaylist) => {
    if (selected.size === 0) return;
    setShowFolderMenu(false);
    setDownloading(true); setTrackStatus({}); setSummary(null);
    localStorage.setItem("spotidl.browser", browser);
    try {
      const { job_id } = await api.downloadToWatched({
        playlist_url: playlist.url,
        track_ids:    Array.from(selected),
        quality,
        browser:      browser === "none" ? null : browser,
        jobs:         4,
      });
      setToast(`Downloading to ${playlist.name}…`);
      setTimeout(() => setToast(""), 2500);
      wireJobEvents(job_id);
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
                  {data.tracks.filter(t => !hiddenIds.has(t.id)).length} tracks
                  {hiddenIds.size > 0 && data.tracks.some(t => hiddenIds.has(t.id)) && (
                    <span style={{ marginLeft:6 }}>
                      · {data.tracks.filter(t => hiddenIds.has(t.id)).length} hidden
                    </span>
                  )}
                  {!!data.excluded_known && data.excluded_known > 0 && (
                    <span style={{ marginLeft:6 }}>
                      · {data.excluded_known} already in your playlists
                    </span>
                  )}
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
              {data.tracks
                .filter(t => !hiddenIds.has(t.id))
                .map((t, i) => (
                  <TrackRow key={t.id} track={t} index={i + 1}
                    selected={selected.has(t.id)}
                    status={trackStatus[t.id]}
                    playing={playingId === t.id}
                    onToggle={() => toggleOne(t.id)}
                    onPlay={() => playPreview(t)}
                    onHide={() => hideTrack(t.id)} />
                ))}
            </div>

            {/* Hidden tracks footer */}
            {(() => {
              const hiddenHere = data.tracks.filter(t => hiddenIds.has(t.id));
              if (hiddenHere.length === 0) return null;
              return (
                <div style={{ marginTop:16, fontSize:12, color:"var(--text-dim)",
                              display:"flex", alignItems:"center", gap:14 }}>
                  <button onClick={() => setShowHidden(v => !v)}
                    style={{ background:"transparent", color:"var(--text-dim)",
                             padding:"4px 10px", border:"1px solid var(--border)",
                             borderRadius:14, fontSize:11 }}>
                    {showHidden ? "Hide" : "Show"} {hiddenHere.length} hidden track{hiddenHere.length === 1 ? "" : "s"}
                  </button>
                  {showHidden && (
                    <button onClick={clearAllHidden}
                      style={{ background:"transparent", color:"var(--text-dim)",
                               padding:"4px 10px", border:"none", fontSize:11,
                               textDecoration:"underline" }}>
                      Restore all
                    </button>
                  )}
                </div>
              );
            })()}

            {/* Expanded hidden tracks list */}
            {showHidden && (
              <div style={{ marginTop:10, background:"var(--surface)",
                            border:"1px dashed var(--border)", borderRadius:12,
                            overflow:"hidden", opacity:0.75 }}>
                {data.tracks.filter(t => hiddenIds.has(t.id)).map((t, i) => (
                  <TrackRow key={t.id} track={t} index={i + 1}
                    selected={false}
                    status={undefined}
                    playing={playingId === t.id}
                    onToggle={() => {}}
                    onPlay={() => playPreview(t)}
                    onHide={() => restoreTrack(t.id)}
                    hidden />
                ))}
              </div>
            )}
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

          {/* Add to watched folder dropdown */}
          {watched.length > 0 && (
            <div ref={folderMenuRef} style={{ position:"relative" }}>
              <button onClick={() => setShowFolderMenu(v => !v)} disabled={downloading}
                style={{ background:"var(--surface-2)", color:"var(--text)",
                         padding:"8px 14px", border:"1px solid var(--border)" }}>
                → Add to folder ▾
              </button>
              {showFolderMenu && (
                <div style={{
                  position:"absolute", bottom:"calc(100% + 6px)", right:0,
                  background:"var(--surface)", border:"1px solid var(--border)",
                  borderRadius:10, padding:4, minWidth:240,
                  boxShadow:"0 8px 24px rgba(0,0,0,0.5)", zIndex:100,
                }}>
                  {watched.map(p => (
                    <button key={p.url} onClick={() => downloadToWatched(p)}
                      style={{
                        width:"100%", padding:"8px 12px", background:"transparent",
                        color:"var(--text)", borderRadius:6, textAlign:"left",
                        display:"flex", flexDirection:"column", gap:2, fontSize:13,
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = "var(--surface-2)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <span style={{ fontWeight:500 }}>{p.name}</span>
                      <span style={{ fontSize:10, color:"var(--text-dim)",
                                     overflow:"hidden", textOverflow:"ellipsis",
                                     whiteSpace:"nowrap" }}>
                        {p.folder}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
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
  onHide: () => void;
  hidden?: boolean;
}

function TrackRow({ track, index, selected, playing, status,
                    onToggle, onPlay, onHide, hidden }: RowProps) {
  // Play-button content: status icon if finished, pause if playing, play otherwise.
  const playContent  = status ? (status === "ok" ? "✓" : status === "skip" ? "○" : "✕")
                              : playing ? "❚❚" : "▶";
  const playColor    = status ? STATUS_COLOR[status]
                              : playing ? "var(--accent)" : "var(--text)";
  const playBg       = playing ? "var(--accent)" : "var(--surface-2)";
  const playFg       = playing ? "#000" : playColor;
  const playTitle    = status ? `Download ${status}`
                              : playing ? "Pause preview" : "Play 30s preview";

  return (
    <div
      onClick={hidden ? undefined : onToggle}
      style={{
        display:"grid",
        gridTemplateColumns:"24px 34px 44px 1fr 1fr 50px 48px 28px",
        padding:"10px 14px", borderBottom:"1px solid var(--border)",
        background: hidden ? "transparent"
                    : selected ? "rgba(29, 185, 84, 0.08)"
                    : (index % 2 ? "var(--surface-2)" : "transparent"),
        alignItems:"center", fontSize:13, cursor: hidden ? "default" : "pointer", gap:10,
        opacity: hidden ? 0.55 : 1,
      }}
    >
      {/* Checkbox */}
      <input type="checkbox" checked={selected} onChange={onToggle} disabled={hidden}
        onClick={e => e.stopPropagation()}
        style={{ cursor: hidden ? "not-allowed" : "pointer", accentColor:"var(--accent)" }} />

      {/* Always-visible play / status button */}
      <button onClick={e => { e.stopPropagation(); if (!status) onPlay(); }}
        title={playTitle} disabled={!!status}
        style={{
          width:28, height:28, borderRadius:"50%",
          background: playBg, color: playFg,
          display:"flex", alignItems:"center", justifyContent:"center",
          fontSize: playing ? 9 : 11, fontWeight:700,
          border: `1px solid ${playing ? "var(--accent)" : "var(--border)"}`,
          padding:0,
          cursor: status ? "default" : "pointer",
        }}>
        {playContent}
      </button>

      {/* Album art (also clickable to play, secondary affordance) */}
      <div onClick={e => { e.stopPropagation(); if (!status) onPlay(); }}
        style={{
          width:40, height:40, borderRadius:4, position:"relative",
          background:"var(--surface-2)", overflow:"hidden",
          cursor: status ? "default" : "pointer", flexShrink:0,
        }}>
        {track.cover_url && (
          <img src={track.cover_url} alt=""
            style={{ width:"100%", height:"100%", objectFit:"cover",
                     opacity: playing ? 0.4 : 1, transition:"opacity 0.15s" }} />
        )}
        {playing && (
          <div style={{ position:"absolute", inset:0, display:"flex",
                        alignItems:"center", justifyContent:"center",
                        color:"#fff", fontSize:11, fontWeight:700 }}>
            ❚❚
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

      {/* Hide / restore button */}
      <button onClick={e => { e.stopPropagation(); onHide(); }}
        title={hidden ? "Restore this track" : "Hide from suggestions"}
        style={{
          width:24, height:24, borderRadius:"50%",
          background:"transparent", color:"var(--text-dim)",
          border:"none", padding:0, fontSize:14,
          opacity:0.5, transition:"opacity 0.15s, color 0.15s, background 0.15s",
        }}
        onMouseEnter={e => {
          e.currentTarget.style.opacity   = "1";
          e.currentTarget.style.color     = hidden ? "var(--accent)" : "var(--red)";
          e.currentTarget.style.background = "var(--surface-2)";
        }}
        onMouseLeave={e => {
          e.currentTarget.style.opacity   = "0.5";
          e.currentTarget.style.color     = "var(--text-dim)";
          e.currentTarget.style.background = "transparent";
        }}>
        {hidden ? "↻" : "×"}
      </button>
    </div>
  );
}

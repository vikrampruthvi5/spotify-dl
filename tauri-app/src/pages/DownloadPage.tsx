import { useState, useRef } from "react";
import { api, streamJobEvents, type JobEvent, type SourceInfo } from "../api/client";

interface Props { outputDir: string; quality: string; }

interface TrackRow {
  artist: string; title: string;
  status: "pending" | "downloading" | "ok" | "skip" | "fail";
  bpm?: number; camelot?: string;
}

const STATUS_ICON: Record<string, string> = {
  pending: "·", downloading: "⠸", ok: "✓", skip: "○", fail: "✕",
};
const STATUS_COLOR: Record<string, string> = {
  pending: "var(--text-dim)", downloading: "var(--accent-2)",
  ok: "var(--accent)", skip: "var(--yellow)", fail: "var(--red)",
};

export default function DownloadPage({ outputDir, quality }: Props) {
  const [url, setUrl]         = useState("");
  const [info, setInfo]       = useState<SourceInfo | null>(null);
  const [tracks, setTracks]   = useState<TrackRow[]>([]);
  const [status, setStatus]   = useState<"idle"|"fetching"|"downloading"|"done">("idle");
  const [summary, setSummary] = useState<{downloaded:number;skipped:number;failed:number}|null>(null);
  const [error, setError]     = useState("");
  const esRef = useRef<EventSource | null>(null);

  const fetch_ = async () => {
    if (!url.trim()) return;
    setStatus("fetching"); setError(""); setInfo(null); setTracks([]);
    try {
      const i = await api.getInfo(url.trim());
      setInfo(i);
      setTracks(i.tracks_preview.map(t => ({
        artist: t.artist, title: t.title, status: "pending",
      })));
      setStatus("idle");
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
      setStatus("idle");
    }
  };

  const download = async () => {
    if (!info) return;
    setStatus("downloading"); setSummary(null); setError("");
    setTracks(prev => prev.map(t => ({ ...t, status: "pending" })));

    try {
      const { job_id } = await api.download({
        url: url.trim(), output_dir: outputDir, quality, jobs: 4,
      });
      esRef.current = streamJobEvents(job_id, (ev: JobEvent) => {
        if (ev.type === "track_start") {
          setTracks(prev => prev.map(t =>
            t.artist === ev.artist && t.title === ev.title
              ? { ...t, status: "downloading" } : t
          ));
        } else if (ev.type === "track_done") {
          setTracks(prev => prev.map(t =>
            t.artist === ev.artist && t.title === ev.title
              ? { ...t, status: ev.status, bpm: ev.bpm, camelot: ev.camelot } : t
          ));
        } else if (ev.type === "summary") {
          setSummary({ downloaded: ev.downloaded, skipped: ev.skipped, failed: ev.failed });
        } else if (ev.type === "error") {
          setError(ev.message);
        }
      }, () => setStatus("done"));
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
      setStatus("idle");
    }
  };

  return (
    <div style={{ padding: 32, maxWidth: 780, margin: "0 auto" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 24 }}>Download</h1>

      {/* URL input */}
      <div style={{ display:"flex", gap:8, marginBottom: 24 }}>
        <input
          value={url}
          onChange={e => { setUrl(e.target.value); setInfo(null); }}
          onKeyDown={e => e.key === "Enter" && fetch_()}
          placeholder="Paste a Spotify or YouTube URL…"
          style={{ flex:1, fontSize:14, padding:"10px 14px" }}
        />
        <button
          onClick={fetch_}
          disabled={status === "fetching" || !url.trim()}
          style={{ background:"var(--surface-2)", color:"var(--text)",
                   padding:"10px 20px", border:"1px solid var(--border)" }}
        >
          {status === "fetching" ? "Fetching…" : "Fetch"}
        </button>
      </div>

      {error && (
        <div style={{ background:"#1a0505", border:"1px solid var(--red)", borderRadius:8,
                      padding:"10px 14px", color:"var(--red)", marginBottom:16, fontSize:13 }}>
          {error}
        </div>
      )}

      {/* Source info card */}
      {info && (
        <div style={{ background:"var(--surface)", border:"1px solid var(--border)",
                      borderRadius:12, padding:"16px 20px", marginBottom:20 }}>
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
            <div>
              <div style={{ fontSize:16, fontWeight:600 }}>{info.name}</div>
              <div style={{ color:"var(--text-dim)", fontSize:13, marginTop:4 }}>
                {info.type} · {info.owner} · {info.total_tracks} tracks
              </div>
            </div>
            <button
              onClick={download}
              disabled={status === "downloading"}
              style={{ background:"var(--accent)", color:"#000",
                       padding:"8px 20px", fontWeight:600 }}
            >
              {status === "downloading" ? "Downloading…" : "Download All"}
            </button>
          </div>
        </div>
      )}

      {/* Track list */}
      {tracks.length > 0 && (
        <div style={{ background:"var(--surface)", border:"1px solid var(--border)",
                      borderRadius:12, overflow:"hidden" }}>
          <div style={{ padding:"12px 20px", borderBottom:"1px solid var(--border)",
                        fontSize:12, color:"var(--text-dim)", fontWeight:600,
                        display:"grid", gridTemplateColumns:"24px 1fr 1fr 80px" }}>
            <span></span><span>ARTIST</span><span>TITLE</span><span>BPM / KEY</span>
          </div>
          <div style={{ maxHeight:420, overflowY:"auto" }}>
            {tracks.map((t, i) => (
              <div key={i} style={{
                display:"grid", gridTemplateColumns:"24px 1fr 1fr 80px",
                padding:"9px 20px", borderBottom:"1px solid var(--border)",
                background: i % 2 ? "var(--surface-2)" : "transparent",
                alignItems:"center", fontSize:13,
              }}>
                <span style={{ color: STATUS_COLOR[t.status], fontWeight:700 }}>
                  {STATUS_ICON[t.status]}
                </span>
                <span style={{ color:"var(--text-dim)", overflow:"hidden",
                               textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                  {t.artist}
                </span>
                <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                  {t.title}
                </span>
                <span style={{ color:"var(--accent-2)", fontSize:11 }}>
                  {t.bpm ? `${Math.round(t.bpm)}bpm` : ""}
                  {t.camelot ? ` ${t.camelot}` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary */}
      {summary && (
        <div style={{ display:"flex", gap:16, marginTop:20 }}>
          {[
            ["Downloaded", summary.downloaded, "var(--accent)"],
            ["Skipped",    summary.skipped,    "var(--yellow)"],
            ["Failed",     summary.failed,     "var(--red)"],
          ].map(([label, val, color]) => (
            <div key={String(label)} style={{
              flex:1, background:"var(--surface)", border:`1px solid var(--border)`,
              borderRadius:10, padding:"14px 20px", textAlign:"center",
            }}>
              <div style={{ fontSize:26, fontWeight:700, color: String(color) }}>{String(val)}</div>
              <div style={{ color:"var(--text-dim)", fontSize:12, marginTop:2 }}>{String(label)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

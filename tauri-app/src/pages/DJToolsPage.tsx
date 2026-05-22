import { useState } from "react";
import { api, streamJobEvents, type JobEvent } from "../api/client";

interface Props { outputDir: string; desktop: string; }

type Tool = "analyze" | "scan" | "dupes" | "crate" | "rekordbox" | "setcheck";

const TOOLS: { id: Tool; icon: string; label: string; desc: string }[] = [
  { id:"analyze",   icon:"⚡", label:"Analyze BPM + Key",  desc:"Detect BPM and Camelot key for every untagged track in your library." },
  { id:"scan",      icon:"🔍", label:"Tag Scanner",        desc:"Find tracks missing BPM, cover art, album, or key." },
  { id:"dupes",     icon:"♻",  label:"Duplicate Finder",   desc:"Spot byte-identical files and same-title duplicates." },
  { id:"crate",     icon:"♬",  label:"Crate Builder",      desc:"Filter library by BPM range, Camelot key, and energy. Saves as M3U." },
  { id:"rekordbox", icon:"◉",  label:"Rekordbox Export",   desc:"Export full library as Pioneer Rekordbox XML." },
  { id:"setcheck",  icon:"✓",  label:"Set Check",          desc:"Compare a Spotify playlist against your local library." },
];

export default function DJToolsPage({ outputDir, desktop }: Props) {
  const [active, setActive]   = useState<Tool>("analyze");
  const [output, setOutput]   = useState<string[]>([]);
  const [busy, setBusy]       = useState(false);

  // Analyze state
  const [analyzeForce, setAnalyzeForce] = useState(false);

  // Crate state
  const [crateBpm, setCrateBpm]       = useState("");
  const [crateKey, setCrateKey]       = useState("");
  const [crateEnergy, setCrateEnergy] = useState("");

  // Setcheck state
  const [setUrl, setSetUrl] = useState("");

  const log = (line: string) =>
    setOutput(prev => [...prev.slice(-199), line]);

  const clearLog = () => setOutput([]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const runAnalyze = async () => {
    setBusy(true); clearLog(); log("Starting analysis…");
    try {
      const { job_id } = await api.analyze({ directory: outputDir, force: analyzeForce });
      streamJobEvents(job_id, (ev: JobEvent) => {
        if (ev.type === "analyzed")
          log(`✓  ${ev.file}  ${ev.bpm ? Math.round(ev.bpm) + "bpm " : ""}${ev.camelot ?? ""}`);
        else if (ev.type === "summary")
          log(`\nDone — ${(ev as { analyzed: number }).analyzed} analyzed`);
        else if (ev.type === "error")
          log(`✕  ${ev.message}`);
      }, () => setBusy(false));
    } catch (e: unknown) { log(`Error: ${String(e)}`); setBusy(false); }
  };

  const runScan = async () => {
    setBusy(true); clearLog(); log("Scanning tags…");
    try {
      const res = await api.scan(outputDir);
      if (res.total === 0) { log("All tracks have complete tags!"); }
      else {
        log(`Found ${res.total} tracks with missing tags:\n`);
        res.issues.forEach(i =>
          log(`  ${i.path.split("/").pop()}  →  missing: ${i.missing.join(", ")}`)
        );
      }
    } catch (e: unknown) { log(`Error: ${String(e)}`); }
    setBusy(false);
  };

  const runDupes = async () => {
    setBusy(true); clearLog(); log("Scanning for duplicates…");
    try {
      const res = await api.dupes(outputDir);
      const total = res.by_hash_count + res.by_tags_count;
      if (total === 0) { log("No duplicates found!"); }
      else {
        if (res.by_hash_count) {
          log(`\n${res.by_hash_count} byte-identical group(s):`);
          res.by_hash.forEach(g => g.forEach((f, i) =>
            log(`  ${i === 0 ? "ORIG" : "COPY"}  ${f.split("/").pop()}`)
          ));
        }
        if (res.by_tags_count) {
          log(`\n${res.by_tags_count} same-title group(s):`);
          res.by_tags.slice(0, 10).forEach(g => g.forEach((f, i) =>
            log(`  #${i+1}  ${f.split("/").pop()}`)
          ));
        }
      }
    } catch (e: unknown) { log(`Error: ${String(e)}`); }
    setBusy(false);
  };

  const runCrate = async () => {
    setBusy(true); clearLog();
    const [bpmMin, bpmMax] = crateBpm.includes("-")
      ? crateBpm.split("-").map(Number) : [undefined, undefined];
    try {
      const res = await api.buildCrate({
        directory: outputDir,
        bpm_min: bpmMin, bpm_max: bpmMax,
        key: crateKey || undefined,
        energy_min: crateEnergy ? Number(crateEnergy) : undefined,
        output_m3u: `${outputDir}/dj_crate.m3u`,
      });
      log(`Built crate: ${res.count} tracks`);
      if (res.m3u) log(`Saved to: ${res.m3u}`);
    } catch (e: unknown) { log(`Error: ${String(e)}`); }
    setBusy(false);
  };

  const runRekordbox = async () => {
    setBusy(true); clearLog(); log("Exporting Rekordbox XML…");
    try {
      const res = await api.rekordbox({
        directory: outputDir,
        output_path: `${desktop}/rekordbox.xml`,
      });
      log(`Exported ${res.exported} tracks → ${res.path}`);
    } catch (e: unknown) { log(`Error: ${String(e)}`); }
    setBusy(false);
  };

  const runSetCheck = async () => {
    if (!setUrl.trim()) return;
    setBusy(true); clearLog(); log("Fetching playlist…");
    try {
      const res = await api.setCheck({ url: setUrl.trim(), directory: outputDir });
      log(`${res.playlist}  —  ${res.found}/${res.total} tracks found locally`);
      if (res.missing > 0) {
        log(`\nMissing (${res.missing}):`);
        res.missing_tracks.forEach(t => log(`  ✕  ${t.artist} — ${t.title}`));
      } else {
        log("\nAll tracks are in your library ✓");
      }
    } catch (e: unknown) { log(`Error: ${String(e)}`); }
    setBusy(false);
  };

  const RUN: Record<Tool, () => void> = {
    analyze: runAnalyze, scan: runScan, dupes: runDupes,
    crate: runCrate, rekordbox: runRekordbox, setcheck: runSetCheck,
  };

  const tool = TOOLS.find(t => t.id === active)!;

  return (
    <div style={{ display:"flex", height:"100%", overflow:"hidden" }}>
      {/* Tool list */}
      <div style={{ width:200, borderRight:"1px solid var(--border)",
                    padding:"16px 0", flexShrink:0, overflowY:"auto" }}>
        {TOOLS.map(t => (
          <button key={t.id} onClick={() => { setActive(t.id); clearLog(); }}
            style={{
              width:"100%", background: active === t.id ? "var(--surface-2)" : "transparent",
              color: active === t.id ? "var(--text)" : "var(--text-dim)",
              borderRadius:0, padding:"10px 16px",
              textAlign:"left", display:"flex", alignItems:"center", gap:8,
              borderLeft:`3px solid ${active === t.id ? "var(--accent-2)" : "transparent"}`,
            }}>
            <span>{t.icon}</span> {t.label}
          </button>
        ))}
      </div>

      {/* Detail + output */}
      <div style={{ flex:1, padding:28, display:"flex", flexDirection:"column", gap:16, overflow:"auto" }}>
        <div>
          <h2 style={{ fontSize:18, fontWeight:700 }}>{tool.icon} {tool.label}</h2>
          <p style={{ color:"var(--text-dim)", fontSize:13, marginTop:6 }}>{tool.desc}</p>
        </div>

        {/* Tool-specific controls */}
        {active === "analyze" && (
          <label style={{ display:"flex", alignItems:"center", gap:8, fontSize:13, cursor:"pointer" }}>
            <input type="checkbox" checked={analyzeForce}
              onChange={e => setAnalyzeForce(e.target.checked)} />
            Force re-analyze tracks that already have BPM tags
          </label>
        )}
        {active === "crate" && (
          <div style={{ display:"flex", gap:10, flexWrap:"wrap" }}>
            <input value={crateBpm} onChange={e => setCrateBpm(e.target.value)}
              placeholder="BPM range (e.g. 120-130)" style={{ width:180 }} />
            <input value={crateKey} onChange={e => setCrateKey(e.target.value)}
              placeholder="Key / Camelot (e.g. 8A)" style={{ width:180 }} />
            <input value={crateEnergy} onChange={e => setCrateEnergy(e.target.value)}
              placeholder="Min energy (0.0–1.0)" style={{ width:160 }} />
          </div>
        )}
        {active === "setcheck" && (
          <input value={setUrl} onChange={e => setSetUrl(e.target.value)}
            placeholder="Spotify playlist URL…" style={{ maxWidth:480 }} />
        )}

        <button onClick={RUN[active]} disabled={busy}
          style={{ alignSelf:"flex-start", background:"var(--accent-2)", color:"#fff",
                   padding:"8px 22px", fontWeight:600 }}>
          {busy ? "Running…" : `Run ${tool.label}`}
        </button>

        {/* Output log */}
        {output.length > 0 && (
          <div style={{
            flex:1, background:"var(--surface)", border:"1px solid var(--border)",
            borderRadius:10, padding:"12px 16px", fontFamily:"monospace", fontSize:12,
            color:"var(--text-dim)", overflowY:"auto", whiteSpace:"pre-wrap",
            maxHeight:"calc(100vh - 360px)",
          }}>
            {output.join("\n")}
          </div>
        )}
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import { api, type SpotifyUserPlaylist } from "../api/client";

interface Props {
  trackIds: string[];
  defaultName?: string;
  onClose: () => void;
  onSuccess?: (info: { playlistName: string; added: number }) => void;
}

export default function PlaylistPickerModal({
  trackIds, defaultName, onClose, onSuccess,
}: Props) {
  const [playlists, setPlaylists] = useState<SpotifyUserPlaylist[]>([]);
  const [loading, setLoading]     = useState(true);
  const [search, setSearch]       = useState("");
  const [mode, setMode]           = useState<"pick" | "create">("pick");
  const [newName, setNewName]     = useState(defaultName ?? `SpotiDL · ${new Date().toLocaleDateString()}`);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError]         = useState("");

  useEffect(() => {
    api.listUserPlaylists()
      .then(res => setPlaylists(res.playlists))
      .catch(e => setError(String((e as Error).message ?? e)))
      .finally(() => setLoading(false));
  }, []);

  const filtered = playlists.filter(p =>
    !search || p.name.toLowerCase().includes(search.toLowerCase())
  );

  const addTo = async (playlist_id: string, name: string) => {
    setSubmitting(true);
    setError("");
    try {
      const res = await api.addTracksToUserPlaylist({ playlist_id, track_ids: trackIds });
      onSuccess?.({ playlistName: name, added: res.added });
      onClose();
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
      setSubmitting(false);
    }
  };

  const createAndAdd = async () => {
    if (!newName.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const pl  = await api.createUserPlaylist({ name: newName.trim() });
      const res = await api.addTracksToUserPlaylist({ playlist_id: pl.id, track_ids: trackIds });
      onSuccess?.({ playlistName: pl.name, added: res.added });
      onClose();
    } catch (e: unknown) {
      setError(String((e as Error).message ?? e));
      setSubmitting(false);
    }
  };

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, background:"rgba(0,0,0,0.6)",
      display:"flex", alignItems:"center", justifyContent:"center",
      zIndex:1000, backdropFilter:"blur(4px)",
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:520, maxWidth:"90vw", maxHeight:"80vh",
        background:"var(--surface)", border:"1px solid var(--border)",
        borderRadius:14, overflow:"hidden", display:"flex", flexDirection:"column",
        boxShadow:"0 20px 60px rgba(0,0,0,0.5)",
      }}>
        {/* Header */}
        <div style={{ padding:"18px 22px", borderBottom:"1px solid var(--border)" }}>
          <div style={{ fontSize:16, fontWeight:700, marginBottom:4 }}>
            Add to Spotify Playlist
          </div>
          <div style={{ color:"var(--text-dim)", fontSize:12 }}>
            {trackIds.length} track{trackIds.length === 1 ? "" : "s"} selected
          </div>
        </div>

        {/* Mode tabs */}
        <div style={{ display:"flex", padding:"0 22px", borderBottom:"1px solid var(--border)" }}>
          {(["pick", "create"] as const).map(m => (
            <button key={m} onClick={() => setMode(m)}
              style={{
                background:"transparent",
                color: mode === m ? "var(--text)" : "var(--text-dim)",
                padding:"10px 16px", borderRadius:0, fontSize:13,
                fontWeight: mode === m ? 600 : 400,
                borderBottom: `2px solid ${mode === m ? "var(--accent)" : "transparent"}`,
                marginBottom:-1,
              }}>
              {m === "pick" ? "Existing" : "Create new"}
            </button>
          ))}
        </div>

        {/* Body */}
        {mode === "pick" ? (
          <div style={{ flex:1, overflow:"hidden", display:"flex", flexDirection:"column" }}>
            <div style={{ padding:"12px 22px" }}>
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search your playlists…"
                style={{ width:"100%" }} />
            </div>
            <div style={{ flex:1, overflowY:"auto" }}>
              {loading && (
                <div style={{ padding:30, textAlign:"center", color:"var(--text-dim)" }}>
                  Loading your playlists…
                </div>
              )}
              {!loading && filtered.length === 0 && (
                <div style={{ padding:30, textAlign:"center", color:"var(--text-dim)" }}>
                  No playlists found.
                </div>
              )}
              {filtered.map(p => (
                <button key={p.id} onClick={() => addTo(p.id, p.name)} disabled={submitting}
                  style={{
                    width:"100%", padding:"10px 22px", background:"transparent",
                    borderRadius:0, display:"flex", alignItems:"center", gap:12,
                    borderBottom:"1px solid var(--border)", textAlign:"left",
                  }}>
                  {p.cover_url ? (
                    <img src={p.cover_url} alt=""
                      style={{ width:36, height:36, borderRadius:4, objectFit:"cover" }} />
                  ) : (
                    <div style={{ width:36, height:36, borderRadius:4, background:"var(--surface-2)" }} />
                  )}
                  <div style={{ flex:1, overflow:"hidden" }}>
                    <div style={{ color:"var(--text)", fontSize:13, fontWeight:500,
                                  overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                      {p.name}
                    </div>
                    <div style={{ color:"var(--text-dim)", fontSize:11, marginTop:2 }}>
                      {p.tracks_total} tracks · {p.owner ?? ""}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ padding:"20px 22px", flex:1 }}>
            <label style={{ fontSize:12, color:"var(--text-dim)", display:"block",
                            marginBottom:6 }}>Playlist name</label>
            <input value={newName} onChange={e => setNewName(e.target.value)}
              autoFocus style={{ width:"100%", marginBottom:14 }}
              onKeyDown={e => e.key === "Enter" && createAndAdd()} />
            <div style={{ color:"var(--text-dim)", fontSize:11 }}>
              The playlist will be private and owned by you.
            </div>
          </div>
        )}

        {error && (
          <div style={{ padding:"10px 22px", background:"#1a0505",
                        color:"var(--red)", fontSize:12, borderTop:"1px solid var(--red)" }}>
            {error}
          </div>
        )}

        {/* Footer */}
        <div style={{ padding:"14px 22px", borderTop:"1px solid var(--border)",
                      display:"flex", justifyContent:"flex-end", gap:8 }}>
          <button onClick={onClose} disabled={submitting}
            style={{ background:"transparent", color:"var(--text-dim)",
                     padding:"7px 16px", border:"1px solid var(--border)" }}>
            Cancel
          </button>
          {mode === "create" && (
            <button onClick={createAndAdd} disabled={submitting || !newName.trim()}
              style={{ background:"var(--accent)", color:"#000",
                       padding:"7px 18px", fontWeight:600 }}>
              {submitting ? "Adding…" : "Create & Add"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

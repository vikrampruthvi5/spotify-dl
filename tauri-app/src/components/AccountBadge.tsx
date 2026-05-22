import { useState, useEffect, useRef } from "react";
import { api, type SpotifyProfile } from "../api/client";

export default function AccountBadge() {
  const [profile, setProfile] = useState<SpotifyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const pollRef = useRef<number | null>(null);

  const refresh = async () => {
    try {
      const res = await api.authStatus();
      setProfile(res.profile);
    } catch {
      setProfile(null);
    }
    setLoading(false);
  };

  useEffect(() => { refresh(); }, []);

  // Poll once a second for up to 90 s after the user clicks Connect,
  // to detect the OAuth redirect coming back from the browser.
  const startPolling = () => {
    const start = Date.now();
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      const res = await api.authStatus();
      if (res.authenticated) {
        setProfile(res.profile);
        window.clearInterval(pollRef.current!);
        pollRef.current = null;
      } else if (Date.now() - start > 90000) {
        window.clearInterval(pollRef.current!);
        pollRef.current = null;
      }
    }, 1000);
  };

  const connect = async () => {
    const { url } = await api.authLoginUrl();
    window.open(url, "_blank", "noopener,noreferrer");
    startPolling();
  };

  const logout = async () => {
    await api.authLogout();
    setProfile(null);
    setMenuOpen(false);
  };

  if (loading) {
    return (
      <div style={{ padding:"12px 16px", color:"var(--text-dim)", fontSize:11 }}>
        Checking Spotify…
      </div>
    );
  }

  if (!profile) {
    return (
      <button onClick={connect}
        style={{
          margin:"8px 12px", padding:"9px 14px",
          background:"var(--accent)", color:"#000",
          fontSize:12, fontWeight:600, borderRadius:8,
          display:"flex", alignItems:"center", gap:6, justifyContent:"center",
        }}>
        <span style={{ fontSize:14 }}>♪</span> Connect Spotify
      </button>
    );
  }

  return (
    <div style={{ position:"relative" }}>
      <button onClick={() => setMenuOpen(v => !v)}
        style={{
          width:"calc(100% - 24px)", margin:"4px 12px", padding:"6px 8px",
          background: menuOpen ? "var(--surface-2)" : "transparent",
          color:"var(--text)", borderRadius:8,
          display:"flex", alignItems:"center", gap:8, fontSize:12,
        }}>
        {profile.avatar_url ? (
          <img src={profile.avatar_url} alt=""
            style={{ width:24, height:24, borderRadius:12, objectFit:"cover" }} />
        ) : (
          <div style={{ width:24, height:24, borderRadius:12, background:"var(--accent)",
                        color:"#000", display:"flex", alignItems:"center",
                        justifyContent:"center", fontSize:11, fontWeight:700 }}>
            {profile.display_name.charAt(0).toUpperCase()}
          </div>
        )}
        <span style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap",
                       flex:1, textAlign:"left", fontWeight:500 }}>
          {profile.display_name}
        </span>
      </button>

      {menuOpen && (
        <div style={{
          position:"absolute", bottom:"calc(100% + 4px)", left:12, right:12,
          background:"var(--surface-2)", border:"1px solid var(--border)",
          borderRadius:8, padding:4, zIndex:10,
        }}>
          <button onClick={logout}
            style={{ width:"100%", padding:"7px 10px", background:"transparent",
                     color:"var(--red)", fontSize:12, textAlign:"left",
                     display:"flex", alignItems:"center", gap:6 }}>
            ⎋  Disconnect
          </button>
        </div>
      )}
    </div>
  );
}

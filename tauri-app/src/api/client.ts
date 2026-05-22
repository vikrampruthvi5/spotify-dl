// Thin typed client over the SpotiDL FastAPI server.
// All requests go to /api/* — Vite proxies to :8765 in dev,
// FastAPI serves the built React app directly in production.

const BASE = "/api";

async function _json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface TrackMeta {
  id?: string;
  title: string;
  artist: string;
  album: string;
  year?: string;
  duration_ms?: number;
  cover_url?: string;
}

export interface SourceInfo {
  type: "playlist" | "album" | "track";
  name: string;
  owner: string;
  total_tracks: number;
  cover_url?: string;
  tracks_preview: TrackMeta[];
}

export interface LibraryTrack extends TrackMeta {
  path: string;
  filename: string;
  size_kb: number;
  bpm?: number;
  key?: string;
  camelot?: string;
  energy?: number;
  danceability?: number;
  valence?: number;
  has_cover: boolean;
}

export interface ScanIssue {
  path: string;
  missing: string[];
}

export interface DupeResult {
  by_hash: string[][];
  by_tags: string[][];
  by_hash_count: number;
  by_tags_count: number;
}

export interface TrendingTrack {
  id: string;
  title: string;
  artist: string;
  album: string;
  duration_ms: number;
  year?: string;
  cover_url?: string;
  popularity: number;
  spotify_url?: string;
  preview_url?: string | null;
}

export interface SpotifyProfile {
  id: string;
  display_name: string;
  avatar_url: string | null;
  followers: number;
  url?: string;
}

export interface SpotifyUserPlaylist {
  id: string;
  name: string;
  tracks_total: number;
  url?: string;
  cover_url?: string | null;
  owner?: string;
  collaborative?: boolean;
  public?: boolean;
}

export interface TrendingResult {
  region: string;
  label: string;
  language: string;
  playlist_name: string;
  playlist_id: string;
  playlist_url: string;
  cover_url: string | null;
  tracks: TrendingTrack[];
}

export interface WatchedPlaylist {
  url: string;
  name: string;
  folder: string;
  total_tracks: number;
  downloaded_ids: string[];
}

export interface WatcherStatus {
  running: boolean;
  poll_interval: number;
  playlists: number;
}

// ── SSE job events ────────────────────────────────────────────────────────────

export type JobEvent =
  | { type: "start";       name: string;  total: number }
  | { type: "track_start"; artist: string; title: string }
  | { type: "track_done";  status: "ok" | "skip" | "fail"; artist: string; title: string;
      path?: string; bpm?: number; key?: string; camelot?: string }
  | { type: "summary";     downloaded: number; skipped: number; failed: number;
      failed_tracks: { artist: string; title: string }[] }
  | { type: "analyzed";    file: string; path: string; bpm?: number; key?: string; camelot?: string }
  | { type: "error";       message: string }
  | { type: "done" };

export function streamJobEvents(
  jobId: string,
  onEvent: (e: JobEvent) => void,
  onClose?: () => void,
): EventSource {
  const es = new EventSource(`${BASE}/jobs/${jobId}/events`);
  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data) as JobEvent;
    onEvent(data);
    if (data.type === "done") {
      es.close();
      onClose?.();
    }
  };
  es.onerror = () => { es.close(); onClose?.(); };
  return es;
}

export function streamWatcherEvents(
  onNotification: (msg: string) => void,
): EventSource {
  const es = new EventSource(`${BASE}/watcher/events`);
  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data) as { type: string; message: string };
    if (data.type === "notification") onNotification(data.message);
  };
  return es;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export const api = {
  health: () =>
    fetch(`${BASE}/health`).then((r) => _json<{ status: string }>(r)),

  config: () =>
    fetch(`${BASE}/config`).then((r) =>
      _json<{ output_dir: string; quality: string; home: string; desktop: string }>(r)
    ),

  getInfo: (url: string) =>
    fetch(`${BASE}/info?url=${encodeURIComponent(url)}`).then((r) =>
      _json<SourceInfo>(r)
    ),

  download: (body: {
    url: string; output_dir: string; quality: string;
    organize?: boolean; browser?: string; jobs?: number;
  }) =>
    fetch(`${BASE}/download`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => _json<{ job_id: string }>(r)),

  downloadTracks: (body: {
    track_ids: string[]; output_dir: string; quality: string;
    organize?: boolean; browser?: string | null; jobs?: number; name?: string;
  }) =>
    fetch(`${BASE}/download-tracks`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => _json<{ job_id: string }>(r)),

  getTrending: (region: string) =>
    fetch(`${BASE}/trending?region=${encodeURIComponent(region)}`).then((r) =>
      _json<TrendingResult>(r)
    ),

  getTrendingRegions: () =>
    fetch(`${BASE}/trending/regions`).then((r) =>
      _json<{ id: string; label: string; language: string; query: string }[]>(r)
    ),

  // ── Spotify OAuth ──────────────────────────────────────────────────────────
  authStatus: () =>
    fetch(`${BASE}/auth/status`).then((r) =>
      _json<{ authenticated: boolean; profile: SpotifyProfile | null }>(r)
    ),

  authLoginUrl: () =>
    fetch(`${BASE}/auth/login`).then((r) => _json<{ url: string }>(r)),

  authLogout: () =>
    fetch(`${BASE}/auth/logout`, { method: "POST" }).then((r) =>
      _json<{ authenticated: boolean }>(r)
    ),

  // ── User Spotify playlists ─────────────────────────────────────────────────
  listUserPlaylists: () =>
    fetch(`${BASE}/spotify/playlists`).then((r) =>
      _json<{ playlists: SpotifyUserPlaylist[] }>(r)
    ),

  createUserPlaylist: (body: { name: string; description?: string; public?: boolean }) =>
    fetch(`${BASE}/spotify/playlists`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) =>
      _json<{ id: string; name: string; url?: string; tracks_total: number }>(r)
    ),

  addTracksToUserPlaylist: (body: { playlist_id: string; track_ids: string[] }) =>
    fetch(`${BASE}/spotify/playlists/add-tracks`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => _json<{ added: number }>(r)),

  getLibrary: (dir: string) =>
    fetch(`${BASE}/library?dir=${encodeURIComponent(dir)}`).then((r) =>
      _json<LibraryTrack[]>(r)
    ),

  scan: (dir: string) =>
    fetch(`${BASE}/scan?dir=${encodeURIComponent(dir)}`).then((r) =>
      _json<{ total: number; issues: ScanIssue[] }>(r)
    ),

  dupes: (dir: string) =>
    fetch(`${BASE}/dupes?dir=${encodeURIComponent(dir)}`).then((r) =>
      _json<DupeResult>(r)
    ),

  analyze: (body: { directory: string; force?: boolean }) =>
    fetch(`${BASE}/analyze`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => _json<{ job_id: string }>(r)),

  rekordbox: (body: { directory: string; output_path?: string }) =>
    fetch(`${BASE}/rekordbox`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => _json<{ exported: number; path: string }>(r)),

  buildCrate: (body: {
    directory: string; bpm_min?: number; bpm_max?: number;
    key?: string; energy_min?: number; output_m3u?: string;
  }) =>
    fetch(`${BASE}/crate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => _json<{ count: number; tracks: string[]; m3u?: string }>(r)),

  setCheck: (body: { url: string; directory: string }) =>
    fetch(`${BASE}/setcheck`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) =>
      _json<{ playlist: string; total: number; found: number; missing: number;
              missing_tracks: TrackMeta[] }>(r)
    ),

  // Watcher
  watcherStatus: () =>
    fetch(`${BASE}/watcher/status`).then((r) => _json<WatcherStatus>(r)),

  watcherStart: (body: { quality?: string; browser?: string | null; organize?: boolean; poll_interval_mins?: number }) =>
    fetch(`${BASE}/watcher/start`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => _json<{ running: boolean }>(r)),

  watcherStop: () =>
    fetch(`${BASE}/watcher/stop`, { method: "POST" }).then((r) =>
      _json<{ running: boolean }>(r)
    ),

  watcherCheck: () =>
    fetch(`${BASE}/watcher/check`, { method: "POST" }).then((r) =>
      _json<{ triggered: boolean }>(r)
    ),

  // Playlists
  listPlaylists: () =>
    fetch(`${BASE}/playlists`).then((r) =>
      _json<{ playlists: WatchedPlaylist[] }>(r)
    ),

  addPlaylist: (body: { url: string; folder?: string }) =>
    fetch(`${BASE}/playlists`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => _json<WatchedPlaylist>(r)),

  deletePlaylist: (url: string) =>
    fetch(`${BASE}/playlists?url=${encodeURIComponent(url)}`, {
      method: "DELETE",
    }).then((r) => _json<{ deleted: boolean }>(r)),
};

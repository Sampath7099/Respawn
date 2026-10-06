// Thin client for the Respawn API, plus batched clickstream tracking.
// Auth is an HttpOnly cookie set by /auth/login, so this file never sees the token.

const BASE = "/api";

export const currentUser = () => localStorage.getItem("respawn_user"); // display only, not a credential

// One id per browser tab session, sent with every event so the warehouse can group them.
function sessionId() {
  let id = sessionStorage.getItem("respawn_sid");
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem("respawn_sid", id);
  }
  return id;
}

export async function api(path, { method = "GET", body, headers = {}, keepalive = false } = {}) {
  const res = await fetch(BASE + path, {
    method,
    credentials: "same-origin",
    keepalive,
    headers: { "Content-Type": "application/json", "X-Session-Id": sessionId(), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    localStorage.removeItem("respawn_user");
    if (location.pathname !== "/login") location.href = "/login";
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.status === 204 ? null : res.json();
}

export async function login(userId) {
  await api("/auth/login", { method: "POST", body: { user_id: userId } });
  localStorage.setItem("respawn_user", userId);
}

export async function logout() {
  await api("/auth/logout", { method: "POST" }).catch(() => {});
  localStorage.removeItem("respawn_user");
  location.href = "/login";
}

// Clickstream: buffer events, send one request every few seconds.
let queue = [];
export function track(event_type, game_id = null) {
  if (currentUser()) queue.push({ event_type, game_id });
}
function flush(keepalive = false) {
  if (!queue.length || !currentUser()) return;
  const batch = queue.splice(0, 100);
  // keepalive lets the request outlive the page, so the last batch isn't lost on close
  api("/events", { method: "POST", body: batch, keepalive }).catch(() => {});
}
setInterval(flush, 3000);
addEventListener("pagehide", () => flush(true));

export const coverUrl = (id) => `https://cdn.akamai.steamstatic.com/steam/apps/${id}/header.jpg`;
export const price = (p) => (p === null || p === undefined ? "Not for sale" : Number(p) === 0 ? "Free" : `$${Number(p).toFixed(2)}`);

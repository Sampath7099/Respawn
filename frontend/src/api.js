// Thin client for the Respawn API, plus batched clickstream tracking.

const BASE = "/api";

export function getToken() {
  return localStorage.getItem("respawn_token");
}

export function setSession(token, user) {
  localStorage.setItem("respawn_token", token);
  localStorage.setItem("respawn_user", user);
}

export function clearSession() {
  localStorage.removeItem("respawn_token");
  localStorage.removeItem("respawn_user");
}

export async function api(path, { method = "GET", body, headers = {} } = {}) {
  const token = getToken();
  const res = await fetch(BASE + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    clearSession();
    window.location.href = "/login";
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

// Clickstream: buffer events and send them in one request every few seconds,
// so browsing doesn't fire a request per click.
let queue = [];
export function track(event_type, game_id = null) {
  if (!getToken()) return;
  queue.push({ event_type, game_id });
}
function flush() {
  if (!queue.length || !getToken()) return;
  const batch = queue;
  queue = [];
  api("/events", { method: "POST", body: batch }).catch(() => {});
}
setInterval(flush, 3000);
window.addEventListener("beforeunload", flush);

export const coverUrl = (id) => `https://cdn.akamai.steamstatic.com/steam/apps/${id}/header.jpg`;
export const price = (p) => (Number(p) === 0 ? "Free" : `$${Number(p).toFixed(2)}`);

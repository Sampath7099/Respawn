import { useEffect, useState } from "react";
import { login } from "../api.js";
import { Logo } from "../components/ui.jsx";

// Demo accounts are real Steam users from the dataset, so their library,
// A/B arm and recommendations are all real.
const SAMPLES = ["76561197970982479", "js41637", "evcentric", "doctr", "Riot-Punch"];
const BOOT = ["> establishing uplink…", "> loading 32,132 titles…", "> ranker online", "> awaiting player id_"];

export default function Login() {
  const [userId, setUserId] = useState("");
  const [error, setError] = useState("");
  const [lines, setLines] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setLines((n) => (n < BOOT.length ? n + 1 : n)), 350);
    return () => clearInterval(t);
  }, []);

  const enter = async (id) => {
    setError("");
    try {
      await login(id);
      window.location.href = "/";
    } catch (e) {
      setError(e.message === "unknown user" ? "ACCESS DENIED · unknown player id" : e.message);
    }
  };

  return (
    <div className="login">
      <div className="synth fixed" aria-hidden="true">
        <div className="sun" />
        <div className="horizon-grid" />
      </div>
      <div className="login-box">
        <Logo big />
        <p className="tagline mono">YOUR NEXT FAVOURITE GAME IS ONE RESPAWN AWAY</p>
        <div className="boot mono" aria-hidden="true">
          {BOOT.slice(0, lines).map((l) => (
            <div key={l}>{l}</div>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            enter(userId.trim());
          }}
        >
          <input placeholder="steam user id" value={userId} onChange={(e) => setUserId(e.target.value)} aria-label="Steam user id" />
          <button className="primary" disabled={!userId.trim()}>
            Jack in ▸
          </button>
        </form>
        {error && <p className="error mono">{error}</p>}
        <p className="muted small">or play as a real Steam user</p>
        <div className="chips center">
          {SAMPLES.map((s) => (
            <button key={s} className="chip" onClick={() => enter(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

import { useState } from "react";
import { api, setSession } from "../api.js";

// Demo accounts are real Steam users from the dataset, so their library,
// A/B arm and recommendations are all real.
const SAMPLES = ["76561197970982479", "js41637", "evcentric", "doctr", "Riot-Punch"];

export default function Login() {
  const [userId, setUserId] = useState("");
  const [error, setError] = useState("");

  const login = async (id) => {
    setError("");
    try {
      const { token } = await api("/auth/login", { method: "POST", body: { user_id: id } });
      setSession(token, id);
      window.location.href = "/";
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="login">
      <div className="login-box">
        <h1 className="logo big">
          RE<span>SPAWN</span>
        </h1>
        <p className="muted">Your next favourite game is one respawn away.</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            login(userId.trim());
          }}
        >
          <input placeholder="Steam user id" value={userId} onChange={(e) => setUserId(e.target.value)} />
          <button className="primary" disabled={!userId.trim()}>
            Enter the store
          </button>
        </form>
        {error && <p className="error">{error}</p>}
        <p className="muted small">Or play as a real Steam user:</p>
        <div className="chips">
          {SAMPLES.map((s) => (
            <button key={s} className="chip" onClick={() => login(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

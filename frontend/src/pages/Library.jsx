import { useEffect, useState } from "react";
import { api } from "../api.js";
import GameCard from "../components/GameCard.jsx";
import { SkeletonGrid } from "../components/ui.jsx";

export default function Library() {
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("library");

  useEffect(() => {
    api("/me").then(setMe);
  }, []);

  const games = me ? (tab === "library" ? me.library : me.wishlist) : null;

  return (
    <>
      <div className="page-head">
        <h1 className="section-title">Your library</h1>
        {me && (
          <span className="chip-mono">
            {me.user_id} · A/B ARM {me.variant.toUpperCase()}
          </span>
        )}
      </div>
      <div className="tabs">
        <button className={tab === "library" ? "active" : ""} onClick={() => setTab("library")}>
          Owned <b>{me?.library_size ?? "–"}</b>
        </button>
        <button className={tab === "wishlist" ? "active" : ""} onClick={() => setTab("wishlist")}>
          Wishlist <b>{me?.wishlist.length ?? "–"}</b>
        </button>
      </div>
      {games === null ? (
        <SkeletonGrid count={10} />
      ) : games.length ? (
        <div className="grid">
          {games.map((g, i) => (
            <GameCard key={g.game_id} game={g} index={i} />
          ))}
        </div>
      ) : (
        <div className="empty">
          <span className="mono neon-pink">NOTHING HERE YET</span>
        </div>
      )}
    </>
  );
}

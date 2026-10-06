import { useEffect, useState } from "react";
import { api } from "../api.js";
import GameCard from "../components/GameCard.jsx";

export default function Library() {
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("library");

  useEffect(() => {
    api("/me").then(setMe);
  }, []);

  if (!me) return <p className="muted">Loading…</p>;
  const games = tab === "library" ? me.library : me.wishlist;

  return (
    <>
      <div className="tabs">
        <button className={tab === "library" ? "active" : ""} onClick={() => setTab("library")}>
          Library ({me.library_size})
        </button>
        <button className={tab === "wishlist" ? "active" : ""} onClick={() => setTab("wishlist")}>
          Wishlist ({me.wishlist.length})
        </button>
      </div>
      <div className="grid">
        {games.map((g) => (
          <GameCard key={g.game_id} game={g} />
        ))}
      </div>
      {!games.length && <p className="muted">Nothing here yet.</p>}
    </>
  );
}

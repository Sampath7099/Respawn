import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import GameCard from "../components/GameCard.jsx";
import { SkeletonGrid } from "../components/ui.jsx";

const GENRES = ["Action", "Adventure", "RPG", "Strategy", "Simulation", "Indie", "Casual", "Racing", "Sports", "Free to Play"];
const SIZE = 24;

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const genre = params.get("genre") || "";
  const page = Number(params.get("page") || 1);
  const [games, setGames] = useState(null);
  const [text, setText] = useState(q);

  useEffect(() => {
    setGames(null);
    const qs = new URLSearchParams({ page, size: SIZE });
    if (q) qs.set("q", q);
    if (genre) qs.set("genre", genre);
    api(`/games?${qs}`).then(setGames).catch(() => setGames([]));
  }, [q, genre, page]);

  const update = (next) => setParams({ ...Object.fromEntries(params), page: 1, ...next });

  return (
    <>
      <div className="page-head">
        <h1 className="section-title">Browse the archive</h1>
        <span className="chip-mono">
          {genre || "ALL GENRES"} {q && `· "${q}"`} · PAGE {page}
        </span>
      </div>

      <form
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          update({ q: text });
        }}
      >
        <span className="prompt mono">&gt;_</span>
        <input placeholder="search games…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search games" />
        <button className="primary">Search</button>
      </form>

      <div className="chips genre-bar">
        <button className={`chip ${!genre ? "active" : ""}`} onClick={() => update({ genre: "" })}>
          All
        </button>
        {GENRES.map((g) => (
          <button key={g} className={`chip ${genre === g ? "active" : ""}`} onClick={() => update({ genre: g })}>
            {g}
          </button>
        ))}
      </div>

      {games === null ? (
        <SkeletonGrid count={12} />
      ) : games.length ? (
        <div className="grid">
          {games.map((g, i) => (
            <GameCard key={g.game_id} game={g} index={i} />
          ))}
        </div>
      ) : (
        <div className="empty">
          <span className="mono neon-pink">404 // NO SIGNAL</span>
          <p className="muted">No games match that search.</p>
        </div>
      )}

      <div className="pager">
        <button className="ghost" disabled={page <= 1} onClick={() => update({ page: page - 1 })}>
          ◂ Prev
        </button>
        <span className="mono">{String(page).padStart(2, "0")}</span>
        <button className="ghost" disabled={!games || games.length < SIZE} onClick={() => update({ page: page + 1 })}>
          Next ▸
        </button>
      </div>
    </>
  );
}

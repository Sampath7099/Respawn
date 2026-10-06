import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import GameCard from "../components/GameCard.jsx";

const GENRES = ["", "Action", "Adventure", "RPG", "Strategy", "Simulation", "Indie", "Casual", "Racing", "Sports", "Free to Play"];

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const genre = params.get("genre") || "";
  const page = Number(params.get("page") || 1);
  const [games, setGames] = useState([]);
  const [text, setText] = useState(q);

  useEffect(() => {
    const qs = new URLSearchParams({ page, size: 24 });
    if (q) qs.set("q", q);
    if (genre) qs.set("genre", genre);
    api(`/games?${qs}`).then(setGames);
  }, [q, genre, page]);

  const update = (next) => setParams({ ...Object.fromEntries(params), page: 1, ...next });

  return (
    <>
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          update({ q: text });
        }}
      >
        <input placeholder="Search games…" value={text} onChange={(e) => setText(e.target.value)} />
        <select value={genre} onChange={(e) => update({ genre: e.target.value })}>
          {GENRES.map((g) => (
            <option key={g} value={g}>
              {g || "All genres"}
            </option>
          ))}
        </select>
        <button className="primary">Search</button>
      </form>

      <div className="grid">
        {games.map((g) => (
          <GameCard key={g.game_id} game={g} />
        ))}
      </div>
      {!games.length && <p className="muted">No games found.</p>}

      <div className="pager">
        <button className="ghost" disabled={page <= 1} onClick={() => update({ page: page - 1 })}>
          ← Prev
        </button>
        <span>Page {page}</span>
        <button className="ghost" disabled={games.length < 24} onClick={() => update({ page: page + 1 })}>
          Next →
        </button>
      </div>
    </>
  );
}

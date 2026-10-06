import { useState } from "react";
import { Link } from "react-router-dom";
import { coverUrl, price, track } from "../api.js";
import { SkeletonGrid } from "./ui.jsx";

// Cards tilt towards the cursor: the mouse position sets two CSS variables.
function tilt(e) {
  const r = e.currentTarget.getBoundingClientRect();
  e.currentTarget.style.setProperty("--rx", `${((e.clientY - r.top) / r.height - 0.5) * -8}deg`);
  e.currentTarget.style.setProperty("--ry", `${((e.clientX - r.left) / r.width - 0.5) * 10}deg`);
}
function untilt(e) {
  e.currentTarget.style.setProperty("--rx", "0deg");
  e.currentTarget.style.setProperty("--ry", "0deg");
}

// `source` = "rec" for cards in the recommendation row: clicks are logged as
// rec_click, which feeds the A/B test's click-through metric.
export default function GameCard({ game, source, rank, index = 0 }) {
  const [broken, setBroken] = useState(false);
  return (
    <Link
      to={`/game/${game.game_id}`}
      className="card"
      style={{ "--i": index }}
      onMouseMove={tilt}
      onMouseLeave={untilt}
      onClick={() => track(source === "rec" ? "rec_click" : "game_click", game.game_id)}
    >
      <div className="cover-wrap">
        {broken ? (
          <div className="cover placeholder">{game.title}</div>
        ) : (
          <img className="cover" src={coverUrl(game.game_id)} alt={game.title} loading="lazy" onError={() => setBroken(true)} />
        )}
        {rank && <span className="rank">{String(rank).padStart(2, "0")}</span>}
        <span className="view">VIEW ▸</span>
      </div>
      <div className="card-body">
        <div className="card-title">{game.title}</div>
        <div className="card-meta">
          <span className="tag">{game.primary_genre}</span>
          <span className="price">{price(game.price)}</span>
        </div>
      </div>
    </Link>
  );
}

export function Row({ title, subtitle, games, source, ranked = false, loading = false }) {
  if (!loading && !games?.length) return null;
  return (
    <section className="row">
      <div className="row-head">
        <h2 className="section-title">{title}</h2>
        {subtitle && <span className="chip-mono">{subtitle}</span>}
      </div>
      {loading ? (
        <SkeletonGrid count={5} />
      ) : (
        <div className="grid">
          {games.map((g, i) => (
            <GameCard key={g.game_id} game={g} source={source} rank={ranked ? i + 1 : null} index={i} />
          ))}
        </div>
      )}
    </section>
  );
}
